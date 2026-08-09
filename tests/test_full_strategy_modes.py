from scalp.config import AppConfig
from scalp.decision import StrategyDecisionEngine
from scalp.models import DataMode
from scalp.features import build_features
from scalp.regimes import regime_scores
from scalp.strategies.lc import LiquidityCascade
from conftest import make_market

def test_full_lc_refuses_missing_microstructure():
    df=build_features(make_market("breakout",360)); r=df.dropna().iloc[-1]
    out=LiquidityCascade().evaluate(r,regime_scores(r),__import__('scalp.models',fromlist=['Direction']).Direction.LONG,DataMode.MICROSTRUCTURE)
    assert not out.eligible and out.missing_features

def test_full_lc_can_evaluate_with_microstructure_fields():
    df=build_features(make_market("breakout",360)); r=df.dropna().iloc[-1].copy()
    for k,v in {"ofi":.4,"depth_imbalance":.3,"microprice_change_bps":.2,"replenishment_bid":10,"replenishment_ask":5,"cvd_delta":10,"spot_cvd_delta":5}.items(): r[k]=v
    from scalp.models import Direction
    out=LiquidityCascade().evaluate(r,regime_scores(r),Direction.LONG,DataMode.MICROSTRUCTURE)
    assert out.eligible and out.proxy is False
