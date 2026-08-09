from __future__ import annotations
from scalp.backtest import BacktestEngine
from scalp.models import DataMode
from scalp.config import AppConfig
from scalp.optimize import grid_search
from scalp.progress import emit_progress, map_progress

class WalkForwardRunner:
    """Chronological rolling walk-forward. Risk policy is never optimized here."""
    def __init__(self,config,data_mode=DataMode.OHLCV_PROXY): self.config=config; self.data_mode=data_mode
    def run(self,frames,train_bars=None,validation_bars=None,test_bars=None,step_bars=None,expanding=False,tune=False,progress=None):
        n=min(len(x) for x in frames.values())
        train_bars=train_bars or max(200,int(n*.50)); validation_bars=validation_bars or max(80,int(n*.15)); test_bars=test_bars or max(80,int(n*.15)); step_bars=step_bars or test_bars
        # Determine fold count up front so progress is meaningful.
        starts=[]; cursor=train_bars+validation_bars
        while cursor<n:
            if min(n,cursor+test_bars)-cursor<80: break
            starts.append(cursor); cursor+=step_bars
        if not starts: return {"error":"INSUFFICIENT_SAMPLE","folds":[],"summary":{}}
        folds=[]
        for fold,test_start in enumerate(starts):
            fold_cb=map_progress(progress,fold/len(starts)*100,(fold+1)/len(starts)*100)
            test_end=min(n,test_start+test_bars); train_start=0 if expanding else max(0,test_start-validation_bars-train_bars); train_end=test_start-validation_bars; val_start=train_end; val_end=test_start
            train={s:d.iloc[train_start:train_end].copy() for s,d in frames.items()}; val={s:d.iloc[val_start:val_end].copy() for s,d in frames.items()}; test={s:d.iloc[test_start:test_end].copy() for s,d in frames.items()}
            cfg=self.config; chosen={}; emit_progress(fold_cb,0,f"Fold {fold+1}/{len(starts)}: preparing")
            if tune:
                grid={"strategies.min_score":[max(50,cfg.strategies.min_score-6),cfg.strategies.min_score,min(90,cfg.strategies.min_score+6)],"strategies.min_separation":[max(2,cfg.strategies.min_separation-4),cfg.strategies.min_separation,min(30,cfg.strategies.min_separation+4)]}
                candidates=grid_search(cfg,train,grid,self.data_mode,progress=map_progress(fold_cb,3,50))[:3]; best=None
                for j,cand in enumerate(candidates):
                    emit_progress(fold_cb,50+j/max(1,len(candidates))*18,f"Fold {fold+1}: validating candidate {j+1}/{len(candidates)}")
                    raw=cfg.model_dump(); raw["strategies"]["min_score"]=cand["strategies.min_score"]; raw["strategies"]["min_separation"]=cand["strategies.min_separation"]
                    c=AppConfig.model_validate(raw); vr=BacktestEngine(c,self.data_mode).run(val); score=(vr["summary"]["profit_factor"],vr["summary"]["net_pnl"])
                    if best is None or score>best[0]: best=(score,c,cand,vr)
                if best: _,cfg,chosen,val_report=best
                else: val_report=BacktestEngine(cfg,self.data_mode).run(val)
                emit_progress(fold_cb,70,f"Fold {fold+1}: frozen parameters selected")
            else:
                val_report=BacktestEngine(cfg,self.data_mode).run(val,progress=map_progress(fold_cb,5,30))
            train_report=BacktestEngine(cfg,self.data_mode).run(train,progress=map_progress(fold_cb,72 if tune else 30,84 if tune else 60))
            test_report=BacktestEngine(cfg,self.data_mode).run(test,progress=map_progress(fold_cb,84 if tune else 60,100))
            folds.append({"fold":fold,"train":{"start":str(train[next(iter(train))].timestamp.iloc[0]),"end":str(train[next(iter(train))].timestamp.iloc[-1]),"summary":train_report["summary"]},"validation":{"start":str(val[next(iter(val))].timestamp.iloc[0]),"end":str(val[next(iter(val))].timestamp.iloc[-1]),"summary":val_report["summary"]},"test":{"start":str(test[next(iter(test))].timestamp.iloc[0]),"end":str(test[next(iter(test))].timestamp.iloc[-1]),"summary":test_report["summary"]},"chosen_params":chosen,"report":test_report})
        tests=[f["test"]["summary"] for f in folds]; total_trades=sum(x["trades"] for x in tests); net=sum(x["net_pnl"] for x in tests); wins=sum(x["trades"]*x["win_rate"]/100 for x in tests)
        summary={"folds":len(folds),"net_pnl":round(net,2),"trades":total_trades,"win_rate":round(wins/total_trades*100,2) if total_trades else 0,"positive_folds_pct":round(sum(x["net_pnl"]>0 for x in tests)/len(tests)*100,2),"median_profit_factor":round(sorted(x["profit_factor"] for x in tests)[len(tests)//2],3),"max_fold_drawdown_pct":round(max(x["max_drawdown_pct"] for x in tests),2),"data_mode":self.data_mode.value,"tuned":tune}
        emit_progress(progress,100,f"Walk-forward complete · {len(folds)} folds")
        return {"summary":summary,"folds":folds}
