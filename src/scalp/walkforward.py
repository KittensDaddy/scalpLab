from __future__ import annotations
from copy import deepcopy
from scalp.backtest import BacktestEngine
from scalp.models import DataMode
from scalp.config import AppConfig
from scalp.optimize import grid_search

class WalkForwardRunner:
    """Chronological rolling walk-forward. Risk policy is never optimized here."""
    def __init__(self,config,data_mode=DataMode.OHLCV_PROXY): self.config=config; self.data_mode=data_mode
    def run(self,frames,train_bars=None,validation_bars=None,test_bars=None,step_bars=None,expanding=False,tune=False):
        n=min(len(x) for x in frames.values())
        train_bars=train_bars or max(200,int(n*.50)); validation_bars=validation_bars or max(80,int(n*.15)); test_bars=test_bars or max(80,int(n*.15)); step_bars=step_bars or test_bars
        folds=[]; test_start=train_bars+validation_bars; fold=0
        while test_start<n:
            test_end=min(n,test_start+test_bars)
            if test_end-test_start<80: break
            train_start=0 if expanding else max(0,test_start-validation_bars-train_bars)
            train_end=test_start-validation_bars; val_start=train_end; val_end=test_start
            train={s:d.iloc[train_start:train_end].copy() for s,d in frames.items()}; val={s:d.iloc[val_start:val_end].copy() for s,d in frames.items()}; test={s:d.iloc[test_start:test_end].copy() for s,d in frames.items()}
            cfg=self.config; chosen={}
            if tune:
                grid={"strategies.min_score":[max(50,cfg.strategies.min_score-6),cfg.strategies.min_score,min(90,cfg.strategies.min_score+6)],"strategies.min_separation":[max(2,cfg.strategies.min_separation-4),cfg.strategies.min_separation,min(30,cfg.strategies.min_separation+4)]}
                candidates=grid_search(cfg,train,grid,self.data_mode)[:3]; best=None
                for cand in candidates:
                    raw=cfg.model_dump(); raw["strategies"]["min_score"]=cand["strategies.min_score"]; raw["strategies"]["min_separation"]=cand["strategies.min_separation"]
                    c=AppConfig.model_validate(raw); vr=BacktestEngine(c,self.data_mode).run(val); score=(vr["summary"]["profit_factor"],vr["summary"]["net_pnl"])
                    if best is None or score>best[0]: best=(score,c,cand,vr)
                if best: _,cfg,chosen,val_report=best
                else: val_report=BacktestEngine(cfg,self.data_mode).run(val)
            else: val_report=BacktestEngine(cfg,self.data_mode).run(val)
            train_report=BacktestEngine(cfg,self.data_mode).run(train); test_report=BacktestEngine(cfg,self.data_mode).run(test)
            folds.append({"fold":fold,"train":{"start":str(train[next(iter(train))].timestamp.iloc[0]),"end":str(train[next(iter(train))].timestamp.iloc[-1]),"summary":train_report["summary"]},"validation":{"start":str(val[next(iter(val))].timestamp.iloc[0]),"end":str(val[next(iter(val))].timestamp.iloc[-1]),"summary":val_report["summary"]},"test":{"start":str(test[next(iter(test))].timestamp.iloc[0]),"end":str(test[next(iter(test))].timestamp.iloc[-1]),"summary":test_report["summary"]},"chosen_params":chosen,"report":test_report})
            fold+=1; test_start+=step_bars
        if not folds: return {"error":"INSUFFICIENT_SAMPLE","folds":[],"summary":{}}
        tests=[f["test"]["summary"] for f in folds]; total_trades=sum(x["trades"] for x in tests); net=sum(x["net_pnl"] for x in tests); wins=sum(x["trades"]*x["win_rate"]/100 for x in tests)
        summary={"folds":len(folds),"net_pnl":round(net,2),"trades":total_trades,"win_rate":round(wins/total_trades*100,2) if total_trades else 0,"positive_folds_pct":round(sum(x["net_pnl"]>0 for x in tests)/len(tests)*100,2),"median_profit_factor":round(sorted(x["profit_factor"] for x in tests)[len(tests)//2],3),"max_fold_drawdown_pct":round(max(x["max_drawdown_pct"] for x in tests),2),"data_mode":self.data_mode.value,"tuned":tune}
        return {"summary":summary,"folds":folds}
