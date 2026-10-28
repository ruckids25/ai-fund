from core.config import risk_config, watchlist


def test_risk_yaml_matches_risk_rules():
    r = risk_config()
    lb = r["loss_budget"]
    assert lb["hard_stop"] == -15000
    assert lb["soft_stop"] == -7500
    assert lb["daily_stop"] == -600
    assert lb["risk_per_trade"] == 300
    assert r["positions"]["max_open_total"] == 3
    c, s = r["desks"]["crypto"], r["desks"]["stocks"]
    assert c["max_leverage"] == 5 and c["margin_mode"] == "isolated"
    assert c["max_margin_pct"] == 0.20 and c["liq_buffer_pct"] == 0.50
    assert c["capital_thb"] <= -lb["hard_stop"]  # never deposit more than the loss budget
    assert s["margin"] is False and s["max_position_pct"] == 0.33
    assert r["api"]["max_committee_tickers_per_day"] == 5


def test_risk_values_are_sane():
    lb = risk_config()["loss_budget"]
    assert lb["hard_stop"] < lb["soft_stop"] < lb["daily_stop"] < 0 < lb["risk_per_trade"]
    assert risk_config()["fx"]["usdthb"] > 0


def test_watchlist():
    w = watchlist()
    assert w["stocks"] == ["NVDA", "AAPL", "MSFT"]
    assert all(sym.endswith(":USDT") for sym in w["crypto"])
