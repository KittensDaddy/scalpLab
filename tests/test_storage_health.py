from scalp.config import StorageConfig
from scalp.live.storage_health import StorageManager

def test_storage_fallback_and_status(tmp_path):
    cfg=StorageConfig(bulk_dir=str(tmp_path/"bulk"),fallback_bulk_dir=str(tmp_path/"fallback"),state_dir=str(tmp_path/"state"))
    s=StorageManager(cfg).status(); assert s["bulk"]["total"]>0 and s["level"] in {"OK","WARNING","PRESSURE","EMERGENCY"}
