"""Bring Alpaca paper orders into the ledger: fills, exits, PnL and R. Reads Alpaca only.

  .venv/bin/python scripts/reconcile_orders.py

Closed, cancelled and rejected rows are never revisited, so reruns change nothing except
last_sync_ts on open rows, and pnl_thb keeps the fx of the sync that closed it. A failure on
one order does not stop the others; the exit code is 1 if any failed, and cron_reconcile.sh alerts.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.alpaca import AlpacaError, AlpacaPaper  # noqa: E402
from core.config import env, resolve, risk_config  # noqa: E402
from core.ledger import Ledger, utcnow  # noqa: E402

log = logging.getLogger("reconcile")
VENUE = "alpaca_paper"
LEG_REASON = {"stop": "stop", "stop_limit": "stop", "trailing_stop": "stop", "limit": "target"}


def _ts(text: str) -> str:
    """Alpaca timestamp (may carry nanoseconds) → the ledger's UTC ISO-8601 seconds."""
    trimmed = re.sub(r"\.\d+", "", text).replace("Z", "+00:00")
    return datetime.fromisoformat(trimmed).astimezone(timezone.utc).isoformat(timespec="seconds")


def _closed_by_close_all() -> bool:
    """A position gone with no leg filled: risk_monitor and fund.py write the hard stop to the halt flag."""
    path = resolve(env("HALT_FLAG_PATH", "data/halt.flag"))
    return path.exists() and "hard stop" in path.read_text()


def _exit_from_legs(parent: dict) -> tuple[float, str, str] | None:
    for leg in parent.get("legs") or []:
        if leg["status"] == "filled":
            reason = LEG_REASON.get(leg["type"], "manual")
            return float(leg["filled_avg_price"]), _ts(leg["filled_at"]), reason
    return None


def _exit_from_activities(client, symbol: str, qty: float, filled_at: str) -> tuple[float, str, str] | None:
    """Sell fills after the entry, once they add up to the whole position. Partial exits stay open."""
    total = value = 0.0
    last = None
    for a in client.activities(after=filled_at):
        if a["symbol"] == symbol and a["side"] == "sell" and total < qty:
            q = float(a["qty"])
            total, value, last = total + q, value + q * float(a["price"]), a["transaction_time"]
    if last is None or total < qty - 1e-9:
        return None
    return value / total, _ts(last), "close_all" if _closed_by_close_all() else "manual"


def sync_order(row, client, held: set[str], fx: float, now: str) -> dict:
    """The ledger fields for one order, from the broker's current view of it."""
    fields = {"last_sync_ts": now}
    parent = client.order(row["broker_id"])
    filled_qty = float(parent.get("filled_qty") or 0)
    if parent["status"] == "rejected":
        return {**fields, "status": "rejected"}
    if filled_qty == 0:
        if parent["status"] in ("canceled", "expired"):
            return {**fields, "status": "cancelled"}
        return fields                 # still working

    fill_price = float(parent["filled_avg_price"])
    filled_ts = _ts(parent["filled_at"])
    fields.update(status="filled", fill_price=fill_price, filled_qty=filled_qty, filled_ts=filled_ts)

    found = _exit_from_legs(parent)
    if found is None and row["symbol"] not in held:
        found = _exit_from_activities(client, row["symbol"], filled_qty, parent["filled_at"])
    if found is None:
        return fields

    exit_price, closed_ts, reason = found
    risk = fill_price - row["stop"]    # long only; <= 0 if the entry filled through the stop
    hold = datetime.fromisoformat(closed_ts) - datetime.fromisoformat(filled_ts)
    fields.update(status="closed", exit_price=exit_price, closed_ts=closed_ts, exit_reason=reason,
                  pnl_thb=(exit_price - fill_price) * filled_qty * fx, fx_usdthb=fx,
                  r_multiple=(exit_price - fill_price) / risk if risk > 0 else None,
                  hold_days=hold.total_seconds() / 86400)
    return fields


def reconcile(client, ledger, fx: float, now: str | None = None) -> tuple[int, int]:
    """Return (orders checked, orders failed). Raises AlpacaError if positions cannot be read."""
    now = now or utcnow()
    held = {p["symbol"] for p in client.positions()}
    rows = ledger.orders_to_reconcile(VENUE)
    failed = 0
    for row in rows:
        if not row["broker_id"]:
            log.error("order %s has no broker_id", row["id"])
            failed += 1
            continue
        try:
            ledger.update_order(row["id"], **sync_order(row, client, held, fx, now))
        except AlpacaError as e:
            log.error("order %s: %s", row["id"], e)
            failed += 1
    return len(rows), failed


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        checked, failed = reconcile(AlpacaPaper(), Ledger(), risk_config()["fx"]["usdthb"])
    except AlpacaError as e:
        log.error("%s", e)
        return 1
    print(f"checked {checked}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
