from scalp.features import build_features
from scalp.regimes import regime_scores
from scalp.models import Direction,DataMode
from scalp.strategies import all_strategies

def test_all_six_strategies_return_scores(breakout_df):
    f=build_features(breakout_df).dropna().reset_index(drop=True); row=f.iloc[-1]; reg=regime_scores(row)
    ids=set()
    for s in all_strategies():
        r=s.evaluate(row,reg,Direction.LONG,DataMode.OHLCV_PROXY)
        ids.add(r.strategy_id); assert 0<=r.score<=100; assert 0<=r.evidence_agreement<=100
    assert ids=={"TC","LC","LSR","RB","VB","TR"}

def test_lc_lsr_tr_are_proxy_in_ohlcv(breakout_df):
    f=build_features(breakout_df).dropna().reset_index(drop=True); row=f.iloc[-1]; reg=regime_scores(row)
    by={s.id:s for s in all_strategies()}
    for sid in ["LC","LSR","TR"]:
        assert by[sid].evaluate(row,reg,Direction.LONG,DataMode.OHLCV_PROXY).proxy
