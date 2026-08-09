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

def symbols_arg(s): return [x.strip().upper() for x in s.split(',') if x.strip()]
def dump(x): print(json.dumps(x,indent=2,default=str))

def main():
    p=argparse.ArgumentParser(prog="scalp",description="ScalpLab research terminal")
    sub=p.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("serve"); s.add_argument("--host",default="0.0.0.0"); s.add_argument("--port",type=int,default=8080)
    for name in ["backtest","walkforward","replay"]:
        q=sub.add_parser(name); q.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT"); q.add_argument("--interval",default="5m"); q.add_argument("--days",type=int,default=14); q.add_argument("--from",dest="start"); q.add_argument("--to",dest="end")
    q=sub.add_parser("optimize"); q.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT"); q.add_argument("--interval",default="5m"); q.add_argument("--days",type=int,default=90)
    r=sub.add_parser("record"); r.add_argument("--symbols"); r.add_argument("--full-l2")
    sh=sub.add_parser("shadow"); sh.add_argument("--symbols")
    sub.add_parser("doctor"); sub.add_parser("storage-status"); st=sub.add_parser("storage-prune"); st.add_argument("--apply",action="store_true")
    rd=sub.add_parser("radar"); rd.add_argument("--limit",type=int,default=30)
    td=sub.add_parser("tardis-sample"); td.add_argument("--symbol",required=True); td.add_argument("--day",required=True); td.add_argument("--type",default="incremental_book_L2")
    tr=sub.add_parser("tardis-replay"); tr.add_argument("--symbol",required=True); tr.add_argument("--day",required=True); tr.add_argument("--interval",default="1m")
    ml=sub.add_parser("ml-research"); ml.add_argument("--symbol",default="BTCUSDT"); ml.add_argument("--interval",default="5m"); ml.add_argument("--days",type=int,default=90)
    sub.add_parser("selftest")
    args=p.parse_args(); svc=ResearchService()
    if args.cmd=="serve": uvicorn.run("scalp.web.app:app",host=args.host,port=args.port,reload=False); return
    if args.cmd=="doctor": dump(doctor(load_config())); return
    if args.cmd=="radar":
        from scalp.live.radar import MarketRadar
        dump(MarketRadar(load_config().live.futures_rest_base).scan(args.limit)); return
    if args.cmd=="storage-status": dump(StorageManager(load_config().storage).status()); return
    if args.cmd=="storage-prune": dump(StorageManager(load_config().storage).prune_raw_l2(dry_run=not args.apply)); return
    if args.cmd=="selftest": raise SystemExit(subprocess.call([sys.executable,"-m","pytest","-q"]))
    if args.cmd=="tardis-sample": print(TardisSampleClient().download(args.type,args.day,args.symbol)); return
    if args.cmd=="tardis-replay": dump(svc.replay_tardis_sample(args.symbol,args.day,args.interval)["summary"]); return
    if args.cmd=="ml-research":
        from scalp.ml.baseline import logistic_walkforward
        cfg=svc.config(); frame=svc.fetch_frames([args.symbol],args.interval,args.days,cfg)[args.symbol.upper()]; dump(logistic_walkforward(frame)); return
    if args.cmd in {"record","shadow"}:
        cfg=load_config(); raw=cfg.model_dump()
        if getattr(args,"symbols",None): raw["live"]["symbols"]=symbols_arg(args.symbols)
        if args.cmd=="record" and getattr(args,"full_l2",None): raw["live"]["full_l2_symbols"]=symbols_arg(args.full_l2)
        cfg=AppConfig.model_validate(raw)
        if args.cmd=="record": run_recorder(cfg)
        else: run_shadow(cfg)
        return
    syms=symbols_arg(args.symbols)
    if args.cmd=="backtest":
        out=svc.run_range(syms,args.interval,args.start,args.end) if args.start and args.end else svc.run(syms,args.interval,args.days); dump(out["summary"])
    elif args.cmd=="replay":
        if not args.start or not args.end:
            p.error("replay requires --from and --to")
        dump(svc.replay_range(syms,args.interval,args.start,args.end)["summary"])
    elif args.cmd=="walkforward":
        out=svc.walkforward_range(syms,args.interval,args.start,args.end) if args.start and args.end else svc.walkforward(syms,args.interval,args.days); dump({k:(v.get("summary") if isinstance(v,dict) else v) for k,v in out.items()})
    elif args.cmd=="optimize": dump(svc.optimize(syms,args.interval,args.days)[:10])
if __name__=="__main__": main()
