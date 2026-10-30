"""Fill in what actually happened after every stock committee decision, taken or not.

  envs/data/bin/python scripts/label_outcomes.py

close0 is the close of the session the committee used, and ret5/ret10 are that many NYSE
sessions later. A horizon stays empty until every one of its sessions has a closed candle, so a
holiday or a data gap only delays a label. Stored values are never changed, so reruns are safe
even though Yahoo later adjusts old prices for dividends. Exit code 1 if any ticker failed.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ledger import Ledger  # noqa: E402

log = logging.getLogger("label")
BENCHMARK = "SPY"
Candles = dict  # session date -> (high, low, close)


def _forward(candles: Candles, day: date, sessions: list[date], n: int) -> list[date] | None:
    """The n sessions after `day`, or None until all of them have a candle."""
    next_n = [s for s in sessions if s > day][:n]
    return next_n if len(next_n) == n and all(s in candles for s in next_n) else None


def _close0(candles: Candles, day: date) -> float | None:
    before = [d for d in candles if d <= day]
    return candles[max(before)][2] if before else None


def _ret(candles: Candles, day: date, sessions: list[date], n: int) -> float | None:
    window, c0 = _forward(candles, day, sessions, n), _close0(candles, day)
    return candles[window[-1]][2] / c0 - 1 if window and c0 else None


def label(candles: Candles, spy: Candles, day: date, sessions: list[date]) -> dict:
    """Pure: every value that can be known so far, None for the rest."""
    c0 = _close0(candles, day)
    window = _forward(candles, day, sessions, 10)
    return {
        "close0": c0,
        "ret5": _ret(candles, day, sessions, 5),
        "ret10": _ret(candles, day, sessions, 10),
        "max_up10": max(candles[d][0] for d in window) / c0 - 1 if window and c0 else None,
        "max_dn10": min(candles[d][1] for d in window) / c0 - 1 if window and c0 else None,
        "spy_ret5": _ret(spy, day, sessions, 5),
        "spy_ret10": _ret(spy, day, sessions, 10),
    }


def label_all(ledger, fetch, sessions_between, today: date) -> tuple[int, int, int]:
    """Return (decisions pending, rows changed, failures). fetch(ticker, days) -> Candles."""
    pending = []
    failed = 0
    for row in ledger.decisions_to_label():
        try:
            pending.append((row["id"], row["symbol"], date.fromisoformat(json.loads(row["payload"])["date"])))
        except (TypeError, ValueError, KeyError):
            log.error("decision %s has no usable date", row["id"])
            failed += 1
    if not pending:
        return 0, 0, failed

    oldest = min(day for _, _, day in pending)
    days = (today - oldest).days + 15     # calendar days are more than enough sessions
    sessions = sessions_between(oldest - timedelta(days=7), today)
    candles: dict[str, Candles] = {}
    for ticker in {s for _, s, _ in pending} | {BENCHMARK}:
        try:
            candles[ticker] = fetch(ticker, days)
        except Exception as e:  # keep the other tickers' labels
            log.error("%s: %s", ticker, type(e).__name__)
            failed += 1

    changed = 0
    for decision_id, symbol, day in pending:
        if symbol in candles:
            values = label(candles[symbol], candles.get(BENCHMARK, {}), day, sessions)
            changed += ledger.save_outcome(decision_id, values)
    return len(pending), changed, failed


def _fetch(ticker: str, days: int) -> Candles:
    from core.data import get_stock_daily

    df = get_stock_daily(ticker, days)
    return {t.date(): (r.high, r.low, r.close) for t, r in df.iterrows()}


def _sessions(start: date, end: date) -> list[date]:
    from core.data import nyse_sessions

    return [t.date() for t in nyse_sessions(start, end).index]


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    pending, changed, failed = label_all(Ledger(), _fetch, _sessions, datetime.now(timezone.utc).date())
    print(f"pending {pending}, changed {changed}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
