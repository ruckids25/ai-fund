"""Daily stocks loop: committee → risk_gate → Alpaca paper. Run after the US close.

  envs/ta/bin/python fund.py [--dry] [--tickers NVDA ...]   # --dry sends no order or cancel
  envs/ta/bin/python fund.py --halt "reason"                # no orders until the flag is cleared

The committee only proposes; only an approved evaluate_order() reaches the broker.
Any failure reading the account stops the run. PnL covers the stocks desk only until
risk_monitor adds crypto. Committee "sell" opens nothing: stocks are long-only and
exits are left to the broker stop/target.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from core import notify, risk_gate
from core.alpaca import AlpacaError, AlpacaPaper, order_payload
from core.config import risk_config, watchlist
from core.ledger import Ledger
from core.risk_gate import AccountState

log = logging.getLogger("fund")


def account_state(client, cfg: dict) -> tuple[AccountState, set[str]]:
    acct, positions = client.account(), client.positions()
    fx = cfg["fx"]["usdthb"]
    equity = float(acct["equity"])
    held = {p["symbol"] for p in positions}
    return AccountState(
        total_pnl_thb=(equity - cfg["desks"]["stocks"]["paper_baseline_usd"]) * fx,
        daily_pnl_thb=(equity - float(acct["last_equity"])) * fx,
        open_positions=len(held),
        stocks_open_value_usd=sum(abs(float(p["market_value"])) for p in positions),
    ), held


def last_closed_session(client, clock: dict) -> tuple[str, str]:
    """(latest session already closed, today in New York); broker clock and calendar are NY time."""
    now = clock["timestamp"][:16]
    ny_today = now[:10]
    start = (date.fromisoformat(ny_today) - timedelta(days=7)).isoformat()
    closed = [d["date"] for d in client.calendar(start, ny_today) if f"{d['date']}T{d['close']}" <= now]
    return closed[-1], ny_today


def cancel_stale_entries(client) -> list[str]:
    """Yesterday's entries that never filled: their signal is out of date."""
    gone = []
    for o in client.open_orders():
        if (o.get("client_order_id", "").startswith("fund-") and o["side"] == "buy"
                and float(o.get("filled_qty") or 0) == 0):
            client.cancel(o["id"])
            gone.append(o["symbol"])
    return gone


def _committee(ticker: str, day: str, ledger):
    from desks.committee.ta_committee import run_committee  # envs/ta only
    return run_committee(ticker, day, ledger=ledger)


def _round(price):
    return round(price, 2) if isinstance(price, (int, float)) else price


def run(tickers: list[str] | None = None, *, dry: bool = False, client=None, committee=_committee,
        ledger=None, cfg: dict | None = None, today: date | None = None) -> list[str]:
    """Return the report lines. Raises AlpacaError if the broker cannot be read."""
    cfg = cfg or risk_config()
    client = client or AlpacaPaper()
    ledger = ledger or Ledger()
    today = today or datetime.now(timezone.utc).date()
    lines = []

    clock = client.clock()
    if clock["is_open"] and not dry:
        return ["ตลาดเปิดอยู่: ไม่รัน (signal ต้องมาจากแท่งที่ปิดแล้ว)"]
    day, ny_today = last_closed_session(client, clock)
    if day != ny_today and not dry:     # holiday, or started before today's close
        return [f"วันนี้ ({ny_today}) ไม่มี session ที่ปิดแล้ว: ไม่รัน"]

    state, held = account_state(client, cfg)
    limits = risk_gate.check_limits(state, cfg)
    if limits.level in ("soft", "hard"):
        risk_gate.set_halt(limits.reason)
    if limits.level == "hard":
        if not dry:
            client.close_all()
        return [f"🛑 {limits.reason}: " + ("(dry) ไม่ได้ปิด position" if dry else "ปิดทุก position แล้ว")]
    if risk_gate.is_halted():
        return [f"⏸ halted: {limits.reason or 'halt flag set'} — ไม่เปิดออเดอร์"]
    if not limits.ok:
        return [f"⏸ {limits.reason} — ไม่เปิดออเดอร์"]

    if not dry:
        stale = cancel_stale_entries(client)
        if stale:
            lines.append("ยกเลิก entry ค้าง: " + ", ".join(stale))

    month_start = today.replace(day=1).isoformat()
    spent = ledger.api_cost_usd(month_start)
    if spent >= cfg["api"]["monthly_limit_usd"]:
        return lines + [f"ค่า API เดือนนี้ ${spent:.2f} ถึงเพดานแล้ว: ไม่รัน committee"]

    wanted = [t for t in (tickers or watchlist()["stocks"]) if t not in held]
    for ticker in wanted[:cfg["api"]["max_committee_tickers_per_day"]]:
        try:
            dec = committee(ticker, day, ledger)
        except Exception as e:  # one failed ticker must not stop the others
            log.exception("committee %s", ticker)
            lines.append(f"{ticker}: committee ล้มเหลว ({type(e).__name__})")
            continue
        if dec.action != "buy":
            lines.append(f"{ticker}: {dec.rating} → ไม่เปิด")
            continue

        entry, stop, target = _round(dec.entry), _round(dec.stop), _round(dec.target)
        gate = risk_gate.evaluate_order("stocks", "buy", entry, stop, state, cfg=cfg)
        decision_id = ledger.log_decision(
            "stocks", ticker, "risk_gate", "pass" if gate.approved else "reject", entry=entry,
            stop=stop, target=target, reason="; ".join(gate.reasons) or None,
            payload={"qty": gate.qty, "risk_thb": gate.risk_thb})
        if not gate.approved:
            lines.append(f"{ticker}: {dec.rating} → gate ปฏิเสธ: {'; '.join(gate.reasons)}")
            continue

        plan = f"{gate.qty:.0f} หุ้น @ {entry} stop {stop} target {target} เสี่ยง {gate.risk_thb:.0f} บาท"
        if dry:
            lines.append(f"{ticker}: {dec.rating} → (dry) {plan}")
        else:
            try:
                order = client.submit(order_payload(ticker, gate.qty, entry, stop, target, f"fund-{day}-{ticker}"))
            except AlpacaError as e:     # e.g. duplicate client_order_id on a rerun
                lines.append(f"{ticker}: ส่งออเดอร์ไม่สำเร็จ ({e})")
                continue
            ledger.log_order("stocks", "alpaca_paper", ticker, "buy", gate.qty, stop=stop,
                             risk_thb=gate.risk_thb, entry=entry, target=target,
                             decision_id=decision_id, broker_id=order["id"])
            lines.append(f"{ticker}: {dec.rating} → ส่งแล้ว {plan}")
        state = AccountState(state.total_pnl_thb, state.daily_pnl_thb, state.open_positions + 1,
                             state.stocks_open_value_usd + gate.qty * entry)
    return lines or ["ไม่มีตัวให้พิจารณา"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--halt", metavar="REASON")
    ap.add_argument("--tickers", nargs="+")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.halt:
        risk_gate.set_halt(args.halt)
        notify.send(f"⏸ ai-fund halted: {args.halt}")
        return 0
    try:
        lines, rc = run(args.tickers, dry=args.dry), 0
    except AlpacaError as e:
        lines, rc = [f"⚠️ Alpaca: {e}"], 1
    msg = f"ai-fund · fund.py{' --dry' if args.dry else ''}\n" + "\n".join(lines)
    print(msg)
    if not args.dry:
        notify.send(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
