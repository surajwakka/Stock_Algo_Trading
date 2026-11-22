import json
from pathlib import Path
import fundamentals

def test_profile_is_paper_only():
    c = json.loads(Path("config/paper_config.json").read_text())
    assert c["mode"] == "paper_only"
    assert c["live_trading_enabled"] is False
    assert c["starting_virtual_capital_inr"] == 50000
    assert c["risk_per_trade_pct"] == 1.0

def test_fundamental_missing_data_blocks():
    ok, reason = fundamentals.evaluate({}, {"min_market_cap_inr": 1, "max_trailing_pe": 60, "min_return_on_equity": .08})
    assert not ok and "missing metrics" in reason

def test_fundamental_pass():
    rules = {"min_market_cap_inr": 10_000_000_000, "max_trailing_pe": 60, "min_return_on_equity": .08}
    metrics = {"market_cap_inr": 20_000_000_000, "trailing_pe": 25, "return_on_equity": .12}
    assert fundamentals.evaluate(metrics, rules)[0]
