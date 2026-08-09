from __future__ import annotations
from pathlib import Path
import gzip, json, os, shutil, time
from datetime import datetime, timezone
from scalp.live.integrity import IntegrityStore

class ChunkWriter:
    """Crash-tolerant append buffer: write .tmp, fsync, atomic rename to .jsonl.gz."""
    def __init__(self, root:str, session_id:str, integrity:IntegrityStore, segment_seconds=60, max_events=10000, source="BINANCE_LIVE"):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.session_id=session_id; self.integrity=integrity; self.segment_seconds=segment_seconds; self.max_events=max_events; self.source=source
        self.buffers={}; self.started={}

    def add(self,event:dict):
        key=(event.get("market","unknown"),event.get("symbol","GLOBAL"),event.get("event_type","event"))
        self.buffers.setdefault(key,[]).append(event); self.started.setdefault(key,time.time())
        if len(self.buffers[key])>=self.max_events or time.time()-self.started[key]>=self.segment_seconds: self.flush_key(key)

    def flush_key(self,key):
        rows=self.buffers.get(key,[])
        if not rows: return None
        market,symbol,etype=key; start=min(int(x.get("receive_ts",0)) for x in rows); end=max(int(x.get("receive_ts",0)) for x in rows)
        dt=datetime.fromtimestamp(start/1000,tz=timezone.utc); folder=self.root/market/symbol/dt.strftime("%Y-%m-%d")/etype; folder.mkdir(parents=True,exist_ok=True)
        name=f"{dt.strftime('%H-%M-%S')}_{start}_{end}.jsonl.gz"; final=folder/name; tmp=folder/(name+".tmp")
        with open(tmp,"wb") as raw:
            with gzip.GzipFile(fileobj=raw,mode="wb",compresslevel=5) as gz:
                for row in rows: gz.write((json.dumps(row,separators=(",",":"),default=str)+"\n").encode())
            raw.flush(); os.fsync(raw.fileno())
        os.replace(tmp,final)
        self.integrity.register_coverage(self.source,symbol,etype,start,end,"HEALTHY",self.session_id,str(final),len(rows))
        self.buffers[key]=[]; self.started[key]=time.time(); return final

    def flush_all(self):
        return [self.flush_key(k) for k in list(self.buffers)]

    @staticmethod
    def recover_incomplete(root):
        return [str(p) for p in Path(root).rglob("*.tmp")]

    @staticmethod
    def recover_orphan_coverage(root,integrity:IntegrityStore,source,session_id=None):
        """Re-register finalized chunks if power failed between rename and SQLite metadata commit."""
        root=Path(root)
        if not root.exists(): return []
        known=integrity.coverage_paths(); recovered=[]
        for p in root.rglob("*.jsonl.gz"):
            if str(p) in known: continue
            try:
                # path = root / market / symbol / date / event_type / HH-MM-SS_start_end.jsonl.gz
                rel=p.relative_to(root); market,symbol,_,etype=rel.parts[:4]
                stem=p.name[:-len(".jsonl.gz")]; parts=stem.split("_")
                start=int(parts[-2]); end=int(parts[-1])
                integrity.register_coverage(source,symbol,etype,start,end,"RECOVERED_FINALIZED_CHUNK",session_id,str(p),0)
                recovered.append(str(p))
            except Exception:
                continue
        return recovered
