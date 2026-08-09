from __future__ import annotations
import itertools
from scalp.config import AppConfig
from scalp.backtest import BacktestEngine
from scalp.models import DataMode
from scalp.progress import emit_progress, map_progress

def grid_search(base:AppConfig,frames,grid:dict[str,list],data_mode=DataMode.OHLCV_PROXY,progress=None):
    keys=list(grid); rows=[]; combos=list(itertools.product(*[grid[k] for k in keys])); total=max(1,len(combos))
    for i,vals in enumerate(combos):
        raw=base.model_dump(); params=dict(zip(keys,vals))
        for k,v in params.items():
            section,name=k.split('.',1); raw[section][name]=v
        emit_progress(progress,i/total*100,f"Optimization {i+1}/{total}: {params}")
        cfg=AppConfig.model_validate(raw); r=BacktestEngine(cfg,data_mode).run(frames,progress=map_progress(progress,i/total*100,(i+1)/total*100)); s=r['summary']
        rows.append({**params,'net_pnl':s['net_pnl'],'profit_factor':s['profit_factor'],'max_drawdown_pct':s['max_drawdown_pct'],'trades':s['trades'],'avg_r':s['avg_r']})
    rows.sort(key=lambda x:(x['profit_factor'],x['net_pnl']),reverse=True)
    emit_progress(progress,100,f"Optimization complete · {len(rows)} parameter sets")
    return rows
