from __future__ import annotations
from collections import defaultdict

def score_calibration(trades:list[dict], min_samples:int=30):
    buckets=defaultdict(list)
    for t in trades:
        score=float(t.get('setup_quality',0)); lo=int(score//5)*5; lo=min(lo,95)
        buckets[f"{lo:02d}-{min(lo+4,100):02d}"].append(t)
    out={}
    for b,items in sorted(buckets.items()):
        n=len(items); wins=sum(float(x.get('net_pnl',0))>0 for x in items); avg_r=sum(float(x.get('r_multiple',0)) for x in items)/n
        out[b]={"samples":n,"win_rate":round(wins/n*100,2),"avg_r":round(avg_r,3),"calibrated":n>=min_samples}
    return out
