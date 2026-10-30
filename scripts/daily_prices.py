"""Send the latest closed price of every watchlist symbol to Telegram.

Run from envs/data:  envs/data/bin/python scripts/daily_prices.py [--dry]
--dry prints the message instead of sending. Exits non-zero if any symbol fails.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import data, notify  # noqa: E402
from core.config import watchlist  # noqa: E402

log = logging.getLogger("daily_prices")


def _line(sym: str, df) -> str:
    last, prev = df["close"].iloc[-1], df["close"].iloc[-2]
    chg = (last / prev - 1) * 100
    return f"{sym:<14} {last:>12,.2f}  {chg:+6.2f}%  ({df.index[-1]:%Y-%m-%d})"


def build_message() -> tuple[str, int]:
    wl, lines, errors = watchlist(), [], 0
    lines.append("📈 หุ้น (ราคาปิดล่าสุด)")
    for t in wl["stocks"]:
        try:
            lines.append(_line(t, data.get_stock_daily(t, 5)))
        except Exception as e:  # report and keep going
            errors += 1
            lines.append(f"{t:<14} ดึงข้อมูลไม่ได้ ({type(e).__name__})")
    lines.append("\n🪙 คริปโต (แท่งรายวันที่ปิดล่าสุด, OKX perp)")
    for s in wl["crypto"]:
        try:
            lines.append(_line(s, data.get_crypto_ohlcv(s, "1d", 5)))
        except Exception as e:
            errors += 1
            lines.append(f"{s:<14} ดึงข้อมูลไม่ได้ ({type(e).__name__})")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"ai-fund · ราคาปิด · {stamp}\n\n" + "\n".join(lines), errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    msg, errors = build_message()
    if args.dry:
        print(msg)
    elif not notify.send(msg):
        log.error("telegram send failed")
        return 2
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
