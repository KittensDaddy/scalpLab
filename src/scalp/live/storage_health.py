from __future__ import annotations
from pathlib import Path
import shutil, time

class StorageManager:
    _usage_cache={}
    def __init__(self,cfg): self.cfg=cfg
    def bulk_root(self):
        preferred=Path(self.cfg.bulk_dir)
        try:
            preferred.mkdir(parents=True,exist_ok=True); test=preferred/".write-test"; test.write_text("ok"); test.unlink(); return preferred
        except Exception:
            fallback=Path(self.cfg.fallback_bulk_dir); fallback.mkdir(parents=True,exist_ok=True); return fallback
    @staticmethod
    def stats(path):
        p=Path(path); p.mkdir(parents=True,exist_ok=True); u=shutil.disk_usage(p); used=u.total-u.free
        return {"path":str(p),"total":u.total,"used":used,"free":u.free,"used_pct":used/u.total*100 if u.total else 0}
    def usage_metrics(self,root,ttl=60):
        root=Path(root); key=str(root); cached=self._usage_cache.get(key)
        if cached and time.time()-cached[0]<ttl: return cached[1]
        now=time.time(); today=now-86400; week=now-7*86400; today_bytes=week_bytes=0; cats={}; files=0
        try:
            for p in root.rglob('*'):
                if not p.is_file(): continue
                try: st=p.stat()
                except OSError: continue
                files+=1; size=st.st_size
                if st.st_mtime>=today: today_bytes+=size
                if st.st_mtime>=week: week_bytes+=size
                try: cat=p.relative_to(root).parts[0]
                except Exception: cat='other'
                cats[cat]=cats.get(cat,0)+size
        except OSError: pass
        avg=week_bytes/7; free=self.stats(root)["free"]; days=free/avg if avg>0 else None
        out={"files":files,"today_bytes":today_bytes,"seven_day_bytes":week_bytes,"avg_bytes_per_day_7d":avg,"estimated_days_until_full":days,"categories":cats}; self._usage_cache[key]=(time.time(),out); return out
    def status(self):
        root=self.bulk_root(); bulk=self.stats(root); state=self.stats(Path(self.cfg.state_dir)); pct=bulk["used_pct"]
        level="OK"
        if pct>=self.cfg.emergency_pct: level="EMERGENCY"
        elif pct>=self.cfg.pressure_pct: level="PRESSURE"
        elif pct>=self.cfg.warning_pct: level="WARNING"
        return {"bulk":bulk,"state":state,"level":level,"retention_days":self.cfg.raw_l2_retention_days,"usage":self.usage_metrics(root)}
    def prune_raw_l2(self,dry_run=True):
        root=self.bulk_root()/"live"; cutoff=time.time()-self.cfg.raw_l2_retention_days*86400; removed=[]
        if not root.exists(): return removed
        for p in root.rglob("*.jsonl.gz"):
            if "/depth/" not in str(p).replace('\\','/') and p.parent.name!="depth": continue
            if p.stat().st_mtime<cutoff:
                removed.append({"path":str(p),"bytes":p.stat().st_size})
                if not dry_run: p.unlink(missing_ok=True)
        self._usage_cache.pop(str(self.bulk_root()),None)
        return removed
