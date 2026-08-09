from __future__ import annotations
import itertools
from scalp.config import AppConfig
from scalp.backtest import BacktestEngine
from scalp.models import DataMode

def grid_search(base:AppConfig,frames,grid:dict[str,list],data_mode=DataMode.OHLCV_PROXY):
    keys=list(grid); rows=[]
    for vals in itertools.product(*[grid[k] for k in keys]):
        raw=base.model_dump(); params=dict(zip(keys,vals))
        for k,v in params.items():
            section,name=k.split('.',1); raw[section][name]=v
        cfg=AppConfig.model_validate(raw); r=BacktestEngine(cfg,data_mode).run(frames); s=r['summary']
        rows.append({**params,'net_pnl':s['net_pnl'],'profit_factor':s['profit_factor'],'max_drawdown_pct':s['max_drawdown_pct'],'trades':s['trades'],'avg_r':s['avg_r']})
    rows.sort(key=lambda x:(x['profit_factor'],x['net_pnl']),reverse=True)
    return rows
