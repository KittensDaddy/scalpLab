from scalp.live.chunks import ChunkWriter
from scalp.live.integrity import IntegrityStore

def test_chunk_writer_atomic_finalize(tmp_path):
    db=IntegrityStore(tmp_path/"state.db"); w=ChunkWriter(tmp_path/"bulk","s1",db,segment_seconds=999,max_events=2)
    base={"market":"futures","symbol":"BTCUSDT","event_type":"trade","receive_ts":1000,"exchange_ts":1000,"session_id":"s1"}
    w.add(base|{"payload":{"p":1}}); w.add(base|{"receive_ts":1001,"payload":{"p":2}})
    files=list((tmp_path/"bulk").rglob("*.jsonl.gz")); assert len(files)==1
    assert not list((tmp_path/"bulk").rglob("*.tmp"))

def test_finalized_chunk_orphan_metadata_is_recovered(tmp_path):
    db=IntegrityStore(tmp_path/'state.db'); sid,_=db.begin_session('host')
    w=ChunkWriter(str(tmp_path/'live'),sid,db,1,10,source='BINANCE_LIVE')
    w.add({'market':'futures','symbol':'BTCUSDT','event_type':'depth','receive_ts':1000})
    fp=w.flush_all()[0]
    # Simulate metadata loss after successful atomic rename.
    import sqlite3
    with sqlite3.connect(db.path) as c: c.execute('DELETE FROM coverage WHERE path=?',(str(fp),))
    got=ChunkWriter.recover_orphan_coverage(tmp_path/'live',db,'BINANCE_LIVE',sid)
    assert str(fp) in got
    assert str(fp) in db.coverage_paths()
