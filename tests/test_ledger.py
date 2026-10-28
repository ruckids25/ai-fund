import sqlite3

import pytest

from core.ledger import Ledger


@pytest.fixture
def led(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite")


def test_tables_created(led):
    with sqlite3.connect(led.path) as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"decisions", "orders", "api_costs", "daily_pnl"} <= names


def test_wal_mode(led):
    with sqlite3.connect(led.path) as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_decision_order_roundtrip(led):
    d = led.log_decision("stocks", "NVDA", "committee", "buy", confidence=0.7,
                         entry=100, stop=96, payload={"x": 1})
    o = led.log_order("stocks", "alpaca_paper", "NVDA", "buy", 2, stop=96, risk_thb=264,
                      entry=100, decision_id=d)
    assert len(led.open_orders()) == 1
    led.update_order(o, status="closed", exit_price=96, pnl_thb=-264, closed_ts="2026-10-28T00:00:00+00:00")
    assert led.open_orders() == []
    assert led.realized_pnl_thb() == -264


def test_order_requires_stop(led):
    with pytest.raises(sqlite3.IntegrityError):
        led.log_order("crypto", "okx_dry", "BTC/USDT:USDT", "buy", 0.01, stop=None, risk_thb=300)


def test_invalid_desk_rejected(led):
    with pytest.raises(sqlite3.IntegrityError):
        led.log_decision("forex", "EURUSD", "kronos", "pass")


def test_api_cost_and_daily_pnl(led):
    led.log_api_cost("ta_committee", "claude-sonnet-5-5", 0.42, symbol="NVDA")
    assert led.api_cost_usd("2000-01-01") == pytest.approx(0.42)
    led.record_daily_pnl("2026-10-28", "total", -100, 50, fx_usdthb=33)
    led.record_daily_pnl("2026-10-28", "total", -120, 40, fx_usdthb=33)  # upsert
    with sqlite3.connect(led.path) as c:
        assert c.execute("SELECT COUNT(*), realized_thb FROM daily_pnl").fetchone() == (1, -120)
