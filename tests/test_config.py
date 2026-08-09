import pytest
from scalp.config import AppConfig

def test_invalid_risk_rejected():
    with pytest.raises(Exception):
        AppConfig.model_validate({"risk":{"normal_risk_pct":1.0,"max_symbol_risk_pct":0.5,"max_total_open_risk_pct":2}})
