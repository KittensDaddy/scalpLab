from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any

@dataclass(slots=True)
class MarketEvent:
    event_type: str
    exchange: str
    market: str
    symbol: str
    exchange_ts: int
    receive_ts: int
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    quality: str = "HEALTHY"
    source: str = "BINANCE_LIVE"
    def to_dict(self): return asdict(self)

@dataclass(slots=True)
class GapRecord:
    gap_id: str
    start_ts: int
    end_ts: int | None
    reason: str
    session_id: str | None
    symbol: str | None = None
    stream: str | None = None
    recoverable: bool = False
    repaired_source: str | None = None
    notes: str = ""
    def to_dict(self): return asdict(self)
