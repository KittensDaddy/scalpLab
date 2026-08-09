from scalp.backtest import BacktestEngine
from scalp.config import AppConfig
from scalp.models import DataMode
from scalp.progress import map_progress
from scalp.data.binance import BinanceFuturesClient, HistoricalCacheIndex
from conftest import make_market


def test_backtest_reports_monotonic_progress_to_100():
    seen=[]
    BacktestEngine(AppConfig(),DataMode.OHLCV_PROXY).run(
        {"BTCUSDT":make_market("trend",n=240)},
        progress=lambda pct,msg: seen.append((pct,msg)),
    )
    assert seen
    assert seen[0][0] == 0
    assert seen[-1][0] == 100
    assert all(a[0] <= b[0] for a,b in zip(seen,seen[1:]))
    assert any("Replay" in msg for _,msg in seen)


def test_progress_mapping():
    seen=[]
    cb=map_progress(lambda p,m: seen.append((p,m)),20,60)
    cb(50,"half")
    assert seen == [(40.0,"half")]


def test_binance_kline_cache_reports_progress(tmp_path):
    import pandas as pd
    root=tmp_path/"binance_usdm"/"klines"/"BTCUSDT"/"5m"; root.mkdir(parents=True)
    frame=make_market(n=2); frame.to_csv(root/"2026-01-01.csv.gz",index=False,compression="gzip")
    seen=[]
    out=BinanceFuturesClient(cache_dir=str(tmp_path)).klines(
        "BTCUSDT","5m",
        int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()*1000),
        int(pd.Timestamp("2026-01-01T00:05:00Z").timestamp()*1000),
        progress=lambda pct,msg: seen.append((pct,msg)),
    )
    assert len(out)==2
    assert seen[-1][0]==100
    assert any("Cache hit" in message for _,message in seen)
    assert out.attrs["historical_data"]["coverage_pct"]==100
    assert out.attrs["historical_data"]["day_access_sources"]=={"LOCAL_CACHE":1}


def test_binance_archive_parser_accepts_headerless_futures_zip():
    import io, zipfile
    row="1786320000000,100,102,99,101,12,1786320299999,1212,8,7,707,0\n"
    payload=io.BytesIO()
    with zipfile.ZipFile(payload,"w") as archive:
        archive.writestr("BTCUSDT-5m-2026-08-10.csv",row)
    frame=BinanceFuturesClient._archive_frame(payload.getvalue())
    assert len(frame)==1
    assert frame.iloc[0].close==101
    assert str(frame.iloc[0].timestamp.tz)=="UTC"


def test_binance_archive_is_used_before_rest(monkeypatch,tmp_path):
    import pandas as pd
    day=pd.Timestamp.now(tz="UTC").floor("D")
    frame=make_market(n=2); frame["timestamp"]=[day,day+pd.Timedelta(minutes=5)]
    client=BinanceFuturesClient(cache_dir=str(tmp_path))
    monkeypatch.setattr(client,"_archive_klines",lambda *args,**kwargs: frame)
    monkeypatch.setattr(client,"_fetch_kline_chunk",lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("REST must not be called")))
    out=client.klines("BTCUSDT","5m",int(day.timestamp()*1000),int((day+pd.Timedelta(minutes=5)).timestamp()*1000))
    assert len(out)==2


def test_historical_cache_cleanup_protects_recently_used_files(tmp_path):
    import sqlite3, time
    index=HistoricalCacheIndex(tmp_path); old=tmp_path/"old.csv.gz"; hot=tmp_path/"hot.csv.gz"
    old.write_bytes(b"old"); hot.write_bytes(b"hot")
    index.touch(old,"BTCUSDT","5m","2026-01-01",False,"BINANCE_ARCHIVE")
    index.touch(hot,"ETHUSDT","5m","2026-01-01",True,"LOCAL_CACHE")
    with sqlite3.connect(index.db) as conn: conn.execute("UPDATE entries SET last_used=? WHERE path=?",(time.time()-7201,"old.csv.gz"))
    preview=index.cleanup(dry_run=True)
    assert preview["eligible_files"]==1 and old.exists() and hot.exists()
    result=index.cleanup(dry_run=False)
    assert result["eligible_files"]==1 and not old.exists() and hot.exists()


def test_research_coverage_summarizes_sources_without_global_state():
    from scalp.service import ResearchService
    frame=make_market(n=2); frame.attrs["historical_data"]={"coverage_pct":97.5,"day_access_sources":{"LOCAL_CACHE":2,"BINANCE_DAILY_ARCHIVE":1}}
    coverage=ResearchService._historical_coverage({"BTCUSDT":frame})
    assert coverage["minimum_coverage_pct"]==97.5
    assert coverage["sources"]=={"LOCAL_CACHE":2,"BINANCE_DAILY_ARCHIVE":1}


def test_known_unavailable_day_skips_network_forever(monkeypatch,tmp_path):
    import pandas as pd
    root=tmp_path/"binance_usdm"/"klines"/"GRVTUSDT"/"1h"; root.mkdir(parents=True)
    (root/"2026-07-30.csv.unavailable").write_text("not listed")
    frame=make_market(n=1); frame["timestamp"]=[pd.Timestamp("2026-07-31T00:00:00Z")]
    frame.to_csv(root/"2026-07-31.csv.gz",index=False,compression="gzip")
    client=BinanceFuturesClient(cache_dir=str(tmp_path))
    monkeypatch.setattr(client,"_archive_klines",lambda *a,**k: (_ for _ in ()).throw(AssertionError("known unavailable day used network")))
    out=client.klines("GRVTUSDT","1h",int(pd.Timestamp("2026-07-30T00:00:00Z").timestamp()*1000),int(pd.Timestamp("2026-07-31T00:00:00Z").timestamp()*1000))
    assert len(out)==1
