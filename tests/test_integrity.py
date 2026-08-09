from scalp.live.integrity import IntegrityStore
from scalp.models import GapReason

def test_sessions_gaps_and_latest_features(tmp_path):
    db=IntegrityStore(tmp_path/"integrity.db")
    sid,prev=db.begin_session("host:boot1"); assert prev is None
    db.heartbeat(sid,{"x":1}); gid=db.record_gap(10,None,GapReason.NETWORK_OUTAGE,sid,"BTCUSDT","depth")
    db.close_gap(gid,20); db.update_latest_feature("BTCUSDT",20,"HEALTHY",{"ofi":.2})
    assert db.recent_gaps()[0]["end_ts"]==20
    assert db.latest_feature("BTCUSDT")["feature"]["ofi"]==.2
    db.end_session(sid,"CLEAN"); assert db.last_session()["status"]=="CLEAN"
