import gzip, json

from scalp.data_inspector import DataInspector
from scalp.live.integrity import IntegrityStore


def test_inspector_marks_continuous_healthy_features_replay_ready(tmp_path):
    db=IntegrityStore(tmp_path/"integrity.db"); start=1_000_000; end=start+3_600_000
    chunk=tmp_path/"features.jsonl.gz"
    with gzip.open(chunk,"wt") as handle:
        handle.write(json.dumps({"receive_ts":start+1000,"mid":100,"spread_bps":1,"subscription_tier":"FULL_L2_DERIVED","universe_snapshot_id":"daily-1"})+"\n")
    db.register_coverage("LOCAL_DERIVED","BTCUSDT","feature",start,end,"HEALTHY","s1",str(chunk),3600)
    db.update_latest_feature("BTCUSDT",end,"HEALTHY",{"spread_bps":1,"ofi":.2})
    result=DataInspector(db).inspect("BTCUSDT",1,end_ms=end)
    assert result["verdict"]=="REPLAY READY"
    assert result["usable_for_microstructure_replay"] is True
    assert result["replay_coverage_pct"]==100
    assert result["recording_bounds"]=={"start_ms":start,"end_ms":end}
    assert result["files"][0]["tier"]=="FULL_L2_DERIVED"


def test_inspector_exposes_gaps_and_missing_files(tmp_path):
    db=IntegrityStore(tmp_path/"integrity.db"); start=2_000_000; end=start+3_600_000
    db.register_coverage("LOCAL_DERIVED","ETHUSDT","feature",start,end,"HEALTHY","s1",str(tmp_path/"gone.gz"),10)
    db.record_gap(start+1000,start+2000,"NETWORK_OUTAGE","s1","ETHUSDT","futures")
    result=DataInspector(db).inspect("ETHUSDT",1,end_ms=end)
    assert result["usable_for_microstructure_replay"] is False
    assert result["verdict"]=="INCOMPLETE"
    assert result["files"][0]["status"]=="MISSING"
    assert result["gaps"][0]["reason"]=="NETWORK_OUTAGE"


def test_inspector_rejects_semantically_invalid_features(tmp_path):
    db=IntegrityStore(tmp_path/"integrity.db"); start=3_000_000; end=start+3_600_000
    chunk=tmp_path/"bad-feature.jsonl.gz"
    with gzip.open(chunk,"wt") as handle:
        handle.write(json.dumps({"receive_ts":start+1000,"mid":100,"spread_bps":-2})+"\n")
    db.register_coverage("LOCAL_DERIVED","BTCUSDT","feature",start,end,"HEALTHY","s1",str(chunk),1)
    db.update_latest_feature("BTCUSDT",end,"HEALTHY",{})
    result=DataInspector(db).inspect("BTCUSDT",1,end_ms=end)
    assert result["sanity"]["passed"] is False
    assert any("negative spread" in x for x in result["reasons"])
