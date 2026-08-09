from scalp.strategies.base import Strategy
from scalp.models import Direction, DataMode
class RangeMeanReversion(Strategy):
    id="RB"
    def evaluate(self,r,reg,d,mode):
        long=d==Direction.LONG; p=float(r.close); atr=float(r.atr or 0); pos=float(r.range_pos if r.range_pos==r.range_pos else .5)
        edge=pos<=.20 if long else pos>=.80
        neutral=float(r.adx or 0)<=21 and abs(float(r.ema20_slope or 0))<=.12
        rsi=(r.rsi<=47) if long else (r.rsi>=53)
        reject=(r.close>r.open) if long else (r.close<r.open)
        ev={"STRUCTURE":.8 if neutral else -.5,"LIQUIDITY":.6 if edge else -.4,"VOLATILITY":.35 if reg["RANGE"]>20 else -.1,"ORDER_FLOW":.2 if reject else -.1}
        score=15+(28 if neutral else 0)+(28 if edge else 0)+(10 if rsi else 0)+(10 if reject else 0)
        rf=[]; ra=[]
        if neutral: rf.append("Low-trend range conditions")
        else: ra.append("Directional regime too strong")
        if edge: rf.append("Price located at range edge")
        else: ra.append("Price not near range edge")
        stop=(r.range_low-.25*atr) if long else (r.range_high+.25*atr); mid=(r.range_low+r.range_high)/2
        dist=abs(p-stop); er=abs(mid-p)/max(dist,1e-12)
        return self.result(d,score,ev,reg["RANGE"],mode,rf,ra,stop,mid,er,35,proxy=False)
