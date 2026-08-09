from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json, sqlite3, time, uuid
from scalp.models import GapReason

def now_ms(): return int(time.time()*1000)

class IntegrityStore:
    def __init__(self, path="data/state/integrity.db"):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,start_ts INTEGER,end_ts INTEGER,status TEXT,host TEXT,notes TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS heartbeats(session_id TEXT PRIMARY KEY,ts INTEGER,state_json TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS gaps(id TEXT PRIMARY KEY,start_ts INTEGER,end_ts INTEGER,reason TEXT,session_id TEXT,symbol TEXT,stream TEXT,recoverable INTEGER,repaired_source TEXT,notes TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS coverage(source TEXT,symbol TEXT,data_type TEXT,start_ts INTEGER,end_ts INTEGER,quality TEXT,session_id TEXT,path TEXT,rows INTEGER,PRIMARY KEY(source,symbol,data_type,start_ts,end_ts,path))")
            c.execute("CREATE TABLE IF NOT EXISTS latest_features(symbol TEXT PRIMARY KEY,ts INTEGER,quality TEXT,feature_json TEXT)")

    def begin_session(self, host="local") -> tuple[str,dict|None]:
        previous=self.last_session(); ts=now_ms(); sid=str(uuid.uuid4())
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)",(sid,ts,None,"RUNNING",host,""))
        return sid,previous

    def end_session(self,sid,status="CLEAN",notes=""):
        with sqlite3.connect(self.path) as c: c.execute("UPDATE sessions SET end_ts=?,status=?,notes=? WHERE id=?",(now_ms(),status,notes,sid))

    def last_session(self):
        with sqlite3.connect(self.path) as c:
            r=c.execute("SELECT id,start_ts,end_ts,status,host,notes FROM sessions ORDER BY start_ts DESC LIMIT 1").fetchone()
        return dict(zip(["id","start_ts","end_ts","status","host","notes"],r)) if r else None

    def heartbeat(self,sid,state:dict):
        ts=now_ms()
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO heartbeats VALUES(?,?,?)",(sid,ts,json.dumps(state,separators=(",",":"))))
        return ts

    def last_heartbeat(self,sid):
        with sqlite3.connect(self.path) as c: r=c.execute("SELECT ts,state_json FROM heartbeats WHERE session_id=?",(sid,)).fetchone()
        return {"ts":r[0],"state":json.loads(r[1])} if r else None

    def record_gap(self,start_ts,end_ts=None,reason=GapReason.UNKNOWN,session_id=None,symbol=None,stream=None,recoverable=False,notes=""):
        gid=str(uuid.uuid4())
        reason=reason.value if hasattr(reason,"value") else str(reason)
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO gaps VALUES(?,?,?,?,?,?,?,?,?,?)",(gid,start_ts,end_ts,reason,session_id,symbol,stream,int(recoverable),None,notes))
        return gid

    def close_gap(self,gid,end_ts=None,repaired_source=None):
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE gaps SET end_ts=?,repaired_source=COALESCE(?,repaired_source) WHERE id=?",(end_ts or now_ms(),repaired_source,gid))

    def recent_gaps(self,limit=100):
        with sqlite3.connect(self.path) as c:
            rows=c.execute("SELECT id,start_ts,end_ts,reason,session_id,symbol,stream,recoverable,repaired_source,notes FROM gaps ORDER BY start_ts DESC LIMIT ?",(limit,)).fetchall()
        keys=["id","start_ts","end_ts","reason","session_id","symbol","stream","recoverable","repaired_source","notes"]
        return [dict(zip(keys,r)) for r in rows]

    def register_coverage(self,source,symbol,data_type,start_ts,end_ts,quality,session_id,path,rows):
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO coverage VALUES(?,?,?,?,?,?,?,?,?)",(source,symbol,data_type,start_ts,end_ts,quality,session_id,path,rows))

    def coverage(self,symbol,start_ts,end_ts):
        with sqlite3.connect(self.path) as c:
            rows=c.execute("SELECT source,symbol,data_type,start_ts,end_ts,quality,session_id,path,rows FROM coverage WHERE symbol=? AND end_ts>=? AND start_ts<=? ORDER BY start_ts",(symbol,start_ts,end_ts)).fetchall()
        keys=["source","symbol","data_type","start_ts","end_ts","quality","session_id","path","rows"]
        return [dict(zip(keys,r)) for r in rows]


    def coverage_paths(self):
        with sqlite3.connect(self.path) as c:
            return {r[0] for r in c.execute("SELECT path FROM coverage WHERE path IS NOT NULL AND path != ''").fetchall()}

    def update_latest_feature(self,symbol,ts,quality,feature):
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO latest_features VALUES(?,?,?,?)",(symbol,ts,quality,json.dumps(feature,separators=(",",":"),default=str)))

    def latest_feature(self,symbol):
        with sqlite3.connect(self.path) as c: r=c.execute("SELECT ts,quality,feature_json FROM latest_features WHERE symbol=?",(symbol,)).fetchone()
        return {"ts":r[0],"quality":r[1],"feature":json.loads(r[2])} if r else None

    def latest_features(self):
        with sqlite3.connect(self.path) as c: rows=c.execute("SELECT symbol,ts,quality,feature_json FROM latest_features ORDER BY symbol").fetchall()
        return {r[0]:{"ts":r[1],"quality":r[2],"feature":json.loads(r[3])} for r in rows}
