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
from scalp.progress import emit_progress, map_progress

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
    def fetch_frames_range(self,symbols,interval,start,end,cfg=None,progress=None):
        cfg=cfg or self._cfg(interval); c=self.client(cfg); sm=utc_ms(start); em=utc_ms(end); symbols=[s.upper() for s in symbols]
        frames={}; total=max(1,len(symbols))
        for i,s in enumerate(symbols):
            local=map_progress(progress,i/total*100,(i+1)/total*100)
            frames[s]=c.klines(s,interval,sm,em,progress=local)
        emit_progress(progress,100,f"Historical data ready for {len(frames)} symbol(s)")
        return frames
    def fetch_frames(self,symbols,interval,lookback_days,cfg=None,progress=None):
        end=datetime.now(timezone.utc); start=end-timedelta(days=lookback_days); return self.fetch_frames_range(symbols,interval,start,end,cfg,progress)
    def run_range(self,symbols,interval,start,end,overrides=None,data_mode=DataMode.OHLCV_PROXY,progress=None):
        cfg=self._cfg(interval,overrides); emit_progress(progress,0,"Preparing backtest")
        frames=self.fetch_frames_range(symbols,interval,start,end,cfg,map_progress(progress,2,35))
        report=BacktestEngine(cfg,data_mode).run(frames,progress=map_progress(progress,35,99))
        emit_progress(progress,100,"Backtest complete")
        return report
    def run(self,symbols,interval,lookback_days,overrides=None,progress=None):
        end=datetime.now(timezone.utc); start=end-timedelta(days=lookback_days); return self.run_range(symbols,interval,start,end,overrides,progress=progress)
    def replay_range(self,symbols,interval,start,end,overrides=None,progress=None):
        cfg=self._cfg(interval,overrides); loader=RecordedFeatureLoader(cfg.storage.bulk_dir+"/features",cfg.storage.fallback_bulk_dir+"/features"); frames={}; coverage={}
        emit_progress(progress,0,"Loading locally recorded microstructure")
        symbols=[s.upper() for s in symbols]; total=max(1,len(symbols))
        for i,s in enumerate(symbols):
            emit_progress(progress,2+23*i/total,f"Loading recorded features for {s}")
            f=loader.load(s,start,end)
            if f.empty: continue
            bars=loader.to_bars(f,{"1m":"1min","3m":"3min","5m":"5min","15m":"15min"}.get(interval,interval),cfg.backtest.abort_below_microstructure_coverage_pct); frames[s]=bars
            expected=max(1,int((pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()*1000/cfg.live.feature_snapshot_ms)); coverage[s]=min(100,len(f)/expected*100)
        if not frames: raise ValueError("No locally recorded microstructure features found for selected range")
        below={s:v for s,v in coverage.items() if v < cfg.backtest.abort_below_microstructure_coverage_pct}
        if below:
            raise ValueError(f"Microstructure coverage below {cfg.backtest.abort_below_microstructure_coverage_pct}% for {below}; select a cleaner range or lower the explicit research threshold")
        emit_progress(progress,27,"Recorded data loaded; replaying strategies")
        report=BacktestEngine(cfg,DataMode.MICROSTRUCTURE).run(frames,progress=map_progress(progress,27,99)); report["coverage"]={"microstructure_pct":coverage,"source":"LOCAL_RECORDED","minimum_required_pct":cfg.backtest.abort_below_microstructure_coverage_pct}
        emit_progress(progress,100,"Microstructure replay complete")
        return report
    def walkforward(self,symbols,interval,lookback_days,overrides=None,tune=False,progress=None):
        cfg=self._cfg(interval,overrides); frames=self.fetch_frames(symbols,interval,lookback_days,cfg,map_progress(progress,0,22)); return WalkForwardRunner(cfg).run(frames,tune=tune,progress=map_progress(progress,22,100))
    def walkforward_range(self,symbols,interval,start,end,overrides=None,tune=False,progress=None):
        cfg=self._cfg(interval,overrides); frames=self.fetch_frames_range(symbols,interval,start,end,cfg,map_progress(progress,0,22)); return WalkForwardRunner(cfg).run(frames,tune=tune,progress=map_progress(progress,22,100))
    def optimize(self,symbols,interval,lookback_days,progress=None):
        cfg=self._cfg(interval); frames=self.fetch_frames(symbols,interval,lookback_days,cfg,map_progress(progress,0,20)); return grid_search(cfg,frames,{"strategies.min_score":[62,68,74],"strategies.min_separation":[6,10,14]},progress=map_progress(progress,20,100))
    def replay_tardis_sample(self,symbol,day,interval="1m",overrides=None,progress=None):
        cfg=self._cfg(interval,overrides); c=TardisSampleClient(); emit_progress(progress,0,"Downloading/checking Tardis L2 sample")
        book=c.download("incremental_book_L2",day,symbol); emit_progress(progress,15,"L2 sample ready; downloading/checking trades")
        trades=c.download("trades",day,symbol); emit_progress(progress,30,"Building 1-second microstructure features")
        feats=TardisReplayBuilder(book,trades).build(symbol.upper())
        if feats.empty: raise ValueError("Tardis sample produced no replayable features")
        emit_progress(progress,55,f"Built {len(feats):,} feature snapshots; resampling")
        bars=RecordedFeatureLoader.to_bars(feats,{"1m":"1min","3m":"3min","5m":"5min","15m":"15min"}.get(interval,interval),cfg.backtest.abort_below_microstructure_coverage_pct)
        report=BacktestEngine(cfg,DataMode.MICROSTRUCTURE).run({symbol.upper():bars},progress=map_progress(progress,58,99)); report["coverage"]={"source":"TARDIS_FREE_SAMPLE","day":str(day),"features":len(feats)}; emit_progress(progress,100,"Tardis replay complete"); return report
    def coverage(self,symbol,start,end):
        cfg=self.config(); db=IntegrityStore(Path(cfg.storage.state_dir)/"integrity.db"); return db.coverage(symbol.upper(),utc_ms(start),utc_ms(end))
