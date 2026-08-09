from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import time
import httpx
import pandas as pd

FAPI = "https://fapi.binance.com"
SPOT = "https://api.binance.com"
KLINE_COLS = ["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]
INTERVAL_MS = {"1m":60_000,"3m":180_000,"5m":300_000,"15m":900_000,"30m":1_800_000,"1h":3_600_000,"2h":7_200_000,"4h":14_400_000,"6h":21_600_000,"8h":28_800_000,"12h":43_200_000,"1d":86_400_000}

class BinanceDataError(RuntimeError): pass

@dataclass
class BinanceFuturesClient:
    timeout: float = 15
    pause_seconds: float = 0.12
    cache_dir: str = "data/cache"

    def _client(self): return httpx.Client(base_url=FAPI, timeout=self.timeout, headers={"User-Agent":"scalplab/0.2"})
    def exchange_info(self) -> dict:
        with self._client() as c:
            r=c.get("/fapi/v1/exchangeInfo"); r.raise_for_status(); return r.json()
    def usdt_perpetual_symbols(self) -> list[str]:
        return sorted(s["symbol"] for s in self.exchange_info().get("symbols",[]) if s.get("quoteAsset")=="USDT" and s.get("contractType")=="PERPETUAL" and s.get("status")=="TRADING")

    def _fetch_kline_chunk(self,symbol,interval,start_ms,end_ms):
        rows=[]; cursor=start_ms; step=INTERVAL_MS[interval]
        with self._client() as c:
            while cursor<=end_ms:
                r=c.get("/fapi/v1/klines",params={"symbol":symbol,"interval":interval,"startTime":cursor,"endTime":end_ms,"limit":1500})
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

    def klines(self,symbol:str,interval:str,start_ms:int,end_ms:int)->pd.DataFrame:
        """Exact-range historical pull with day-partition cache; only missing UTC days are downloaded."""
        if interval not in INTERVAL_MS: raise ValueError(f"Unsupported interval {interval}")
        symbol=symbol.upper().strip(); root=Path(self.cache_dir)/"binance_usdm"/"klines"/symbol/interval; root.mkdir(parents=True,exist_ok=True)
        start=pd.to_datetime(start_ms,unit="ms",utc=True); end=pd.to_datetime(end_ms,unit="ms",utc=True)
        day=start.floor("D"); parts=[]
        while day<=end.floor("D"):
            day_end=day+pd.Timedelta(days=1)-pd.Timedelta(milliseconds=1); fp=root/f"{day.strftime('%Y-%m-%d')}.csv.gz"
            if fp.exists(): part=pd.read_csv(fp,parse_dates=["timestamp"]); part["timestamp"]=pd.to_datetime(part.timestamp,utc=True)
            else:
                part=self._fetch_kline_chunk(symbol,interval,int(day.timestamp()*1000),int(day_end.timestamp()*1000))
                if not part.empty: part.to_csv(fp,index=False,compression="gzip")
            if not part.empty: parts.append(part)
            day+=pd.Timedelta(days=1)
        if not parts: raise BinanceDataError(f"No klines returned for {symbol}")
        out=pd.concat(parts,ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
        return out[(out.timestamp>=start)&(out.timestamp<=end)].reset_index(drop=True)

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
                r=c.get("/fapi/v1/aggTrades",params={"symbol":symbol,"limit":1000,"startTime":chunk_start,"endTime":chunk_end}); r.raise_for_status(); batch=r.json()
                while batch:
                    for x in batch:
                        ts=int(x.get("T",0)); aid=int(x["a"])
                        if chunk_start<=ts<=chunk_end and aid not in seen:
                            rows.append(x); seen.add(aid)
                    if len(batch)<1000 or int(batch[-1].get("T",0))>=chunk_end: break
                    last_id=int(batch[-1]["a"])
                    r=c.get("/fapi/v1/aggTrades",params={"symbol":symbol,"limit":1000,"fromId":last_id+1}); r.raise_for_status(); batch=r.json()
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
                r=c.get("/fapi/v1/fundingRate",params={"symbol":symbol,"startTime":cursor,"endTime":end_ms,"limit":1000}); r.raise_for_status(); batch=r.json()
                if not batch: break
                rows.extend(batch); cursor=int(batch[-1]["fundingTime"])+1
                if len(batch)<1000: break
                time.sleep(self.pause_seconds)
        if not rows: return pd.DataFrame(columns=["timestamp","funding_rate"])
        return pd.DataFrame({"timestamp":pd.to_datetime([x["fundingTime"] for x in rows],unit="ms",utc=True),"funding_rate":[float(x["fundingRate"]) for x in rows]})

    def depth_snapshot(self,symbol,limit=1000):
        with self._client() as c:
            r=c.get("/fapi/v1/depth",params={"symbol":symbol.upper(),"limit":limit}); r.raise_for_status(); return r.json()

def utc_ms(value:str|datetime)->int:
    if isinstance(value,str):
        value=pd.Timestamp(value)
        value=value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return int(value.timestamp()*1000)
