from __future__ import annotations
from pathlib import Path
import json, sqlite3, uuid
from datetime import datetime, timezone

class RunStore:
    def __init__(self,path=None):
        if path is None:
            from scalp.runtime_storage import runtime_roots
            path=runtime_roots.current().results/"runs.db"
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT, request_json TEXT, report_json TEXT)")
    def save(self,request,report):
        rid=str(uuid.uuid4())[:10]
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO runs VALUES (?,?,?,?)",(rid,datetime.now(timezone.utc).isoformat(),json.dumps(request),json.dumps(report)))
        return rid
    def get(self,rid):
        with sqlite3.connect(self.path) as c:
            row=c.execute("SELECT id,created_at,request_json,report_json FROM runs WHERE id=?",(rid,)).fetchone()
        if not row: return None
        return {"id":row[0],"created_at":row[1],"request":json.loads(row[2]),"report":json.loads(row[3])}
    def recent(self,limit=20):
        with sqlite3.connect(self.path) as c:
            rows=c.execute("SELECT id,created_at,request_json,report_json FROM runs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        out=[]
        for r in rows:
            req=json.loads(r[2]); rep=json.loads(r[3])
            out.append({"id":r[0],"created_at":r[1],"symbols":req.get("symbols"),"interval":req.get("interval"),"summary":rep.get("summary",{})})
        return out
