from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime
import math, uuid
import numpy as np
import pandas as pd

from scalp.config import AppConfig
from scalp.features import build_features, add_multitimeframe_context
from scalp.models import DataMode, Direction, ExecutionMode, Trade, StrategyResult
from scalp.regimes import dominant_regime
from scalp.decision import StrategyDecisionEngine
from scalp.calibration import score_calibration

@dataclass
class PendingOrder:
    symbol: str
    direction: Direction
    result: StrategyResult
    signal_time: pd.Timestamp
    signal_price: float
    risk_pct: float
    mode: ExecutionMode
    ttl: int
    regime: str = "UNKNOWN"

class BacktestEngine:
    def __init__(self, config: AppConfig, data_mode: DataMode = DataMode.OHLCV_PROXY):
        self.cfg=config
        self.data_mode=data_mode
        self.decision=StrategyDecisionEngine(config, data_mode)
        self.cash=float(config.risk.initial_equity)
        self.trades: list[Trade]=[]
        self.open_trades: dict[str,Trade]={}
        self.pending: dict[str,PendingOrder]={}
        self.no_trade=defaultdict(int)
        self.score_snapshots=[]
        self.equity_curve=[]
        self.last_selected={}
        self.frames={}
        self.indices={}

    def prepare(self, frames: dict[str,pd.DataFrame]):
        self.frames={}
        for symbol,raw in frames.items():
            df=build_features(add_multitimeframe_context(raw,self.cfg.data.interval)).dropna(subset=["atr","ema20","ema50","range_high","range_low","prev_high20","prev_low20"]).reset_index(drop=True)
            # A time discontinuity is data quality information. Never carry a microstructure trade silently across it.
            if len(df)>1:
                typical=df.timestamp.diff().dropna().median()
                df["data_gap_before"]=df.timestamp.diff() > typical*1.5
            else: df["data_gap_before"]=False
            if "data_quality_gap" in df.columns:
                df["data_gap_before"] = df["data_gap_before"].fillna(False) | df["data_quality_gap"].fillna(False).astype(bool)
            self.frames[symbol]=df
        self.indices={s:{ts:i for i,ts in enumerate(df.timestamp)} for s,df in self.frames.items()}

    def _strategy_results(self,row):
        d=self.decision.evaluate(row)
        return d.regimes,d.results

    def _select(self,results:list[StrategyResult]):
        return self.decision.select(results)

    def _execution_mode(self,r:StrategyResult):
        return self.decision.execution_mode(r)

    def _open_risk_pct(self):
        total=0.0
        for t in self.open_trades.values():
            if t.remaining_quantity<=0: continue
            ref=t.entry_price
            total += abs(t.remaining_quantity*(ref-t.stop_final))/max(self.cash,1e-9)*100
        for p in self.pending.values(): total+=p.risk_pct
        return total

    def _corr_multiplier(self,symbol,idx,direction):
        if not self.open_trades: return 1.0
        df=self.frames[symbol]
        start=max(0,idx-60); base=df.close.iloc[start:idx+1].pct_change().dropna()
        corrs=[]
        for osym,t in self.open_trades.items():
            if t.direction!=direction.value or osym==symbol: continue
            odf=self.frames.get(osym)
            if odf is None: continue
            a=df[["timestamp","close"]].iloc[start:idx+1].copy(); b=odf[["timestamp","close"]].copy()
            m=a.merge(b,on="timestamp",suffixes=("_a","_b"));
            if len(m)<20: continue
            c=m.close_a.pct_change().corr(m.close_b.pct_change())
            if pd.notna(c): corrs.append(float(c))
        if corrs and max(corrs)>=self.cfg.risk.correlation_threshold:
            return self.cfg.risk.correlated_risk_multiplier
        return 1.0

    def _plan_pending(self,symbol,row,idx,result,regime_name="UNKNOWN"):
        if symbol in self.open_trades or symbol in self.pending: return
        risk=min(self.cfg.risk.normal_risk_pct,self.cfg.risk.max_symbol_risk_pct)
        if result.strategy_id=="TR" and result.proxy: risk=min(risk,self.cfg.risk.c_mode_risk_pct)
        risk*=self._corr_multiplier(symbol,idx,result.direction)
        if self._open_risk_pct()+risk > self.cfg.risk.max_total_open_risk_pct:
            self.no_trade["NO_TRADE_PORTFOLIO_RISK"]+=1; return
        self.pending[symbol]=PendingOrder(symbol,result.direction,result,row.timestamp,float(row.close),risk,self._execution_mode(result),self.cfg.execution.passive_ttl_bars,regime_name)

    def _try_fill(self,symbol,row):
        p=self.pending.get(symbol)
        if not p: return
        side=1 if p.direction==Direction.LONG else -1
        openp=float(row.open); bps=1e-4
        maker=False
        if p.mode==ExecutionMode.MARKET:
            fill=openp*(1+side*self.cfg.execution.market_slippage_bps*bps)
        elif p.mode==ExecutionMode.AGGRESSIVE:
            fill=openp*(1+side*self.cfg.execution.aggressive_slippage_bps*bps)
        else:
            limit=p.signal_price*(1-side*self.cfg.execution.passive_offset_bps*bps)
            touched=(float(row.low)<=limit) if side>0 else (float(row.high)>=limit)
            if not touched:
                p.ttl-=1
                if p.ttl<=0:
                    self.pending.pop(symbol,None); self.no_trade["NO_TRADE_MISSED_FILL"]+=1
                return
            fill=limit; maker=True
        stop=float(p.result.stop_price or p.signal_price)
        if (side>0 and stop>=fill) or (side<0 and stop<=fill):
            dist=max(float(row.atr),fill*.0015); stop=fill-side*dist
        risk_dist=abs(fill-stop)
        if risk_dist<=0:
            self.pending.pop(symbol,None); return
        risk_amount=self.cash*(p.risk_pct/100)
        qty=risk_amount/risk_dist
        notional_cap=self.cash*(self.cfg.risk.max_position_notional_pct/100)
        qty=min(qty, notional_cap/max(fill,1e-12))
        if qty<=1e-12:
            self.pending.pop(symbol,None); return
        target=fill+side*max(p.result.expected_r,1.0)*risk_dist
        fee_rate=(self.cfg.execution.maker_fee_bps if maker else self.cfg.execution.taker_fee_bps)*1e-4
        entry_fee=abs(fill*qty)*fee_rate
        self.cash-=entry_fee
        trade=Trade(
            trade_id=str(uuid.uuid4())[:8],symbol=symbol,direction=p.direction.value,strategy_entry=p.result.strategy_id,
            strategy_exit=None,transitions=[p.result.strategy_id],regime=p.regime,data_mode=self.data_mode.value,
            entry_time=str(row.timestamp),exit_time=None,signal_price=p.signal_price,entry_price=fill,exit_price=None,
            stop_initial=stop,stop_final=stop,target=target,quantity=qty,remaining_quantity=qty,risk_pct=p.risk_pct,
            setup_quality=p.result.score,evidence_agreement=p.result.evidence_agreement,execution_mode=p.mode.value,maker=maker,
            fees=entry_fee,slippage=abs(fill-openp)*qty,net_pnl=-entry_fee,reasons_for=p.result.reasons_for,reasons_against=p.result.reasons_against)
        self.open_trades[symbol]=trade; self.pending.pop(symbol,None)

    def _close_qty(self,t:Trade,price:float,qty:float,reason:str,maker=False):
        side=1 if t.direction=="LONG" else -1
        gross=(price-t.entry_price)*qty*side
        fee_rate=(self.cfg.execution.maker_fee_bps if maker else self.cfg.execution.taker_fee_bps)*1e-4
        fee=abs(price*qty)*fee_rate
        t.gross_pnl+=gross; t.fees+=fee; t.net_pnl+=gross-fee
        self.cash+=gross-fee; t.remaining_quantity=max(0,t.remaining_quantity-qty)
        if t.remaining_quantity<=1e-12:
            t.exit_price=price; t.exit_reason=reason

    def _manage_trade(self,symbol,row,idx):
        t=self.open_trades.get(symbol)
        if not t: return
        side=1 if t.direction=="LONG" else -1
        if bool(row.get("data_gap_before",False)):
            t.invalid_data_gap=True
            # Conservative accounting: assume the protective stop was reached during an unresolved gap.
            self._close_qty(t,t.stop_final,t.remaining_quantity,"INVALID_DATA_GAP_CONSERVATIVE")
            self._finalize(symbol,row.timestamp); return
        stop=t.stop_final; target=t.target
        tp1=t.entry_price+side*self.cfg.backtest.tp1_r*abs(t.entry_price-t.stop_initial)
        stop_hit=(row.low<=stop) if side>0 else (row.high>=stop)
        target_hit=(row.high>=target) if side>0 else (row.low<=target)
        tp1_hit=(row.high>=tp1) if side>0 else (row.low<=tp1)
        if stop_hit and (target_hit or (tp1_hit and not t.tp1_hit)) and self.cfg.execution.stop_first_on_ambiguous_bar:
            self._close_qty(t,stop,t.remaining_quantity,"STOP_AMBIGUOUS_FIRST")
        else:
            if stop_hit:
                self._close_qty(t,stop,t.remaining_quantity,"STOP")
            elif target_hit:
                self._close_qty(t,target,t.remaining_quantity,"TARGET")
            elif tp1_hit and not t.tp1_hit:
                q=t.quantity*self.cfg.backtest.tp1_fraction
                self._close_qty(t,tp1,q,"TP1_PARTIAL")
                t.tp1_hit=True
                if self.cfg.backtest.move_stop_to_breakeven_after_tp1: t.stop_final=t.entry_price
        if t.remaining_quantity<=1e-12:
            self._finalize(symbol,row.timestamp); return
        # dynamic transition / opposing exit at bar close
        reg,results=self._strategy_results(row); selected,_=self._select(results)
        if selected:
            if selected.direction.value==t.direction and selected.strategy_id!=t.transitions[-1] and selected.score>=self.cfg.strategies.min_score+5:
                t.transitions.append(selected.strategy_id)
            elif selected.direction.value!=t.direction and selected.score>=self.cfg.strategies.min_score+8:
                px=float(row.close)*(1-side*self.cfg.execution.aggressive_slippage_bps*1e-4)
                t.strategy_exit=selected.strategy_id
                self._close_qty(t,px,t.remaining_quantity,"OPPOSING_STRATEGY")
                self._finalize(symbol,row.timestamp); return
        # max hold
        entry_idx=self.indices[symbol].get(pd.Timestamp(t.entry_time),idx)
        if idx-entry_idx>=self.cfg.execution.max_hold_bars:
            self._close_qty(t,float(row.close),t.remaining_quantity,"TIME_STOP")
            self._finalize(symbol,row.timestamp)

    def _finalize(self,symbol,ts):
        t=self.open_trades.pop(symbol)
        t.exit_time=str(ts)
        risk_amount=abs(t.entry_price-t.stop_initial)*t.quantity
        t.r_multiple=t.net_pnl/max(risk_amount,1e-12)
        self.trades.append(t)

    def run(self,frames:dict[str,pd.DataFrame]) -> dict:
        self.prepare(frames)
        timestamps=sorted(set().union(*[set(df.timestamp) for df in self.frames.values()]))
        for ts in timestamps:
            # fills then position management
            for symbol,df in self.frames.items():
                idx=self.indices[symbol].get(ts)
                if idx is None: continue
                row=df.iloc[idx]
                self._try_fill(symbol,row)
                self._manage_trade(symbol,row,idx)
            # signals after close -> next bar execution
            for symbol,df in self.frames.items():
                idx=self.indices[symbol].get(ts)
                if idx is None or idx<2 or symbol in self.open_trades or symbol in self.pending: continue
                row=df.iloc[idx]
                reg,results=self._strategy_results(row)
                winner,reason=self._select(results)
                best={f"{r.strategy_id}_{r.direction.value}":round(r.score,2) for r in results}
                self.score_snapshots.append({"timestamp":str(ts),"symbol":symbol,"regime":dominant_regime(reg),"scores":best,"selected":winner.strategy_id+"_"+winner.direction.value if winner else None,"no_trade":reason})
                if not winner:
                    self.no_trade[reason]+=1; continue
                self._plan_pending(symbol,row,idx,winner,dominant_regime(reg))
            mtm=self.cash
            for symbol,t in self.open_trades.items():
                idx=self.indices[symbol].get(ts)
                if idx is not None:
                    px=float(self.frames[symbol].iloc[idx].close); side=1 if t.direction=="LONG" else -1
                    mtm+=(px-t.entry_price)*t.remaining_quantity*side
            self.equity_curve.append({"timestamp":str(ts),"equity":mtm})
        # close remaining at final close
        for symbol in list(self.open_trades):
            df=self.frames[symbol]; row=df.iloc[-1]; t=self.open_trades[symbol]
            self._close_qty(t,float(row.close),t.remaining_quantity,"END_OF_TEST"); self._finalize(symbol,row.timestamp)
        return self.report()

    def report(self):
        trades=[t.to_dict() for t in self.trades]
        valid=[t for t in self.trades if not t.invalid_data_gap]
        invalid=[t for t in self.trades if t.invalid_data_gap]
        valid_net=sum(t.net_pnl for t in valid)
        accounting_net=self.cash-float(self.cfg.risk.initial_equity)
        gross=sum(t.gross_pnl for t in self.trades); fees=sum(t.fees for t in self.trades)
        invalid_gap_pnl=sum(t.net_pnl for t in invalid)
        wins=[t for t in valid if t.net_pnl>0]; losses=[t for t in valid if t.net_pnl<0]
        gp=sum(t.net_pnl for t in wins); gl=abs(sum(t.net_pnl for t in losses))
        eq=pd.DataFrame(self.equity_curve)
        maxdd=0.0
        if not eq.empty:
            peak=eq.equity.cummax(); dd=(peak-eq.equity)/peak.replace(0,np.nan); maxdd=float(dd.max() or 0)*100
        by_strategy={}
        for sid in ["TC","LC","LSR","RB","VB","TR"]:
            ts=[t for t in valid if t.strategy_entry==sid]
            by_strategy[sid]={"trades":len(ts),"net_pnl":round(sum(x.net_pnl for x in ts),4),"win_rate":round(100*sum(x.net_pnl>0 for x in ts)/len(ts),2) if ts else 0,"avg_r":round(sum(x.r_multiple for x in ts)/len(ts),3) if ts else 0}
        by_symbol={}
        for s in self.frames:
            ts=[t for t in valid if t.symbol==s]
            by_symbol[s]={"trades":len(ts),"net_pnl":round(sum(x.net_pnl for x in ts),4),"win_rate":round(100*sum(x.net_pnl>0 for x in ts)/len(ts),2) if ts else 0}
        by_regime={}
        for regime in sorted(set(t.regime for t in valid)):
            ts=[t for t in valid if t.regime==regime]
            by_regime[regime]={"trades":len(ts),"net_pnl":round(sum(x.net_pnl for x in ts),4),"win_rate":round(100*sum(x.net_pnl>0 for x in ts)/len(ts),2) if ts else 0,"avg_r":round(sum(x.r_multiple for x in ts)/len(ts),3) if ts else 0}
        by_direction={}
        for direction in ["LONG","SHORT"]:
            ts=[t for t in valid if t.direction==direction]
            by_direction[direction]={"trades":len(ts),"net_pnl":round(sum(x.net_pnl for x in ts),4),"win_rate":round(100*sum(x.net_pnl>0 for x in ts)/len(ts),2) if ts else 0,"avg_r":round(sum(x.r_multiple for x in ts)/len(ts),3) if ts else 0}
        r_bins={"<-2R":0,"-2..-1R":0,"-1..0R":0,"0..1R":0,"1..2R":0,">=2R":0}
        for t in valid:
            r=t.r_multiple
            key="<-2R" if r<-2 else "-2..-1R" if r<-1 else "-1..0R" if r<0 else "0..1R" if r<1 else "1..2R" if r<2 else ">=2R"
            r_bins[key]+=1
        return {
            "summary":{"initial_equity":self.cfg.risk.initial_equity,"ending_equity":round(self.cash,2),"net_pnl":round(accounting_net,2),"valid_trade_net_pnl":round(valid_net,2),"invalid_gap_pnl":round(invalid_gap_pnl,2),"gross_pnl":round(gross,2),"return_pct":round(accounting_net/self.cfg.risk.initial_equity*100,2),"trades":len(valid),"invalid_gap_trades":len(invalid),"win_rate":round(len(wins)/len(valid)*100,2) if valid else 0,"profit_factor":round(gp/gl,3) if gl else (999 if gp else 0),"avg_r":round(sum(t.r_multiple for t in valid)/len(valid),3) if valid else 0,"max_drawdown_pct":round(maxdd,2),"fees":round(fees,2),"data_mode":self.data_mode.value,"config_hash":self.cfg.hash()},
            "by_strategy":by_strategy,"by_symbol":by_symbol,"by_regime":by_regime,"by_direction":by_direction,"r_distribution":r_bins,"no_trade_reasons":dict(self.no_trade),"calibration":score_calibration([t.to_dict() for t in valid]),"equity_curve":self.equity_curve,"trades":trades,"score_snapshots":self.score_snapshots[-1000:]
        }
