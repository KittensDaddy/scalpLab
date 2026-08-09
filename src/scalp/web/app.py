from __future__ import annotations
import asyncio, json, traceback, uuid
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from scalp.service import ResearchService
from scalp.storage import RunStore
from scalp.config import load_config, AppConfig
from scalp.live.integrity import IntegrityStore
from scalp.live.storage_health import StorageManager
from scalp.live.doctor import doctor_async
from scalp.live.recorder import BinanceLiveRecorder
from scalp.live.shadow import ShadowPaperTrader, ShadowStore
from scalp.data.tardis import TardisSampleClient

BASE=Path(__file__).resolve().parent
app=FastAPI(title="ScalpLab",version="0.2.0")
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")
templates=Jinja2Templates(directory=BASE/"templates")
service=ResearchService(); store=RunStore(); jobs={}
recorder=None; recorder_task=None; shadow=None; shadow_task=None

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

class RecorderRequest(BaseModel):
    symbols:list[str]=["BTCUSDT","ETHUSDT","SOLUSDT"]
    full_l2_symbols:list[str]=["BTCUSDT","ETHUSDT","SOLUSDT"]

class TardisRequest(BaseModel):
    symbol:str="BTCUSDT"; day:str; data_type:str="incremental_book_L2"

@app.get("/",response_class=HTMLResponse)
def home(request:Request): return templates.TemplateResponse(request,"index.html",{})
@app.get("/api/health")
def health(): return {"ok":True,"version":"0.2.0","live_money":False}

@app.get("/api/symbols")
async def symbols():
    try: return {"symbols":await asyncio.to_thread(service.symbols)}
    except Exception as e: return {"symbols":["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT"],"warning":str(e)}

def _overrides(req):
    return {"strategies":{"enabled":req.strategies,"min_score":req.min_score,"min_separation":req.min_separation},"risk":{"initial_equity":req.initial_equity,"normal_risk_pct":req.risk_pct,"max_total_open_risk_pct":req.max_open_risk_pct,"max_position_notional_pct":req.max_position_notional_pct},"execution":{"maker_fee_bps":req.maker_fee_bps,"taker_fee_bps":req.taker_fee_bps,"market_slippage_bps":req.market_slippage_bps}}

async def _run_job(jid,req,kind="backtest"):
    jobs[jid]={"status":"RUNNING","progress":10,"message":"Preparing market data"}
    try:
        if kind=="replay":
            if not req.start_time or not req.end_time: raise ValueError("Replay requires exact start and end")
            jobs[jid].update(progress=35,message="Loading locally recorded microstructure")
            report=await asyncio.to_thread(service.replay_range,req.symbols,req.interval,req.start_time,req.end_time,_overrides(req))
        elif kind=="walkforward":
            jobs[jid].update(progress=35,message="Running chronological walk-forward folds")
            if req.start_time and req.end_time: report=await asyncio.to_thread(service.walkforward_range,req.symbols,req.interval,req.start_time,req.end_time,_overrides(req),req.walkforward_tune)
            else: report=await asyncio.to_thread(service.walkforward,req.symbols,req.interval,req.lookback_days,_overrides(req),req.walkforward_tune)
        else:
            jobs[jid].update(progress=35,message="Fetching Binance history and building features")
            if req.start_time and req.end_time: report=await asyncio.to_thread(service.run_range,req.symbols,req.interval,req.start_time,req.end_time,_overrides(req))
            else: report=await asyncio.to_thread(service.run,req.symbols,req.interval,req.lookback_days,_overrides(req))
        jobs[jid].update(progress=90,message="Saving reproducible run")
        rid=store.save(req.model_dump()|{"kind":kind},report); jobs[jid]={"status":"DONE","progress":100,"run_id":rid,"report":report}
    except Exception as e: jobs[jid]={"status":"ERROR","progress":100,"error":str(e),"trace":traceback.format_exc()[-4000:]}

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
    return {"running":bool(recorder_task and not recorder_task.done()),"health":getattr(recorder,"health",None),"live_money":False}
@app.post("/api/recorder/start")
async def recorder_start(req:RecorderRequest):
    global recorder,recorder_task
    if recorder_task and not recorder_task.done(): return {"running":True,"message":"already running"}
    cfg=load_config(); raw=cfg.model_dump(); raw["live"]["symbols"]=[s.upper() for s in req.symbols]; raw["live"]["full_l2_symbols"]=[s.upper() for s in req.full_l2_symbols]; cfg=AppConfig.model_validate(raw)
    recorder=BinanceLiveRecorder(cfg); recorder_task=asyncio.create_task(recorder.start()); return {"running":True}
@app.post("/api/recorder/stop")
async def recorder_stop():
    if recorder: recorder.stop()
    return {"running":False}

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
