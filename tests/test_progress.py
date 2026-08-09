from scalp.backtest import BacktestEngine
from scalp.config import AppConfig
from scalp.models import DataMode
from scalp.progress import map_progress
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
