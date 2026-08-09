from __future__ import annotations
import httpx

class MarketRadar:
    """Cheap whole-market REST radar. It ranks USDT perpetuals without subscribing to every L2 stream."""
    def __init__(self,base="https://fapi.binance.com",timeout=10): self.base=base; self.timeout=timeout
    def scan(self,limit=30):
        with httpx.Client(base_url=self.base,timeout=self.timeout) as c:
            info=c.get("/fapi/v1/exchangeInfo"); info.raise_for_status(); tradable={s["symbol"] for s in info.json().get("symbols",[]) if s.get("quoteAsset")=="USDT" and s.get("contractType")=="PERPETUAL" and s.get("status")=="TRADING"}
            tick=c.get("/fapi/v1/ticker/24hr"); tick.raise_for_status(); rows=[]
            for x in tick.json():
                if x.get("symbol") not in tradable: continue
                qv=float(x.get("quoteVolume",0)); pct=abs(float(x.get("priceChangePercent",0))); trades=float(x.get("count",0));
                # Cross-sectional anomaly/activity score; not a trade signal.
                rows.append({"symbol":x["symbol"],"quote_volume":qv,"abs_change_pct":pct,"trades_24h":trades})
        if not rows: return []
        by_vol=sorted(rows,key=lambda x:x["quote_volume"],reverse=True); vr={x["symbol"]:1-i/max(1,len(by_vol)-1) for i,x in enumerate(by_vol)}
        by_move=sorted(rows,key=lambda x:x["abs_change_pct"],reverse=True); mr={x["symbol"]:1-i/max(1,len(by_move)-1) for i,x in enumerate(by_move)}
        by_tr=sorted(rows,key=lambda x:x["trades_24h"],reverse=True); tr={x["symbol"]:1-i/max(1,len(by_tr)-1) for i,x in enumerate(by_tr)}
        for x in rows: x["radar_score"]=round((vr[x["symbol"]]*.5+mr[x["symbol"]]*.3+tr[x["symbol"]]*.2)*100,2)
        return sorted(rows,key=lambda x:x["radar_score"],reverse=True)[:limit]
