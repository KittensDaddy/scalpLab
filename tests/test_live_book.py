import pytest
from scalp.live.book import LocalOrderBook, SequenceGap
from scalp.models import BookQuality

def test_futures_book_snapshot_bridge_and_gap():
    b=LocalOrderBook("BTCUSDT")
    b.apply_snapshot({"lastUpdateId":100,"bids":[["100","2"]],"asks":[["101","3"]]})
    out=b.apply_futures_delta({"U":101,"u":102,"pu":100,"b":[["100","4"]],"a":[["101","2"]]})
    assert out["applied"] and b.quality==BookQuality.HEALTHY and b.last_update_id==102
    m=b.metrics(); assert m["best_bid"]==100 and m["best_ask"]==101
    with pytest.raises(SequenceGap): b.apply_futures_delta({"U":104,"u":104,"pu":103,"b":[],"a":[]})
