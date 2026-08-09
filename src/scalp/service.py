from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
from scalp.config import AppConfig, load_config
from scalp.data.binance import BinanceFuturesClient, utc_ms
from scalp.backtest import BacktestEngine
from scalp.models import DataMode
from scalp.walkforward import WalkForwardRunner
from scalp.optimize import grid_search
from scalp.replay.loader import RecordedFeatureLoader
from scalp.live.integrity import IntegrityStore
from scalp.data.tardis import TardisSampleClient
from scalp.replay.tardis import TardisReplayBuilder

class ResearchService:
    def __init__(self,config_path="config/default.yaml"): self.config_path=config_path
    def config(self): return load_config(self.config_path)
    def client(self,cfg): return BinanceFuturesClient(cfg.data.request_timeout,cfg.data.request_pause_seconds,cfg.data.cache_dir)
    def symbols(self):
        cfg=self.config(); return self.client(cfg).usdt_perpetual_symbols()
    def _cfg(self,interval,overrides=None):
        cfg=self.config(); raw=cfg.model_dump()
        if overrides:
            for section,vals in overrides.items():
                if section in raw and isinstance(vals,dict): raw[section].update(vals)
        raw["data"]["interval"]=interval; return AppConfig.model_validate(raw)
    def fetch_frames_range(self,symbols,interval,start,end,cfg=None):
        cfg=cfg or self._cfg(interval); c=self.client(cfg); sm=utc_ms(start); em=utc_ms(end)
        return {s.upper():c.klines(s.upper(),interval,sm,em) for s in symbols}
    def fetch_frames(self,symbols,interval,lookback_days,cfg=None):
        end=datetime.now(timezone.utc); start=end-timedelta(days=lookback_days); return self.fetch_frames_range(symbols,interval,start,end,cfg)
    def run_range(self,symbols,interval,start,end,overrides=None,data_mode=DataMode.OHLCV_PROXY):
        cfg=self._cfg(interval,overrides); frames=self.fetch_frames_range(symbols,interval,start,end,cfg); return BacktestEngine(cfg,data_mode).run(frames)
    def run(self,symbols,interval,lookback_days,overrides=None):
        end=datetime.now(timezone.utc); start=end-timedelta(days=lookback_days); return self.run_range(symbols,interval,start,end,overrides)
    def replay_range(self,symbols,interval,start,end,overrides=None):
        cfg=self._cfg(interval,overrides); loader=RecordedFeatureLoader(cfg.storage.bulk_dir+"/features",cfg.storage.fallback_bulk_dir+"/features"); frames={}; coverage={}
        for s in symbols:
            f=loader.load(s,start,end)
            if f.empty: continue
            bars=loader.to_bars(f,{"1m":"1min","3m":"3min","5m":"5min","15m":"15min"}.get(interval,interval),cfg.backtest.abort_below_microstructure_coverage_pct); frames[s.upper()]=bars
            expected=max(1,int((pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()*1000/cfg.live.feature_snapshot_ms)); coverage[s.upper()]=min(100,len(f)/expected*100)
        if not frames: raise ValueError("No locally recorded microstructure features found for selected range")
        below={s:v for s,v in coverage.items() if v < cfg.backtest.abort_below_microstructure_coverage_pct}
        if below:
            raise ValueError(f"Microstructure coverage below {cfg.backtest.abort_below_microstructure_coverage_pct}% for {below}; select a cleaner range or lower the explicit research threshold")
        report=BacktestEngine(cfg,DataMode.MICROSTRUCTURE).run(frames); report["coverage"]={"microstructure_pct":coverage,"source":"LOCAL_RECORDED","minimum_required_pct":cfg.backtest.abort_below_microstructure_coverage_pct}; return report
    def walkforward(self,symbols,interval,lookback_days,overrides=None,tune=False):
        cfg=self._cfg(interval,overrides); frames=self.fetch_frames(symbols,interval,lookback_days,cfg); return WalkForwardRunner(cfg).run(frames,tune=tune)
    def walkforward_range(self,symbols,interval,start,end,overrides=None,tune=False):
        cfg=self._cfg(interval,overrides); frames=self.fetch_frames_range(symbols,interval,start,end,cfg); return WalkForwardRunner(cfg).run(frames,tune=tune)
    def optimize(self,symbols,interval,lookback_days):
        cfg=self._cfg(interval); frames=self.fetch_frames(symbols,interval,lookback_days,cfg); return grid_search(cfg,frames,{"strategies.min_score":[62,68,74],"strategies.min_separation":[6,10,14]})
    def replay_tardis_sample(self,symbol,day,interval="1m",overrides=None):
        cfg=self._cfg(interval,overrides); c=TardisSampleClient(); book=c.download("incremental_book_L2",day,symbol); trades=c.download("trades",day,symbol)
        feats=TardisReplayBuilder(book,trades).build(symbol.upper())
        if feats.empty: raise ValueError("Tardis sample produced no replayable features")
        bars=RecordedFeatureLoader.to_bars(feats,{"1m":"1min","3m":"3min","5m":"5min","15m":"15min"}.get(interval,interval),cfg.backtest.abort_below_microstructure_coverage_pct)
        report=BacktestEngine(cfg,DataMode.MICROSTRUCTURE).run({symbol.upper():bars}); report["coverage"]={"source":"TARDIS_FREE_SAMPLE","day":str(day),"features":len(feats)}; return report
    def coverage(self,symbol,start,end):
        cfg=self.config(); db=IntegrityStore(Path(cfg.storage.state_dir)/"integrity.db"); return db.coverage(symbol.upper(),utc_ms(start),utc_ms(end))
