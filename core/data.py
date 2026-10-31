"""Market data: US stock daily candles (OpenBB/yfinance) and crypto OHLCV (ccxt/OKX public).

Heavy deps (openbb, ccxt, pandas, pandas_market_calendars) are imported lazily so the
core package stays installable into every venv. Run this module from envs/data.

Conventions for every returned DataFrame:
- index `timestamp`: tz-aware UTC, the candle's *open* label (stocks: session date 00:00 UTC)
- columns: open, high, low, close, volume (float)
- only closed candles — the still-forming last candle is dropped (no look-ahead)
- sorted ascending, no duplicate timestamps
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]
OKX_PAGE = 300  # max candles per OKX request


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- stocks ----------

def nyse_sessions(start, end) -> "pd.DataFrame":
    """NYSE schedule (market_open / market_close in UTC) indexed by session date."""
    import pandas_market_calendars as mcal

    return mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)


def get_stock_daily(ticker: str, days: int, *, now: datetime | None = None) -> "pd.DataFrame":
    """Last `days` closed daily sessions for `ticker`."""
    import pandas as pd
    from openbb import obb

    now = now or _now()
    start = (now - timedelta(days=int(days * 1.6) + 10)).date()
    raw = obb.equity.price.historical(
        ticker, provider="yfinance", start_date=start.isoformat(), interval="1d"
    ).to_df()

    df = raw[COLUMNS].astype(float)
    df.index = pd.to_datetime(df.index).tz_localize("UTC")
    df.index.name = "timestamp"
    df = df[~df.index.duplicated(keep="last")].sort_index()

    # drop today's session if NYSE has not closed yet
    sched = nyse_sessions(df.index[-1].date(), df.index[-1].date())
    if not sched.empty and sched["market_close"].iloc[0] > now:
        df = df.iloc[:-1]
    # Yahoo can leave a finished session's close empty for hours: not a usable candle yet
    return df.dropna(subset=COLUMNS).tail(days)


# ---------- crypto ----------

@lru_cache(maxsize=1)
def _okx():
    import ccxt

    ex = ccxt.okx({"enableRateLimit": True})  # public endpoints only — no keys
    ex.load_markets()
    return ex


def timeframe_ms(timeframe: str) -> int:
    import ccxt

    return ccxt.Exchange.parse_timeframe(timeframe) * 1000


def get_crypto_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 500, *,
                     now: datetime | None = None) -> "pd.DataFrame":
    """Last `limit` closed candles from OKX, paginating past the per-request cap."""
    import pandas as pd

    ex = _okx()
    tf = timeframe_ms(timeframe)
    now_ms = int((now or _now()).timestamp() * 1000)
    since = now_ms - (limit + 2) * tf

    rows: list[list] = []
    while since < now_ms:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=OKX_PAGE)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + tf
        if nxt <= since:
            break
        since = nxt

    df = pd.DataFrame(rows, columns=["timestamp", *COLUMNS])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
    df = df[df.index + pd.Timedelta(milliseconds=tf) <= pd.Timestamp(now_ms, unit="ms", tz="UTC")]
    return df[COLUMNS].astype(float).tail(limit)


# ---------- validation ----------

def expected_index(df: "pd.DataFrame", *, kind: str, timeframe: str = "1d") -> "pd.DatetimeIndex":
    """Timestamps that should exist between df's first and last candle."""
    import pandas as pd

    first, last = df.index[0], df.index[-1]
    if kind == "stock":
        sessions = nyse_sessions(first.date(), last.date()).index
        return pd.DatetimeIndex(sessions).tz_localize("UTC")
    return pd.date_range(first, last, freq=pd.Timedelta(milliseconds=timeframe_ms(timeframe)))


def validate_candles(df: "pd.DataFrame", expected: "pd.DatetimeIndex") -> dict:
    """Return problems found; every list empty means the series is clean."""
    return {
        "missing": [str(t) for t in expected.difference(df.index)],
        "duplicates": [str(t) for t in df.index[df.index.duplicated()]],
        "unexpected": [str(t) for t in df.index.difference(expected)],
        "bad_ohlc": [str(t) for t in df.index[
            (df["high"] < df[["open", "close"]].max(axis=1))
            | (df["low"] > df[["open", "close"]].min(axis=1))
            | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        ]],
        "nan": [str(t) for t in df.index[df[COLUMNS].isna().any(axis=1)]],
    }
