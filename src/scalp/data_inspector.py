from __future__ import annotations

import gzip
import json
import sqlite3
import time
import math
from pathlib import Path

from scalp.live.integrity import IntegrityStore


class DataInspector:
    def __init__(self, integrity: IntegrityStore):
        self.integrity=integrity

    @staticmethod
    def _union_ms(intervals):
        total=0; end=None
        for start,stop in sorted(intervals):
            if end is None: current=start; end=stop
            elif start<=end: end=max(end,stop)
            else: total+=end-current; current=start; end=stop
        return total+(end-current if end is not None else 0)

    def inspect(self,symbol:str,hours:float=1,end_ms:int|None=None):
        symbol=symbol.upper(); end_ms=end_ms or int(time.time()*1000); start_ms=end_ms-int(hours*3_600_000)
        segments=self.integrity.coverage(symbol,start_ms,end_ms)
        clipped=[(max(start_ms,x["start_ts"]),min(end_ms,x["end_ts"])) for x in segments if x["end_ts"]>=start_ms]
        covered=self._union_ms(clipped); coverage_pct=min(100,covered/max(1,end_ms-start_ms)*100)
        by_type={}; files=[]; corrupt=missing=0
        # Coverage is ordered oldest-first; inspect newest physical chunks first.
        for row in reversed(segments):
            item=by_type.setdefault(row["data_type"],{"segments":0,"rows":0,"bytes":0,"latest_ms":0,"qualities":set()})
            item["segments"]+=1; item["rows"]+=int(row.get("rows") or 0); item["latest_ms"]=max(item["latest_ms"],int(row["end_ts"])); item["qualities"].add(row["quality"])
            path=Path(row["path"]); size=path.stat().st_size if path.exists() else 0; item["bytes"]+=size
            status="OK" if path.exists() else "MISSING"; metadata={}
            if not path.exists(): missing+=1
            elif len(files)<30 and path.suffix==".gz":
                try:
                    with gzip.open(path,"rt") as handle: metadata=json.loads(handle.readline() or "{}")
                except Exception: status="CORRUPT"; corrupt+=1
            files.append({"path":str(path),"bytes":size,"status":status,"data_type":row["data_type"],"start_ts":row["start_ts"],"end_ts":row["end_ts"],"rows":row["rows"],"tier":metadata.get("subscription_tier"),"snapshot_id":metadata.get("universe_snapshot_id")})
        for value in by_type.values(): value["qualities"]=sorted(value["qualities"]); value["freshness_seconds"]=(end_ms-value["latest_ms"])/1000 if value["latest_ms"] else None
        with sqlite3.connect(self.integrity.path) as conn:
            rows=conn.execute("SELECT start_ts,end_ts,reason,stream,notes FROM gaps WHERE (symbol=? OR symbol IS NULL) AND start_ts<=? AND COALESCE(end_ts,?)>=? ORDER BY start_ts",(symbol,end_ms,end_ms,start_ms)).fetchall()
            symbols=[x[0] for x in conn.execute("SELECT DISTINCT symbol FROM coverage WHERE symbol NOT IN ('GLOBAL','') ORDER BY symbol").fetchall()]
            bounds=conn.execute("SELECT MIN(start_ts),MAX(end_ts) FROM coverage WHERE symbol=?",(symbol,)).fetchone()
        gaps=[dict(zip(("start_ts","end_ts","reason","stream","notes"),x)) for x in rows]
        latest=self.integrity.latest_feature(symbol); feature=by_type.get("feature")
        replay_coverage=0
        if feature:
            feature_intervals=[(max(start_ms,x["start_ts"]),min(end_ms,x["end_ts"])) for x in segments if x["data_type"]=="feature"]
            replay_coverage=min(100,self._union_ms(feature_intervals)/max(1,end_ms-start_ms)*100)
        feature_paths=[Path(x["path"]) for x in segments if x["data_type"]=="feature" and Path(x["path"]).exists()]
        samples,sanity=self._sample_features(feature_paths,start_ms,end_ms)
        healthy_book=bool(latest and latest["quality"]=="HEALTHY")
        usable=replay_coverage>=90 and not gaps and not missing and not corrupt and sanity["passed"]
        verdict="REPLAY READY" if usable else "CAPTURING" if segments and healthy_book else "INCOMPLETE" if segments else "NO DATA"
        reasons=[]
        if replay_coverage<90: reasons.append(f"Derived-feature coverage is {replay_coverage:.1f}%; replay requires 90%")
        if gaps: reasons.append(f"{len(gaps)} integrity gap(s) overlap this range")
        if missing or corrupt: reasons.append(f"{missing} missing and {corrupt} corrupt chunk file(s)")
        reasons.extend(sanity["issues"])
        if not healthy_book: reasons.append("Latest full-L2 book is not healthy")
        return {"symbol":symbol,"start_ms":start_ms,"end_ms":end_ms,"hours":hours,"recording_bounds":{"start_ms":bounds[0],"end_ms":bounds[1]},"verdict":verdict,"usable_for_microstructure_replay":usable,"coverage_pct":coverage_pct,"replay_coverage_pct":replay_coverage,"healthy_book":healthy_book,"latest_feature":latest,"reasons":reasons,"sanity":sanity,"samples":samples,"by_type":by_type,"segments":segments,"gaps":gaps,"files":sorted(files,key=lambda x:x["end_ts"],reverse=True)[:30],"available_symbols":symbols}

    @staticmethod
    def _sample_features(paths,start_ms,end_ms,limit=180):
        rows=[]; invalid=0; previous=None; nonmonotonic=0
        for path in sorted(paths):
            try:
                with gzip.open(path,"rt") as handle:
                    for line in handle:
                        item=json.loads(line); ts=int(item.get("receive_ts") or 0)
                        if not start_ms<=ts<=end_ms: continue
                        if previous is not None and ts<previous: nonmonotonic+=1
                        previous=ts
                        values={k:item.get(k) for k in ("mid","spread_bps","depth_imbalance","ofi","cvd_delta")}
                        try:
                            clean={k:(float(v) if v is not None else None) for k,v in values.items()}
                            if any(v is not None and not math.isfinite(v) for v in clean.values()): raise ValueError
                            rows.append({"ts":ts,**clean})
                        except (TypeError,ValueError): invalid+=1
            except (OSError,EOFError,json.JSONDecodeError): invalid+=1
        issues=[]
        if invalid: issues.append(f"{invalid} sampled feature row(s) contain invalid numeric data")
        if nonmonotonic: issues.append(f"{nonmonotonic} feature timestamp(s) are out of order")
        if any((x["mid"] is not None and x["mid"]<=0) for x in rows): issues.append("Feature samples contain a non-positive mid price")
        if any((x["spread_bps"] is not None and x["spread_bps"]<0) for x in rows): issues.append("Feature samples contain a negative spread")
        if not rows: issues.append("No readable derived-feature samples exist in this range")
        if len(rows)>limit:
            step=(len(rows)-1)/(limit-1); rows=[rows[round(i*step)] for i in range(limit)]
        return rows,{"passed":not issues,"issues":issues,"sample_count":len(rows),"invalid_rows":invalid,"nonmonotonic_rows":nonmonotonic}
