from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

class DataMode(str, Enum):
    OHLCV_PROXY = "OHLCV_PROXY"
    TRADE_FLOW = "TRADE_FLOW"
    MICROSTRUCTURE = "MICROSTRUCTURE"

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"

class ExecutionMode(str, Enum):
    PASSIVE = "PASSIVE_LIMIT"
    AGGRESSIVE = "AGGRESSIVE_LIMIT"
    MARKET = "MARKET"

class BookQuality(str, Enum):
    SYNCING = "SYNCING"
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    UNTRUSTED = "UNTRUSTED"
    RESYNCING = "RESYNCING"

class GapReason(str, Enum):
    POWER_LOSS = "POWER_LOSS"
    MANUAL_REBOOT = "MANUAL_REBOOT"
    PROCESS_CRASH = "PROCESS_CRASH"
    NETWORK_OUTAGE = "NETWORK_OUTAGE"
    BINANCE_DISCONNECT = "BINANCE_DISCONNECT"
    STREAM_SEQUENCE_GAP = "STREAM_SEQUENCE_GAP"
    DISK_FULL = "DISK_FULL"
    RECORDER_OVERLOAD = "RECORDER_OVERLOAD"
    CLOCK_SYNC_ERROR = "CLOCK_SYNC_ERROR"
    UNKNOWN = "UNKNOWN"

@dataclass
class Evidence:
    family: str
    bullish: float = 0.0
    bearish: float = 0.0
    available: bool = True
    reason: str = ""

@dataclass
class StrategyResult:
    strategy_id: str
    direction: Direction
    eligible: bool
    score: float
    evidence_agreement: float
    regime_compatibility: float
    execution_quality: float
    data_mode: DataMode
    proxy: bool
    reasons_for: list[str] = field(default_factory=list)
    reasons_against: list[str] = field(default_factory=list)
    evidence: dict[str, float] = field(default_factory=dict)
    stop_price: float | None = None
    target_price: float | None = None
    expected_r: float = 0.0
    urgency: float = 50.0
    required_features: list[str] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["direction"] = self.direction.value
        d["data_mode"] = self.data_mode.value
        return d

@dataclass
class Trade:
    trade_id: str
    symbol: str
    direction: str
    strategy_entry: str
    strategy_exit: str | None
    transitions: list[str]
    regime: str
    data_mode: str
    entry_time: str
    exit_time: str | None
    signal_price: float
    entry_price: float
    exit_price: float | None
    stop_initial: float
    stop_final: float
    target: float
    quantity: float
    remaining_quantity: float
    risk_pct: float
    setup_quality: float
    evidence_agreement: float
    execution_mode: str
    maker: bool
    fees: float = 0.0
    slippage: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str | None = None
    tp1_hit: bool = False
    reasons_for: list[str] = field(default_factory=list)
    reasons_against: list[str] = field(default_factory=list)
    invalid_data_gap: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
