from __future__ import annotations
import asyncio, json, traceback, uuid, time
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from scalp.service import ResearchService
from scalp.storage import RunStore
from scalp.config import load_config
from scalp.live.integrity import IntegrityStore
from scalp.live.storage_health import StorageManager
from scalp.live.doctor import doctor_async
from scalp.live.shadow import ShadowPaperTrader, ShadowStore
from scalp.data.tardis import TardisSampleClient
from scalp.runtime import fd_stats
from scalp.runtime_storage import runtime_roots
from scalp.universe import UniverseService
from scalp.strategy_rules import StrategyVersionStore, RuleInterpreter
from scalp.recorder_control import RecorderControlStore

BASE=Path(__file__).resolve().parent
app=FastAPI(title="ScalpLab",version="0.2.2")
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")
templates=Jinja2Templates(directory=BASE/"templates")
service=ResearchService(); store=RunStore(); jobs={}
shadow=None; shadow_task=None

class BacktestRequest(BaseModel):
    symbols:list[str]=["BTCUSDT","ETHUSDT","SOLUSDT"]
    interval:str="5m"
    lookback_days:int=Field(14,ge=1,le=3650)
    start_time:str|None=None
    end_time:str|None=None
    source:str="BINANCE"
    strategies:list[str]=["TC","LC","LSR","RB","VB","TR"]
    initial_equity:float=Field(10000,gt=0)
    risk_pct:float=Field(0.5,gt=0,le=5)
    max_open_risk_pct:float=Field(2.0,gt=0,le=10)
    min_score:float=Field(68,ge=0,le=100)
    min_separation:float=Field(10,ge=0,le=100)
    maker_fee_bps:float=Field(2,ge=0)
    taker_fee_bps:float=Field(5,ge=0)
    market_slippage_bps:float=Field(1.5,ge=0)
    max_position_notional_pct:float=Field(100,gt=0,le=1000)
    walkforward_tune:bool=False
    universe_snapshot_id:str|None=None
    strategy_versions:dict[str,str]=Field(default_factory=dict)

class RecorderRequest(BaseModel):
    symbols:list[str]=["BTCUSDT","ETHUSDT","SOLUSDT"]
    full_l2_symbols:list[str]=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]

class StoragePathRequest(BaseModel):
    path:str

class DraftRequest(BaseModel):
    name:str
    definition:dict
    base_revision:str|None=None

class DefinitionRequest(BaseModel):
    definition:dict

class TardisRequest(BaseModel):
    symbol:str="BTCUSDT"; day:str; data_type:str="incremental_book_L2"

@app.get("/",response_class=HTMLResponse)
async def home(request:Request): return templates.TemplateResponse(request,"index.html",{})
@app.get("/api/health")
async def health(): return {"ok":True,"version":"0.2.2","live_money":False,"runtime":fd_stats()}


@app.get("/api/runtime")
async def runtime_status():
    web=fd_stats(); recorder=RecorderControlStore().status()
    return web | {"web":web,"recorder":recorder}

@app.get("/api/universe")
def universe(): return UniverseService().latest()

@app.post("/api/universe/refresh")
async def universe_refresh():
    try: return await asyncio.to_thread(UniverseService().refresh)
    except Exception as e: raise HTTPException(502,str(e))

@app.get("/api/settings/storage")
def storage_settings():
    layout=runtime_roots.current(); return {"runtime_root":str(layout.root),"estimate":runtime_roots.estimate()}

@app.post("/api/settings/storage/validate")
def storage_validate(req:StoragePathRequest):
    try: return runtime_roots.validate(req.path)
    except ValueError as e: raise HTTPException(400,str(e))

@app.post("/api/settings/storage/migrate")
def storage_migrate(req:StoragePathRequest):
    producing=any(v.get("status")=="RUNNING" for v in jobs.values()) or bool(shadow_task and not shadow_task.done()) or RecorderControlStore().status().get("state")=="RECORDING"
    try: return runtime_roots.migrate(req.path,jobs_running=producing)
    except (ValueError,RuntimeError) as e: raise HTTPException(409,str(e))

@app.get("/api/strategies")
def strategies_list(): return {"strategies":StrategyVersionStore().list(),"feature_registry":__import__('scalp.strategy_rules',fromlist=['FEATURES']).FEATURES}

@app.post("/api/strategies/drafts")
def strategy_create(req:DraftRequest):
    try: return StrategyVersionStore().create_draft(req.name,req.definition,req.base_revision)
    except ValueError as e: raise HTTPException(400,str(e))

@app.put("/api/strategies/{sid}/draft")
def strategy_update(sid:str,req:DefinitionRequest):
    try: return StrategyVersionStore().update(sid,req.definition)
    except ValueError as e: raise HTTPException(409,str(e))

@app.post("/api/strategies/validate")
def strategy_validate(req:DefinitionRequest): return RuleInterpreter().validate(req.definition)

@app.post("/api/strategies/{sid}/test")
def strategy_test(sid:str, rows:list[dict]):
    item=StrategyVersionStore().get(sid)
    if not item or "definition" not in item: raise HTTPException(404,"custom strategy not found")
    engine=RuleInterpreter(); verdict=engine.validate(item["definition"])
    if not verdict["valid"]: raise HTTPException(400,verdict["errors"])
    return {side:[engine.evaluate(item["definition"][side]["conditions"],row,rows[i-1] if i else None) for i,row in enumerate(rows)] for side in ("long","short")}

@app.post("/api/strategies/{sid}/publish")
def strategy_publish(sid:str):
    try: return StrategyVersionStore().publish(sid)
    except ValueError as e: raise HTTPException(409,str(e))

@app.post("/api/strategies/{sid}/archive")
def strategy_archive(sid:str):
    try: return StrategyVersionStore().archive(sid)
    except ValueError as e: raise HTTPException(409,str(e))

@app.get("/api/symbols")
async def symbols():
    try: return {"symbols":await asyncio.to_thread(service.symbols)}
    except Exception as e: return {"symbols":["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT"],"warning":str(e)}

def _overrides(req):
    return {"strategies":{"enabled":req.strategies,"min_score":req.min_score,"min_separation":req.min_separation},"risk":{"initial_equity":req.initial_equity,"normal_risk_pct":req.risk_pct,"max_total_open_risk_pct":req.max_open_risk_pct,"max_position_notional_pct":req.max_position_notional_pct},"execution":{"maker_fee_bps":req.maker_fee_bps,"taker_fee_bps":req.taker_fee_bps,"market_slippage_bps":req.market_slippage_bps}}

async def _run_job(jid,req,kind="backtest"):
    started=time.time()
    jobs[jid]={"status":"RUNNING","progress":0,"message":"Starting","started_at":started,"updated_at":started}
    def on_progress(percent,message):
        jobs[jid].update(progress=round(float(percent),1),message=str(message),updated_at=time.time())
    try:
        universe=UniverseService().latest()
        if req.universe_snapshot_id and universe.get("snapshot_id") != req.universe_snapshot_id:
            candidate=UniverseService().root/f"{req.universe_snapshot_id}.json"
            if not candidate.exists(): raise ValueError("unknown universe_snapshot_id")
            universe=json.loads(candidate.read_text())
        req.universe_snapshot_id=req.universe_snapshot_id or universe.get("snapshot_id")
        version_store=StrategyVersionStore(); resolved={}
        for strategy in req.strategies:
            vid=req.strategy_versions.get(strategy,strategy)
            item=version_store.get(vid)
            if not item or item.get("status") != "published" or item.get("archived"):
                raise ValueError(f"strategy version is not published: {strategy}={vid}")
            resolved[strategy]={"id":vid,"hash":item.get("hash") or f"builtin-{strategy}-r1"}
        req.strategy_versions={k:v["id"] for k,v in resolved.items()}
        if kind=="replay":
            if not req.start_time or not req.end_time: raise ValueError("Replay requires exact start and end")
            report=await asyncio.to_thread(service.replay_range,req.symbols,req.interval,req.start_time,req.end_time,overrides=_overrides(req),progress=on_progress)
        elif kind=="walkforward":
            if req.start_time and req.end_time:
                report=await asyncio.to_thread(service.walkforward_range,req.symbols,req.interval,req.start_time,req.end_time,overrides=_overrides(req),tune=req.walkforward_tune,progress=on_progress)
            else:
                report=await asyncio.to_thread(service.walkforward,req.symbols,req.interval,req.lookback_days,overrides=_overrides(req),tune=req.walkforward_tune,progress=on_progress)
        else:
            if req.start_time and req.end_time:
                report=await asyncio.to_thread(service.run_range,req.symbols,req.interval,req.start_time,req.end_time,overrides=_overrides(req),progress=on_progress)
            else:
                report=await asyncio.to_thread(service.run,req.symbols,req.interval,req.lookback_days,overrides=_overrides(req),progress=on_progress)
        on_progress(99.5,"Saving reproducible run")
        rid=store.save(req.model_dump()|{"kind":kind,"universe_symbols":[x["symbol"] for x in universe.get("assets",[])],"strategy_version_hashes":resolved},report)
        jobs[jid]={"status":"DONE","progress":100,"message":"Complete","run_id":rid,"report":report,"started_at":started,"updated_at":time.time()}
    except Exception as e:
        jobs[jid]={"status":"ERROR","progress":100,"error":str(e),"trace":traceback.format_exc()[-4000:],"started_at":started,"updated_at":time.time()}

@app.post("/api/backtests")
async def create_backtest(req:BacktestRequest):
    jid=str(uuid.uuid4())[:8]; asyncio.create_task(_run_job(jid,req,"backtest")); return {"job_id":jid}
@app.post("/api/replay")
async def create_replay(req:BacktestRequest):
    jid=str(uuid.uuid4())[:8]; asyncio.create_task(_run_job(jid,req,"replay")); return {"job_id":jid}
@app.post("/api/walkforward")
async def create_walkforward(req:BacktestRequest):
    jid=str(uuid.uuid4())[:8]; asyncio.create_task(_run_job(jid,req,"walkforward")); return {"job_id":jid}
@app.get("/api/jobs/{jid}")
def job(jid:str): return jobs.get(jid,{"status":"NOT_FOUND"})
@app.get("/api/runs")
def runs(): return {"runs":store.recent(30)}
@app.get("/api/runs/{rid}")
def run(rid:str): return store.get(rid) or {"error":"not found"}

@app.get("/api/data-integrity")
def data_integrity():
    cfg=load_config(); db=IntegrityStore(Path(cfg.storage.state_dir)/"integrity.db")
    return {"last_session":db.last_session(),"gaps":db.recent_gaps(100),"latest_features":db.latest_features(),"storage":StorageManager(cfg.storage).status()}
@app.get("/api/coverage/{symbol}")
def coverage(symbol:str,start:str,end:str): return {"segments":service.coverage(symbol,start,end)}
@app.get("/api/storage")
def storage_status(): return StorageManager(load_config().storage).status()
@app.post("/api/storage/prune")
def storage_prune(dry_run:bool=True): return {"dry_run":dry_run,"files":StorageManager(load_config().storage).prune_raw_l2(dry_run=dry_run)}
@app.get("/api/doctor")
async def doctor(): return await doctor_async(load_config())

@app.get("/api/recorder/status")
def recorder_status():
    status=RecorderControlStore().status()
    return status | {"health":status.get("recorder"),"live_money":False}
@app.post("/api/recorder/start")
async def recorder_start(req:RecorderRequest):
    if len(req.full_l2_symbols)>4: raise HTTPException(400,"full L2 is capped at four symbols")
    cid=RecorderControlStore().command("start",req.model_dump()); return {"accepted":True,"command_id":cid}
@app.post("/api/recorder/stop")
async def recorder_stop():
    cid=RecorderControlStore().command("stop"); return {"accepted":True,"command_id":cid}

@app.get("/api/shadow/status")
def shadow_status():
    cfg=load_config(); return {"running":bool(shadow_task and not shadow_task.done()),"recent":ShadowStore(cfg.shadow.persist_path).recent(50),"live_money":False}
@app.post("/api/shadow/start")
async def shadow_start():
    global shadow,shadow_task
    if shadow_task and not shadow_task.done(): return {"running":True,"message":"already running"}
    cfg=load_config(); shadow=ShadowPaperTrader(cfg); shadow_task=asyncio.create_task(shadow.start()); return {"running":True,"live_money":False}
@app.post("/api/shadow/stop")
async def shadow_stop():
    if shadow: shadow.stop()
    return {"running":False}

@app.post("/api/tardis/sample")
async def tardis_sample(req:TardisRequest):
    p=await asyncio.to_thread(TardisSampleClient().download,req.data_type,req.day,req.symbol); return {"path":str(p),"source":"TARDIS_FREE_SAMPLE"}
