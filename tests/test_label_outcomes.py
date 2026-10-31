"""Outcome labels from candle fixtures, and run metadata: no network."""
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("label_outcomes", ROOT / "scripts" / "label_outcomes.py")
lo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lo)

DAY = date(2026, 11, 2)   # Monday; 2026-11-26 Thanksgiving is the holiday used below


def weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


SESSIONS = weekdays(DAY, 12)


def flat(sessions, close=100.0):
    """High/low 1 point around the close."""
    return {d: (close + 1, close - 1, close) for d in sessions}


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite")


def add_decision(ledger, action="buy", day="2026-11-02", symbol="NVDA", desk="stocks", stage="committee"):
    return ledger.log_decision(desk, symbol, stage, action, payload={"date": day})


def outcome(ledger, did):
    with ledger._conn() as c:
        return c.execute("SELECT * FROM decision_outcomes WHERE decision_id = ?", (did,)).fetchone()


def test_label_values():
    c = flat(SESSIONS[:11])
    c[SESSIONS[5]] = (121.0, 110.0, 120.0)    # 5th session after DAY
    c[SESSIONS[10]] = (111.0, 89.0, 90.0)     # 10th
    spy = flat(SESSIONS[:11], 400.0)
    spy[SESSIONS[5]] = (411.0, 409.0, 410.0)
    v = lo.label(c, spy, DAY, SESSIONS)
    assert v["close0"] == 100.0
    assert v["ret5"] == pytest.approx(0.20) and v["ret10"] == pytest.approx(-0.10)
    assert v["max_up10"] == pytest.approx(0.21) and v["max_dn10"] == pytest.approx(-0.11)
    assert v["spy_ret5"] == pytest.approx(0.025) and v["spy_ret10"] == pytest.approx(0.0)


def test_nothing_before_five_sessions():
    v = lo.label(flat(SESSIONS[:5]), flat(SESSIONS[:5]), DAY, SESSIONS)    # DAY + 4 after it
    assert v["close0"] == 100.0 and all(v[k] is None for k in v if k != "close0")


def test_ret5_available_before_ret10():
    v = lo.label(flat(SESSIONS[:6]), flat(SESSIONS[:6]), DAY, SESSIONS)
    assert v["ret5"] == 0 and v["ret10"] is None and v["max_up10"] is None


def test_holiday_is_not_counted_as_a_session():
    start = date(2026, 11, 23)
    sessions = [d for d in weekdays(start, 8) if d != date(2026, 11, 26)]
    c = flat(sessions)
    c[sessions[5]] = (131.0, 129.0, 130.0)
    assert sessions[5] == date(2026, 12, 1)
    assert lo.label(c, {}, start, sessions)["ret5"] == pytest.approx(0.30)


def test_missing_candle_delays_the_label():
    c = flat(SESSIONS[:6])
    del c[SESSIONS[3]]
    assert lo.label(c, {}, DAY, SESSIONS)["ret5"] is None


def test_unclosed_future_is_not_used_for_close0():
    c = flat(SESSIONS[1:3], 200.0)
    assert lo.label(c, {}, DAY, SESSIONS)["close0"] is None


def run(ledger, candles, today=date(2026, 12, 1), sessions=SESSIONS):
    return lo.label_all(ledger, lambda t, d: candles[t], lambda a, b: sessions, today)


def test_labels_every_action_only_for_stock_committee(ledger):
    ids = [add_decision(ledger, a) for a in ("buy", "hold", "sell", "review")]
    gate = add_decision(ledger, "pass", stage="risk_gate")
    crypto = add_decision(ledger, desk="crypto")
    data = {"NVDA": flat(SESSIONS), "SPY": flat(SESSIONS, 400.0)}
    assert run(ledger, data) == (4, 4, 0)
    assert all(outcome(ledger, i)["ret5"] == 0 for i in ids)
    assert outcome(ledger, gate) is None and outcome(ledger, crypto) is None


def test_rerun_does_not_change_stored_values(ledger):
    did = add_decision(ledger)
    run(ledger, {"NVDA": flat(SESSIONS), "SPY": flat(SESSIONS)})
    first = dict(outcome(ledger, did))
    # Yahoo re-adjusts history: complete rows are not pending any more
    assert run(ledger, {"NVDA": flat(SESSIONS, 50.0), "SPY": flat(SESSIONS, 50.0)}) == (0, 0, 0)
    assert dict(outcome(ledger, did)) == first


def test_partial_row_is_completed_later_keeping_old_values(ledger):
    did = add_decision(ledger)
    run(ledger, {"NVDA": flat(SESSIONS[:6]), "SPY": flat(SESSIONS[:6])})
    r = outcome(ledger, did)
    assert r["ret5"] == 0 and r["ret10"] is None
    c = flat(SESSIONS, 50.0)
    c[DAY] = (51.0, 49.0, 50.0)
    run(ledger, {"NVDA": c, "SPY": flat(SESSIONS)})
    r = outcome(ledger, did)
    assert r["close0"] == 100.0 and r["ret10"] == 0


def test_failed_ticker_does_not_stop_others(ledger):
    bad, good = add_decision(ledger, symbol="BAD"), add_decision(ledger, symbol="NVDA")

    def fetch(t, d):
        if t == "BAD":
            raise ValueError("no data")
        return flat(SESSIONS)

    assert lo.label_all(ledger, fetch, lambda a, b: SESSIONS, date(2026, 12, 1)) == (2, 1, 1)
    assert outcome(ledger, bad) is None and outcome(ledger, good)["ret5"] == 0


def test_benchmark_failure_keeps_stock_label_and_retries(ledger):
    did = add_decision(ledger)

    def fetch(t, d):
        if t == "SPY":
            raise ValueError("no data")
        return flat(SESSIONS)

    assert lo.label_all(ledger, fetch, lambda a, b: SESSIONS, date(2026, 12, 1)) == (1, 1, 1)
    r = outcome(ledger, did)
    assert r["ret5"] == 0 and r["spy_ret5"] is None
    assert len(ledger.decisions_to_label()) == 1


def test_decision_without_date_is_reported(ledger):
    ledger.log_decision("stocks", "NVDA", "committee", "buy")
    assert run(ledger, {}) == (0, 0, 1)


def test_run_id_tags_decisions_and_finish_counts_them(ledger):
    before = add_decision(ledger)
    run_id = ledger.start_run("fund", strategy_version="v1", tickers=json.dumps(["NVDA"]))
    tagged = add_decision(ledger)
    ledger.finish_run(run_id, 0.5, ["NVDA: boom"])
    after = add_decision(ledger)
    with ledger._conn() as c:
        ids = {r["id"]: r["run_id"] for r in c.execute("SELECT id, run_id FROM decisions")}
        r = c.execute("SELECT * FROM runs").fetchone()
    assert ids[before] is None and ids[tagged] == run_id and ids[after] is None
    assert r["n_decisions"] == 1 and r["api_cost_usd"] == 0.5 and json.loads(r["errors"]) == ["NVDA: boom"]


def test_close0_is_only_the_committee_session():
    c = flat(SESSIONS[:6])
    del c[DAY]
    v = lo.label(c, c, DAY, SESSIONS)
    assert v["close0"] is None and v["ret5"] is None


def test_nan_is_never_stored(ledger):
    did = add_decision(ledger)
    assert ledger.save_outcome(did, {"close0": float("nan")}) is False
    assert outcome(ledger, did) is None
