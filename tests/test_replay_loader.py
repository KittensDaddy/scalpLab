import gzip, json
import pandas as pd
from scalp.replay.loader import RecordedFeatureLoader


def test_replay_preserves_availability_and_micro_features(tmp_path):
    rows=[]
    base=pd.Timestamp('2026-08-01T00:00:00Z')
    for i in range(70):
        rows.append({
            'receive_ts': int((base+pd.Timedelta(seconds=i)).timestamp()*1000),
            'mid': 100+i*.01,
            'aggressive_volume_5s': 2,
            'ofi': .2,
            'cvd': i,
            'cvd_delta': 1,
            'depth_imbalance': .15,
            'microprice_change_bps': .05,
            'replenishment_bid': 2,
            'replenishment_ask': 1,
            'absorption_bid': .3,
            'absorption_ask': .1,
            'spot_cvd_delta': 1 if i>=30 else 0,
            'spot_available': i>=30,
            'oi_delta': .001,
            'oi_available': True,
            'funding_rate': .0001,
            'funding_available': True,
        })
    f=tmp_path/'features'/'futures'/'BTCUSDT'/'2026-08-01'/'feature'
    f.mkdir(parents=True)
    p=f/'x.jsonl.gz'
    with gzip.open(p,'wt') as h:
        for r in rows: h.write(json.dumps(r)+'\n')
    loader=RecordedFeatureLoader(str(tmp_path/'features'),str(tmp_path/'none'))
    frame=loader.load('BTCUSDT',base,base+pd.Timedelta(seconds=69))
    bars=loader.to_bars(frame,'1min')
    assert len(bars)==2
    assert bool(bars.iloc[0].spot_available) is True
    assert bool(bars.iloc[0].oi_available) is True
    assert 'ofi' in bars and bars.iloc[0].ofi == .2
    assert bars.iloc[0].feature_coverage_pct >= 99
    assert bool(bars.iloc[0].data_quality_gap) is False
    assert bool(bars.iloc[1].data_quality_gap) is True
