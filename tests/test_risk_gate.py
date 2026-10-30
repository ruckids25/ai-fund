"""Every rule in RISK_RULES.md that risk_gate enforces, including exact boundaries."""
import copy

import pytest

from core import risk_gate as rg
from core.config import risk_config
from core.risk_gate import AccountState

CLEAN = AccountState(total_pnl_thb=0, daily_pnl_thb=0, open_positions=0)


@pytest.fixture(autouse=True)
def halt_flag(tmp_path, monkeypatch):
    path = tmp_path / "HALT"
    monkeypatch.setenv("HALT_FLAG_PATH", str(path))
    return path


@pytest.fixture
def cfg():
    c = copy.deepcopy(risk_config())
    c["fx"]["usdthb"] = 33.0      # pin fx so the expected sizes survive weekly updates
    return c


def state(**kw):
    return AccountState(**{"total_pnl_thb": 0, "daily_pnl_thb": 0, "open_positions": 0, **kw})


def test_config_matches_risk_rules():
    c = risk_config()
    assert c["loss_budget"] == {"hard_stop": -15000, "soft_stop": -7500, "daily_stop": -600,
                                "risk_per_trade": 300}
    assert c["positions"]["max_open_total"] == 3
    d = c["desks"]
    assert (d["crypto"]["max_leverage"], d["crypto"]["margin_mode"], d["crypto"]["max_margin_pct"],
            d["crypto"]["liq_buffer_pct"]) == (5, "isolated", 0.20, 0.50)
    assert (d["stocks"]["margin"], d["stocks"]["max_position_pct"], d["stocks"]["max_total_pct"]) == (False, 0.33, 1.0)


def test_size_position_is_risk_over_stop_distance(cfg):
    assert rg.size_position(100, 95, 33.0, cfg) == pytest.approx(300 / 33 / 5)
    assert rg.size_position(100, 105, 33.0, cfg) == pytest.approx(300 / 33 / 5)


@pytest.mark.parametrize("kw,level", [
    (dict(total_pnl_thb=-7499), "ok"),
    (dict(total_pnl_thb=-7500), "soft"),
    (dict(total_pnl_thb=-14999), "soft"),
    (dict(total_pnl_thb=-15000), "hard"),
    (dict(total_pnl_thb=-20000), "hard"),
    (dict(daily_pnl_thb=-599), "ok"),
    (dict(daily_pnl_thb=-600), "daily"),
    (dict(open_positions=2), "ok"),
    (dict(open_positions=3), "max_positions"),
    (dict(total_pnl_thb=-15000, daily_pnl_thb=-600, open_positions=3), "hard"),
])
def test_check_limits(cfg, kw, level):
    assert rg.check_limits(state(**kw), cfg).level == level


@pytest.mark.parametrize("entry,stop,lev,ok", [
    (100, 90, 5, True),     # liq dist 19.5 >= 15
    (100, 85, 5, False),    # 19.5 < 22.5
    (100, 85, 3, True),     # lower leverage fixes it
    (100, 110, 5, True),    # short mirrors long
    (100, 115, 5, False),
    (100, 100, 5, False),   # no stop distance
    (100, 90, 0, False),
])
def test_check_liquidation(cfg, entry, stop, lev, ok):
    assert rg.check_liquidation(entry, stop, lev, cfg) is ok


def test_stocks_size_floors_to_whole_shares(cfg):
    d = rg.evaluate_order("stocks", "buy", 100, 95, CLEAN, cfg=cfg)
    assert d.approved and d.qty == 1 and d.risk_thb == 165.0 and d.risk_thb <= 300


def test_stocks_capped_at_33_pct_of_capital(cfg):
    d = rg.evaluate_order("stocks", "buy", 500, 499, CLEAN, cfg=cfg)
    assert d.approved and d.qty == 1      # risk alone would allow 9 shares = $4,500


def test_stocks_capped_by_remaining_capital(cfg):
    d = rg.evaluate_order("stocks", "buy", 50, 49, state(stocks_open_value_usd=2900), cfg=cfg)
    assert d.approved and d.qty == 2
    full = rg.evaluate_order("stocks", "buy", 50, 49, state(stocks_open_value_usd=3000), cfg=cfg)
    assert not full.approved


def test_stocks_too_expensive_for_one_share_is_rejected(cfg):
    d = rg.evaluate_order("stocks", "buy", 1200, 1190, CLEAN, cfg=cfg)
    assert not d.approved and "zero" in d.reasons[0]


def test_stocks_no_short_no_leverage(cfg):
    assert not rg.evaluate_order("stocks", "sell", 100, 105, CLEAN, cfg=cfg).approved
    assert not rg.evaluate_order("stocks", "buy", 100, 95, CLEAN, leverage=2, cfg=cfg).approved


def test_crypto_risk_sizing_long_and_short(cfg):
    long = rg.evaluate_order("crypto", "buy", 100, 90, CLEAN, leverage=5, cfg=cfg)
    short = rg.evaluate_order("crypto", "sell", 100, 110, CLEAN, leverage=5, cfg=cfg)
    assert long.approved and short.approved and long.qty == short.qty == 0.909
    assert long.risk_thb == pytest.approx(0.909 * 10 * 33)


def test_crypto_margin_capped_at_20_pct(cfg):
    d = rg.evaluate_order("crypto", "buy", 100, 99, CLEAN, leverage=5, cfg=cfg)
    assert d.approved and d.qty == 4.545
    assert d.qty * 100 / 5 * 33 <= 15000 * 0.20


def test_crypto_leverage_limits(cfg):
    assert rg.evaluate_order("crypto", "buy", 100, 99, CLEAN, leverage=5, cfg=cfg).approved
    assert not rg.evaluate_order("crypto", "buy", 100, 99, CLEAN, leverage=6, cfg=cfg).approved
    assert not rg.evaluate_order("crypto", "buy", 100, 99, CLEAN, leverage=0.5, cfg=cfg).approved


def test_crypto_rejected_when_liquidation_too_close(cfg):
    d = rg.evaluate_order("crypto", "buy", 100, 85, CLEAN, leverage=5, cfg=cfg)
    assert not d.approved and "liquidation" in d.reasons[0]


def test_crypto_requires_isolated(cfg):
    cfg["desks"]["crypto"]["margin_mode"] = "cross"
    assert not rg.evaluate_order("crypto", "buy", 100, 90, CLEAN, cfg=cfg).approved


@pytest.mark.parametrize("side,entry,stop", [
    ("buy", 100, None),
    ("buy", 100, 100),
    ("buy", 100, 101),
    ("sell", 100, 99),
    ("hold", 100, 95),
    ("buy", float("nan"), 95),
    ("buy", 100, float("inf")),
    ("buy", -100, -105),
    ("buy", "100", 95),
])
def test_bad_inputs_rejected(cfg, side, entry, stop):
    d = rg.evaluate_order("crypto", side, entry, stop, CLEAN, cfg=cfg)
    assert not d.approved and d.qty == 0


def test_unknown_desk_and_bad_fx_rejected(cfg):
    assert not rg.evaluate_order("forex", "buy", 100, 95, CLEAN, cfg=cfg).approved
    cfg["fx"]["usdthb"] = 0
    assert not rg.evaluate_order("stocks", "buy", 100, 95, CLEAN, cfg=cfg).approved


def test_daily_stop_rejects_but_does_not_halt(cfg, halt_flag):
    d = rg.evaluate_order("stocks", "buy", 100, 95, state(daily_pnl_thb=-600), cfg=cfg)
    assert not d.approved and not d.close_all and not halt_flag.exists()
    assert rg.evaluate_order("stocks", "buy", 100, 95, CLEAN, cfg=cfg).approved


def test_max_positions_rejects(cfg):
    assert not rg.evaluate_order("stocks", "buy", 100, 95, state(open_positions=3), cfg=cfg).approved


def test_soft_stop_stays_halted_after_pnl_recovers(cfg, halt_flag):
    d = rg.evaluate_order("stocks", "buy", 100, 95, state(total_pnl_thb=-7500), cfg=cfg)
    assert not d.approved and not d.close_all and halt_flag.exists()
    assert not rg.evaluate_order("stocks", "buy", 100, 95, CLEAN, cfg=cfg).approved
    rg.clear_halt()
    assert rg.evaluate_order("stocks", "buy", 100, 95, CLEAN, cfg=cfg).approved


def test_hard_stop_asks_to_close_everything(cfg):
    d = rg.evaluate_order("crypto", "buy", 100, 90, state(total_pnl_thb=-15000), cfg=cfg)
    assert not d.approved and d.close_all and rg.is_halted()


def test_manual_halt_blocks_and_records_reason(cfg, halt_flag):
    assert not rg.is_halted()
    rg.set_halt("fund.py --halt")
    assert rg.is_halted() and "fund.py --halt" in halt_flag.read_text()
    d = rg.evaluate_order("stocks", "buy", 100, 95, CLEAN, cfg=cfg)
    assert not d.approved and d.reasons == ["halt flag set"]
