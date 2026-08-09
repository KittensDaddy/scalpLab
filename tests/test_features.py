from scalp.features import build_features

def test_features_no_lookahead_breakout(trend_df):
    f=build_features(trend_df)
    i=100
    expected=trend_df.high.iloc[i-20:i].max()
    assert abs(f.prev_high20.iloc[i]-expected)<1e-9

def test_core_features_exist(trend_df):
    f=build_features(trend_df)
    for c in ["ema20","ema50","atr","rsi","adx","range_pos","bb_width_pct","taker_buy_share"]:
        assert c in f.columns
