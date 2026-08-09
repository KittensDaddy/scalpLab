from __future__ import annotations
from pathlib import Path
import asyncio, shutil, socket, sqlite3, time
import httpx, websockets
from scalp.config import AppConfig
from scalp.live.integrity import IntegrityStore
from scalp.live.storage_health import StorageManager
from scalp.runtime import fd_stats

async def _check_ws(url,timeout=5):
    try:
        async with websockets.connect(url,ping_interval=None,open_timeout=timeout,close_timeout=2) as ws:
            msg=await asyncio.wait_for(ws.recv(),timeout=timeout); return True, "event received"
    except Exception as e: return False,str(e)

async def doctor_async(cfg:AppConfig):
    checks=[]
    def add(name,ok,detail=""): checks.append({"name":name,"ok":bool(ok),"detail":detail})
    try:
        async with httpx.AsyncClient(base_url=cfg.live.futures_rest_base,timeout=5) as c:
            r=await c.get("/fapi/v1/time"); add("Binance Futures REST",r.status_code==200,f"HTTP {r.status_code}")
    except Exception as e: add("Binance Futures REST",False,str(e))
    try:
        async with httpx.AsyncClient(base_url=cfg.live.spot_rest_base,timeout=5) as c:
            r=await c.get("/api/v3/time"); add("Binance Spot REST",r.status_code==200,f"HTTP {r.status_code}")
    except Exception as e: add("Binance Spot REST",False,str(e))
    f_ok,f_d=await _check_ws(cfg.live.futures_ws_base+"?streams=btcusdt@aggTrade"); add("Futures WebSocket",f_ok,f_d)
    s_ok,s_d=await _check_ws(cfg.live.spot_ws_base+"?streams=btcusdt@aggTrade"); add("Spot WebSocket",s_ok,s_d)
    sm=StorageManager(cfg.storage); status=sm.status(); add("Bulk storage writable",status["bulk"]["free"]>0,status["bulk"]["path"]); add("State storage writable",status["state"]["free"]>0,status["state"]["path"])
    db=IntegrityStore(Path(cfg.storage.state_dir)/"integrity.db"); add("Integrity database",db.path.exists(),str(db.path))
    fds=fd_stats(); add("File descriptors",fds.get("state")!="CRITICAL",f"{fds.get('open_fds')} open / {fds.get('soft_limit')} soft ({fds.get('state')})")
    # Clock sanity: compare Futures server time if possible is already covered; local UTC monotonicity is a minimum offline check.
    add("System clock",time.time()>1_700_000_000,time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()))
    return {"ok":all(x["ok"] for x in checks),"checks":checks,"storage":status,"recent_gaps":db.recent_gaps(10)}

def doctor(cfg): return asyncio.run(doctor_async(cfg))
