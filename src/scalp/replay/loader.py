from __future__ import annotations
from pathlib import Path
import gzip,json
import pandas as pd

class RecordedFeatureLoader:
    def __init__(self,root="/data/scalp/features",fallback="data/bulk/features"):
        self.root=Path(root) if Path(root).exists() else Path(fallback)
    def files(self,symbol,start=None,end=None):
        if not self.root.exists(): return []
        return sorted(self.root.rglob(f"*/{symbol.upper()}/*/feature/*.jsonl.gz"))
    def load(self,symbol,start,end):
        start=pd.Timestamp(start,tz="UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start).tz_convert("UTC")
        end=pd.Timestamp(end,tz="UTC") if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end).tz_convert("UTC")
        rows=[]
        for p in self.files(symbol,start,end):
            with gzip.open(p,"rt") as f:
                for line in f:
                    x=json.loads(line); ts=pd.to_datetime(x.get("receive_ts"),unit="ms",utc=True)
                    if start<=ts<=end: x["timestamp"]=ts; rows.append(x)
        return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True) if rows else pd.DataFrame()
    @staticmethod
    def to_bars(features:pd.DataFrame,interval="1min",min_coverage_pct=90.0):
        if features.empty: return features
        x=features.copy().set_index("timestamp")
        price=x["mid"].astype(float)
        base=pd.DataFrame({"open":price.resample(interval).first(),"high":price.resample(interval).max(),"low":price.resample(interval).min(),"close":price.resample(interval).last()})
        # Use aggressive volume as a transparent volume proxy for recorded microstructure replay.
        if "aggressive_volume_5s" in x: base["volume"]=x.aggressive_volume_5s.astype(float).resample(interval).sum()
        else: base["volume"]=1.0
        # Preserve sub-bar integrity. A bar can exist while several 1-second snapshots inside
        # it are missing, so timestamp continuity alone is insufficient for microstructure replay.
        sample_count=price.resample(interval).count()
        diffs=x.index.to_series().diff().dropna().dt.total_seconds()
        cadence=max(float(diffs.median()) if not diffs.empty else 1.0, 0.001)
        interval_seconds=pd.to_timedelta(interval).total_seconds()
        expected=max(1.0, interval_seconds/cadence)
        base["feature_coverage_pct"]=(sample_count/expected*100).clip(upper=100)
        base["data_quality_gap"]=base["feature_coverage_pct"] < float(min_coverage_pct)
        extra=["cvd","cvd_delta","spot_cvd","spot_cvd_delta","ofi","taker_imbalance","trade_velocity_5s","depth_imbalance","microprice","microprice_delta_bps","microprice_change_bps","replenishment_bid","replenishment_ask","cancel_bid","cancel_ask","absorption_bid","absorption_ask","oi","oi_delta","funding_rate","spot_perp_basis_bps","liquidation_buy_notional","liquidation_sell_notional","spread_bps"]
        for c in extra:
            if c in x: base[c]=pd.to_numeric(x[c],errors="coerce").resample(interval).last()
        # Availability is provenance, not a numeric neutral signal. A bar is available if any
        # underlying feature snapshot in that bar had the source online.
        for c in ["spot_available","oi_available","funding_available"]:
            if c in x: base[c]=x[c].fillna(False).astype(bool).resample(interval).max().astype(bool)
        base=base.dropna(subset=["open","high","low","close"]).reset_index()
        base["quote_volume"]=base.volume*base.close; base["trades"]=0; base["taker_buy_base"]=(base.volume*(base.get("taker_imbalance",0)+1)/2).clip(lower=0); base["taker_buy_quote"]=base.taker_buy_base*base.close
        return base
