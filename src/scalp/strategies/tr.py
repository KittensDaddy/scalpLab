from scalp.strategies.base import Strategy,val,missing
from scalp.models import Direction, DataMode
class TrendReversal(Strategy):
    id="TR"
    full_features=("ofi","microprice_change_bps","absorption_bid","absorption_ask","cvd_delta")
    def evaluate(self,r,reg,d,mode):
        long=d==Direction.LONG; p=float(val(r,"close")); atr=float(val(r,"atr")); ema20=val(r,"ema20"); ema50=val(r,"ema50")
        prior=(ema20<ema50) if long else (ema20>ema50)
        reclaim=(p>ema20 and val(r,"rsi")>50) if long else (p<ema20 and val(r,"rsi")<50)
        candle_momentum=(val(r,"cvd_slope")>0) if long else (val(r,"cvd_slope")<0)
        extreme=(val(r,"low")<val(r,"range_low") and p>val(r,"range_low")) if long else (val(r,"high")>val(r,"range_high") and p<val(r,"range_high"))
        required=self.required_features(mode); miss=missing(r,required)
        if mode==DataMode.MICROSTRUCTURE and miss:
            return self.result(d,0,{},reg.get("TRANSITION",0),mode,[],["Full TR disabled: required microstructure features missing"],None,None,0,eligible=False,proxy=False,required=required,missing_features=miss)
        rf=[]; ra=[]
        if prior: rf.append("Established opposing trend existed")
        if reclaim: rf.append("Fast structure and momentum reclaimed")
        if extreme: rf.append("Failed extreme supports regime transition")
        if mode==DataMode.MICROSTRUCTURE:
            ofi=val(r,"ofi"); micro=val(r,"microprice_change_bps"); cvd=val(r,"cvd_delta"); scvd=val(r,"spot_cvd_delta"); oi=val(r,"oi_delta")
            absn=val(r,"absorption_bid" if long else "absorption_ask")
            flow=(ofi>0 and micro>0) if long else (ofi<0 and micro<0)
            spot_available=bool(r.get("spot_available", False))
            oi_available=bool(r.get("oi_available", False))
            divergence=(cvd>0 and scvd>0) if long else (cvd<0 and scvd<0)
            deleveraging=oi_available and oi<=0
            cross_score=(.45 if divergence else -.15) if spot_available else 0
            deriv_score=(.35 if deleveraging else -.1) if oi_available else 0
            ev={"STRUCTURE":.65 if prior and reclaim else -.15,"LIQUIDITY":.55 if extreme else 0,"ORDER_FLOW":.75 if flow else -.2,"L2_MICROSTRUCTURE":.7 if absn>=.18 else 0,"CROSS_MARKET":cross_score,"DERIVATIVES":deriv_score,"VOLATILITY":.25 if reg.get("TRANSITION",0)>15 else 0}
            score=8+(15 if prior else 0)+(22 if reclaim else 0)+(13 if extreme else 0)+(15 if flow else 0)+(10 if absn>=.18 else 0)+(8 if spot_available and divergence else 0)+(5 if deleveraging else 0)
            if flow: rf.append("OFI and microprice confirm directional turn")
            if absn>=.18: rf.append("Liquidity absorption supports reversal")
            if spot_available and divergence: rf.append("Spot/futures flow confirms turn")
            elif not spot_available: ra.append("Spot confirmation unavailable")
            if deleveraging: rf.append("OI is not expanding against reversal")
            elif not oi_available: ra.append("Open-interest confirmation unavailable")
            proxy=False
        else:
            ev={"STRUCTURE":.55 if prior and reclaim else -.2,"LIQUIDITY":.55 if extreme else 0,"ORDER_FLOW":.4 if candle_momentum else -.05,"VOLATILITY":.25 if reg.get("TRANSITION",0)>15 else 0}
            score=12+(20 if prior else 0)+(28 if reclaim else 0)+(15 if candle_momentum else 0)+(18 if extreme else 0)
            if candle_momentum: rf.append("Taker-flow proxy confirms turn")
            ra.append("TR structural proxy: L2/derivatives confirmation unavailable")
            proxy=True
        stop=(min(val(r,"low"),val(r,"range_low"))-.3*atr) if long else (max(val(r,"high"),val(r,"range_high"))+.3*atr); dist=abs(p-stop); target=p+(1.8*dist if long else -1.8*dist)
        return self.result(d,score,ev,reg.get("TRANSITION",0)+reg.get("EXHAUSTION",0)*.35,mode,rf,ra,stop,target,1.8,75,proxy=proxy,required=required,missing_features=miss)
