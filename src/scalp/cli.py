from __future__ import annotations
import argparse, json, subprocess, sys
import uvicorn
from scalp.service import ResearchService
from scalp.config import load_config, AppConfig
from scalp.live.recorder import run_recorder
from scalp.live.shadow import run_shadow
from scalp.live.doctor import doctor
from scalp.live.storage_health import StorageManager
from scalp.data.tardis import TardisSampleClient
from scalp.progress import ConsoleProgress
from scalp.runtime import ensure_nofile_limit
from scalp.recorder_control import run_daemon

def symbols_arg(s): return [x.strip().upper() for x in s.split(',') if x.strip()]
def dump(x): print(json.dumps(x,indent=2,default=str))

def main():
    p=argparse.ArgumentParser(prog="scalp",description="ScalpLab research terminal")
    sub=p.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("serve"); s.add_argument("--host",default="0.0.0.0"); s.add_argument("--port",type=int,default=8080); s.add_argument("--fd-limit",type=int,default=8192); s.add_argument("--max-connections",type=int,default=64)
    for name in ["backtest","walkforward","replay"]:
        q=sub.add_parser(name); q.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT"); q.add_argument("--interval",default="5m"); q.add_argument("--days",type=int,default=14); q.add_argument("--from",dest="start"); q.add_argument("--to",dest="end")
    q=sub.add_parser("optimize"); q.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT"); q.add_argument("--interval",default="5m"); q.add_argument("--days",type=int,default=90)
    r=sub.add_parser("record"); r.add_argument("--symbols"); r.add_argument("--full-l2")
    sub.add_parser("recorder-daemon")
    sh=sub.add_parser("shadow"); sh.add_argument("--symbols")
    sub.add_parser("doctor"); sub.add_parser("storage-status"); st=sub.add_parser("storage-prune"); st.add_argument("--apply",action="store_true")
    rd=sub.add_parser("radar"); rd.add_argument("--limit",type=int,default=30)
    td=sub.add_parser("tardis-sample"); td.add_argument("--symbol",required=True); td.add_argument("--day",required=True); td.add_argument("--type",default="incremental_book_L2")
    tr=sub.add_parser("tardis-replay"); tr.add_argument("--symbol",required=True); tr.add_argument("--day",required=True); tr.add_argument("--interval",default="1m")
    ml=sub.add_parser("ml-research"); ml.add_argument("--symbol",default="BTCUSDT"); ml.add_argument("--interval",default="5m"); ml.add_argument("--days",type=int,default=90)
    sub.add_parser("selftest")
    args=p.parse_args(); svc=ResearchService()
    if args.cmd=="serve":
        lim=ensure_nofile_limit(args.fd_limit)
        print(f"ScalpLab server FD limit: {lim.get('soft')} soft / {lim.get('hard')} hard · max HTTP concurrency {args.max_connections}", file=sys.stderr)
        uvicorn.run("scalp.web.app:app",host=args.host,port=args.port,reload=False,limit_concurrency=args.max_connections,backlog=max(64,args.max_connections*2),timeout_keep_alive=2)
        return
    if args.cmd=="recorder-daemon": run_daemon(); return
    if args.cmd=="doctor": dump(doctor(load_config())); return
    if args.cmd=="radar":
        from scalp.live.radar import MarketRadar
        dump(MarketRadar(load_config().live.futures_rest_base).scan(args.limit)); return
    if args.cmd=="storage-status": dump(StorageManager(load_config().storage).status()); return
    if args.cmd=="storage-prune": dump(StorageManager(load_config().storage).prune_raw_l2(dry_run=not args.apply)); return
    if args.cmd=="selftest": raise SystemExit(subprocess.call([sys.executable,"-m","pytest","-q"]))
    if args.cmd=="tardis-sample": print(TardisSampleClient().download(args.type,args.day,args.symbol)); return
    if args.cmd=="tardis-replay":
        prog=ConsoleProgress(); dump(svc.replay_tardis_sample(args.symbol,args.day,args.interval,progress=prog)["summary"]); return
    if args.cmd=="ml-research":
        from scalp.ml.baseline import logistic_walkforward
        prog=ConsoleProgress(); cfg=svc.config(); frame=svc.fetch_frames([args.symbol],args.interval,args.days,cfg,progress=prog)[args.symbol.upper()]; dump(logistic_walkforward(frame)); return
    if args.cmd in {"record","shadow"}:
        cfg=load_config(); raw=cfg.model_dump()
        if getattr(args,"symbols",None): raw["live"]["symbols"]=symbols_arg(args.symbols)
        if args.cmd=="record" and getattr(args,"full_l2",None): raw["live"]["full_l2_symbols"]=symbols_arg(args.full_l2)
        cfg=AppConfig.model_validate(raw)
        if args.cmd=="record": run_recorder(cfg,show_status=True)
        else: run_shadow(cfg,show_status=True)
        return
    syms=symbols_arg(args.symbols); prog=ConsoleProgress()
    if args.cmd=="backtest":
        out=svc.run_range(syms,args.interval,args.start,args.end,progress=prog) if args.start and args.end else svc.run(syms,args.interval,args.days,progress=prog); dump(out["summary"])
    elif args.cmd=="replay":
        if not args.start or not args.end: p.error("replay requires --from and --to")
        dump(svc.replay_range(syms,args.interval,args.start,args.end,progress=prog)["summary"])
    elif args.cmd=="walkforward":
        out=svc.walkforward_range(syms,args.interval,args.start,args.end,progress=prog) if args.start and args.end else svc.walkforward(syms,args.interval,args.days,progress=prog); dump({k:(v.get("summary") if isinstance(v,dict) else v) for k,v in out.items()})
    elif args.cmd=="optimize": dump(svc.optimize(syms,args.interval,args.days,progress=prog)[:10])
if __name__=="__main__": main()
