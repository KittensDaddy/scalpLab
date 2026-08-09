from pathlib import Path

import pytest

from scalp.runtime_storage import RuntimeRootManager, validate_runtime_root
from scalp.strategy_rules import RuleInterpreter, StrategyVersionStore, DeclarativeStrategy, FEATURES, FEATURE_DESCRIPTIONS
from scalp.models import DataMode, Direction
from scalp.universe import UniverseService, normalized_base
from scalp.config import load_config
from scalp.live.recorder import BinanceLiveRecorder
from scalp.recorder_control import configured_recorder, recorder_daemon
from scalp.runtime_storage import runtime_roots


RULE = {
    "long": {"base_score": 25, "conditions": {"all": [{"field": "close", "op": "gt", "other_field": "ema20"}]}, "score": [{"when":{"field":"rsi","op":"gt","value":50},"weight":50,"evidence_family":"momentum"}],
             "trade": {"stop_anchor": "low", "atr_offset": 1, "target_r": 2, "urgency": 50, "minimum_expected_r": 1}},
    "short": {"base_score": 25, "conditions": {"field": "close", "op": "lt", "other_field": "ema20"}, "score": [{"when":{"field":"rsi","op":"lt","value":50},"weight":50,"evidence_family":"momentum"}],
              "trade": {"stop_anchor": "high", "atr_offset": 1, "target_r": 2, "urgency": 50, "minimum_expected_r": 1}},
}


def test_rule_validation_evaluation_and_immutability(tmp_path):
    engine = RuleInterpreter()
    assert engine.validate(RULE)["valid"]
    assert engine.evaluate(RULE["long"]["conditions"], {"close": 2, "ema20": 1})
    store = StrategyVersionStore(tmp_path / "rules.db")
    draft = store.create_draft("LC/v1", RULE, "LC-r1")
    published = store.publish(draft["id"])
    assert published["hash"]
    with pytest.raises(ValueError, match="only drafts"):
        store.update(draft["id"], RULE)


def test_every_strategy_indicator_has_plain_language_help():
    assert set(FEATURES)==set(FEATURE_DESCRIPTIONS)
    assert all(len(text)>20 for text in FEATURE_DESCRIPTIONS.values())


def test_published_rule_adapter_produces_trade_geometry():
    strategy=DeclarativeStrategy("TC",RULE)
    row={"close":102,"ema20":100,"rsi":60,"low":99,"high":103,"atr":2}
    result=strategy.evaluate(row,{"TREND_UP":80,"TREND_DOWN":20},Direction.LONG,DataMode.OHLCV_PROXY)
    assert result.eligible
    assert result.score==75
    assert result.evidence_agreement==50
    assert result.stop_price==97
    assert result.expected_r==2


def test_runtime_migration_keeps_recovery_copy(tmp_path):
    source = tmp_path / "source"; source.mkdir(); (source / "payload").write_text("kept")
    manager = RuntimeRootManager(tmp_path / "pointer.json", source)
    result = manager.migrate(tmp_path / "destination")
    assert (tmp_path / "destination" / "payload").read_text() == "kept"
    assert (source / "payload").read_text() == "kept"
    assert result["old_data_retained"] is True


def test_universe_ranking_and_multiplier_mapping(tmp_path):
    exchange = {"symbols": [{"symbol": "1000PEPEUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                            {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL"}]}
    tickers = [{"symbol": "BTCUSDT", "quoteVolume": "20"}, {"symbol": "1000PEPEUSDT", "quoteVolume": "10"}]
    cmc = {"data": {"cryptoCurrencyList": [{"id": 1, "symbol": "BTC", "quotes": [{"marketCap": 100_000_000_000}], "tags": []},
                                                  {"id": 2, "symbol": "PEPE", "quotes": [{"marketCap": 500_000_000}], "tags": ["memes"]}]}}
    def fetch(url): return exchange if "exchangeInfo" in url else tickers if "ticker/24hr" in url else cmc
    snapshot = UniverseService(tmp_path, fetch).refresh()
    assert [x["symbol"] for x in snapshot["assets"]] == ["BTCUSDT", "1000PEPEUSDT"]
    assert snapshot["assets"][1]["theme_tags"] == ["Meme"]
    assert normalized_base("1000PEPEUSDT") == "PEPE"


def test_runtime_root_owns_all_mutable_config_paths():
    cfg=load_config(); root=runtime_roots.current().root
    assert Path(cfg.storage.bulk_dir)==root
    assert Path(cfg.storage.state_dir)==root/"state"
    assert Path(cfg.data.cache_dir).is_relative_to(root)
    assert Path(cfg.shadow.persist_path).is_relative_to(root)


def test_recorder_separates_lightweight_and_full_l2_streams():
    recorder=BinanceLiveRecorder(load_config())
    light=recorder._light_streams("futures",["BTCUSDT","ETHUSDT"])
    assert "btcusdt@aggTrade" in light
    assert not any("@depth" in stream for stream in light)
    assert all("@depth" in f"{s.lower()}@depth@{recorder.live.depth_speed}" for s in recorder.live.full_l2_symbols)


def test_recorder_daemon_starts_capture_automatically():
    import inspect
    assert inspect.signature(recorder_daemon).parameters["auto_start"].default is True
    recorder=configured_recorder()
    assert recorder.live.full_l2_symbols
    assert len(recorder.live.full_l2_symbols)<=4


def test_book_sync_health_explains_waiting_bridge(monkeypatch):
    import asyncio
    recorder=BinanceLiveRecorder(load_config())
    async def snapshot(market,symbol): return {"lastUpdateId":100,"bids":[["1","1"]],"asks":[["2","1"]]}
    monkeypatch.setattr(recorder,"_snapshot",snapshot)
    asyncio.run(recorder._sync_book("futures","BTCUSDT"))
    health=recorder.health["streams"]["futures:BTCUSDT:book"]
    assert health["state"]=="SYNCING"
    assert health["reason"]=="WAITING_FOR_STREAM_BRIDGE"


def test_recorder_selects_snapshot_top20_without_changing_l2(monkeypatch):
    import asyncio
    assets=[{"symbol":f"COIN{i}USDT"} for i in range(30)]
    monkeypatch.setattr(UniverseService,"latest",lambda self:{"snapshot_id":"daily-1","selection_date":"2026-08-10","assets":assets})
    class FixedDateTime:
        @classmethod
        def now(cls,tz=None):
            import datetime
            return datetime.datetime(2026,8,10,tzinfo=datetime.timezone.utc)
    monkeypatch.setattr("scalp.live.recorder.datetime",FixedDateTime)
    async def all_spot(self,symbols): return list(symbols)
    monkeypatch.setattr(BinanceLiveRecorder,"_available_spot_symbols",all_spot)
    recorder=BinanceLiveRecorder(load_config()); l2=list(recorder.live.full_l2_symbols)
    asyncio.run(recorder._refresh_universe(initial=True))
    assert recorder.light_symbols==[f"COIN{i}USDT" for i in range(20)]
    assert recorder.live.full_l2_symbols==l2
