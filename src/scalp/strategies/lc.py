from scalp.strategies.base import Strategy,val,missing
from scalp.models import Direction, DataMode
class LiquidityCascade(Strategy):
    id="LC"
    full_features=("ofi","depth_imbalance","microprice_change_bps","replenishment_bid","replenishment_ask","cvd_delta")
    def evaluate(self,r,reg,d,mode):
        long=d==Direction.LONG; p=float(val(r,"close")); atr=float(val(r,"atr")); lvl=float(val(r,"prev_high20") if long else val(r,"prev_low20"))
        breakout=(p>lvl and val(r,"close_loc")>.65) if long else (p<lvl and val(r,"close_loc")<.35)
        volume=val(r,"vol_ratio")>=1.35; expand=atr>=val(r,"atr_ma",atr or 1)*1.05
        flow=(val(r,"taker_buy_share",.5)>=.56) if long else (val(r,"taker_buy_share",.5)<=.44)
        continuation=(val(r,"ret1")>0) if long else (val(r,"ret1")<0)
        required=self.required_features(mode); miss=missing(r,required)
        full=mode==DataMode.MICROSTRUCTURE and not miss
        if mode==DataMode.MICROSTRUCTURE and miss:
            return self.result(d,0,{},reg.get("EXPANSION",0),mode,[],["Full LC disabled: required microstructure features missing"],None,None,0,eligible=False,proxy=False,required=required,missing_features=miss)
        rf=[]; ra=[]
        if breakout: rf.append("Prior liquidity level broken with close acceptance")
        else: ra.append("No accepted liquidity break")
        if volume: rf.append("Relative volume expanded")
        if full:
            ofi=val(r,"ofi"); imb=val(r,"depth_imbalance"); micro=val(r,"microprice_change_bps"); cvd=val(r,"cvd_delta"); scvd=val(r,"spot_cvd_delta")
            book=(ofi>0.12 and imb>0.08 and micro>=0) if long else (ofi<-0.12 and imb<-0.08 and micro<=0)
            flow_full=(cvd>0) if long else (cvd<0)
            spot_available=bool(r.get("spot_available", False))
            spot=(scvd>0) if long else (scvd<0)
            opposing_replenish=val(r,"replenishment_ask" if long else "replenishment_bid")
            supporting_replenish=val(r,"replenishment_bid" if long else "replenishment_ask")
            follow=supporting_replenish>=opposing_replenish*.45
            cross_score=(.45 if spot else -.2) if spot_available else 0
            ev={"LIQUIDITY":.85 if breakout else -.6,"ORDER_FLOW":.8 if flow_full else -.35,"L2_MICROSTRUCTURE":.85 if book and follow else -.35,"CROSS_MARKET":cross_score,"VOLATILITY":.55 if expand else .05,"STRUCTURE":.5 if continuation else -.15}
            score=8+(38 if breakout else 0)+(14 if flow_full else 0)+(16 if book else 0)+(8 if follow else 0)+(7 if spot_available and spot else 0)+(7 if expand else 0)
            if flow_full: rf.append("CVD supports continuation")
            if book: rf.append("OFI/depth/microprice support accepted continuation")
            if follow: rf.append("Supporting depth replenishes as price advances")
            if spot_available and spot: rf.append("Spot flow confirms futures")
            elif not spot_available: ra.append("Spot confirmation unavailable")
            proxy=False
        else:
            ev={"LIQUIDITY":.75 if breakout else -.5,"ORDER_FLOW":.55 if flow else -.1,"VOLATILITY":.55 if expand else .05,"STRUCTURE":.45 if continuation else -.1}
            score=10+(48 if breakout else 0)+(14 if volume else 0)+(10 if expand else 0)+(10 if flow else 0)+(8 if continuation else 0)
            if flow: rf.append("Taker flow proxy supports breakout")
            ra.append("LC proxy: event-level book acceptance/consumption unavailable")
            proxy=True
        stop=(lvl-.35*atr) if long else (lvl+.35*atr); dist=abs(p-stop); target=p+(2.0*dist if long else -2.0*dist)
        return self.result(d,score,ev,reg.get("EXPANSION",0),mode,rf,ra,stop,target,2.0,88,proxy=proxy,required=required,missing_features=miss)
