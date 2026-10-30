"""risk_monitor against a fake broker: no network, no Telegram."""
import copy
import json

import pytest

import risk_monitor as rm
from core import risk_gate
from core.alpaca import AlpacaError
from core.config import risk_config
from core.ledger import Ledger

DAY = "2026-11-02"
POS = {"symbol": "NVDA", "market_value": "200", "unrealized_pl": "-10"}


class Broker:
    def __init__(self, equity=100000.0, last_equity=None, positions=(), orders=(), fail=False):
        self.equity, self.last_equity = equity, equity if last_equity is None else last_equity
        self._positions, self._orders, self.fail = list(positions), list(orders), fail
        self.closed = 0

    def account(self):
        if self.fail:
            raise AlpacaError("GET /v2/account: HTTP 500")
        return {"equity": str(self.equity), "last_equity": str(self.last_equity)}

    def positions(self): return self._positions
    def open_orders(self): return self._orders

    def close_all(self):
        self.closed += 1
        self._positions, self._orders = [], []


@pytest.fixture(autouse=True)
def halt_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("HALT_FLAG_PATH", str(tmp_path / "halt.flag"))
    monkeypatch.setenv("RISK_STATE_DIR", str(tmp_path))


@pytest.fixture
def cfg():
    c = copy.deepcopy(risk_config())
    c["fx"]["usdthb"] = 33.0
    return c


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite")


def seen_today(**kw):
    return {"level": "ok", "level_date": DAY, "heartbeat": DAY, "failures": 0, **kw}


def test_healthy_run_is_silent_after_heartbeat(cfg, ledger):
    alerts, new = rm.check(Broker(), cfg, ledger, {}, dry=False, today=DAY)
    assert len(alerts) == 1 and "ทำงานปกติ" in alerts[0] and new["heartbeat"] == DAY
    assert rm.check(Broker(), cfg, ledger, new, dry=False, today=DAY)[0] == []
    assert len(rm.check(Broker(), cfg, ledger, new, dry=False, today="2026-11-03")[0]) == 1


def test_daily_stop_alerts_once_per_day_without_halting(cfg, ledger):
    b = Broker(equity=99980, last_equity=100000, positions=[POS])       # -660 THB
    alerts, new = rm.check(b, cfg, ledger, seen_today(), dry=False, today=DAY)
    assert "daily stop" in alerts[0] and not risk_gate.is_halted() and not b.closed
    assert rm.check(b, cfg, ledger, new, dry=False, today=DAY)[0] == []
    next_day = rm.check(b, cfg, ledger, new, dry=False, today="2026-11-03")[0]
    assert any("daily stop" in a for a in next_day)


def test_soft_stop_halts_keeps_positions_alerts_once(cfg, ledger):
    b = Broker(equity=99770, positions=[POS])                            # -7,590 THB
    alerts, new = rm.check(b, cfg, ledger, seen_today(), dry=False, today=DAY)
    assert "soft stop" in alerts[0] and risk_gate.is_halted() and not b.closed
    assert rm.check(b, cfg, ledger, new, dry=False, today=DAY)[0] == []


def test_halt_survives_recovery(cfg, ledger):
    rm.check(Broker(equity=99770), cfg, ledger, seen_today(), dry=False, today=DAY)
    alerts, new = rm.check(Broker(), cfg, ledger, seen_today(level="soft"), dry=False, today=DAY)
    assert risk_gate.is_halted() and alerts == [] and new["level"] == "ok"


def test_hard_stop_closes_and_cancels_only_when_something_is_open(cfg, ledger):
    b = Broker(equity=99500, positions=[POS])                            # -16,500 THB
    alerts, new = rm.check(b, cfg, ledger, seen_today(), dry=False, today=DAY)
    assert b.closed == 1 and risk_gate.is_halted() and "hard stop" in alerts[0]
    assert rm.check(b, cfg, ledger, new, dry=False, today=DAY)[0] == [] and b.closed == 1
    only_orders = Broker(equity=99500, orders=[{"id": "x"}])
    rm.check(only_orders, cfg, ledger, new, dry=False, today=DAY)
    assert only_orders.closed == 1


def test_dry_changes_nothing(cfg, ledger):
    b = Broker(equity=99500, positions=[POS])
    alerts, _ = rm.check(b, cfg, ledger, seen_today(), dry=True, today=DAY)
    assert "hard stop" in alerts[0] and not b.closed and not risk_gate.is_halted()
    with ledger._conn() as c:
        assert c.execute("select count(*) from daily_pnl").fetchone()[0] == 0


def test_publishes_level_for_freqtrade_but_not_in_dry(cfg, ledger):
    rm.check(Broker(equity=99500), cfg, ledger, seen_today(), dry=True, today=DAY)
    assert rm.risk_state.read_snapshot("risk_state.json") is None
    rm.check(Broker(equity=99500), cfg, ledger, seen_today(), dry=False, today=DAY)
    snap = rm.risk_state.read_snapshot("risk_state.json")
    assert snap["level"] == "hard" and snap["total_pnl_thb"] == pytest.approx(-16500)


def test_crypto_pnl_counts_towards_limits_and_stale_alerts_once(cfg, ledger, monkeypatch):
    rm.risk_state.write_snapshot("crypto_pnl.json", {"realized_usd": -230.0, "unrealized_usd": 0.0,
                                                     "daily_usd": 0.0, "open_positions": 0})
    alerts, new = rm.check(Broker(), cfg, ledger, seen_today(), dry=False, today=DAY)
    assert "soft stop" in alerts[0] and not new["crypto_stale"]
    monkeypatch.setattr(rm.risk_state, "is_stale", lambda s, now=None: True)
    alerts, new = rm.check(Broker(), cfg, ledger, new, dry=False, today=DAY)
    assert any("freqtrade" in a for a in alerts) and new["crypto_stale"]
    assert not any("freqtrade" in a for a in rm.check(Broker(), cfg, ledger, new, dry=False, today=DAY)[0])


def test_daily_pnl_snapshot_splits_realized_and_unrealized(cfg, ledger):
    rm.check(Broker(equity=99950, positions=[POS]), cfg, ledger, seen_today(), dry=False, today=DAY)
    with ledger._conn() as c:
        r = c.execute("select * from daily_pnl").fetchone()
    assert r["desk"] == "stocks" and r["unrealized_thb"] == pytest.approx(-330)
    assert r["realized_thb"] == pytest.approx(-1650 + 330)


def _main(monkeypatch, tmp_path, broker, sent=True):
    path = tmp_path / "state.json"
    msgs = []
    monkeypatch.setattr(rm, "AlpacaPaper", lambda: broker)
    monkeypatch.setattr(rm, "STATE_PATH", str(path))
    monkeypatch.setattr(rm, "Ledger", lambda: Ledger(tmp_path / "l.sqlite"))
    monkeypatch.setattr(rm.notify, "send", lambda m: (msgs.append(m), sent)[1])
    monkeypatch.setattr("sys.argv", ["risk_monitor.py"])
    return path, msgs


def test_broker_outage_alerts_once_on_third_failure(monkeypatch, tmp_path):
    path, msgs = _main(monkeypatch, tmp_path, Broker(fail=True))
    assert [rm.main() for _ in range(5)] == [1] * 5
    assert len(msgs) == 1 and "3 รอบติด" in msgs[0]
    assert json.loads(path.read_text())["failures"] == 5


def test_undelivered_alert_is_retried(monkeypatch, tmp_path):
    path, msgs = _main(monkeypatch, tmp_path, Broker(), sent=False)
    rm.main()
    rm.main()
    assert len(msgs) == 2 and not path.exists()
