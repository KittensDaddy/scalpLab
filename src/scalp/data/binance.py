from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib, io, sqlite3, threading, time, zipfile
import httpx
import pandas as pd

FAPI = "https://fapi.binance.com"
VISION = "https://data.binance.vision"
SPOT = "https://api.binance.com"
KLINE_COLS = ["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]
INTERVAL_MS = {"1m":60_000,"3m":180_000,"5m":300_000,"15m":900_000,"30m":1_800_000,"1h":3_600_000,"2h":7_200_000,"4h":14_400_000,"6h":21_600_000,"8h":28_800_000,"12h":43_200_000,"1d":86_400_000}

class BinanceDataError(RuntimeError): pass

class _WeightedRequestGate:
    """Process-wide leaky bucket which prevents concurrent research jobs bursting REST weight."""
    def __init__(self, weight_per_minute: float = 900):
        self.seconds_per_weight=60.0/weight_per_minute
        self.lock=threading.Lock(); self.next_slot=0.0

    def wait(self,weight: int):
        with self.lock:
            now=time.monotonic(); slot=max(now,self.next_slot)
            self.next_slot=slot+self.seconds_per_weight*max(1,weight)
        delay=slot-now
        if delay>0: time.sleep(delay)

    def cooldown(self,seconds: float):
        with self.lock: self.next_slot=max(self.next_slot,time.monotonic()+seconds)

_REST_GATE=_WeightedRequestGate()

class HistoricalCacheIndex:
    def __init__(self,cache_dir: str | Path):
        self.root=Path(cache_dir); self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/"cache-index.db"
        with sqlite3.connect(self.db,timeout=10) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS entries (path TEXT PRIMARY KEY,symbol TEXT,interval TEXT,day TEXT,bytes INTEGER,last_used REAL,hits INTEGER DEFAULT 0,misses INTEGER DEFAULT 0,source TEXT)")

    def touch(self,path: Path,symbol: str,interval: str,day: str,hit: bool,source: str):
        try: relative=str(path.relative_to(self.root)); size=path.stat().st_size if path.exists() else 0
        except (ValueError,OSError): return
        with sqlite3.connect(self.db,timeout=10) as conn:
            conn.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET bytes=excluded.bytes,last_used=excluded.last_used,hits=entries.hits+excluded.hits,misses=entries.misses+excluded.misses,source=CASE WHEN excluded.hits>0 THEN entries.source ELSE excluded.source END",
                         (relative,symbol,interval,day,size,time.time(),1 if hit else 0,0 if hit else 1,source))

    def status(self) -> dict:
        with sqlite3.connect(self.db) as conn:
            row=conn.execute("SELECT COUNT(*),COALESCE(SUM(bytes),0),MAX(last_used),COALESCE(SUM(hits),0),COALESCE(SUM(misses),0) FROM entries").fetchone()
            recent=conn.execute("SELECT symbol,interval,day,bytes,last_used,hits,misses,source FROM entries ORDER BY last_used DESC LIMIT 20").fetchall()
        return {"files":row[0],"bytes":row[1],"last_used":row[2],"hits":row[3],"misses":row[4],"minimum_hot_seconds":7200,
                "recent":[dict(zip(("symbol","interval","day","bytes","last_used","hits","misses","source"),x)) for x in recent]}

    def cleanup(self,dry_run=True,minimum_age_seconds=7200) -> dict:
        cutoff=time.time()-max(7200,minimum_age_seconds); removed=[]; reclaimed=0
        with sqlite3.connect(self.db,timeout=10) as conn:
            rows=conn.execute("SELECT path,bytes,last_used FROM entries WHERE last_used<? ORDER BY last_used",(cutoff,)).fetchall()
            for relative,size,last_used in rows:
                path=(self.root/relative).resolve()
                if self.root.resolve() not in path.parents or not path.is_file(): continue
                removed.append({"path":relative,"bytes":size,"last_used":last_used}); reclaimed+=size
                if not dry_run:
                    path.unlink(); conn.execute("DELETE FROM entries WHERE path=?",(relative,))
        return {"dry_run":dry_run,"eligible_files":len(removed),"eligible_bytes":reclaimed,"minimum_hot_seconds":7200,"files":removed}

@dataclass
class BinanceFuturesClient:
    timeout: float = 15
    pause_seconds: float = 0.12
    cache_dir: str = "data/cache"

    def _client(self): return httpx.Client(base_url=FAPI, timeout=self.timeout, headers={"User-Agent":"scalplab/0.2"})

    @staticmethod
    def _archive_frame(content: bytes) -> pd.DataFrame:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names=[name for name in archive.namelist() if not name.endswith("/")]
            if len(names)!=1: raise BinanceDataError("Unexpected Binance archive layout")
            raw=pd.read_csv(archive.open(names[0]),header=None,names=KLINE_COLS,dtype=str)
        # Newer archives may contain a header while older Futures files do not.
        raw=raw[pd.to_numeric(raw.open_time,errors="coerce").notna()].copy()
        if raw.empty: return pd.DataFrame()
        open_time=pd.to_numeric(raw.open_time).astype("int64")
        unit="us" if open_time.max()>10_000_000_000_000 else "ms"
        return pd.DataFrame({
            "timestamp":pd.to_datetime(open_time,unit=unit,utc=True),"open":pd.to_numeric(raw.open),"high":pd.to_numeric(raw.high),"low":pd.to_numeric(raw.low),"close":pd.to_numeric(raw.close),"volume":pd.to_numeric(raw.volume),"quote_volume":pd.to_numeric(raw.quote_volume),"trades":pd.to_numeric(raw.trades),"taker_buy_base":pd.to_numeric(raw.taker_buy_base),"taker_buy_quote":pd.to_numeric(raw.taker_buy_quote),
        }).drop_duplicates("timestamp").sort_values("timestamp")

    def _archive_klines(self,symbol: str,interval: str,period: str,monthly: bool=False) -> pd.DataFrame | None:
        cadence="monthly" if monthly else "daily"
        filename=f"{symbol}-{interval}-{period}.zip"
        path=f"/data/futures/um/{cadence}/klines/{symbol}/{interval}/{filename}"
        with httpx.Client(base_url=VISION,timeout=max(30,self.timeout),follow_redirects=True,headers={"User-Agent":"scalplab/0.2"}) as client:
            response=client.get(path)
            if response.status_code==404: return None
            if response.status_code!=200: raise BinanceDataError(f"Binance archive {response.status_code}: {response.text[:300]}")
            checksum=client.get(path+".CHECKSUM")
        if checksum.status_code==200:
            expected=checksum.text.strip().split()[0].lower()
            actual=hashlib.sha256(response.content).hexdigest()
            if expected and actual!=expected: raise BinanceDataError(f"Checksum failed for Binance archive {filename}")
        return self._archive_frame(response.content)

    @staticmethod
    def _save_day_parts(frame: pd.DataFrame,root: Path):
        if frame.empty: return
        for day,part in frame.groupby(frame.timestamp.dt.strftime("%Y-%m-%d")):
            target=root/f"{day}.csv.gz"; temporary=target.with_suffix(target.suffix+".tmp")
            part.to_csv(temporary,index=False,compression="gzip"); temporary.replace(target)
    def _get(self,client,path,params=None,weight=1):
        """Pace weighted REST calls and recover without hammering after a Binance 429."""
        for attempt in range(5):
            _REST_GATE.wait(weight)
            response=client.get(path,params=params)
            if response.status_code not in (418,429): return response
            retry=response.headers.get("Retry-After")
            try: delay=max(2.0,float(retry)) if retry else min(60.0,5.0*(2**attempt))
            except ValueError: delay=min(60.0,5.0*(2**attempt))
            _REST_GATE.cooldown(delay); time.sleep(delay)
        raise BinanceDataError(f"Binance rate limit remained active after retries: {response.text[:300]}")

    def exchange_info(self) -> dict:
        with self._client() as c:
            r=self._get(c,"/fapi/v1/exchangeInfo",weight=1); r.raise_for_status(); return r.json()
    def usdt_perpetual_symbols(self) -> list[str]:
        return sorted(s["symbol"] for s in self.exchange_info().get("symbols",[]) if s.get("quoteAsset")=="USDT" and s.get("contractType")=="PERPETUAL" and s.get("status")=="TRADING")

    def _fetch_kline_chunk(self,symbol,interval,start_ms,end_ms):
        rows=[]; cursor=start_ms; step=INTERVAL_MS[interval]
        with self._client() as c:
            while cursor<=end_ms:
                r=self._get(c,"/fapi/v1/klines",params={"symbol":symbol,"interval":interval,"startTime":cursor,"endTime":end_ms,"limit":1500},weight=10)
                if r.status_code!=200: raise BinanceDataError(f"Binance {r.status_code}: {r.text[:300]}")
                batch=r.json()
                if not batch: break
                rows.extend(batch); nxt=int(batch[-1][0])+step
                if nxt<=cursor: break
                cursor=nxt
                if len(batch)<1500: break
                time.sleep(self.pause_seconds)
        if not rows: return pd.DataFrame()
        raw=pd.DataFrame(rows,columns=KLINE_COLS)
        return pd.DataFrame({
            "timestamp":pd.to_datetime(raw.open_time,unit="ms",utc=True),"open":pd.to_numeric(raw.open),"high":pd.to_numeric(raw.high),"low":pd.to_numeric(raw.low),"close":pd.to_numeric(raw.close),"volume":pd.to_numeric(raw.volume),"quote_volume":pd.to_numeric(raw.quote_volume),"trades":pd.to_numeric(raw.trades),"taker_buy_base":pd.to_numeric(raw.taker_buy_base),"taker_buy_quote":pd.to_numeric(raw.taker_buy_quote),
        }).drop_duplicates("timestamp").sort_values("timestamp")

    def klines(self,symbol:str,interval:str,start_ms:int,end_ms:int,progress=None)->pd.DataFrame:
        """Archive-first historical pull; REST is only a newest-data/missing-file fallback."""
        if interval not in INTERVAL_MS: raise ValueError(f"Unsupported interval {interval}")
        symbol=symbol.upper().strip(); cache=HistoricalCacheIndex(self.cache_dir); root=Path(self.cache_dir)/"binance_usdm"/"klines"/symbol/interval; root.mkdir(parents=True,exist_ok=True)
        start=pd.to_datetime(start_ms,unit="ms",utc=True); end=pd.to_datetime(end_ms,unit="ms",utc=True)
        day=start.floor("D"); parts=[]
        provenance=[]
        total_days=max(1,(end.floor("D")-day).days+1); completed=0
        while day<=end.floor("D"):
            day_end=day+pd.Timedelta(days=1)-pd.Timedelta(milliseconds=1); fp=root/f"{day.strftime('%Y-%m-%d')}.csv.gz"; unavailable=fp.with_suffix(".unavailable")
            if fp.exists():
                if progress: progress(completed/total_days*100,f"Cache hit · {symbol} {interval} {day.strftime('%Y-%m-%d')}")
                part=pd.read_csv(fp,parse_dates=["timestamp"]); part["timestamp"]=pd.to_datetime(part.timestamp,utc=True)
                cache.touch(fp,symbol,interval,day.strftime("%Y-%m-%d"),True,"LOCAL_CACHE")
                provenance.append({"day":day.strftime("%Y-%m-%d"),"access":"LOCAL_CACHE"})
            elif unavailable.exists():
                if progress: progress(completed/total_days*100,f"Known unavailable · {symbol} was not trading on {day.strftime('%Y-%m-%d')}")
                part=pd.DataFrame(); provenance.append({"day":day.strftime("%Y-%m-%d"),"access":"KNOWN_UNAVAILABLE"})
            else:
                if progress: progress(completed/total_days*100,f"Cache miss · checking Binance archive for {symbol} {interval} {day.strftime('%Y-%m-%d')}")
                # A completed month is one archive download instead of up to 31 REST calls.
                now=pd.Timestamp.now(tz="UTC")
                if day.strftime("%Y-%m") < now.strftime("%Y-%m"):
                    month=self._archive_klines(symbol,interval,day.strftime("%Y-%m"),monthly=True)
                    if month is not None: self._save_day_parts(month,root)
                if fp.exists():
                    if progress: progress(completed/total_days*100,f"Downloaded monthly archive · {symbol} {interval} {day.strftime('%Y-%m')}")
                    part=pd.read_csv(fp,parse_dates=["timestamp"]); part["timestamp"]=pd.to_datetime(part.timestamp,utc=True)
                    cache.touch(fp,symbol,interval,day.strftime("%Y-%m-%d"),False,"BINANCE_MONTHLY_ARCHIVE")
                    provenance.append({"day":day.strftime("%Y-%m-%d"),"access":"BINANCE_MONTHLY_ARCHIVE"})
                else:
                    part=self._archive_klines(symbol,interval,day.strftime("%Y-%m-%d"))
                    source="BINANCE_DAILY_ARCHIVE"
                    if part is None:
                        if progress: progress(completed/total_days*100,f"Archive unavailable · REST fallback for {symbol} {interval} {day.strftime('%Y-%m-%d')}")
                        source="BINANCE_REST_FALLBACK"; part=self._fetch_kline_chunk(symbol,interval,int(day.timestamp()*1000),int(day_end.timestamp()*1000))
                    elif progress: progress(completed/total_days*100,f"Downloaded daily archive · {symbol} {interval} {day.strftime('%Y-%m-%d')}")
                    if not part.empty: self._save_day_parts(part,root)
                    if fp.exists(): cache.touch(fp,symbol,interval,day.strftime("%Y-%m-%d"),False,source)
                    elif day_end < pd.Timestamp.now(tz="UTC").floor("D"):
                        unavailable.write_text("No candles existed in Binance archive or REST for this completed UTC day.\n")
                    provenance.append({"day":day.strftime("%Y-%m-%d"),"access":source})
            if not part.empty: parts.append(part)
            completed+=1
            day+=pd.Timedelta(days=1)
        if progress: progress(100,f"Historical candles ready for {symbol}")
        if not parts: raise BinanceDataError(f"No klines returned for {symbol}")
        out=pd.concat(parts,ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
        out=out[(out.timestamp>=start)&(out.timestamp<=end)].reset_index(drop=True)
        expected=max(1,int((end_ms-start_ms)//INTERVAL_MS[interval])+1)
        sources={name:sum(1 for item in provenance if item["access"]==name) for name in sorted({item["access"] for item in provenance})}
        out.attrs["historical_data"]={"symbol":symbol,"interval":interval,"requested_start":start.isoformat(),"requested_end":end.isoformat(),"first_bar":out.timestamp.min().isoformat() if len(out) else None,"last_bar":out.timestamp.max().isoformat() if len(out) else None,"expected_bars":expected,"available_bars":len(out),"coverage_pct":round(min(100,len(out)/expected*100),2),"day_access_sources":sources,"days":provenance}
        return out

    def agg_trades(self,symbol:str,start_ms:int,end_ms:int)->pd.DataFrame:
        """Backfill recent USD-M aggregate trades within Binance's documented limits.

        The public Futures endpoint only exposes roughly the most recent 24 hours and
        requires a start/end request window shorter than one hour. We therefore chunk
        time requests and use fromId only to drain >1000 trades inside each chunk.
        The returned frame carries ``attrs["complete_range"]`` so recovery code never
        mistakes a clamped recent-history recovery for full coverage.
        """
        symbol=symbol.upper().strip(); original_start=int(start_ms); end_ms=int(end_ms)
        oldest=int(time.time()*1000)-24*60*60*1000
        effective_start=max(original_start,oldest)
        complete=effective_start<=original_start
        if effective_start>end_ms:
            out=pd.DataFrame(columns=["timestamp","agg_id","price","quantity","buyer_is_maker"]); out.attrs["complete_range"]=False; return out
        rows=[]; chunk_start=effective_start; hour=60*60*1000; seen=set()
        with self._client() as c:
            while chunk_start<=end_ms:
                # Keep strictly below one hour as required by the endpoint.
                chunk_end=min(end_ms,chunk_start+hour-1)
                r=self._get(c,"/fapi/v1/aggTrades",params={"symbol":symbol,"limit":1000,"startTime":chunk_start,"endTime":chunk_end},weight=20); r.raise_for_status(); batch=r.json()
                while batch:
                    for x in batch:
                        ts=int(x.get("T",0)); aid=int(x["a"])
                        if chunk_start<=ts<=chunk_end and aid not in seen:
                            rows.append(x); seen.add(aid)
                    if len(batch)<1000 or int(batch[-1].get("T",0))>=chunk_end: break
                    last_id=int(batch[-1]["a"])
                    r=self._get(c,"/fapi/v1/aggTrades",params={"symbol":symbol,"limit":1000,"fromId":last_id+1},weight=20); r.raise_for_status(); batch=r.json()
                    # fromId has no endTime; stop as soon as the next window is reached.
                    if batch and int(batch[0].get("T",0))>chunk_end: break
                    time.sleep(self.pause_seconds)
                chunk_start=chunk_end+1
                if chunk_start<=end_ms: time.sleep(self.pause_seconds)
        if not rows:
            out=pd.DataFrame(columns=["timestamp","agg_id","price","quantity","buyer_is_maker"]); out.attrs["complete_range"]=complete; return out
        rows.sort(key=lambda x:(int(x.get("T",0)),int(x["a"])))
        out=pd.DataFrame({"timestamp":pd.to_datetime([x["T"] for x in rows],unit="ms",utc=True),"agg_id":[int(x["a"]) for x in rows],"price":[float(x["p"]) for x in rows],"quantity":[float(x["q"]) for x in rows],"buyer_is_maker":[bool(x["m"]) for x in rows]})
        out.attrs["complete_range"]=complete
        return out

    def funding(self,symbol:str,start_ms:int,end_ms:int)->pd.DataFrame:
        rows=[]; cursor=start_ms
        with self._client() as c:
            while cursor<=end_ms:
                r=self._get(c,"/fapi/v1/fundingRate",params={"symbol":symbol,"startTime":cursor,"endTime":end_ms,"limit":1000},weight=1); r.raise_for_status(); batch=r.json()
                if not batch: break
                rows.extend(batch); cursor=int(batch[-1]["fundingTime"])+1
                if len(batch)<1000: break
                time.sleep(self.pause_seconds)
        if not rows: return pd.DataFrame(columns=["timestamp","funding_rate"])
        return pd.DataFrame({"timestamp":pd.to_datetime([x["fundingTime"] for x in rows],unit="ms",utc=True),"funding_rate":[float(x["fundingRate"]) for x in rows]})

    def depth_snapshot(self,symbol,limit=1000):
        with self._client() as c:
            r=self._get(c,"/fapi/v1/depth",params={"symbol":symbol.upper(),"limit":limit},weight=20 if limit>=1000 else 5); r.raise_for_status(); return r.json()

def utc_ms(value:str|datetime)->int:
    if isinstance(value,str):
        value=pd.Timestamp(value)
        value=value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return int(value.timestamp()*1000)
