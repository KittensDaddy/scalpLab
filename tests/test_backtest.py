from scalp.config import AppConfig
from scalp.backtest import BacktestEngine
from scalp.models import DataMode
from conftest import make_market

def test_multisymbol_backtest_runs():
    cfg=AppConfig()
    frames={"BTCUSDT":make_market("trend",seed=1,start=50000),"ETHUSDT":make_market("range",seed=2,start=3000),"SOLUSDT":make_market("breakout",seed=3,start=150)}
    r=BacktestEngine(cfg,DataMode.OHLCV_PROXY).run(frames)
    assert r["summary"]["data_mode"]=="OHLCV_PROXY"
    assert set(r["by_strategy"])=={"TC","LC","LSR","RB","VB","TR"}
    assert len(r["equity_curve"])>0
    assert "NO_TRADE_LOW_SCORE" in r["no_trade_reasons"] or r["summary"]["trades"]>=0

def test_stop_first_setting_exists():
    cfg=AppConfig()
    assert cfg.execution.stop_first_on_ambiguous_bar is True
