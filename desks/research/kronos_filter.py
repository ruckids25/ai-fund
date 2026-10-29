"""Kronos cheap filter: sample N future price paths and summarise them.

Run in envs/kronos. Input candles come from core.data (via the parquet cache written by
scripts/fetch_candles.py), so this venv does not need openbb/ccxt.

KronosPredictor.predict() averages its samples internally, so to keep every path we
feed the same series N times through predict_batch() with sample_count=1.
"""
from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vendor" / "Kronos"))

from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

MODEL_ID = "NeoQuasar/Kronos-small"
TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
MAX_CONTEXT = 512


@dataclass
class Forecast:
    symbol: str
    asof: str            # timestamp of the last closed candle used
    horizon: int         # candles ahead
    last_close: float
    p_up: float          # share of paths whose close at `horizon` > last_close
    exp_ret: float       # mean simple return at horizon
    q10: float           # return quantiles at horizon
    q50: float
    q90: float
    n_paths: int
    seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


def future_index(last: pd.Timestamp, horizon: int, kind: str, freq: pd.Timedelta | None) -> pd.DatetimeIndex:
    """Timestamps for the forecast candles (only used for Kronos's time features)."""
    if kind == "stock":
        # business days; NYSE holidays only shift the weekday/day features slightly
        return pd.bdate_range(last + pd.Timedelta(days=1), periods=horizon, tz=last.tz)
    return pd.date_range(last + freq, periods=horizon, freq=freq)


class KronosFilter:
    def __init__(self, *, device: str = "cpu", lookback: int = 400, n_paths: int = 100,
                 temperature: float = 1.0, top_p: float = 0.9, seed: int | None = 0):
        if lookback > MAX_CONTEXT:
            raise ValueError(f"lookback {lookback} > Kronos-small context {MAX_CONTEXT}")
        self.lookback, self.n_paths = lookback, n_paths
        self.temperature, self.top_p, self.seed = temperature, top_p, seed
        tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
        model = Kronos.from_pretrained(MODEL_ID)
        tokenizer.eval()
        model.eval()
        self.predictor = KronosPredictor(model, tokenizer, device=device, max_context=MAX_CONTEXT)

    def sample_paths(self, df: pd.DataFrame, horizon: int, kind: str) -> np.ndarray:
        """Return close-price paths, shape (n_paths, horizon)."""
        hist = df[["open", "high", "low", "close", "volume"]].tail(self.lookback)
        if len(hist) < self.lookback:
            raise ValueError(f"need {self.lookback} candles, got {len(hist)}")
        x_ts = pd.Series(hist.index.tz_convert("UTC").tz_localize(None))
        step = None if kind == "stock" else hist.index[-1] - hist.index[-2]
        y_ts = pd.Series(future_index(hist.index[-1], horizon, kind, step).tz_convert("UTC").tz_localize(None))

        if self.seed is not None:
            torch.manual_seed(self.seed)
        h = hist.reset_index(drop=True)
        preds = self.predictor.predict_batch(
            [h] * self.n_paths, [x_ts] * self.n_paths, [y_ts] * self.n_paths,
            pred_len=horizon, T=self.temperature, top_k=0, top_p=self.top_p,
            sample_count=1, verbose=False,
        )
        return np.stack([p["close"].to_numpy() for p in preds])

    def forecast(self, symbol: str, df: pd.DataFrame, horizon: int, kind: str) -> Forecast:
        t0 = time.perf_counter()
        paths = self.sample_paths(df, horizon, kind)
        last = float(df["close"].iloc[-1])
        ret = paths[:, -1] / last - 1
        q10, q50, q90 = np.quantile(ret, [0.1, 0.5, 0.9])
        return Forecast(
            symbol=symbol, asof=str(df.index[-1]), horizon=horizon, last_close=last,
            p_up=float((ret > 0).mean()), exp_ret=float(ret.mean()),
            q10=float(q10), q50=float(q50), q90=float(q90),
            n_paths=self.n_paths, seconds=round(time.perf_counter() - t0, 2),
        )


def load_candles(symbol: str, timeframe: str) -> pd.DataFrame:
    """Read the parquet cache written by scripts/fetch_candles.py."""
    from scripts.fetch_candles import cache_path  # stdlib-only helper

    return pd.read_parquet(cache_path(symbol, timeframe))


if __name__ == "__main__":
    import argparse
    import json

    sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser(description="Kronos forecast for one cached symbol")
    ap.add_argument("symbol")
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--kind", choices=["stock", "crypto"], default="stock")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--paths", type=int, default=100)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    kf = KronosFilter(device=args.device, n_paths=args.paths)
    fc = kf.forecast(args.symbol, load_candles(args.symbol, args.timeframe), args.horizon, args.kind)
    print(json.dumps(fc.to_dict(), indent=2))
