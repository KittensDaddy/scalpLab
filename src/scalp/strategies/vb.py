from scalp.strategies.base import Strategy
from scalp.models import Direction, DataMode
class VolatilityBreakout(Strategy):
    id="VB"
    def evaluate(self,r,reg,d,mode):
        long=d==Direction.LONG; p=float(r.close); atr=float(r.atr or 0)
        breakout=(r.close>r.prev_high20) if long else (r.close<r.prev_low20)
        compression=float(r.bb_width_pct or .5)<=.35
        expansion=float(r.vol_ratio or 0)>=1.35 and r.atr>=r.atr_ma
        closegood=(r.close_loc>=.68) if long else (r.close_loc<=.32)
        ev={"VOLATILITY":.85 if expansion else (.4 if compression else -.1),"STRUCTURE":.75 if breakout else -.4,"ORDER_FLOW":.25 if r.vol_ratio>=1.35 else 0}
        score=15+(36 if breakout else 0)+(18 if expansion else 0)+(12 if closegood else 0)+(10 if compression else 0)
        rf=[]; ra=[]
        if breakout: rf.append("Breakout beyond prior 20-bar structure")
        if compression: rf.append("Recent volatility compression")
        if expansion: rf.append("Volume/ATR expansion")
        if not breakout: ra.append("No structural breakout")
        level=float(r.prev_high20 if long else r.prev_low20); stop=level-.4*atr if long else level+.4*atr
        dist=abs(p-stop); target=p+(2.2*dist if long else -2.2*dist)
        return self.result(d,score,ev,max(reg["COMPRESSION"],reg["EXPANSION"]),mode,rf,ra,stop,target,2.2,82,proxy=False)
