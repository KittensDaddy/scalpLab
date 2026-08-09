from __future__ import annotations
from collections import defaultdict, deque
import math, time

class MicrostructureTracker:
    def __init__(self):
        self.cvd=defaultdict(float); self.spot_cvd=defaultdict(float); self.prev_metrics={}; self.flow=defaultdict(lambda:deque(maxlen=5000)); self.last_trade={}
        self.cancel_bid=defaultdict(float); self.cancel_ask=defaultdict(float); self.replenish_bid=defaultdict(float); self.replenish_ask=defaultdict(float)
        self.consumed_bid=defaultdict(float); self.consumed_ask=defaultdict(float); self.liquidation_buy=defaultdict(float); self.liquidation_sell=defaultdict(float)
        self.oi={}; self.prev_oi={}; self.funding={}

    def on_trade(self,symbol,price,qty,buyer_is_maker,market="futures",ts=None):
        # buyer_is_maker=True means aggressive seller hit bid.
        signed=-qty if buyer_is_maker else qty
        if market=="spot": self.spot_cvd[symbol]+=signed
        else: self.cvd[symbol]+=signed
        self.flow[(market,symbol)].append((ts or int(time.time()*1000),signed,qty,price))
        self.last_trade[(market,symbol)] = price

    def on_book_delta(self,symbol,stats):
        self.replenish_bid[symbol]+=float(stats.get("bid_added",0)); self.cancel_bid[symbol]+=float(stats.get("bid_removed",0))
        self.replenish_ask[symbol]+=float(stats.get("ask_added",0)); self.cancel_ask[symbol]+=float(stats.get("ask_removed",0))

    def on_liquidation(self,symbol,side,qty,price):
        notional=qty*price
        # Liquidation SELL corresponds long liquidation pressure; BUY corresponds short liquidation pressure.
        if side.upper()=="BUY": self.liquidation_buy[symbol]+=notional
        else: self.liquidation_sell[symbol]+=notional

    def set_oi(self,symbol,value): self.prev_oi[symbol]=self.oi.get(symbol,value); self.oi[symbol]=value
    def set_funding(self,symbol,value): self.funding[symbol]=value

    def snapshot(self,symbol,book_metrics:dict,spot_book_metrics:dict|None=None,now_ms=None):
        now_ms=now_ms or int(time.time()*1000); fut=list(self.flow[("futures",symbol)]); spot=list(self.flow[("spot",symbol)])
        def recent(items,ms=5000): return [x for x in items if now_ms-x[0]<=ms]
        fr=recent(fut); sr=recent(spot)
        buy=sum(max(x[1],0) for x in fr); sell=sum(max(-x[1],0) for x in fr); total=buy+sell
        sbuy=sum(max(x[1],0) for x in sr); ssell=sum(max(-x[1],0) for x in sr)
        oi=self.oi.get(symbol); poi=self.prev_oi.get(symbol)
        out=dict(book_metrics or {})
        out.update({
            "cvd":self.cvd[symbol],"spot_cvd":self.spot_cvd[symbol],"taker_imbalance":(buy-sell)/total if total else 0,
            "trade_velocity_5s":len(fr)/5,"aggressive_volume_5s":total,"spot_taker_imbalance":(sbuy-ssell)/(sbuy+ssell) if sbuy+ssell else 0,
            "spot_available": bool(sr or spot_book_metrics),
            "ofi":(float(out.get("depth_imbalance",0))*0.5)+(((buy-sell)/total if total else 0)*0.5),
            "replenishment_bid":self.replenish_bid[symbol],"replenishment_ask":self.replenish_ask[symbol],
            "cancel_bid":self.cancel_bid[symbol],"cancel_ask":self.cancel_ask[symbol],
            "oi":oi,"oi_delta":(oi-poi)/poi if oi is not None and poi not in (None,0) else 0,
            "oi_available": oi is not None,
            "funding_rate":self.funding.get(symbol,0),"funding_available": symbol in self.funding,
            "liquidation_buy_notional":self.liquidation_buy[symbol],"liquidation_sell_notional":self.liquidation_sell[symbol],
        })
        if spot_book_metrics:
            out["spot_mid"]=spot_book_metrics.get("mid"); out["spot_depth_imbalance"]=spot_book_metrics.get("depth_imbalance",0)
            if out.get("mid") and out.get("spot_mid"): out["spot_perp_basis_bps"]=(out["mid"]-out["spot_mid"])/out["spot_mid"]*10000
        prev=self.prev_metrics.get(symbol,{})
        out["microprice_change_bps"]=float(out.get("microprice_delta_bps",0))-float(prev.get("microprice_delta_bps",0))
        out["cvd_delta"]=self.cvd[symbol]-float(prev.get("cvd",self.cvd[symbol])); out["spot_cvd_delta"]=self.spot_cvd[symbol]-float(prev.get("spot_cvd",self.spot_cvd[symbol]))
        # Approximate absorption: heavy aggression with weak microprice response plus replenishment on defending side.
        resp=abs(float(out.get("microprice_change_bps",0)))
        out["absorption_bid"] = max(0.0, sell/(total or 1) * (1/(1+resp)) * min(1,self.replenish_bid[symbol]/(sell+1e-9)))
        out["absorption_ask"] = max(0.0, buy/(total or 1) * (1/(1+resp)) * min(1,self.replenish_ask[symbol]/(buy+1e-9)))
        self.prev_metrics[symbol]=dict(out)
        # Replenishment/cancellation/liquidation values are interval features, not lifetime counters.
        # Reset after every emitted snapshot so long-running recorder sessions do not inflate evidence.
        self.replenish_bid[symbol]=0.0; self.replenish_ask[symbol]=0.0
        self.cancel_bid[symbol]=0.0; self.cancel_ask[symbol]=0.0
        self.liquidation_buy[symbol]=0.0; self.liquidation_sell[symbol]=0.0
        return out
