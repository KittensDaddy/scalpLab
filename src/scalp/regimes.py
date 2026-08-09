from __future__ import annotations
import math

def clamp(v,a=0,b=100): return max(a,min(b,float(v)))

def regime_scores(row) -> dict[str,float]:
    adx=float(row.get("adx",0) or 0); eff=float(row.get("efficiency",0) or 0)
    slope=float(row.get("ema20_slope",0) or 0); vr=float(row.get("vol_ratio",1) or 1)
    bb=float(row.get("bb_width_pct",0.5) or 0.5); atr=float(row.get("atr",0) or 0); atrma=float(row.get("atr_ma",atr) or atr or 1)
    up=clamp(35 + 2.0*adx + 180*slope + 25*eff) if slope>0 else clamp(25+adx-80*abs(slope))
    down=clamp(35 + 2.0*adx + 180*abs(slope) + 25*eff) if slope<0 else clamp(25+adx-80*abs(slope))
    rng=clamp(90 - 2.8*adx - 45*eff - 150*abs(slope))
    compression=clamp(100*(1-bb))
    expansion=clamp(40*(atr/max(atrma,1e-12)-0.8)+25*(vr-1)+40*bb)
    transition=clamp(65-abs(up-down)*0.55 + 20*(0.35<=eff<=0.55))
    pump=clamp((vr-1.5)*35 + max(slope,0)*450 + max(float(row.get("ret1",0) or 0),0)*2500)
    dump=clamp((vr-1.5)*35 + max(-slope,0)*450 + max(-float(row.get("ret1",0) or 0),0)*2500)
    exhaustion=clamp(max(pump,dump)*0.45 + max(0, vr-2)*15 + max(0, float(row.get("body_frac",0) or 0)-0.65)*25)
    raw={"TREND_UP":up,"TREND_DOWN":down,"RANGE":rng,"COMPRESSION":compression,"EXPANSION":expansion,"TRANSITION":transition,"PUMP":pump,"DUMP":dump,"EXHAUSTION":exhaustion}
    total=sum(raw.values()) or 1
    probs={k:round(v/total*100,2) for k,v in raw.items()}
    return probs

def dominant_regime(scores:dict[str,float])->str:
    return max(scores,key=scores.get) if scores else "UNKNOWN"
