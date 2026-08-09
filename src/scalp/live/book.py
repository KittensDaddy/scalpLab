from __future__ import annotations
from dataclasses import dataclass, field
from scalp.models import BookQuality

class SequenceGap(RuntimeError): pass

@dataclass
class LocalOrderBook:
    symbol: str
    bids: dict[float,float] = field(default_factory=dict)
    asks: dict[float,float] = field(default_factory=dict)
    last_update_id: int | None = None
    quality: BookQuality = BookQuality.SYNCING

    def reset(self):
        self.bids.clear(); self.asks.clear(); self.last_update_id=None; self.quality=BookQuality.RESYNCING

    def apply_snapshot(self, snapshot: dict):
        self.bids = {float(p):float(q) for p,q in snapshot.get("bids",[]) if float(q)>0}
        self.asks = {float(p):float(q) for p,q in snapshot.get("asks",[]) if float(q)>0}
        self.last_update_id = int(snapshot["lastUpdateId"])
        self.quality = BookQuality.SYNCING

    @staticmethod
    def _apply_side(side: dict[float,float], updates):
        added=removed=changed=0.0
        for p,q in updates:
            p=float(p); q=float(q); old=side.get(p,0.0)
            if q == 0:
                if old: removed += old
                side.pop(p,None)
            else:
                if old == 0: added += q
                elif q > old: added += q-old
                else: removed += old-q
                side[p]=q
                changed += abs(q-old)
        return added,removed,changed

    def apply_futures_delta(self, data: dict) -> dict:
        """Apply USD-M diff-depth using U/u/pu continuity semantics."""
        if self.last_update_id is None:
            return {"applied":False,"reason":"NO_SNAPSHOT"}
        U=int(data.get("U",0)); u=int(data.get("u",0)); pu=data.get("pu")
        if u <= self.last_update_id:
            return {"applied":False,"reason":"STALE"}
        if self.quality in {BookQuality.SYNCING, BookQuality.RESYNCING}:
            if not (U <= self.last_update_id + 1 <= u):
                return {"applied":False,"reason":"WAITING_BRIDGE"}
        elif pu is not None and int(pu) != self.last_update_id:
            self.quality=BookQuality.SEQUENCE_GAP
            raise SequenceGap(f"{self.symbol}: pu={pu} expected {self.last_update_id}")
        ba,br,bc=self._apply_side(self.bids,data.get("b",[])); aa,ar,ac=self._apply_side(self.asks,data.get("a",[]))
        self.last_update_id=u; self.quality=BookQuality.HEALTHY
        return {"applied":True,"bid_added":ba,"bid_removed":br,"ask_added":aa,"ask_removed":ar,"changed":bc+ac}

    def apply_spot_delta(self, data: dict) -> dict:
        if self.last_update_id is None: return {"applied":False,"reason":"NO_SNAPSHOT"}
        U=int(data.get("U",0)); u=int(data.get("u",0))
        if u <= self.last_update_id: return {"applied":False,"reason":"STALE"}
        if U > self.last_update_id+1:
            self.quality=BookQuality.SEQUENCE_GAP
            raise SequenceGap(f"{self.symbol}: spot U={U} expected <= {self.last_update_id+1}")
        ba,br,bc=self._apply_side(self.bids,data.get("b",[])); aa,ar,ac=self._apply_side(self.asks,data.get("a",[]))
        self.last_update_id=u; self.quality=BookQuality.HEALTHY
        return {"applied":True,"bid_added":ba,"bid_removed":br,"ask_added":aa,"ask_removed":ar,"changed":bc+ac}

    @property
    def best_bid(self): return max(self.bids) if self.bids else None
    @property
    def best_ask(self): return min(self.asks) if self.asks else None
    def top(self,n=20):
        bids=sorted(self.bids.items(),reverse=True)[:n]; asks=sorted(self.asks.items())[:n]
        return bids,asks
    def metrics(self,n=20):
        bid=self.best_bid; ask=self.best_ask
        if bid is None or ask is None: return {}
        bq=self.bids.get(bid,0.0); aq=self.asks.get(ask,0.0); den=bq+aq
        mid=(bid+ask)/2; micro=(ask*bq+bid*aq)/den if den else mid
        bids,asks=self.top(n); bd=sum(q for _,q in bids); ad=sum(q for _,q in asks); depth=bd+ad
        return {
            "best_bid":bid,"best_ask":ask,"mid":mid,"spread":ask-bid,"spread_bps":(ask-bid)/mid*10000 if mid else 0,
            "microprice":micro,"microprice_delta_bps":(micro-mid)/mid*10000 if mid else 0,
            "depth_bid":bd,"depth_ask":ad,"depth_imbalance":(bd-ad)/depth if depth else 0,
        }
