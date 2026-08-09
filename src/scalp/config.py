from __future__ import annotations
from pathlib import Path
import hashlib, json, yaml
from pydantic import BaseModel, Field, model_validator

class DataConfig(BaseModel):
    interval: str = "5m"
    lookback_days: int = Field(14, ge=1, le=3650)
    cache_dir: str = "data/cache"
    request_timeout: float = Field(15, gt=0)
    request_pause_seconds: float = Field(0.12, ge=0)

class StrategyConfig(BaseModel):
    enabled: list[str] = ["TC", "LC", "LSR", "RB", "VB", "TR"]
    min_score: float = Field(68, ge=0, le=100)
    min_separation: float = Field(10, ge=0, le=100)
    min_evidence_agreement: float = Field(45, ge=0, le=100)
    min_expected_r: float = Field(1.15, ge=0)

class RiskConfig(BaseModel):
    initial_equity: float = Field(10000, gt=0)
    normal_risk_pct: float = Field(0.50, gt=0, le=5)
    c_mode_risk_pct: float = Field(0.25, gt=0, le=2)
    max_symbol_risk_pct: float = Field(0.75, gt=0, le=5)
    max_total_open_risk_pct: float = Field(2.0, gt=0, le=10)
    max_same_direction_beta_risk_pct: float = Field(1.25, gt=0, le=10)
    correlation_threshold: float = Field(0.70, ge=0, le=1)
    correlated_risk_multiplier: float = Field(0.50, gt=0, le=1)
    max_position_notional_pct: float = Field(100.0, gt=0, le=1000)

class ExecutionConfig(BaseModel):
    maker_fee_bps: float = Field(2.0, ge=0)
    taker_fee_bps: float = Field(5.0, ge=0)
    market_slippage_bps: float = Field(1.5, ge=0)
    aggressive_slippage_bps: float = Field(0.6, ge=0)
    passive_offset_bps: float = Field(0.5, ge=0)
    passive_ttl_bars: int = Field(2, ge=1, le=20)
    default_spread_bps: float = Field(1.0, ge=0)
    stop_first_on_ambiguous_bar: bool = True
    max_hold_bars: int = Field(12, ge=1, le=500)

class BacktestConfig(BaseModel):
    tp1_r: float = Field(1.0, gt=0)
    tp1_fraction: float = Field(0.50, gt=0, lt=1)
    move_stop_to_breakeven_after_tp1: bool = True
    seed: int = 42
    abort_below_microstructure_coverage_pct: float = Field(90.0, ge=0, le=100)
    exclude_gap_periods: bool = True

class StorageConfig(BaseModel):
    state_dir: str = "data/state"
    bulk_dir: str = "/data/scalp"
    fallback_bulk_dir: str = "data/bulk"
    raw_segment_seconds: int = Field(60, ge=10, le=3600)
    feature_segment_seconds: int = Field(300, ge=30, le=3600)
    ram_buffer_events: int = Field(10000, ge=100, le=500000)
    raw_l2_retention_days: int = Field(30, ge=1, le=3650)
    warning_pct: float = Field(80.0, ge=1, le=99)
    pressure_pct: float = Field(90.0, ge=1, le=99.5)
    emergency_pct: float = Field(95.0, ge=1, le=99.9)

class LiveConfig(BaseModel):
    futures_ws_base: str = "wss://fstream.binance.com/stream"
    spot_ws_base: str = "wss://stream.binance.com:9443/stream"
    futures_rest_base: str = "https://fapi.binance.com"
    spot_rest_base: str = "https://api.binance.com"
    symbols: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    full_l2_symbols: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    depth_levels: int = Field(1000, ge=100, le=1000)
    depth_speed: str = "100ms"
    feature_snapshot_ms: int = Field(1000, ge=100, le=60000)
    heartbeat_seconds: int = Field(5, ge=1, le=60)
    reconnect_max_seconds: int = Field(60, ge=2, le=600)
    oi_poll_seconds: int = Field(60, ge=15, le=3600)
    funding_poll_seconds: int = Field(300, ge=60, le=7200)
    record_spot_depth: bool = False
    record_force_orders: bool = True

class ShadowConfig(BaseModel):
    enabled: bool = False
    interval: str = "1m"
    seed_lookback_bars: int = Field(120, ge=60, le=1500)
    persist_path: str = "results/shadow.db"
    max_signals_per_symbol: int = Field(1, ge=1, le=10)

class AppConfig(BaseModel):
    data: DataConfig = DataConfig()
    strategies: StrategyConfig = StrategyConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    backtest: BacktestConfig = BacktestConfig()
    storage: StorageConfig = StorageConfig()
    live: LiveConfig = LiveConfig()
    shadow: ShadowConfig = ShadowConfig()

    @model_validator(mode="after")
    def validate_all(self):
        if self.risk.normal_risk_pct > self.risk.max_symbol_risk_pct:
            raise ValueError("normal_risk_pct cannot exceed max_symbol_risk_pct")
        if self.risk.max_symbol_risk_pct > self.risk.max_total_open_risk_pct:
            raise ValueError("max_symbol_risk_pct cannot exceed max_total_open_risk_pct")
        valid = {"TC","LC","LSR","RB","VB","TR"}
        bad = set(self.strategies.enabled) - valid
        if bad:
            raise ValueError(f"Unknown strategies: {sorted(bad)}")
        if not (self.storage.warning_pct < self.storage.pressure_pct < self.storage.emergency_pct):
            raise ValueError("storage thresholds must be warning < pressure < emergency")
        if len(set(self.live.full_l2_symbols)) > 4:
            raise ValueError("full_l2_symbols is capped at four")
        return self

    def hash(self) -> str:
        raw = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

def load_config(path: str | Path | None = None) -> AppConfig:
    path = Path(path or "config/default.yaml")
    if path.exists():
        return AppConfig.model_validate(yaml.safe_load(path.read_text()) or {})
    return AppConfig()
