"""Sheet rows from a ledger fixture and a fake spreadsheet: no network, no gspread."""
import copy
import importlib.util
from datetime import date
from pathlib import Path

import pytest

from core.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sheet_sync", ROOT / "scripts" / "sheet_sync.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)

CFG = {"loss_budget": {"soft_stop": -7500, "hard_stop": -15000}}
SPY = {date(2026, 11, 2): 400.0, date(2026, 11, 3): 404.0, date(2026, 11, 4): 402.0}
TODAY = date(2026, 11, 4)


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "ledger.sqlite")
    run_id = led.start_run("fund", strategy_version="v1", quick_model="q", tickers='["NVDA","AAPL"]')
    led.log_decision("stocks", "AAPL", "committee", "hold", reason="wait", payload={"date": "2026-11-02", "rating": "Hold"})
    com = led.log_decision("stocks", "NVDA", "committee", "buy", confidence=0.7, entry=100, stop=95, target=110,
                           reason="x" * 500, payload={"date": "2026-11-02", "rating": "Buy", "cost_usd": 0.03})
    gate = led.log_decision("stocks", "NVDA", "risk_gate", "pass", entry=100, stop=95, target=110)
    led.log_api_cost("ta", "m", 0.03)
    led.finish_run(run_id, 0.03, [])
    led.save_outcome(com, {"close0": 100.0, "ret5": 0.05, "spy_ret5": 0.01})
    oid = led.log_order("stocks", "alpaca_paper", "NVDA", "buy", 2, stop=95, risk_thb=330, entry=100, target=110,
                        decision_id=gate, broker_id="b1")
    led.update_order(oid, status="closed", ts="2026-11-02T23:05:00+00:00", fill_price=100, filled_qty=2,
                     filled_ts="2026-11-03T14:30:00+00:00", exit_price=110, closed_ts="2026-11-04T15:00:00+00:00",
                     exit_reason="target", pnl_thb=660.0, r_multiple=2.0, hold_days=1.02)
    led.log_order("stocks", "alpaca_paper", "AAPL", "buy", 1, stop=90, risk_thb=330, entry=100, decision_id=None, broker_id="b2")
    led.record_daily_pnl("2026-11-03", "stocks", 0, 100, equity_thb=3370100, fx_usdthb=33.7, open_positions=1, halted=False)
    led.record_daily_pnl("2026-11-03", "crypto", 0, -10, fx_usdthb=33.7)
    led.record_daily_pnl("2026-11-04", "stocks", 660, 0, equity_thb=3370660, fx_usdthb=33.7, open_positions=0, halted=True)
    return led


def tabs_of(ledger):
    return ss.build_tabs(ss.read_ledger(ledger.path), SPY, CFG, TODAY)


def as_dicts(table):
    return [dict(zip(table[0], r)) for r in table[1:]]


def test_trade_row(ledger):
    t = as_dicts(tabs_of(ledger)["Trades"])
    assert [r["symbol"] for r in t] == ["NVDA", "AAPL"]
    r = t[0]
    assert r["strategy_version"] == "v1" and r["entry_limit"] == 100 and r["pnl_thb"] == 660.0
    assert r["exit_reason"] == "target" and r["r_multiple"] == 2.0 and r["broker_id"] == "b1"
    assert t[1]["strategy_version"] == "" and t[1]["fill_price"] == ""     # order without a decision


def test_times_are_bangkok_with_utc_column(ledger):
    r = as_dicts(tabs_of(ledger)["Trades"])[0]
    assert r["submitted_ts_th"] == "2026-11-03 06:05:00"     # crosses midnight
    assert r["submitted_ts_utc"] == "2026-11-02T23:05:00+00:00"
    assert r["filled_ts_th"] == "2026-11-03 21:30:00"


def test_long_rationale_is_cut_and_decision_id_kept(ledger):
    tabs = tabs_of(ledger)
    d = as_dicts(tabs["Decisions"])[1]
    assert len(d["rationale_short"]) == 300 and d["decision_id"] == 2
    assert len(as_dicts(tabs["Trades"])[0]["rationale_short"]) == 300


def test_decision_rows_include_every_committee_decision_and_outcome(ledger):
    hold, buy = as_dicts(tabs_of(ledger)["Decisions"])
    assert hold["action"] == "hold" and hold["gate_result"] == "" and hold["ret5"] == ""
    assert buy["gate_result"] == "pass" and buy["rating"] == "Buy" and buy["api_cost_usd"] == 0.03
    assert buy["close0"] == 100.0 and buy["ret5"] == 0.05 and buy["run_id"] and buy["strategy_version"] == "v1"


def test_gate_is_not_attached_to_a_later_committee_decision(ledger):
    ledger.log_decision("stocks", "NVDA", "committee", "hold", payload={"date": "2026-11-03"})
    rows = as_dicts(tabs_of(ledger)["Decisions"])
    assert rows[1]["gate_result"] == "pass" and rows[2]["gate_result"] == ""


def test_daily_row(ledger):
    first, second = as_dicts(tabs_of(ledger)["Daily"])
    assert first["total_pnl_thb"] == 90 and first["dist_to_soft_thb"] == 7590 and first["dist_to_hard_thb"] == 15090
    assert first["equity_usd"] == pytest.approx(100003, abs=1) and first["open_positions"] == 1
    assert first["halted"] is False and first["spy_ret_day"] == pytest.approx(0.01)
    assert second["daily_pnl_thb"] == 570 and second["halted"] is True
    assert second["spy_ret_day"] == pytest.approx(402 / 404 - 1)


def test_daily_api_cost_and_missing_spy_session(tmp_path):
    costs = [{"ts": "2026-10-31T00:00:00+00:00", "cost_usd": 9.0}, {"ts": "2026-11-01T01:00:00+00:00", "cost_usd": 1.0},
             {"ts": "2026-11-03T01:00:00+00:00", "cost_usd": 2.0}, {"ts": "2026-11-04T01:00:00+00:00", "cost_usd": 4.0}]
    pnl = [{"date": "2026-11-03", "desk": "stocks", "realized_thb": 0, "unrealized_thb": 0},
           {"date": "2026-11-07", "desk": "stocks", "realized_thb": 0, "unrealized_thb": 0}]
    first, weekend = as_dicts(ss.daily_rows(pnl, costs, SPY, CFG))
    assert first["api_cost_usd_today"] == 2 and first["api_cost_usd_mtd"] == 3
    assert weekend["api_cost_usd_today"] == 0 and weekend["api_cost_usd_mtd"] == 7 and weekend["spy_ret_day"] == ""


def test_summary_stats():
    o = lambda i, p, r, closed: {"id": i, "decision_id": 1, "status": "closed", "pnl_thb": p, "r_multiple": r,
                                 "filled_ts": "2026-11-02T14:00:00+00:00", "closed_ts": closed}
    orders = [o(1, 100, 1.0, "2026-11-02T20:00:00+00:00"), o(2, -40, -1.0, "2026-11-03T20:00:00+00:00"),
              o(3, -20, -0.5, "2026-11-03T21:00:00+00:00"), o(4, 60, 1.5, "2026-11-04T20:00:00+00:00"),
              {"id": 5, "decision_id": 1, "status": "submitted", "pnl_thb": None, "r_multiple": None}]
    decisions = [{"id": 1, "run_id": "a"}]
    runs = [{"run_id": "a", "ts": "2026-11-02T23:00:00+00:00", "strategy_version": "v1", "api_cost_usd": 1.5},
            {"run_id": "old", "ts": "2026-10-02T23:00:00+00:00", "strategy_version": "v0", "api_cost_usd": 9.0}]
    v0, v1, total = as_dicts(ss.summary_rows(orders, decisions, runs, SPY, TODAY))
    assert v1["strategy_version"] == "v1" and v1["trades"] == 4 and v1["win_rate"] == 0.5
    assert v1["avg_r"] == pytest.approx(0.25) and v1["profit_factor"] == pytest.approx(160 / 60)
    assert v1["max_dd_thb"] == 60 and v1["cum_pnl_thb"] == 100
    assert v1["spy_ret_same_period"] == pytest.approx(402 / 400 - 1) and v1["api_cost_usd_month"] == 1.5
    assert v0["trades"] == 0 and v0["win_rate"] == "" and v0["api_cost_usd_month"] == 0
    assert total["strategy_version"] == "ALL" and total["trades"] == 4


class FakeSheet:
    def __init__(self, title, rows=5, cols=5):
        self.title, self.row_count, self.col_count = title, rows, cols

    def resize(self, rows, cols):
        self.row_count, self.col_count = rows, cols


class FakeBook:
    def __init__(self, titles=("Notes",)):
        self.sheets = [FakeSheet(t) for t in titles]
        self.cells = {"Notes": [["mine"]]}

    def worksheets(self):
        return self.sheets

    def add_worksheet(self, title, rows, cols):
        s = FakeSheet(title, rows, cols)
        self.sheets.append(s)
        return s

    def values_batch_clear(self, body):
        for r in body["ranges"]:
            self.cells.pop(r, None)

    def values_batch_update(self, body):
        assert body["valueInputOption"] == "RAW"
        for d in body["data"]:
            self.cells[d["range"].split("!")[0]] = copy.deepcopy(d["values"])


def test_two_syncs_give_the_same_sheet_and_notes_untouched(ledger):
    book = FakeBook()
    ss.write_tabs(book, tabs_of(ledger))
    first = copy.deepcopy(book.cells)
    ss.write_tabs(book, tabs_of(ledger))
    assert book.cells == first and book.cells["Notes"] == [["mine"]]
    assert {s.title for s in book.sheets} == {"Notes", "Trades", "Decisions", "Daily", "Runs", "Summary"}


def test_removed_rows_do_not_linger_and_grid_grows():
    book = FakeBook(("Trades",))
    ss.write_tabs(book, {"Trades": [["a"]] * 9})
    assert book.sheets[0].row_count == 9
    ss.write_tabs(book, {"Trades": [["a"]]})
    assert book.cells["Trades"] == [["a"]]


def test_ledger_is_opened_read_only(ledger):
    import sqlite3
    c = sqlite3.connect(f"file:{ledger.path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        c.execute("DELETE FROM orders")
    c.close()
    assert ss.read_ledger(ledger.path)["orders"]


def test_failure_returns_1_and_logs_no_message(monkeypatch, caplog, tmp_path):
    def boom(*a, **k):
        raise ValueError("secret-looking text")
    monkeypatch.setattr(ss, "read_ledger", boom)
    assert ss.main() == 1
    assert "ValueError" in caplog.text and "secret-looking" not in caplog.text


def test_spreadsheet_failure_returns_1(ledger, monkeypatch):
    monkeypatch.setenv("LEDGER_PATH", str(ledger.path))
    monkeypatch.setattr(ss, "_spy_closes", lambda d: SPY)
    def boom():
        raise RuntimeError("no network")
    monkeypatch.setattr(ss, "_spreadsheet", boom)
    assert ss.main() == 1


def test_llm_text_starting_with_equals_is_sent_raw(ledger):
    ledger.log_decision("stocks", "X", "committee", "hold", reason='=IMPORTXML("http://x")', payload={"date": "2026-11-02"})
    book = FakeBook()
    ss.write_tabs(book, tabs_of(ledger))    # FakeBook asserts RAW
    assert as_dicts(book.cells["Decisions"])[-1]["rationale_short"].startswith("=IMPORTXML")
