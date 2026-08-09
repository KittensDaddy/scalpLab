import csv, gzip
from scalp.replay.tardis import TardisReplayBuilder


def write_gz(path, rows):
    with gzip.open(path,'wt',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['exchange','symbol','timestamp','local_timestamp','is_snapshot','side','price','amount'])
        w.writeheader(); w.writerows(rows)


def test_tardis_replay_skips_deltas_before_initial_snapshot(tmp_path):
    p=tmp_path/'book.csv.gz'
    rows=[
        # This bogus bid would destroy the mid if it were incorrectly retained.
        {'exchange':'binance-futures','symbol':'BTCUSDT','timestamp':500000,'local_timestamp':500000,'is_snapshot':'false','side':'bid','price':'1000','amount':'5'},
        {'exchange':'binance-futures','symbol':'BTCUSDT','timestamp':1000000,'local_timestamp':1000000,'is_snapshot':'true','side':'bid','price':'100','amount':'2'},
        {'exchange':'binance-futures','symbol':'BTCUSDT','timestamp':1000001,'local_timestamp':1000001,'is_snapshot':'true','side':'ask','price':'101','amount':'2'},
        {'exchange':'binance-futures','symbol':'BTCUSDT','timestamp':2000000,'local_timestamp':2000000,'is_snapshot':'false','side':'bid','price':'100','amount':'3'},
        {'exchange':'binance-futures','symbol':'BTCUSDT','timestamp':3000000,'local_timestamp':3000000,'is_snapshot':'false','side':'ask','price':'101','amount':'1'},
    ]
    write_gz(p,rows)
    out=TardisReplayBuilder(p).build('BTCUSDT')
    assert not out.empty
    assert out.iloc[0]['mid']==100.5
