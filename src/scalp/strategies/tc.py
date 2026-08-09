from scalp.strategies.base import Strategy, clamp
from scalp.models import Direction, DataMode
class TrendContinuation(Strategy):
    id="TC"
    def evaluate(self,r,reg,d,mode):
        p=float(r.close); atr=float(r.atr or 0); long=d==Direction.LONG
        trend=(r.ema20>r.ema50) if long else (r.ema20<r.ema50)
        slope=(r.ema20_slope>0) if long else (r.ema20_slope<0)
        near=abs(p-float(r.ema20)) <= max(atr*.65,p*.001)
        reclaim=(p>=r.ema20 and r.close>=r.open) if long else (p<=r.ema20 and r.close<=r.open)
        flow=(float(r.taker_buy_share or .5)>=.52) if long else (float(r.taker_buy_share or .5)<=.48)
        ev={"STRUCTURE":.9 if trend else -.7,"VOLATILITY":.35 if r.adx>=18 else .05,"ORDER_FLOW":.45 if flow else -.15,"MACRO_CRYPTO":.35 if slope else -.2}
        score=25+(30 if trend else -15)+(15 if near else 0)+(15 if reclaim else 0)+(10 if r.adx>=18 else 0)+(10 if flow else 0)
        rf=[]; ra=[]
        if trend: rf.append("EMA structure aligned with trend")
        else: ra.append("Trend structure not aligned")
        if near: rf.append("Pullback reached fast trend area")
        if reclaim: rf.append("Pullback closed back with trend")
        if flow: rf.append("Taker flow supports continuation")
        stop=(min(r.low,r.ema20)-.35*atr) if long else (max(r.high,r.ema20)+.35*atr)
        dist=abs(p-stop); target=p+(1.8*dist if long else -1.8*dist)
        return self.result(d,score,ev,reg["TREND_UP" if long else "TREND_DOWN"],mode,rf,ra,stop,target,1.8,60,proxy=False)
