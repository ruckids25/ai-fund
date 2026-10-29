"""Fetch candles via core.data and cache them as parquet for other venvs (Kronos, backtests).

Run in envs/data:
  envs/data/bin/python scripts/fetch_candles.py --universe          # config/universe.yaml
  envs/data/bin/python scripts/fetch_candles.py NVDA BTC/USDT:USDT  # specific symbols
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "candles"


def cache_path(symbol: str, timeframe: str) -> Path:
    """Stdlib-only so other venvs can import it."""
    safe = symbol.replace("/", "-").replace(":", "_")
    return CACHE / f"{safe}__{timeframe}.parquet"


def is_crypto(symbol: str) -> bool:
    return "/" in symbol


def main() -> int:
    import argparse
    import sys

    sys.path.insert(0, str(ROOT))
    from core import data
    from core.config import load_yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--stock-days", type=int, default=800)
    ap.add_argument("--crypto", default="1d:800,4h:3200", help="timeframe:limit list")
    args = ap.parse_args()

    syms = list(args.symbols)
    if args.universe:
        u = load_yaml("universe.yaml")
        syms += u["stocks"] + u["crypto"]
    CACHE.mkdir(parents=True, exist_ok=True)

    failed = 0
    for s in syms:
        jobs = ([(tf, int(n)) for tf, n in (x.split(":") for x in args.crypto.split(","))]
                if is_crypto(s) else [("1d", args.stock_days)])
        for tf, n in jobs:
            try:
                df = data.get_crypto_ohlcv(s, tf, n) if is_crypto(s) else data.get_stock_daily(s, n)
                kind = "crypto" if is_crypto(s) else "stock"
                bad = {k: len(v) for k, v in data.validate_candles(
                    df, data.expected_index(df, kind=kind, timeframe=tf)).items() if v}
                df.to_parquet(cache_path(s, tf))
                print(f"{s:<16}{tf:>4} {len(df):>5} rows  {df.index[0].date()} → {df.index[-1].date()}  {bad or 'clean'}")
            except Exception as e:
                failed += 1
                print(f"{s:<16}{tf:>4} FAILED {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
