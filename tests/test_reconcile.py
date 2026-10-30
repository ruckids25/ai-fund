"""reconcile_orders against fake Alpaca responses: no network."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from core.alpaca import AlpacaError
from core.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reconcile_orders", ROOT / "scripts" / "reconcile_orders.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

FX, NOW = 33.0, "2026-11-05T00:00:00+00:00"
FILLED_AT = "2026-11-02T14:30:05.123456789Z"


class Broker:
    def __init__(self, parents, positions=(), fills=()):
        self.parents, self._positions, self.fills = parents, list(positions), list(fills)
        self.mutations = 0

    def positions(self): return [{"symbol": s} for s in self._positions]
    def activities(self, after=None): return self.fills

    def order(self, oid):
        if self.parents[oid] is None:
            raise AlpacaError(f"GET /v2/orders/{oid}: HTTP 404")
        return self.parents[oid]


def parent(status="filled", qty=2, price=100.0, legs=()):
    return {"status": status, "filled_qty": str(qty), "filled_avg_price": str(price) if qty else None,
            "filled_at": FILLED_AT if qty else None, "legs": list(legs)}


def leg(kind, status="filled", price=95.0, at="2026-11-04T14:30:05Z"):
    return {"type": kind, "status": status, "filled_avg_price": str(price), "filled_at": at}


STOP_OPEN, TARGET_OPEN = leg("stop", "new"), leg("limit", "new")


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite")


@pytest.fixture(autouse=True)
def no_halt(tmp_path, monkeypatch):
    monkeypatch.setenv("HALT_FLAG_PATH", str(tmp_path / "halt.flag"))
    return tmp_path / "halt.flag"


def add(ledger, broker_id="b1", symbol="NVDA", qty=2, stop=95.0):
    return ledger.log_order("stocks", "alpaca_paper", symbol, "buy", qty, stop=stop, risk_thb=300,
                            entry=100.0, target=110.0, broker_id=broker_id)


def row(ledger, oid):
    with ledger._conn() as c:
        return c.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()


def test_full_fill_stays_open(ledger):
    oid = add(ledger)
    rc.reconcile(Broker({"b1": parent(legs=[STOP_OPEN, TARGET_OPEN])}, ["NVDA"]), ledger, FX, NOW)
    r = row(ledger, oid)
    assert (r["status"], r["fill_price"], r["filled_qty"]) == ("filled", 100.0, 2)
    assert r["filled_ts"] == "2026-11-02T14:30:05+00:00" and r["last_sync_ts"] == NOW
    assert r["exit_price"] is None and r["pnl_thb"] is None


def test_partial_fill_uses_real_quantity_for_pnl(ledger):
    oid = add(ledger, qty=5)
    b = Broker({"b1": parent("partially_filled", qty=2, legs=[leg("limit", price=110.0)])})
    rc.reconcile(b, ledger, FX, NOW)
    r = row(ledger, oid)
    assert r["filled_qty"] == 2 and r["qty"] == 5 and r["pnl_thb"] == pytest.approx(10 * 2 * 33)


def test_cancelled_parent_with_partial_fill_counts_as_filled(ledger):
    oid = add(ledger, qty=5)
    rc.reconcile(Broker({"b1": parent("canceled", qty=1, legs=[STOP_OPEN])}, ["NVDA"]), ledger, FX, NOW)
    assert row(ledger, oid)["status"] == "filled"


def test_exit_by_stop(ledger):
    oid = add(ledger)
    rc.reconcile(Broker({"b1": parent(legs=[leg("stop", price=94.0), leg("limit", "canceled")])}), ledger, FX, NOW)
    r = row(ledger, oid)
    assert (r["status"], r["exit_reason"], r["exit_price"]) == ("closed", "stop", 94.0)
    assert r["pnl_thb"] == pytest.approx(-6 * 2 * 33) and r["r_multiple"] == pytest.approx(-1.2)
    assert r["fx_usdthb"] == FX and r["closed_ts"] == "2026-11-04T14:30:05+00:00"
    assert r["hold_days"] == pytest.approx(2.0)


def test_exit_by_target_r_multiple(ledger):
    oid = add(ledger)
    rc.reconcile(Broker({"b1": parent(legs=[leg("stop", "canceled"), leg("limit", price=110.0)])}), ledger, FX, NOW)
    r = row(ledger, oid)
    assert (r["exit_reason"], r["r_multiple"]) == ("target", pytest.approx(2.0))


def test_fill_through_stop_has_no_r_multiple(ledger):
    oid = add(ledger, stop=101.0)
    rc.reconcile(Broker({"b1": parent(legs=[leg("stop", price=99.0)])}), ledger, FX, NOW)
    assert row(ledger, oid)["r_multiple"] is None


@pytest.mark.parametrize("status,expected", [("canceled", "cancelled"), ("expired", "cancelled"),
                                             ("rejected", "rejected")])
def test_never_filled(ledger, status, expected):
    oid = add(ledger)
    rc.reconcile(Broker({"b1": parent(status, qty=0)}), ledger, FX, NOW)
    r = row(ledger, oid)
    assert r["status"] == expected and r["filled_qty"] is None and r["pnl_thb"] is None


@pytest.mark.parametrize("status", ["new", "accepted", "pending_new", "held"])
def test_working_order_only_marks_sync(ledger, status):
    oid = add(ledger)
    rc.reconcile(Broker({"b1": parent(status, qty=0)}), ledger, FX, NOW)
    r = row(ledger, oid)
    assert r["status"] == "submitted" and r["last_sync_ts"] == NOW


SELL = {"symbol": "NVDA", "side": "sell", "qty": "2", "price": "90", "transaction_time": "2026-11-03T15:00:00Z"}


def test_close_all_identified_from_hard_stop_flag(ledger, no_halt):
    no_halt.write_text("2026-11-03T15:00:00+00:00 ถึงเพดานขาดทุนรวม (hard stop): -15,000 บาท\n")
    oid = add(ledger)
    b = Broker({"b1": parent(legs=[leg("stop", "canceled"), leg("limit", "canceled")])}, fills=[SELL])
    rc.reconcile(b, ledger, FX, NOW)
    r = row(ledger, oid)
    assert (r["status"], r["exit_reason"], r["exit_price"]) == ("closed", "close_all", 90.0)
    assert r["pnl_thb"] == pytest.approx(-10 * 2 * 33)


def test_position_closed_by_hand_is_manual(ledger):
    oid = add(ledger)
    fills = [{**SELL, "symbol": "AAPL"}, {**SELL, "side": "buy"}, {**SELL, "qty": "1", "price": "90"},
             {**SELL, "qty": "1", "price": "100"}]
    rc.reconcile(Broker({"b1": parent(legs=[leg("stop", "canceled")])}, fills=fills), ledger, FX, NOW)
    r = row(ledger, oid)
    assert r["exit_reason"] == "manual" and r["exit_price"] == pytest.approx(95.0)


def test_position_gone_without_full_exit_fills_stays_open(ledger):
    oid = add(ledger)
    b = Broker({"b1": parent(legs=[STOP_OPEN])}, fills=[{**SELL, "qty": "1"}])
    rc.reconcile(b, ledger, FX, NOW)
    assert row(ledger, oid)["status"] == "filled"


def test_held_position_ignores_sell_fills(ledger):
    oid = add(ledger)
    rc.reconcile(Broker({"b1": parent(legs=[STOP_OPEN])}, ["NVDA"], fills=[SELL]), ledger, FX, NOW)
    assert row(ledger, oid)["status"] == "filled"


def test_rerun_changes_nothing_and_closed_keeps_its_fx(ledger):
    oid = add(ledger)
    b = Broker({"b1": parent(legs=[leg("stop", price=94.0)])})
    rc.reconcile(b, ledger, FX, NOW)
    first = dict(row(ledger, oid))
    assert rc.reconcile(b, ledger, 40.0, "2026-11-06T00:00:00+00:00") == (0, 0)
    assert dict(row(ledger, oid)) == first


def test_rerun_on_open_order_changes_only_sync_time(ledger):
    oid = add(ledger)
    b = Broker({"b1": parent(legs=[STOP_OPEN])}, ["NVDA"])
    rc.reconcile(b, ledger, FX, NOW)
    first = dict(row(ledger, oid))
    rc.reconcile(b, ledger, FX, "2026-11-06T00:00:00+00:00")
    assert {k for k, v in dict(row(ledger, oid)).items() if v != first[k]} == {"last_sync_ts"}


def test_one_failed_order_does_not_stop_others(ledger):
    bad, good = add(ledger, "b1"), add(ledger, "b2", "AAPL")
    b = Broker({"b1": None, "b2": parent(legs=[STOP_OPEN])}, ["AAPL"])
    assert rc.reconcile(b, ledger, FX, NOW) == (2, 1)
    assert row(ledger, bad)["status"] == "submitted" and row(ledger, good)["status"] == "filled"


def test_other_venues_and_missing_broker_id(ledger):
    other = ledger.log_order("crypto", "okx_dry", "BTC", "buy", 1, stop=1.0, risk_thb=1, broker_id="x")
    add(ledger, broker_id=None)
    assert rc.reconcile(Broker({}), ledger, FX, NOW) == (1, 1)
    assert row(ledger, other)["last_sync_ts"] is None


def test_positions_failure_raises_before_touching_rows(ledger):
    class Down(Broker):
        def positions(self): raise AlpacaError("GET /v2/positions: URLError")
    oid = add(ledger)
    with pytest.raises(AlpacaError):
        rc.reconcile(Down({}), ledger, FX, NOW)
    assert row(ledger, oid)["last_sync_ts"] is None


def test_realized_pnl_counts_reconciled_order(ledger):
    add(ledger)
    rc.reconcile(Broker({"b1": parent(legs=[leg("limit", price=110.0)])}), ledger, FX, NOW)
    assert ledger.realized_pnl_thb() == pytest.approx(10 * 2 * 33)


def test_migration_adds_columns_to_old_database_and_keeps_rows(tmp_path):
    path = tmp_path / "old.sqlite"
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE orders (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, decision_id INTEGER, desk TEXT NOT NULL,
        venue TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, qty REAL NOT NULL, entry REAL, stop REAL NOT NULL,
        target REAL, leverage REAL NOT NULL DEFAULT 1, risk_thb REAL NOT NULL, status TEXT NOT NULL, broker_id TEXT,
        fill_price REAL, exit_price REAL, pnl_thb REAL, closed_ts TEXT)""")
    c.execute("INSERT INTO orders (ts, desk, venue, symbol, side, qty, stop, risk_thb, status) "
              "VALUES ('t', 'stocks', 'alpaca_paper', 'NVDA', 'buy', 1, 90, 100, 'submitted')")
    c.commit()
    c.close()
    Ledger(path)
    led = Ledger(path)         # second open must not fail
    r = row(led, 1)
    assert r["symbol"] == "NVDA" and r["r_multiple"] is None and r["last_sync_ts"] is None


def test_timestamp_with_nanoseconds():
    assert rc._ts(FILLED_AT) == "2026-11-02T14:30:05+00:00"
