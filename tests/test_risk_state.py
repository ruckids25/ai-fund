"""Shared snapshots and the freqtrade entry gate: stale or missing state must reject."""
import copy
import time

import pytest

import fund
from core import risk_gate, risk_state
from core.config import risk_config


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RISK_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HALT_FLAG_PATH", str(tmp_path / "halt.flag"))
    return tmp_path


@pytest.fixture
def cfg():
    c = copy.deepcopy(risk_config())
    c["fx"]["usdthb"] = 33.0
    return c


def publish(**kw):
    risk_state.write_snapshot("risk_state.json", {
        "level": "ok", "total_pnl_thb": 0, "daily_pnl_thb": 0, "open_positions": 0, **kw})


def test_snapshot_round_trip_and_corrupt_file(isolated):
    assert risk_state.read_snapshot("x.json") is None
    risk_state.write_snapshot("x.json", {"a": 1})
    assert risk_state.read_snapshot("x.json")["a"] == 1
    assert not list(isolated.glob("*.tmp"))
    (isolated / "x.json").write_text("{broken")
    assert risk_state.read_snapshot("x.json") is None


def test_stale_boundary():
    now = time.time()
    assert not risk_state.is_stale({"ts": now - 899}, now)
    assert risk_state.is_stale({"ts": now - 901}, now)
    assert risk_state.is_stale({}, now)


def test_entry_rejected_without_risk_state(cfg):
    assert not risk_state.approve_crypto_entry("buy", 100, 90, 5, 0.5, cfg).approved


def test_entry_rejected_when_risk_state_stale(cfg, isolated, monkeypatch):
    publish()
    monkeypatch.setattr(risk_state, "is_stale", lambda s, now=None: True)
    d = risk_state.approve_crypto_entry("buy", 100, 90, 5, 0.5, cfg)
    assert not d.approved and "stale" in d.reasons[0]


def test_entry_approved_long_and_short(cfg):
    publish()
    assert risk_state.approve_crypto_entry("buy", 100, 90, 5, 0.909, cfg).approved
    assert risk_state.approve_crypto_entry("sell", 100, 110, 5, 0.909, cfg).approved


def test_entry_rejected_when_amount_exceeds_approved_size(cfg):
    publish()
    d = risk_state.approve_crypto_entry("buy", 100, 90, 5, 1.2, cfg)
    assert not d.approved and "exceeds" in d.reasons[0]


@pytest.mark.parametrize("kw", [dict(total_pnl_thb=-7500), dict(daily_pnl_thb=-600), dict(open_positions=3)])
def test_entry_rejected_at_limits(cfg, kw):
    publish(**kw)
    assert not risk_state.approve_crypto_entry("buy", 100, 90, 5, 0.5, cfg).approved


def test_entry_rejected_by_halt_flag(cfg):
    publish()
    risk_gate.set_halt("manual")
    assert not risk_state.approve_crypto_entry("buy", 100, 90, 5, 0.5, cfg).approved


def test_account_state_adds_crypto(cfg):
    risk_state.write_snapshot("crypto_pnl.json", {"realized_usd": -10.0, "unrealized_usd": -5.0,
                                                  "daily_usd": -2.0, "open_positions": 2})

    class Broker:
        def account(self): return {"equity": "100000", "last_equity": "100000"}
        def positions(self): return [{"symbol": "NVDA", "market_value": "200"}]

    state, held = fund.account_state(Broker(), cfg)
    assert state.total_pnl_thb == pytest.approx(-15 * 33)
    assert state.daily_pnl_thb == pytest.approx(-2 * 33)
    assert state.open_positions == 3 and held == {"NVDA"}


def test_account_state_without_freqtrade_is_stocks_only(cfg):
    class Broker:
        def account(self): return {"equity": "99990", "last_equity": "100000"}
        def positions(self): return []

    state, _ = fund.account_state(Broker(), cfg)
    assert state.total_pnl_thb == pytest.approx(-330) and state.open_positions == 0
