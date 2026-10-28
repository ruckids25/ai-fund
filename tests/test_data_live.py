"""Live data check for every symbol in the watchlist: pytest -m live (envs/data)."""
import pytest

pytest.importorskip("openbb")

from core import data  # noqa: E402
from core.config import watchlist  # noqa: E402

pytestmark = pytest.mark.live
WL = watchlist()


@pytest.mark.parametrize("ticker", WL["stocks"])
def test_stock_daily_complete(ticker):
    df = data.get_stock_daily(ticker, 250)
    assert len(df) == 250
    assert str(df.index.tz) == "UTC"
    problems = data.validate_candles(df, data.expected_index(df, kind="stock"))
    assert not any(problems.values()), problems


@pytest.mark.parametrize("symbol", WL["crypto"])
@pytest.mark.parametrize("timeframe,limit", [("1h", 1000), ("4h", 500), ("1d", 365)])
def test_crypto_ohlcv_complete(symbol, timeframe, limit):
    df = data.get_crypto_ohlcv(symbol, timeframe, limit)
    assert len(df) == limit
    problems = data.validate_candles(df, data.expected_index(df, kind="crypto", timeframe=timeframe))
    assert not any(problems.values()), problems
