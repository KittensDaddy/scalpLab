from scalp.live.microstructure import MicrostructureTracker

def test_microstructure_snapshot_contains_core_features():
    m=MicrostructureTracker(); m.on_trade("BTCUSDT",100,2,False,"futures",1000); m.on_trade("BTCUSDT",100,1,True,"futures",1100); m.on_trade("BTCUSDT",100,1,False,"spot",1100)
    m.on_book_delta("BTCUSDT",{"bid_added":3,"bid_removed":1,"ask_added":1,"ask_removed":2}); m.set_oi("BTCUSDT",100); m.set_oi("BTCUSDT",101)
    x=m.snapshot("BTCUSDT",{"mid":100,"microprice_delta_bps":.1,"depth_imbalance":.2,"spread_bps":1},None,1200)
    assert "cvd" in x and "ofi" in x and "absorption_bid" in x and x["oi_delta"]>0

def test_interval_book_counters_reset_and_missing_context_is_not_confirmation():
    m=MicrostructureTracker(); s='BTCUSDT'
    m.on_book_delta(s,{'bid_added':5,'bid_removed':1,'ask_added':2,'ask_removed':1})
    first=m.snapshot(s,{'mid':100,'microprice_delta_bps':0,'depth_imbalance':0},None,1000)
    second=m.snapshot(s,{'mid':100,'microprice_delta_bps':0,'depth_imbalance':0},None,2000)
    assert first['replenishment_bid']==5
    assert second['replenishment_bid']==0
    assert second['cancel_bid']==0
    assert second['spot_available'] is False
    assert second['oi_available'] is False
