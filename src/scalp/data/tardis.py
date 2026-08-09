from __future__ import annotations
from pathlib import Path
from datetime import date
import gzip, shutil
import httpx, pandas as pd

BASE="https://datasets.tardis.dev/v1/binance-futures"
ALLOWED={"incremental_book_L2","trades","quotes","derivative_ticker","book_snapshot_25","liquidations"}

class TardisSampleClient:
    """Downloader for publicly available first-day-of-month Tardis CSV sample files."""
    def __init__(self,root="data/tardis",timeout=60): self.root=Path(root); self.timeout=timeout
    def url(self,data_type,day,symbol):
        if data_type not in ALLOWED: raise ValueError(data_type)
        d=pd.Timestamp(day)
        return f"{BASE}/{data_type}/{d.year:04d}/{d.month:02d}/{d.day:02d}/{symbol.upper()}.csv.gz"
    def download(self,data_type,day,symbol):
        d=pd.Timestamp(day)
        if d.day!=1: raise ValueError("Free Tardis sample downloader only supports the first day of a month")
        out=self.root/data_type/f"{d.year:04d}"/f"{d.month:02d}"/f"{d.day:02d}"/f"{symbol.upper()}.csv.gz"; out.parent.mkdir(parents=True,exist_ok=True)
        if out.exists() and out.stat().st_size>0: return out
        with httpx.stream("GET",self.url(data_type,d,symbol),timeout=self.timeout,follow_redirects=True) as r:
            r.raise_for_status()
            with open(out,"wb") as f:
                for chunk in r.iter_bytes(): f.write(chunk)
        return out
    def read(self,data_type,day,symbol): return pd.read_csv(self.download(data_type,day,symbol),compression="gzip")
