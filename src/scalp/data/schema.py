from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class TradeEvent: timestamp:int; price:float; quantity:float; buyer_maker:bool
@dataclass(frozen=True)
class BookLevel: price:float; quantity:float
@dataclass(frozen=True)
class BookSnapshot: timestamp:int; bids:list[BookLevel]; asks:list[BookLevel]; update_id:int
@dataclass(frozen=True)
class OpenInterestPoint: timestamp:int; open_interest:float
@dataclass(frozen=True)
class FundingPoint: timestamp:int; funding_rate:float
@dataclass(frozen=True)
class LiquidationEvent: timestamp:int; side:str; price:float; quantity:float
