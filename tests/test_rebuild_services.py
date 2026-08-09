from pathlib import Path

import pytest

from scalp.runtime_storage import RuntimeRootManager, validate_runtime_root
from scalp.strategy_rules import RuleInterpreter, StrategyVersionStore
from scalp.universe import UniverseService, normalized_base


RULE = {
    "long": {"conditions": {"all": [{"field": "close", "op": "gt", "other_field": "ema_fast"}]}, "score": [],
             "trade": {"stop_anchor": "low", "atr_offset": 1, "target_r": 2, "urgency": 50, "minimum_expected_r": 1}},
    "short": {"conditions": {"field": "close", "op": "lt", "other_field": "ema_fast"}, "score": [],
              "trade": {"stop_anchor": "high", "atr_offset": 1, "target_r": 2, "urgency": 50, "minimum_expected_r": 1}},
}


def test_rule_validation_evaluation_and_immutability(tmp_path):
    engine = RuleInterpreter()
    assert engine.validate(RULE)["valid"]
    assert engine.evaluate(RULE["long"]["conditions"], {"close": 2, "ema_fast": 1})
    store = StrategyVersionStore(tmp_path / "rules.db")
    draft = store.create_draft("LC/v1", RULE, "LC-r1")
    published = store.publish(draft["id"])
    assert published["hash"]
    with pytest.raises(ValueError, match="only drafts"):
        store.update(draft["id"], RULE)


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
