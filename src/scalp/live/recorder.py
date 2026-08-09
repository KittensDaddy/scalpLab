from __future__ import annotations
import asyncio, json, os, signal, socket, time, traceback
from datetime import datetime, timezone
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
from scalp.universe import UniverseService
from scalp.runtime import fd_stats

class BinanceLiveRecorder:
    def __init__(self,cfg:AppConfig,console_status:bool=False):
        self.cfg=cfg; self.live=cfg.live; self.storage_cfg=cfg.storage; self.stop_event=asyncio.Event(); self.console_status=console_status
        self.integrity=IntegrityStore(Path(cfg.storage.state_dir)/"integrity.db")
        self.session_id=None; self.writer=None; self.feature_writer=None
        self.fut_books={s:LocalOrderBook(s) for s in self.live.full_l2_symbols}; self.spot_books={s:LocalOrderBook(s) for s in self.live.full_l2_symbols}
        self.micro=MicrostructureTracker(); self.health={"started_ms":now_ms(),"streams":{},"last_event":{},"errors":[],"dropped":0,"events":0,"trades":0,"depth_updates":0,"features":0,"reconnects":0,"event_lag_ms":{},"fd_high_water":0,"queue_high_water":{}}
        self.gaps={}; self.storage_level="OK"; self.last_prune_ms=0
        self.light_symbols=list(dict.fromkeys(self.live.symbols))
        self.spot_symbols=list(self.light_symbols)
        self.universe_snapshot={}; self.light_refresh=asyncio.Event()

    def _bulk_root(self): return StorageManager(self.storage_cfg).bulk_root()

    async def _refresh_universe(self,initial=False):
        service=UniverseService(); snapshot=service.latest(); today=datetime.now(timezone.utc).date().isoformat()
        try:
            if snapshot.get("selection_date")!=today:
                snapshot=await asyncio.to_thread(service.refresh,False)
        except Exception as exc:
            self.health["errors"]=(self.health.get("errors",[])+[{"ts":now_ms(),"where":"universe_refresh","error":str(exc)}])[-50:]
        assets=snapshot.get("assets",[]); selected=[x["symbol"] for x in assets[:20] if x.get("symbol")]
        if not selected: selected=list(dict.fromkeys(self.live.symbols))
        spot_selected=await self._available_spot_symbols(selected)
        changed=selected!=self.light_symbols or spot_selected!=self.spot_symbols
        self.light_symbols=selected; self.spot_symbols=spot_selected; self.universe_snapshot=snapshot
        self.health["universe"]={"snapshot_id":snapshot.get("snapshot_id"),"selection_date":snapshot.get("selection_date"),"top20":selected,"spot_available":spot_selected,"spot_unavailable":[s for s in selected if s not in spot_selected],"full_l2":list(self.live.full_l2_symbols),"refreshed_ms":now_ms()}
        if changed and not initial:
            self._write_universe_selection(); self.light_refresh.set()

    async def _available_spot_symbols(self,symbols):
        try:
            async with httpx.AsyncClient(base_url=self.live.spot_rest_base,timeout=15) as client:
                response=await client.get("/api/v3/exchangeInfo"); response.raise_for_status(); data=response.json()
            available={x["symbol"] for x in data.get("symbols",[]) if x.get("status")=="TRADING"}
            return [s for s in symbols if s in available]
        except Exception as exc:
            self.health["errors"]=(self.health.get("errors",[])+[{"ts":now_ms(),"where":"spot_symbol_filter","error":str(exc)}])[-50:]
            return list(symbols)

    def _write_universe_selection(self):
        if not self.writer: return
        ts=now_ms(); payload={"snapshot_id":self.universe_snapshot.get("snapshot_id"),"selection_date":self.universe_snapshot.get("selection_date"),"top20":list(self.light_symbols),"spot_available":list(self.spot_symbols),"full_l2":list(self.live.full_l2_symbols),"assets":self.universe_snapshot.get("assets",[])}
        self._write_event("metadata","GLOBAL","universe_selection",payload,ts,tier="TOP100_SELECTION")
        self.writer.flush_key(("metadata","GLOBAL","universe_selection"))

    async def _universe_refresh_loop(self):
        while not self.stop_event.is_set():
            await asyncio.sleep(300)
            await self._refresh_universe()

    async def start(self):
        await self._refresh_universe(initial=True)
        boot_id="unknown"
        try: boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except Exception: pass
        identity=f"{socket.gethostname()}:{boot_id}"
        self.session_id,previous=self.integrity.begin_session(identity)
        bulk=self._bulk_root(); self.writer=ChunkWriter(str(bulk/"live"),self.session_id,self.integrity,self.storage_cfg.raw_segment_seconds,self.storage_cfg.ram_buffer_events,source="BINANCE_LIVE")
        self.feature_writer=ChunkWriter(str(bulk/"features"),self.session_id,self.integrity,self.storage_cfg.feature_segment_seconds,max(100,self.storage_cfg.ram_buffer_events//10),source="LOCAL_DERIVED")
        self._write_universe_selection()
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
            asyncio.create_task(self._lightweight_supervisor(),name="lightweight_ws"),
            asyncio.create_task(self._full_l2_stream_loop(),name="futures_full_l2_ws"),
            asyncio.create_task(self._universe_refresh_loop(),name="universe_refresh"),
            asyncio.create_task(self._feature_loop(),name="features"),
            asyncio.create_task(self._heartbeat_loop(),name="heartbeat"),
            asyncio.create_task(self._derivatives_poll_loop(),name="derivatives"),
        ]
        if self.console_status: tasks.append(asyncio.create_task(self._console_status_loop(),name="console_status"))
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
        for symbol in self.light_symbols:
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
        self.health["streams"][f"{market}:{symbol}:book"]={"state":book.quality.value,"reason":"WAITING_FOR_STREAM_BRIDGE","snapshot_update_id":book.last_update_id,"ts":now_ms()}

    def _light_streams(self,market,symbols):
        streams=[]
        for symbol in symbols:
            s=symbol.lower(); streams.append(f"{s}@aggTrade")
            if market=="spot": streams.append(f"{s}@bookTicker")
        if market=="futures" and self.live.record_force_orders: streams.append("!forceOrder@arr")
        return streams

    async def _lightweight_supervisor(self):
        while not self.stop_event.is_set():
            self.light_refresh.clear(); symbols=tuple(self.light_symbols)
            tasks=[asyncio.create_task(self._ws_loop("futures",self.live.futures_ws_base,self._light_streams("futures",symbols),"TOP20_LIGHTWEIGHT"),name="futures_light"),
                   asyncio.create_task(self._ws_loop("spot",self.live.spot_ws_base,self._light_streams("spot",tuple(self.spot_symbols)),"TOP20_LIGHTWEIGHT"),name="spot_light")]
            refresh=asyncio.create_task(self.light_refresh.wait())
            done,_=await asyncio.wait([*tasks,refresh],return_when=asyncio.FIRST_COMPLETED)
            for task in [*tasks,refresh]: task.cancel()
            await asyncio.gather(*tasks,refresh,return_exceptions=True)
            if not self.light_refresh.is_set() and not self.stop_event.is_set(): await asyncio.sleep(1)

    async def _full_l2_stream_loop(self):
        streams=[f"{s.lower()}@depth@{self.live.depth_speed}" for s in self.live.full_l2_symbols]
        await self._ws_loop("futures",self.live.futures_ws_base,streams,"FULL_L2")

    async def _ws_loop(self,market,base,streams,tier):
        backoff=1
        while not self.stop_event.is_set():
            url=base+"?streams="+"/".join(streams); stream_key=f"{market}:{tier}"
            try:
                async with websockets.connect(url,ping_interval=20,ping_timeout=20,max_queue=10000,close_timeout=5) as ws:
                    active_symbols=self.spot_symbols if market=="spot" and tier=="TOP20_LIGHTWEIGHT" else self.light_symbols if tier=="TOP20_LIGHTWEIGHT" else self.live.full_l2_symbols
                    self.health["streams"][stream_key]={"state":"CONNECTED","ts":now_ms(),"symbols":list(active_symbols)}; backoff=1
                    if stream_key in self.gaps:
                        self.integrity.close_gap(self.gaps.pop(stream_key),now_ms())
                    # Correct local-book bootstrap: connect first, buffer stream events, then obtain REST snapshot.
                    queue=asyncio.Queue(maxsize=50000)
                    async def reader():
                        async for raw in ws:
                            try:
                                queue.put_nowait((now_ms(),raw))
                                used=queue.qsize(); self.health["queue_high_water"][stream_key]=max(used,self.health["queue_high_water"].get(stream_key,0))
                                stream=self.health["streams"].setdefault(stream_key,{})
                                stream["queue_used"]=used; stream["queue_capacity"]=queue.maxsize; stream["queue_utilization_pct"]=used/queue.maxsize*100
                            except asyncio.QueueFull:
                                self.health["dropped"]+=1
                                if f"overload:{stream_key}" not in self.gaps:
                                    self.gaps[f"overload:{stream_key}"]=self.integrity.record_gap(now_ms(),None,GapReason.RECORDER_OVERLOAD,self.session_id,stream=stream_key,notes="WebSocket receive queue full; events dropped")
                    reader_task=asyncio.create_task(reader(),name=f"{market}_reader")
                    try:
                        sync_symbols=self.live.full_l2_symbols if tier=="FULL_L2" else []
                        if sync_symbols:
                            await asyncio.gather(*(self._sync_book(market,symbol) for symbol in sync_symbols))
                        while True:
                            recv,raw=await queue.get(); msg=json.loads(raw); data=msg.get("data",msg); await self._handle(market,data,recv,tier)
                            if queue.qsize()<queue.maxsize//2 and f"overload:{stream_key}" in self.gaps:
                                self.integrity.close_gap(self.gaps.pop(f"overload:{stream_key}"),now_ms())
                    finally:
                        reader_task.cancel(); await asyncio.gather(reader_task,return_exceptions=True)
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.health["reconnects"]+=1
                self.health["streams"][stream_key]={"state":"DISCONNECTED","ts":now_ms(),"error":str(exc)}
                self.health["errors"]=(self.health.get("errors",[])+[{"ts":now_ms(),"where":stream_key,"error":str(exc)}])[-50:]
                if stream_key not in self.gaps:
                    self.gaps[stream_key]=self.integrity.record_gap(self.health.get("last_event",{}).get(stream_key,now_ms()),None,GapReason.NETWORK_OUTAGE,self.session_id,stream=stream_key,notes=str(exc))
                await asyncio.sleep(backoff); backoff=min(self.live.reconnect_max_seconds,backoff*2)

    async def _handle(self,market,data,recv,tier):
        et=data.get("e",""); symbol=data.get("s","GLOBAL").upper(); self.health["last_event"][f"{market}:{tier}"]=recv; self.health["events"]+=1
        exchange_ts=int(data.get("E") or data.get("T") or recv); lag=max(0,recv-exchange_ts); lag_key=f"{market}:{tier}"
        prior=self.health["event_lag_ms"].get(lag_key,{"latest":0,"max":0}); self.health["event_lag_ms"][lag_key]={"latest":lag,"max":max(prior["max"],lag)}
        if et in {"aggTrade","trade"}:
            self.health["trades"]+=1
            self.micro.on_trade(symbol,float(data["p"]),float(data["q"]),bool(data.get("m",False)),market,int(data.get("E",recv)))
            self._write_event(market,symbol,"trade",data,recv,tier=tier)
        elif et=="depthUpdate":
            self.health["depth_updates"]+=1
            books=self.fut_books if market=="futures" else self.spot_books; book=books.get(symbol)
            if not book: return
            try:
                stats=book.apply_futures_delta(data) if market=="futures" else book.apply_spot_delta(data)
                if stats.get("applied"):
                    if market=="futures": self.micro.on_book_delta(symbol,stats)
                    self.health["streams"][f"{market}:{symbol}:book"]={"state":book.quality.value,"update_id":book.last_update_id,"ts":recv}
                    self._write_event(market,symbol,"depth",data,recv,quality=book.quality.value,tier=tier)
                elif stats.get("reason")!="STALE":
                    self.health["streams"][f"{market}:{symbol}:book"]={"state":book.quality.value,"reason":stats.get("reason"),"snapshot_update_id":book.last_update_id,"event_first_update_id":data.get("U"),"event_final_update_id":data.get("u"),"event_previous_update_id":data.get("pu"),"ts":recv}
            except SequenceGap as exc:
                book.quality=BookQuality.UNTRUSTED
                gid=self.integrity.record_gap(recv,None,GapReason.STREAM_SEQUENCE_GAP,self.session_id,symbol,"depth",False,str(exc))
                self.health["streams"][f"{market}:{symbol}:book"]={"state":book.quality.value,"ts":recv,"error":str(exc)}
                await self._sync_book(market,symbol)
                self.integrity.close_gap(gid,now_ms())
        elif et=="forceOrder":
            o=data.get("o",{}); s=o.get("s",symbol).upper(); self.micro.on_liquidation(s,o.get("S",""),float(o.get("q",0)),float(o.get("ap") or o.get("p") or 0)); self._write_event(market,s,"liquidation",data,recv,tier=tier)
        elif et=="bookTicker": self._write_event(market,symbol,"book_ticker",data,recv,tier=tier)
        else: self._write_event(market,symbol,et or "event",data,recv,tier=tier)

    def _write_event(self,market,symbol,event_type,payload,recv,quality="HEALTHY",tier="TOP20_LIGHTWEIGHT"):
        # Under disk pressure keep processing L2 in memory but reduce raw-depth retention first.
        if event_type=="depth":
            if self.storage_level=="EMERGENCY": return
            if self.storage_level=="PRESSURE" and symbol not in set(self.live.full_l2_symbols[:2]): return
        evt=MarketEvent(event_type,"binance",market,symbol,int(payload.get("E",recv)),recv,self.session_id,payload,quality).to_dict()
        evt.update({"universe_snapshot_id":self.universe_snapshot.get("snapshot_id"),"subscription_tier":tier})
        self.writer.add(evt)

    async def _feature_loop(self):
        while not self.stop_event.is_set():
            await asyncio.sleep(self.live.feature_snapshot_ms/1000)
            ts=now_ms()
            for s in self.live.full_l2_symbols:
                fb=self.fut_books.get(s); sb=self.spot_books.get(s)
                if not fb or fb.quality!=BookQuality.HEALTHY: continue
                snap=self.micro.snapshot(s,fb.metrics(),sb.metrics() if sb and sb.quality==BookQuality.HEALTHY else None,ts)
                snap.update({"event_type":"feature","exchange":"local","market":"derived","symbol":s,"exchange_ts":ts,"receive_ts":ts,"session_id":self.session_id,"quality":fb.quality.value,"source":"LOCAL_DERIVED","universe_snapshot_id":self.universe_snapshot.get("snapshot_id"),"subscription_tier":"FULL_L2_DERIVED"})
                self.feature_writer.add(snap); self.health["features"]+=1
                self.integrity.update_latest_feature(s,ts,fb.quality.value,snap)


    async def _console_status_loop(self):
        """Human heartbeat for an infinite recorder; percentage would be misleading."""
        while not self.stop_event.is_set():
            await asyncio.sleep(5)
            elapsed=max(0,(now_ms()-self.health["started_ms"])//1000); h,rem=divmod(elapsed,3600); m,sec=divmod(rem,60)
            fs=self.health.get("streams",{}).get("futures:TOP20_LIGHTWEIGHT",{}).get("state","STARTING"); ss=self.health.get("streams",{}).get("spot:TOP20_LIGHTWEIGHT",{}).get("state","STARTING")
            msg=(f"\r[LIVE {h:02d}:{m:02d}:{sec:02d}] events {self.health['events']:,} · trades {self.health['trades']:,} · "
                 f"depth {self.health['depth_updates']:,} · features {self.health['features']:,} · Futures {fs} · Spot {ss} · disk {self.storage_level}   ")
            print(msg,end="",flush=True)

    async def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            manager=StorageManager(self.storage_cfg); storage=manager.status(); self.storage_level=storage["level"]
            current_fds=fd_stats().get("open_fds") or 0; self.health["fd_high_water"]=max(self.health.get("fd_high_water",0),current_fds)
            if self.storage_level in {"PRESSURE","EMERGENCY"} and now_ms()-self.last_prune_ms>3_600_000:
                await asyncio.to_thread(manager.prune_raw_l2,False); self.last_prune_ms=now_ms()
            self.health["storage"]={"raw":self.writer.stats() if self.writer else None,"features":self.feature_writer.stats() if self.feature_writer else None,"root":str(manager.bulk_root()),"usage":storage.get("usage")}
            state={"last_event":self.health.get("last_event",{}),"streams":self.health.get("streams",{}),"errors":self.health.get("errors",[])[-5:],"bulk":storage,"raw_depth_policy":self.storage_level,"universe":self.health.get("universe"),"writer":self.health.get("storage")}
            self.integrity.heartbeat(self.session_id,state); await asyncio.sleep(self.live.heartbeat_seconds)

    async def _derivatives_poll_loop(self):
        while not self.stop_event.is_set():
            try:
                async with httpx.AsyncClient(base_url=self.live.futures_rest_base,timeout=15) as c:
                    for s in tuple(self.light_symbols):
                        oi=await c.get("/fapi/v1/openInterest",params={"symbol":s})
                        if oi.status_code==200:
                            body=oi.json(); self.micro.set_oi(s,float(body.get("openInterest",0))); self._write_event("futures",s,"open_interest",body|{"E":now_ms()},now_ms())
                        prem=await c.get("/fapi/v1/premiumIndex",params={"symbol":s})
                        if prem.status_code==200:
                            body=prem.json(); self.micro.set_funding(s,float(body.get("lastFundingRate",0))); self._write_event("futures",s,"funding",body|{"E":now_ms()},now_ms())
            except Exception as exc:
                self.health["errors"]=(self.health.get("errors",[])+[{"ts":now_ms(),"where":"derivatives_poll","error":str(exc)}])[-50:]
            await asyncio.sleep(min(self.live.oi_poll_seconds,self.live.funding_poll_seconds))

def run_recorder(cfg:AppConfig,show_status:bool=False):
    rec=BinanceLiveRecorder(cfg,console_status=show_status)
    loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT,signal.SIGTERM):
        try: loop.add_signal_handler(sig,rec.stop)
        except NotImplementedError: pass
    try: loop.run_until_complete(rec.start())
    finally:
        if show_status: print("\nRecorder stopped.")
        loop.close()
