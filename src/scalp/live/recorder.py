from __future__ import annotations
import asyncio, json, os, signal, socket, time, traceback
from pathlib import Path
import httpx, websockets
from scalp.config import AppConfig
from scalp.data.binance import BinanceFuturesClient
from scalp.live.book import LocalOrderBook, SequenceGap
from scalp.live.chunks import ChunkWriter
from scalp.live.events import MarketEvent
from scalp.live.integrity import IntegrityStore, now_ms
from scalp.live.microstructure import MicrostructureTracker
from scalp.live.storage_health import StorageManager
from scalp.models import BookQuality, GapReason

class BinanceLiveRecorder:
    def __init__(self,cfg:AppConfig):
        self.cfg=cfg; self.live=cfg.live; self.storage_cfg=cfg.storage; self.stop_event=asyncio.Event()
        self.integrity=IntegrityStore(Path(cfg.storage.state_dir)/"integrity.db")
        self.session_id=None; self.writer=None; self.feature_writer=None
        self.fut_books={s:LocalOrderBook(s) for s in self.live.full_l2_symbols}; self.spot_books={s:LocalOrderBook(s) for s in self.live.full_l2_symbols}
        self.micro=MicrostructureTracker(); self.health={"started_ms":now_ms(),"streams":{},"last_event":{},"errors":[],"dropped":0}
        self.gaps={}; self.storage_level="OK"; self.last_prune_ms=0

    def _bulk_root(self): return StorageManager(self.storage_cfg).bulk_root()

    async def start(self):
        boot_id="unknown"
        try: boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except Exception: pass
        identity=f"{socket.gethostname()}:{boot_id}"
        self.session_id,previous=self.integrity.begin_session(identity)
        bulk=self._bulk_root(); self.writer=ChunkWriter(str(bulk/"live"),self.session_id,self.integrity,self.storage_cfg.raw_segment_seconds,self.storage_cfg.ram_buffer_events,source="BINANCE_LIVE")
        self.feature_writer=ChunkWriter(str(bulk/"features"),self.session_id,self.integrity,self.storage_cfg.feature_segment_seconds,max(100,self.storage_cfg.ram_buffer_events//10),source="LOCAL_DERIVED")
        incomplete=ChunkWriter.recover_incomplete(bulk)
        ChunkWriter.recover_orphan_coverage(bulk/"live",self.integrity,"BINANCE_LIVE",self.session_id)
        ChunkWriter.recover_orphan_coverage(bulk/"features",self.integrity,"LOCAL_DERIVED",self.session_id)
        gap_window=None
        if previous:
            hb=self.integrity.last_heartbeat(previous["id"]); start=(hb["ts"] if hb else (previous.get("end_ts") or previous["start_ts"]))
            duration=now_ms()-start
            if previous.get("status")=="RUNNING":
                reason=GapReason.POWER_LOSS if previous.get("host")!=identity else GapReason.PROCESS_CRASH
                gap_end=now_ms(); self.integrity.record_gap(start,gap_end,reason,previous["id"],notes="Previous recorder session did not close cleanly"); gap_window=(start,gap_end)
            elif duration > self.live.heartbeat_seconds*2000:
                reason=GapReason.MANUAL_REBOOT if previous.get("host")!=identity else GapReason.UNKNOWN
                gap_end=now_ms(); self.integrity.record_gap(start,gap_end,reason,previous["id"],notes="Recorder was cleanly stopped but market-data coverage was absent until this session"); gap_window=(start,gap_end)
        for tmp in incomplete:
            try: os.replace(tmp,tmp+".incomplete")
            except OSError: pass
        if gap_window and gap_window[1]-gap_window[0] >= 60_000:
            await self._backfill_recoverable(*gap_window)
        tasks=[
            asyncio.create_task(self._futures_stream_loop(),name="futures_ws"),
            asyncio.create_task(self._spot_stream_loop(),name="spot_ws"),
            asyncio.create_task(self._feature_loop(),name="features"),
            asyncio.create_task(self._heartbeat_loop(),name="heartbeat"),
            asyncio.create_task(self._derivatives_poll_loop(),name="derivatives"),
        ]
        try: await self.stop_event.wait()
        finally:
            for t in tasks: t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if self.writer: self.writer.flush_all()
            if self.feature_writer: self.feature_writer.flush_all()
            self.integrity.end_session(self.session_id,"CLEAN")

    def stop(self): self.stop_event.set()

    async def _backfill_recoverable(self,start_ms,end_ms):
        """Backfill recoverable 1m candles only. The original L2 gap remains recorded and unrepaired."""
        root=self._bulk_root()/"historical"/"gap_backfill"; client=BinanceFuturesClient(self.cfg.data.request_timeout,self.cfg.data.request_pause_seconds,self.cfg.data.cache_dir)
        for symbol in self.live.symbols:
            try:
                folder=root/symbol; folder.mkdir(parents=True,exist_ok=True)
                df=await asyncio.to_thread(client.klines,symbol,"1m",start_ms,end_ms)
                if not df.empty:
                    fp=folder/f"{start_ms}_{end_ms}_1m.csv.gz"; df.to_csv(fp,index=False,compression="gzip")
                    self.integrity.register_coverage("BACKFILLED",symbol,"ohlcv_1m",start_ms,end_ms,"RECOVERED",self.session_id,str(fp),len(df))
                trades=await asyncio.to_thread(client.agg_trades,symbol,start_ms,end_ms)
                if not trades.empty:
                    tp=folder/f"{start_ms}_{end_ms}_aggTrades.csv.gz"; trades.to_csv(tp,index=False,compression="gzip")
                    trade_quality="RECOVERED_EXCHANGE_TIME" if trades.attrs.get("complete_range",False) else "RECOVERED_EXCHANGE_TIME_PARTIAL_24H_LIMIT"
                    actual_start=int(trades.timestamp.min().timestamp()*1000) if len(trades) else start_ms
                    self.integrity.register_coverage("BACKFILLED",symbol,"trade_flow",actual_start,end_ms,trade_quality,self.session_id,str(tp),len(trades))
                funding=await asyncio.to_thread(client.funding,symbol,start_ms,end_ms)
                if not funding.empty:
                    fp2=folder/f"{start_ms}_{end_ms}_funding.csv.gz"; funding.to_csv(fp2,index=False,compression="gzip")
                    self.integrity.register_coverage("BACKFILLED",symbol,"funding",start_ms,end_ms,"RECOVERED",self.session_id,str(fp2),len(funding))
            except Exception as exc:
                self.health["errors"]=(self.health.get("errors",[])+[{"ts":now_ms(),"where":"gap_backfill","symbol":symbol,"error":str(exc)}])[-50:]

    async def _snapshot(self,market,symbol):
        base=self.live.futures_rest_base if market=="futures" else self.live.spot_rest_base
        path="/fapi/v1/depth" if market=="futures" else "/api/v3/depth"
        async with httpx.AsyncClient(base_url=base,timeout=15) as c:
            r=await c.get(path,params={"symbol":symbol,"limit":self.live.depth_levels}); r.raise_for_status(); return r.json()

    async def _sync_book(self,market,symbol):
        book=(self.fut_books if market=="futures" else self.spot_books)[symbol]
        book.reset(); snap=await self._snapshot(market,symbol); book.apply_snapshot(snap)
        self.health["streams"][f"{market}:{symbol}:book"]={"state":book.quality.value,"snapshot_update_id":book.last_update_id,"ts":now_ms()}

    def _streams(self,market):
        syms=[s.lower() for s in self.live.symbols]; full={s.lower() for s in self.live.full_l2_symbols}
        streams=[]
        for s in syms:
            streams.append(f"{s}@aggTrade")
            if s in full: streams.append(f"{s}@depth@{self.live.depth_speed}")
        if market=="futures" and self.live.record_force_orders: streams.append("!forceOrder@arr")
        if market=="spot" and not self.live.record_spot_depth: streams=[x for x in streams if "@depth" not in x]
        return streams

    async def _futures_stream_loop(self): await self._ws_loop("futures",self.live.futures_ws_base)
    async def _spot_stream_loop(self): await self._ws_loop("spot",self.live.spot_ws_base)

    async def _ws_loop(self,market,base):
        backoff=1
        while not self.stop_event.is_set():
            streams=self._streams(market); url=base+"?streams="+"/".join(streams)
            try:
                async with websockets.connect(url,ping_interval=20,ping_timeout=20,max_queue=10000,close_timeout=5) as ws:
                    self.health["streams"][market]={"state":"CONNECTED","ts":now_ms()}; backoff=1
                    if market in self.gaps:
                        self.integrity.close_gap(self.gaps.pop(market),now_ms())
                    # Correct local-book bootstrap: connect first, buffer stream events, then obtain REST snapshot.
                    queue=asyncio.Queue(maxsize=50000)
                    async def reader():
                        async for raw in ws:
                            await queue.put((now_ms(),raw))
                    reader_task=asyncio.create_task(reader(),name=f"{market}_reader")
                    try:
                        sync_symbols=self.live.full_l2_symbols if (market=="futures" or self.live.record_spot_depth) else []
                        for symbol in sync_symbols:
                            await self._sync_book(market,symbol)
                        while True:
                            recv,raw=await queue.get(); msg=json.loads(raw); data=msg.get("data",msg); await self._handle(market,data,recv)
                    finally:
                        reader_task.cancel(); await asyncio.gather(reader_task,return_exceptions=True)
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.health["streams"][market]={"state":"DISCONNECTED","ts":now_ms(),"error":str(exc)}
                self.health["errors"]=(self.health.get("errors",[])+[{"ts":now_ms(),"where":market,"error":str(exc)}])[-50:]
                if market not in self.gaps:
                    self.gaps[market]=self.integrity.record_gap(self.health.get("last_event",{}).get(market,now_ms()),None,GapReason.NETWORK_OUTAGE,self.session_id,stream=market,notes=str(exc))
                await asyncio.sleep(backoff); backoff=min(self.live.reconnect_max_seconds,backoff*2)

    async def _handle(self,market,data,recv):
        et=data.get("e",""); symbol=data.get("s","GLOBAL").upper(); self.health["last_event"][market]=recv
        if et in {"aggTrade","trade"}:
            self.micro.on_trade(symbol,float(data["p"]),float(data["q"]),bool(data.get("m",False)),market,int(data.get("E",recv)))
            self._write_event(market,symbol,"trade",data,recv)
        elif et=="depthUpdate":
            books=self.fut_books if market=="futures" else self.spot_books; book=books.get(symbol)
            if not book: return
            try:
                stats=book.apply_futures_delta(data) if market=="futures" else book.apply_spot_delta(data)
                if stats.get("applied"):
                    if market=="futures": self.micro.on_book_delta(symbol,stats)
                    self.health["streams"][f"{market}:{symbol}:book"]={"state":book.quality.value,"update_id":book.last_update_id,"ts":recv}
                    self._write_event(market,symbol,"depth",data,recv,quality=book.quality.value)
            except SequenceGap as exc:
                book.quality=BookQuality.UNTRUSTED
                gid=self.integrity.record_gap(recv,None,GapReason.STREAM_SEQUENCE_GAP,self.session_id,symbol,"depth",False,str(exc))
                self.health["streams"][f"{market}:{symbol}:book"]={"state":book.quality.value,"ts":recv,"error":str(exc)}
                await self._sync_book(market,symbol)
                self.integrity.close_gap(gid,now_ms())
        elif et=="forceOrder":
            o=data.get("o",{}); s=o.get("s",symbol).upper(); self.micro.on_liquidation(s,o.get("S",""),float(o.get("q",0)),float(o.get("ap") or o.get("p") or 0)); self._write_event(market,s,"liquidation",data,recv)
        else: self._write_event(market,symbol,et or "event",data,recv)

    def _write_event(self,market,symbol,event_type,payload,recv,quality="HEALTHY"):
        # Under disk pressure keep processing L2 in memory but reduce raw-depth retention first.
        if event_type=="depth":
            if self.storage_level=="EMERGENCY": return
            if self.storage_level=="PRESSURE" and symbol not in set(self.live.full_l2_symbols[:2]): return
        evt=MarketEvent(event_type,"binance",market,symbol,int(payload.get("E",recv)),recv,self.session_id,payload,quality).to_dict(); self.writer.add(evt)

    async def _feature_loop(self):
        while not self.stop_event.is_set():
            await asyncio.sleep(self.live.feature_snapshot_ms/1000)
            ts=now_ms()
            for s in self.live.full_l2_symbols:
                fb=self.fut_books.get(s); sb=self.spot_books.get(s)
                if not fb or fb.quality!=BookQuality.HEALTHY: continue
                snap=self.micro.snapshot(s,fb.metrics(),sb.metrics() if sb and sb.quality==BookQuality.HEALTHY else None,ts)
                snap.update({"event_type":"feature","exchange":"local","market":"derived","symbol":s,"exchange_ts":ts,"receive_ts":ts,"session_id":self.session_id,"quality":fb.quality.value,"source":"LOCAL_DERIVED"})
                self.feature_writer.add(snap)
                self.integrity.update_latest_feature(s,ts,fb.quality.value,snap)

    async def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            manager=StorageManager(self.storage_cfg); storage=manager.status(); self.storage_level=storage["level"]
            if self.storage_level in {"PRESSURE","EMERGENCY"} and now_ms()-self.last_prune_ms>3_600_000:
                await asyncio.to_thread(manager.prune_raw_l2,False); self.last_prune_ms=now_ms()
            state={"last_event":self.health.get("last_event",{}),"streams":self.health.get("streams",{}),"errors":self.health.get("errors",[])[-5:],"bulk":storage,"raw_depth_policy":self.storage_level}
            self.integrity.heartbeat(self.session_id,state); await asyncio.sleep(self.live.heartbeat_seconds)

    async def _derivatives_poll_loop(self):
        while not self.stop_event.is_set():
            try:
                async with httpx.AsyncClient(base_url=self.live.futures_rest_base,timeout=15) as c:
                    for s in self.live.symbols:
                        oi=await c.get("/fapi/v1/openInterest",params={"symbol":s})
                        if oi.status_code==200: self.micro.set_oi(s,float(oi.json().get("openInterest",0)))
                        prem=await c.get("/fapi/v1/premiumIndex",params={"symbol":s})
                        if prem.status_code==200: self.micro.set_funding(s,float(prem.json().get("lastFundingRate",0)))
            except Exception as exc:
                self.health["errors"]=(self.health.get("errors",[])+[{"ts":now_ms(),"where":"derivatives_poll","error":str(exc)}])[-50:]
            await asyncio.sleep(min(self.live.oi_poll_seconds,self.live.funding_poll_seconds))

def run_recorder(cfg:AppConfig):
    rec=BinanceLiveRecorder(cfg)
    loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT,signal.SIGTERM):
        try: loop.add_signal_handler(sig,rec.stop)
        except NotImplementedError: pass
    try: loop.run_until_complete(rec.start())
    finally: loop.close()
