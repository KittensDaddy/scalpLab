from conftest import make_market
from scalp.config import AppConfig
from scalp.walkforward import WalkForwardRunner

def test_walkforward_rolls_future_folds():
    frames={"BTCUSDT":make_market("trend",1200,1,50000),"ETHUSDT":make_market("range",1200,2,3000)}
    r=WalkForwardRunner(AppConfig()).run(frames,train_bars=500,validation_bars=150,test_bars=150,step_bars=150)
    assert "summary" in r and r["summary"]["folds"]>=2
    assert len(r["folds"])==r["summary"]["folds"]
    assert all("test" in f for f in r["folds"])
