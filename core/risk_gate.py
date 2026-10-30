"""Deterministic risk gate: every order must get an approval from evaluate_order().

No LLM and no network here; numbers come only from config/risk.yaml (RISK_RULES.md).
Fails closed: bad input, a missing stop or a halt flag means reject. Soft and hard
stops write the halt flag, so a PnL rebound cannot reopen trading until a person
clears it. The caller must close all positions when `close_all` is set (hard stop).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from core.config import env, resolve, risk_config
from core.ledger import utcnow


@dataclass(frozen=True)
class AccountState:
    total_pnl_thb: float             # realized + unrealized, all desks, since inception
    daily_pnl_thb: float             # realized + unrealized, all desks, today (UTC)
    open_positions: int              # all desks
    stocks_open_value_usd: float = 0.0


@dataclass(frozen=True)
class LimitCheck:
    level: str                       # ok / max_positions / daily / soft / hard
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.level == "ok"


@dataclass(frozen=True)
class GateDecision:
    approved: bool
    qty: float = 0.0
    risk_thb: float = 0.0
    leverage: float = 1.0
    reasons: list[str] = field(default_factory=list)
    close_all: bool = False          # hard stop: close everything now


def _halt_path() -> Path:
    return resolve(env("HALT_FLAG_PATH", "data/halt.flag"))


def is_halted() -> bool:
    return _halt_path().exists()


def set_halt(reason: str) -> None:
    path = _halt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(f"{utcnow()} {reason}\n")


def clear_halt() -> None:
    """Manual only (after review); nothing in the trading loop should call this."""
    _halt_path().unlink(missing_ok=True)


def size_position(entry: float, stop: float, fx: float, cfg: dict | None = None) -> float:
    """Units that lose exactly risk_per_trade THB at the stop, before caps and rounding."""
    cfg = cfg or risk_config()
    return cfg["loss_budget"]["risk_per_trade"] / fx / abs(entry - stop)


def check_limits(state: AccountState, cfg: dict | None = None) -> LimitCheck:
    """Most severe first; reaching a limit exactly counts as hitting it."""
    cfg = cfg or risk_config()
    budget = cfg["loss_budget"]
    if state.total_pnl_thb <= budget["hard_stop"]:
        return LimitCheck("hard", f"ถึงเพดานขาดทุนรวม (hard stop): {state.total_pnl_thb:,.0f} บาท")
    if state.total_pnl_thb <= budget["soft_stop"]:
        return LimitCheck("soft", f"ถึงเพดานเตือน (soft stop): ขาดทุนรวม {state.total_pnl_thb:,.0f} บาท")
    if state.daily_pnl_thb <= budget["daily_stop"]:
        return LimitCheck("daily", f"ถึงเพดานรายวัน (daily stop): วันนี้ {state.daily_pnl_thb:,.0f} บาท")
    if state.open_positions >= cfg["positions"]["max_open_total"]:
        return LimitCheck("max_positions", f"เปิดอยู่ครบแล้ว {state.open_positions} ตัว")
    return LimitCheck("ok")


def check_liquidation(entry: float, stop: float, lev: float, cfg: dict | None = None) -> bool:
    """Isolated-margin liq must lie beyond the stop by >= liq_buffer_pct of the stop distance.

    Side is read from the stop (below entry = long). Liq is estimated as
    entry * (1 -/+ 1/lev +/- maint_margin_pct), not the exchange's exact tier.
    """
    cfg = cfg or risk_config()
    crypto = cfg["desks"]["crypto"]
    stop_dist = abs(entry - stop)
    if stop_dist == 0 or lev <= 0:
        return False
    liq_dist = entry * (1 / lev - crypto["maint_margin_pct"])
    return liq_dist >= stop_dist * (1 + crypto["liq_buffer_pct"])


def _floor(qty: float, step: float) -> float:
    return round(math.floor(qty / step) * step, 10)


def _valid_inputs(side: str, entry, stop, fx) -> str | None:
    if side not in ("buy", "sell"):
        return f"ไม่รู้จักฝั่ง {side!r}"
    if stop is None:
        return "ไม่มีจุดตัดขาดทุน"          # RISK_RULES 3
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (entry, stop, fx)):
        return "ราคาเข้า จุดตัดขาดทุน และอัตราแลกเปลี่ยนต้องเป็นตัวเลขบวก"
    if (side == "buy" and stop >= entry) or (side == "sell" and stop <= entry):
        return "จุดตัดขาดทุนอยู่ผิดฝั่งของราคาเข้า"
    return None


def _size_stocks(side, entry, stop, leverage, state, fx, cfg) -> tuple[float, str | None]:
    desk = cfg["desks"]["stocks"]
    if side != "buy":
        return 0.0, "หุ้นใช้เงินสดเท่านั้น: short ไม่ได้"
    if leverage != 1:
        return 0.0, "หุ้นใช้เงินสดเท่านั้น: ใช้ leverage ไม่ได้"
    max_value = desk["capital_usd"] * desk["max_position_pct"]
    remaining = desk["capital_usd"] * desk["max_total_pct"] - state.stocks_open_value_usd
    qty = min(size_position(entry, stop, fx, cfg), max_value / entry, remaining / entry)
    return float(math.floor(qty)) if qty > 0 else 0.0, None


def _size_crypto(entry, stop, leverage, qty_step, fx, cfg) -> tuple[float, str | None]:
    desk = cfg["desks"]["crypto"]
    if desk["margin_mode"] != "isolated":
        return 0.0, "crypto ต้องใช้ isolated margin"
    if not 1 <= leverage <= desk["max_leverage"]:
        return 0.0, f"leverage {leverage} อยู่นอกช่วง 1-{desk['max_leverage']}"
    if not check_liquidation(entry, stop, leverage, cfg):
        return 0.0, f"ราคา liquidation ใกล้จุดตัดขาดทุนเกินไปที่ {leverage}x"
    max_margin_usd = desk["capital_thb"] * desk["max_margin_pct"] / fx
    qty = min(size_position(entry, stop, fx, cfg), max_margin_usd * leverage / entry)
    return _floor(qty, qty_step), None


def evaluate_order(desk: str, side: str, entry: float, stop: float, state: AccountState, *,
                   leverage: float = 1, qty_step: float = 0.001,
                   cfg: dict | None = None) -> GateDecision:
    """Approve and size one new position, or reject it with the reasons."""
    cfg = cfg or risk_config()
    limits = check_limits(state, cfg)
    if limits.level in ("soft", "hard"):
        set_halt(limits.reason)
    close_all = limits.level == "hard"

    def reject(reason: str) -> GateDecision:
        return GateDecision(False, leverage=leverage, reasons=[reason], close_all=close_all)

    if is_halted():
        return reject(limits.reason or "สั่งหยุดระบบไว้")
    if not limits.ok:
        return reject(limits.reason)
    if desk not in ("stocks", "crypto"):
        return reject(f"ไม่รู้จัก desk {desk!r}")
    fx = cfg["fx"]["usdthb"]
    bad = _valid_inputs(side, entry, stop, fx)
    if bad:
        return reject(bad)

    if desk == "stocks":
        qty, bad = _size_stocks(side, entry, stop, leverage, state, fx, cfg)
    else:
        qty, bad = _size_crypto(entry, stop, leverage, qty_step, fx, cfg)
    if bad:
        return reject(bad)
    if qty <= 0:
        return reject("ขนาดไม้ไม่ถึงหน่วยขั้นต่ำภายใต้เพดานความเสี่ยง")
    return GateDecision(True, qty=qty, risk_thb=round(qty * abs(entry - stop) * fx, 2), leverage=leverage)
