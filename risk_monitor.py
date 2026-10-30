"""Loop C, every 5 minutes: PnL against the loss limits, between fund.py runs.

  .venv/bin/python risk_monitor.py [--dry]     # --dry prints only: no halt, close or Telegram

Daily stop alerts (risk_gate already blocks new entries), soft stop sets the halt flag,
hard stop also closes everything. Each alert goes out once per episode, retried until
Telegram accepts it. Three failed broker reads in a row alert too, because a silent
monitor looks the same as a healthy one; one summary a day proves it is alive.

Crypto PnL is not counted yet: nothing trades there until freqtrade exists.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from core import notify, risk_gate
from core.alpaca import AlpacaError, AlpacaPaper
from core.config import resolve, risk_config
from core.ledger import Ledger
from fund import account_state

log = logging.getLogger("risk_monitor")
STATE_PATH = "data/risk_monitor_state.json"
FAILURES_BEFORE_ALERT = 3


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def check(client, cfg: dict, ledger, seen: dict, *, dry: bool, today: str) -> tuple[list[str], dict]:
    """One pass. Returns the alerts to send and the state to keep if they are delivered."""
    state, _ = account_state(client, cfg)
    limits = risk_gate.check_limits(state, cfg)
    alerts = []

    if limits.level in ("soft", "hard") and not dry and not risk_gate.is_halted():
        risk_gate.set_halt(limits.reason)
    if limits.level == "hard" and not dry and (client.positions() or client.open_orders()):
        client.close_all()

    level = limits.level if limits.level in ("daily", "soft", "hard") else "ok"
    if level != "ok" and (level != seen.get("level") or (level == "daily" and seen.get("level_date") != today)):
        action = {"daily": "ไม่เปิดเทรดใหม่จนถึงวันถัดไป (UTC)", "soft": "halt แล้ว ต้องทบทวนก่อนเปิดใหม่",
                  "hard": "halt และปิดทุก position แล้ว"}[level]
        alerts.append(f"🛑 ai-fund: {limits.reason} — {action}")

    if seen.get("heartbeat") != today:
        alerts.append(f"ai-fund risk_monitor ทำงานปกติ · PnL รวม {state.total_pnl_thb:+,.0f} บาท "
                      f"· วันนี้ {state.daily_pnl_thb:+,.0f} บาท · เปิดอยู่ {state.open_positions} ตัว"
                      f"{' · HALTED' if risk_gate.is_halted() else ''}")

    if not dry:
        acct = client.account()
        fx = cfg["fx"]["usdthb"]
        unrealized = sum(float(p["unrealized_pl"]) for p in client.positions()) * fx
        ledger.record_daily_pnl(today, "stocks", state.total_pnl_thb - unrealized, unrealized,
                                equity_thb=float(acct["equity"]) * fx, fx_usdthb=fx)
    return alerts, {"level": level, "level_date": today, "heartbeat": today, "failures": 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    path = resolve(STATE_PATH)
    seen = _load(path)
    today = datetime.now(timezone.utc).date().isoformat()
    rc = 0
    try:
        alerts, new = check(AlpacaPaper(), risk_config(), Ledger(), seen, dry=args.dry, today=today)
    except AlpacaError as e:
        log.error("%s", e)
        rc = 1
        failures = seen.get("failures", 0) + 1
        new = {**seen, "failures": failures}
        alerts = [f"⚠️ ai-fund risk_monitor อ่านบัญชีไม่ได้ {failures} รอบติด: {e}"] if failures == FAILURES_BEFORE_ALERT else []

    if args.dry:
        print("\n".join(alerts) or "ไม่มีอะไรต้องแจ้ง")
        return rc
    # keep the old state if Telegram failed, so the same alert is retried next run
    if all([notify.send(a) for a in alerts]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(new))
    return rc


if __name__ == "__main__":
    sys.exit(main())
