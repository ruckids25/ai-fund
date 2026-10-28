"""Offline tests for core.data (run in envs/data)."""
from datetime import datetime, timezone

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("ccxt")

from core import data  # noqa: E402

H = 3_600_000


def _frame(index):
    n = len(index)
    return pd.DataFrame({"open": [10.0] * n, "high": [11.0] * n, "low": [9.0] * n,
                         "close": [10.5] * n, "volume": [1.0] * n}, index=index)


def test_validate_clean_series():
    idx = pd.date_range("2026-10-01", periods=5, freq="h", tz="UTC")
    res = data.validate_candles(_frame(idx), idx)
    assert not any(res.values())


def test_validate_detects_problems():
    idx = pd.date_range("2026-10-01", periods=5, freq="h", tz="UTC")
    df = _frame(idx.delete(2).append(idx[[3]])).sort_index()  # gap + duplicate
    df.iloc[0, df.columns.get_loc("high")] = 1.0                # high < open
    res = data.validate_candles(df, idx)
    assert res["missing"] == [str(idx[2])]
    assert res["duplicates"] == [str(idx[3])]
    assert res["bad_ohlc"] == [str(idx[0])]


def test_stock_expected_index_skips_weekend_and_holiday():
    pytest.importorskip("pandas_market_calendars")
    # 2026-11-26 is Thanksgiving (NYSE closed)
    idx = pd.DatetimeIndex(["2026-11-20", "2026-11-27"]).tz_localize("UTC")
    exp = data.expected_index(_frame(idx), kind="stock")
    assert pd.Timestamp("2026-11-26", tz="UTC") not in exp
    assert pd.Timestamp("2026-11-21", tz="UTC") not in exp  # Saturday
    assert len(exp) == 5


class FakeOKX:
    """Serves hourly candles up to `last_open`, at most `page` per call."""

    def __init__(self, last_open, page=300):
        self.last_open, self.page, self.calls = last_open, page, 0

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        self.calls += 1
        out, t = [], since - since % H
        while t <= self.last_open and len(out) < min(limit, self.page):
            out.append([t, 1.0, 2.0, 0.5, 1.5, 3.0])
            t += H
        return out


def test_crypto_paginates_and_drops_open_candle(monkeypatch):
    now = datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc)
    forming = int(datetime(2026, 10, 28, 10, tzinfo=timezone.utc).timestamp() * 1000)
    fake = FakeOKX(last_open=forming, page=100)
    monkeypatch.setattr(data, "_okx", lambda: fake)

    df = data.get_crypto_ohlcv("BTC/USDT:USDT", "1h", limit=250, now=now)

    assert len(df) == 250
    assert fake.calls >= 3
    assert df.index[-1] == pd.Timestamp("2026-10-28 09:00", tz="UTC")  # 10:00 still forming
    assert str(df.index.tz) == "UTC"
    assert not any(data.validate_candles(df, data.expected_index(df, kind="crypto", timeframe="1h")).values())
