from scalp.strategies.base import Strategy,val,missing
from scalp.models import Direction, DataMode
class LiquiditySweepReversal(Strategy):
    id="LSR"
    full_features=("ofi","microprice_change_bps","absorption_bid","absorption_ask","replenishment_bid","replenishment_ask","cvd_delta")
    def evaluate(self,r,reg,d,mode):
        long=d==Direction.LONG; p=float(val(r,"close")); atr=float(val(r,"atr")); low=val(r,"low"); high=val(r,"high"); rlow=val(r,"range_low"); rhigh=val(r,"range_high")
        sweep=(low<rlow and p>rlow) if long else (high>rhigh and p<rhigh)
        rejection=(val(r,"close_loc")>.62) if long else (val(r,"close_loc")<.38)
        rsi=(val(r,"rsi")<42) if long else (val(r,"rsi")>58); volume=val(r,"vol_ratio")>=1.1
        required=self.required_features(mode); miss=missing(r,required)
        if mode==DataMode.MICROSTRUCTURE and miss:
            return self.result(d,0,{},max(reg.get("RANGE",0),reg.get("EXHAUSTION",0)),mode,[],["Full LSR disabled: required microstructure features missing"],None,None,0,eligible=False,proxy=False,required=required,missing_features=miss)
        rf=[]; ra=[]
        if sweep: rf.append("Prior liquidity was swept and reclaimed")
        else: ra.append("No confirmed sweep/reclaim")
        if mode==DataMode.MICROSTRUCTURE:
            ofi=val(r,"ofi"); micro=val(r,"microprice_change_bps"); cvd=val(r,"cvd_delta"); scvd=val(r,"spot_cvd_delta")
            absorption=val(r,"absorption_bid" if long else "absorption_ask")
            replenish=val(r,"replenishment_bid" if long else "replenishment_ask")
            flow_turn=(ofi>0 and micro>=0) if long else (ofi<0 and micro<=0)
            aggressive_against=(cvd<0) if long else (cvd>0)
            spot_available=bool(r.get("spot_available", False))
            spot_fail=(scvd>0) if long else (scvd<0)
            absorbed=absorption>=.20 and replenish>0
            cross_score=(.35 if spot_fail else -.15) if spot_available else 0
            ev={"LIQUIDITY":.9 if sweep else -.5,"L2_MICROSTRUCTURE":.9 if absorbed else -.2,"ORDER_FLOW":.65 if flow_turn else -.2,"CROSS_MARKET":cross_score,"STRUCTURE":.55 if rejection else -.1}
            score=10+(34 if sweep else 0)+(20 if absorbed else 0)+(16 if flow_turn else 0)+(8 if aggressive_against else 0)+(6 if spot_available and spot_fail else 0)+(8 if rejection else 0)
            if absorbed: rf.append("Aggression is being absorbed with defending-side replenishment")
            if flow_turn: rf.append("OFI/microprice turned back through the swept level")
            if aggressive_against: rf.append("Large aggression made poor progress before reversal")
            if spot_available and spot_fail: rf.append("Spot flow confirms the reversal direction")
            elif not spot_available: ra.append("Spot confirmation unavailable")
            proxy=False
        else:
            ev={"LIQUIDITY":.9 if sweep else -.45,"STRUCTURE":.55 if rejection else -.1,"ORDER_FLOW":.25 if volume else 0,"VOLATILITY":.15}
            score=15+(42 if sweep else 0)+(15 if rejection else 0)+(12 if rsi else 0)+(8 if volume else 0)
            ra.append("LSR proxy: absorption/replenishment unavailable")
            proxy=True
        extreme=float(low if long else high); stop=extreme-.25*atr if long else extreme+.25*atr; dist=abs(p-stop); target=p+(1.6*dist if long else -1.6*dist)
        return self.result(d,score,ev,max(reg.get("RANGE",0),reg.get("EXHAUSTION",0)),mode,rf,ra,stop,target,1.6,72,proxy=proxy,required=required,missing_features=miss)
