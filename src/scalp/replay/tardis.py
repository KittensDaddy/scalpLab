from __future__ import annotations
import csv,gzip,heapq
from pathlib import Path
import pandas as pd
from scalp.live.book import LocalOrderBook
from scalp.live.microstructure import MicrostructureTracker
from scalp.models import BookQuality

class TardisReplayBuilder:
    """Build 1-second microstructure features from normalized Tardis incremental L2 + trades CSV.gz."""
    def __init__(self,book_file,trades_file=None): self.book_file=Path(book_file); self.trades_file=Path(trades_file) if trades_file else None
    @staticmethod
    def _rows(path,kind):
        if not path or not path.exists(): return
        with gzip.open(path,"rt",newline="") as f:
            for row in csv.DictReader(f):
                ts=int(row.get("local_timestamp") or row.get("timestamp") or 0); yield ts,kind,row
    def build(self,symbol):
        streams=[self._rows(self.book_file,"book")]
        if self.trades_file: streams.append(self._rows(self.trades_file,"trade"))
        merged=heapq.merge(*streams,key=lambda x:x[0]); book=LocalOrderBook(symbol); book.quality=BookQuality.SYNCING; micro=MicrostructureTracker(); rows=[]; current_sec=None; snapshot_active=False; have_snapshot=False
        for ts,kind,row in merged:
            sec=ts//1_000_000
            if current_sec is not None and sec>current_sec and book.bids and book.asks:
                ms=current_sec*1000; snap=micro.snapshot(symbol,book.metrics(),None,ms); snap.update({"timestamp":pd.to_datetime(ms,unit="ms",utc=True),"quality":"HEALTHY","source":"TARDIS"}); rows.append(snap)
            current_sec=sec
            if kind=="book":
                is_snapshot=str(row.get("is_snapshot","")).lower()=="true"; side=row.get("side"); price=float(row.get("price",0)); amount=float(row.get("amount",0))
                # Tardis may contain buffered deltas before the first generated snapshot.
                # They cannot establish book state and must be ignored until snapshot begins.
                if not is_snapshot and not have_snapshot:
                    continue
                if is_snapshot and not snapshot_active:
                    book.bids.clear(); book.asks.clear(); snapshot_active=True; have_snapshot=True
                elif not is_snapshot: snapshot_active=False
                target=book.bids if side=="bid" else book.asks; old=target.get(price,0.0)
                if amount==0: target.pop(price,None)
                else: target[price]=amount
                if not is_snapshot:
                    stats={"bid_added":0,"bid_removed":0,"ask_added":0,"ask_removed":0}
                    add=max(amount-old,0); rem=max(old-amount,0)
                    if side=="bid": stats.update(bid_added=add,bid_removed=rem)
                    else: stats.update(ask_added=add,ask_removed=rem)
                    micro.on_book_delta(symbol,stats)
                book.quality=BookQuality.HEALTHY
            else:
                side=str(row.get("side","buy")).lower(); micro.on_trade(symbol,float(row.get("price",0)),float(row.get("amount",0)),buyer_is_maker=(side=="sell"),market="futures",ts=ts//1000)
        return pd.DataFrame(rows)
