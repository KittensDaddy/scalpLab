from __future__ import annotations
import asyncio, json, sqlite3, time, uuid
from pathlib import Path
import pandas as pd, websockets
from scalp.config import AppConfig
from scalp.data.binance import BinanceFuturesClient, utc_ms
from scalp.features import build_features, add_multitimeframe_context
from scalp.decision import StrategyDecisionEngine
from scalp.models import DataMode, Direction
from scalp.live.integrity import IntegrityStore

class ShadowStore:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,ts INTEGER,symbol TEXT,direction TEXT,strategy TEXT,score REAL,mode TEXT,entry REAL,stop REAL,target REAL,status TEXT,pnl REAL,reason TEXT,detail_json TEXT)")
    def add(self,row):
        with sqlite3.connect(self.path) as c: c.execute("INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",tuple(row[k] for k in ["id","ts","symbol","direction","strategy","score","mode","entry","stop","target","status","pnl","reason","detail_json"]))
    def recent(self,limit=100):
        with sqlite3.connect(self.path) as c: rows=c.execute("SELECT id,ts,symbol,direction,strategy,score,mode,entry,stop,target,status,pnl,reason,detail_json FROM decisions ORDER BY ts DESC LIMIT ?",(limit,)).fetchall()
        keys=["id","ts","symbol","direction","strategy","score","mode","entry","stop","target","status","pnl","reason","detail_json"]
        return [dict(zip(keys,r)) for r in rows]

class ShadowPaperTrader:
    """Live paper/shadow loop. Never contains Binance order endpoints or API-key handling."""
    def __init__(self,cfg:AppConfig,console_status:bool=False):
        self.cfg=cfg; self.client=BinanceFuturesClient(cfg.data.request_timeout,cfg.data.request_pause_seconds,cfg.data.cache_dir)
        self.integrity=IntegrityStore(Path(cfg.storage.state_dir)/"integrity.db"); self.store=ShadowStore(cfg.shadow.persist_path)
        self.frames={}; self.pending={}; self.open={}; self.stop_event=asyncio.Event(); self.equity=float(cfg.risk.initial_equity); self.console_status=console_status; self.started=time.time(); self.bars_seen=0
    async def seed(self):
        end=pd.Timestamp.now(tz="UTC"); start=end-pd.Timedelta(minutes=self.cfg.shadow.seed_lookback_bars*5)
        for s in self.cfg.live.symbols:
            self.frames[s]=await asyncio.to_thread(self.client.klines,s,self.cfg.shadow.interval,utc_ms(start),utc_ms(end))
    def _mode_and_row(self,symbol,df):
        x=build_features(add_multitimeframe_context(df,self.cfg.shadow.interval)).dropna(subset=["atr","ema20","ema50","range_high","range_low","prev_high20","prev_low20"])
        if x.empty: return DataMode.TRADE_FLOW,None
        row=x.iloc[-1].copy(); latest=self.integrity.latest_feature(symbol)
        if latest and latest["quality"]=="HEALTHY" and int(time.time()*1000)-latest["ts"]<5000:
            for k,v in latest["feature"].items():
                if k not in {"timestamp","event_type","symbol"}: row[k]=v
            return DataMode.MICROSTRUCTURE,row
        return DataMode.TRADE_FLOW,row
    def _process_bar(self,symbol,bar):
        # Fill a signal no earlier than the following bar, with the same execution-style assumptions as research backtests.
        p=self.pending.get(symbol)
        if p and symbol not in self.open:
            side=1 if p["direction"]=="LONG" else -1; openp=float(bar["open"]); bps=1e-4; maker=False; fill=None
            if p["execution_mode"]=="MARKET": fill=openp*(1+side*self.cfg.execution.market_slippage_bps*bps)
            elif p["execution_mode"]=="AGGRESSIVE_LIMIT": fill=openp*(1+side*self.cfg.execution.aggressive_slippage_bps*bps)
            else:
                limit=p["signal_price"]*(1-side*self.cfg.execution.passive_offset_bps*bps); touched=float(bar["low"])<=limit if side>0 else float(bar["high"])>=limit
                if touched: fill=limit; maker=True
                else:
                    p["ttl"]-=1
                    if p["ttl"]<=0:
                        p.update(status="MISSED_FILL",reason="PASSIVE_TTL"); self.store.add(p); self.pending.pop(symbol,None)
            if fill is not None:
                risk_dist=abs(fill-p["stop"])
                if risk_dist<=0: self.pending.pop(symbol,None)
                else:
                    risk_amount=self.equity*(p["risk_pct"]/100); qty=risk_amount/risk_dist; qty=min(qty,(self.equity*self.cfg.risk.max_position_notional_pct/100)/max(fill,1e-12))
                    fee_rate=(self.cfg.execution.maker_fee_bps if maker else self.cfg.execution.taker_fee_bps)*1e-4; entry_fee=abs(fill*qty)*fee_rate
                    p.update(entry=fill,qty=qty,fees=entry_fee,slippage=abs(fill-openp)*qty,status="OPEN",bars_open=0,maker=maker); self.open[symbol]=p; self.pending.pop(symbol,None); self.store.add(p)
        t=self.open.get(symbol)
        if t:
            side=1 if t["direction"]=="LONG" else -1; stop=t["stop"]; target=t["target"]; t["bars_open"]+=1
            sh=float(bar["low"])<=stop if side>0 else float(bar["high"])>=stop; th=float(bar["high"])>=target if side>0 else float(bar["low"])<=target
            reason=None; px=None
            if sh and th: px=stop; reason="STOP_AMBIGUOUS_FIRST"
            elif sh: px=stop; reason="STOP"
            elif th: px=target; reason="TARGET"
            elif t["bars_open"]>=self.cfg.execution.max_hold_bars: px=float(bar["close"]); reason="TIME_STOP"
            if px is not None:
                gross=(px-t["entry"])*side*t["qty"]; exit_fee=abs(px*t["qty"])*self.cfg.execution.taker_fee_bps*1e-4; net=gross-t["fees"]-exit_fee; self.equity+=net
                t.update(status="CLOSED",pnl=net,reason=reason,fees=t["fees"]+exit_fee,exit=px); self.store.add(t); self.open.pop(symbol,None)
        df=pd.concat([self.frames.get(symbol,pd.DataFrame()),pd.DataFrame([bar])],ignore_index=True).drop_duplicates("timestamp",keep="last").tail(max(500,self.cfg.shadow.seed_lookback_bars)).reset_index(drop=True); self.frames[symbol]=df
        mode,row=self._mode_and_row(symbol,df)
        if row is None or symbol in self.open or symbol in self.pending: return
        de=StrategyDecisionEngine(self.cfg,mode); decision=de.evaluate(row)
        if not decision.winner: return
        w=decision.winner; side=1 if w.direction==Direction.LONG else -1; stop=float(w.stop_price); dist=abs(float(row.close)-stop); target=float(row.close)+side*max(w.expected_r,1)*dist; exec_mode=de.execution_mode(w).value
        risk=min(self.cfg.risk.normal_risk_pct,self.cfg.risk.max_symbol_risk_pct)
        if w.strategy_id=="TR" and w.proxy: risk=min(risk,self.cfg.risk.c_mode_risk_pct)
        self.pending[symbol]={"id":str(uuid.uuid4())[:10],"ts":int(pd.Timestamp(row.timestamp).timestamp()*1000),"symbol":symbol,"direction":w.direction.value,"strategy":w.strategy_id,"score":w.score,"mode":mode.value,"entry":0.0,"stop":stop,"target":target,"status":"PENDING_NEXT_BAR","pnl":0.0,"reason":"","detail_json":json.dumps(w.to_dict(),default=str),"execution_mode":exec_mode,"signal_price":float(row.close),"ttl":self.cfg.execution.passive_ttl_bars,"risk_pct":risk}
        self.store.add(self.pending[symbol])

    def _invalidate_all(self,reason="LIVE_DATA_GAP"):
        for symbol,t in list(self.open.items()):
            side=1 if t["direction"]=="LONG" else -1; px=t["stop"]; gross=(px-t["entry"])*side*t.get("qty",0); exit_fee=abs(px*t.get("qty",0))*self.cfg.execution.taker_fee_bps*1e-4; net=gross-t.get("fees",0)-exit_fee
            t.update(status="INVALID_DATA_GAP",pnl=net,reason=reason,exit=px); self.store.add(t); self.open.pop(symbol,None)
        for symbol,p in list(self.pending.items()): p.update(status="CANCELLED_DATA_GAP",reason=reason); self.store.add(p); self.pending.pop(symbol,None)

    async def start(self):
        await self.seed(); streams="/".join(f"{s.lower()}@kline_{self.cfg.shadow.interval}" for s in self.cfg.live.symbols); url=self.cfg.live.futures_ws_base+"?streams="+streams
        while not self.stop_event.is_set():
            try:
                async with websockets.connect(url,ping_interval=20,ping_timeout=20) as ws:
                    async for raw in ws:
                        msg=json.loads(raw).get("data",{}); k=msg.get("k",{})
                        if not k.get("x"): continue
                        self.bars_seen+=1
                        bar={"timestamp":pd.to_datetime(k["t"],unit="ms",utc=True),"open":float(k["o"]),"high":float(k["h"]),"low":float(k["l"]),"close":float(k["c"]),"volume":float(k["v"]),"quote_volume":float(k["q"]),"trades":int(k["n"]),"taker_buy_base":float(k["V"]),"taker_buy_quote":float(k["Q"])}
                        self._process_bar(k["s"].upper(),bar)
                        if self.console_status:
                            elapsed=int(time.time()-self.started); h,rem=divmod(elapsed,3600); m,sec=divmod(rem,60)
                            print(f"\r[SHADOW LIVE {h:02d}:{m:02d}:{sec:02d}] bars {self.bars_seen:,} · equity {self.equity:,.2f} · open {len(self.open)} · pending {len(self.pending)}   ",end="",flush=True)
            except asyncio.CancelledError: raise
            except Exception:
                self._invalidate_all("SHADOW_STREAM_GAP"); await asyncio.sleep(3)
    def stop(self): self.stop_event.set()

def run_shadow(cfg,show_status:bool=False):
    try: asyncio.run(ShadowPaperTrader(cfg,console_status=show_status).start())
    finally:
        if show_status: print("\nShadow mode stopped.")
