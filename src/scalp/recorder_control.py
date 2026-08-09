from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scalp.config import AppConfig, load_config
from scalp.live.recorder import BinanceLiveRecorder
from scalp.runtime import fd_stats
from scalp.runtime_storage import runtime_roots


class RecorderControlStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or runtime_roots.current().state / "recorder-control.db"); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY,created_at TEXT,action TEXT,payload TEXT,handled_at TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS health (singleton INTEGER PRIMARY KEY CHECK(singleton=1),updated_at REAL,pid INTEGER,state TEXT,payload TEXT)")

    def command(self, action: str, payload: dict | None = None):
        cid=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as c: c.execute("INSERT INTO commands VALUES (?,?,?,?,NULL)",(cid,now,action,json.dumps(payload or {})))
        return cid

    def next_command(self):
        with sqlite3.connect(self.path) as c:
            row=c.execute("SELECT id,action,payload FROM commands WHERE handled_at IS NULL ORDER BY created_at LIMIT 1").fetchone()
        return None if not row else {"id":row[0],"action":row[1],"payload":json.loads(row[2])}

    def handled(self, cid):
        with sqlite3.connect(self.path) as c: c.execute("UPDATE commands SET handled_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),cid))

    def heartbeat(self, state, payload=None):
        body={"fd":fd_stats(), **(payload or {})}
        with sqlite3.connect(self.path) as c: c.execute("INSERT OR REPLACE INTO health VALUES (1,?,?,?,?)",(time.time(),os.getpid(),state,json.dumps(body)))

    def status(self):
        with sqlite3.connect(self.path) as c: row=c.execute("SELECT updated_at,pid,state,payload FROM health WHERE singleton=1").fetchone()
        if not row: return {"running":False,"state":"OFFLINE","stale":True}
        age=time.time()-row[0]; payload=json.loads(row[3]); return {"running":age<15 and row[2] != "STOPPED","state":row[2],"stale":age>=15,"age_seconds":age,"pid":row[1],**payload}


async def recorder_daemon(poll_seconds=1.0):
    store=RecorderControlStore(); recorder=None; task=None; store.heartbeat("IDLE")
    while True:
        # Resolve the control database again so an atomic runtime-root switch
        # cannot leave this long-lived daemon polling the retired location.
        store=RecorderControlStore()
        cmd=store.next_command()
        if cmd:
            try:
                if cmd["action"] == "start":
                    if task and not task.done(): recorder.stop(); await asyncio.wait_for(task, timeout=15)
                    cfg=load_config(); raw=cfg.model_dump(); payload=cmd["payload"]
                    raw["live"]["symbols"]=[x.upper() for x in payload.get("symbols",raw["live"]["symbols"])]
                    full=[x.upper() for x in payload.get("full_l2_symbols",raw["live"]["full_l2_symbols"])]
                    if len(full)>4: raise ValueError("full L2 is capped at four symbols")
                    raw["live"]["full_l2_symbols"]=full; recorder=BinanceLiveRecorder(AppConfig.model_validate(raw)); task=asyncio.create_task(recorder.start())
                elif cmd["action"] == "stop" and recorder:
                    recorder.stop()
                store.handled(cmd["id"])
            except Exception as exc:
                store.heartbeat("ERROR",{"error":str(exc)}); store.handled(cmd["id"])
        state="RECORDING" if task and not task.done() else "IDLE"
        if task and task.done() and task.exception(): state="ERROR"
        store.heartbeat(state,{"recorder":getattr(recorder,"health",None)})
        await asyncio.sleep(poll_seconds)


def run_daemon():
    from scalp.runtime import ensure_nofile_limit
    ensure_nofile_limit(16384)
    try: asyncio.run(recorder_daemon())
    finally: RecorderControlStore().heartbeat("STOPPED")
