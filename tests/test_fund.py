"""fund.py against a fake broker and committee: no network, no LLM."""
import copy
from datetime import date
from types import SimpleNamespace

import pytest

import fund
from core import risk_gate
from core.alpaca import AlpacaPaper, AlpacaError, order_payload
from core.config import risk_config
from core.ledger import Ledger


class FakeBroker:
    def __init__(self, equity=100000.0, last_equity=100000.0, positions=(), orders=(), is_open=False):
        self.equity, self.last_equity, self._positions = equity, last_equity, list(positions)
        self._orders, self.is_open = list(orders), is_open
        self.submitted, self.cancelled, self.closed = [], [], False

    now = "2026-10-29T19:00:00.000-04:00"   # after that day's close
    submit_error = None

    def clock(self): return {"is_open": self.is_open, "timestamp": self.now}
    def account(self): return {"equity": str(self.equity), "last_equity": str(self.last_equity)}
    def positions(self): return self._positions
    def open_orders(self): return self._orders
    def calendar(self, start, end):
        days = ["2026-10-28", "2026-10-29", "2026-10-30"]
        return [{"date": d, "close": "16:00"} for d in days if d <= end]
    def cancel(self, oid): self.cancelled.append(oid)
    def close_all(self): self.closed = True

    def submit(self, payload):
        if self.submit_error:
            raise self.submit_error
        self.submitted.append(payload)
        return {"id": f"b{len(self.submitted)}"}


def buy(entry=100.0, stop=95.0, target=110.0, rating="Overweight", action="buy"):
    return SimpleNamespace(action=action, rating=rating, entry=entry, stop=stop, target=target)


def committee(decisions):
    """decisions: ticker → decision, or an Exception to raise. Records what was called."""
    def call(ticker, day, ledger):
        call.seen.append((ticker, day))
        d = decisions.get(ticker, buy())
        if isinstance(d, Exception):
            raise d
        return d
    call.seen = []
    return call


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


def go(broker, comm, ledger, cfg, tickers=("NVDA",), **kw):
    return fund.run(list(tickers), client=broker, committee=comm, ledger=ledger, cfg=cfg,
                    today=date(2026, 10, 30), **kw)


def test_approved_buy_submits_bracket_and_logs(ledger, cfg):
    b, c = FakeBroker(), committee({})
    go(b, c, ledger, cfg)
    assert c.seen == [("NVDA", "2026-10-29")]     # last closed session
    p = b.submitted[0]
    assert (p["order_class"], p["qty"], p["limit_price"], p["time_in_force"]) == ("bracket", "1", "100.00", "gtc")
    assert p["stop_loss"]["stop_price"] == "95.00" and p["take_profit"]["limit_price"] == "110.00"
    assert p["client_order_id"] == "fund-2026-10-29-NVDA"
    o = ledger.open_orders("stocks")[0]
    assert (o["symbol"], o["stop"], o["risk_thb"], o["broker_id"]) == ("NVDA", 95.0, 165.0, "b1")


def test_dry_sends_nothing(ledger, cfg):
    stale = {"id": "x", "symbol": "AAPL", "side": "buy", "filled_qty": "0", "client_order_id": "fund-old"}
    b = FakeBroker(orders=[stale])
    lines = go(b, committee({}), ledger, cfg, dry=True)
    assert not b.submitted and not b.cancelled and "(ทดลอง)" in lines[0]
    assert not ledger.open_orders()


@pytest.mark.parametrize("dec", [buy(stop=None), buy(stop=101.0), buy(entry=None)])
def test_gate_rejection_never_reaches_broker(ledger, cfg, dec):
    b = FakeBroker()
    lines = go(b, committee({"NVDA": dec}), ledger, cfg)
    assert not b.submitted and "ด่านความเสี่ยงปฏิเสธ" in lines[0]


@pytest.mark.parametrize("rating,action", [("Hold", "hold"), ("Underweight", "sell"), ("REVIEW", "review")])
def test_non_buy_opens_nothing(ledger, cfg, rating, action):
    b = FakeBroker()
    go(b, committee({"NVDA": buy(rating=rating, action=action)}), ledger, cfg)
    assert not b.submitted


def test_new_orders_count_towards_max_positions(ledger, cfg):
    b = FakeBroker(positions=[{"symbol": "XOM", "market_value": "100"}])
    lines = go(b, committee({}), ledger, cfg, tickers=("NVDA", "AAPL", "MSFT"))
    assert [p["symbol"] for p in b.submitted] == ["NVDA", "AAPL"]
    assert "ด่านความเสี่ยงปฏิเสธ" in lines[2]


def test_held_ticker_skipped_and_ticker_cap(ledger, cfg):
    b = FakeBroker(positions=[{"symbol": "NVDA", "market_value": "100"}])
    c = committee({"A": buy(action="hold")})
    go(b, c, ledger, cfg, tickers=("NVDA", "A", "A2", "A3", "A4", "A5", "A6"))
    assert [t for t, _ in c.seen] == ["A", "A2", "A3", "A4", "A5"]


def test_committee_failure_does_not_stop_others(ledger, cfg):
    b = FakeBroker()
    lines = go(b, committee({"NVDA": ValueError("boom")}), ledger, cfg, tickers=("NVDA", "AAPL"))
    assert "ล้มเหลว" in lines[0] and [p["symbol"] for p in b.submitted] == ["AAPL"]


def test_unclosed_session_is_not_used(ledger, cfg):
    b, c = FakeBroker(), committee({"NVDA": buy(action="hold")})
    b.now = "2026-10-30T06:00:00.000-04:00"       # morning before the 10-30 session
    go(b, c, ledger, cfg, dry=True)
    assert c.seen == [("NVDA", "2026-10-29")]
    c2 = committee({})
    assert "ไม่มี session" in go(b, c2, ledger, cfg)[0] and not c2.seen and not b.submitted


def test_submit_failure_keeps_going_and_logs_no_order(ledger, cfg):
    b = FakeBroker()
    b.submit_error = AlpacaError("HTTP 422 duplicate")
    lines = go(b, committee({}), ledger, cfg, tickers=("NVDA", "AAPL"))
    assert len(lines) == 2 and "ไม่สำเร็จ" in lines[0] and not ledger.open_orders()


def test_market_open_refuses(ledger, cfg):
    b, c = FakeBroker(is_open=True), committee({})
    go(b, c, ledger, cfg)
    assert not c.seen and not b.submitted


def test_halt_flag_blocks_before_spending_on_committee(ledger, cfg):
    risk_gate.set_halt("manual")
    b, c = FakeBroker(), committee({})
    assert "หยุดอยู่" in go(b, c, ledger, cfg)[0]
    assert not c.seen and not b.submitted


def test_daily_stop_uses_last_equity(ledger, cfg):
    b, c = FakeBroker(equity=99980, last_equity=100000), committee({})   # -$20 = -660 THB
    go(b, c, ledger, cfg)
    assert not c.seen and not risk_gate.is_halted()


def test_soft_stop_halts(ledger, cfg):
    b, c = FakeBroker(equity=99770, last_equity=99770), committee({})    # -$230 = -7,590 THB
    go(b, c, ledger, cfg)
    assert not c.seen and risk_gate.is_halted() and not b.closed


def test_hard_stop_closes_all_but_not_in_dry(ledger, cfg):
    b = FakeBroker(equity=99500, last_equity=99500)                       # -$500 = -16,500 THB
    go(b, committee({}), ledger, cfg, dry=True)
    assert not b.closed and risk_gate.is_halted()
    go(b, committee({}), ledger, cfg)
    assert b.closed


def test_stale_entries_cancelled_but_not_filled_or_foreign(ledger, cfg):
    orders = [
        {"id": "1", "symbol": "A", "side": "buy", "filled_qty": "0", "client_order_id": "fund-x"},
        {"id": "2", "symbol": "B", "side": "buy", "filled_qty": "1", "client_order_id": "fund-y"},
        {"id": "3", "symbol": "C", "side": "sell", "filled_qty": "0", "client_order_id": "fund-z"},
        {"id": "4", "symbol": "D", "side": "buy", "filled_qty": "0", "client_order_id": "manual"},
    ]
    b = FakeBroker(orders=orders)
    go(b, committee({"NVDA": buy(action="hold")}), ledger, cfg)
    assert b.cancelled == ["1"]


def test_monthly_api_budget_blocks_committee(ledger, cfg):
    ledger.log_api_cost("ta_committee", "m", 30.0)
    cfg["api"]["monthly_limit_usd"] = 30
    b, c = FakeBroker(), committee({})
    fund.run(["NVDA"], client=b, committee=c, ledger=ledger, cfg=cfg)
    assert not c.seen


def test_order_payload_without_usable_target_keeps_stop():
    for target in (None, 90.0):
        p = order_payload("X", 2, 100.0, 95.0, target, "id")
        assert p["order_class"] == "oto" and p["stop_loss"] == {"stop_price": "95.00"}
        assert "take_profit" not in p


@pytest.mark.parametrize("flag", ["false", "https://api.alpaca.markets/v2"])
def test_client_refuses_non_paper(monkeypatch, flag):
    monkeypatch.setenv("ALPACA_PAPER", flag)
    with pytest.raises(AlpacaError):
        AlpacaPaper()


@pytest.mark.parametrize("flag", ["true", "https://paper-api.alpaca.markets/v2"])
def test_client_accepts_paper(monkeypatch, flag):
    monkeypatch.setenv("ALPACA_PAPER", flag)
    AlpacaPaper()
