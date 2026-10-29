"""Walk-forward test of the Kronos filter on cached candles (envs/kronos).

  run    : for every origin candle after --start, forecast with history up to that candle only,
           then record the realised return `horizon` candles later. Appends to results.csv and
           resumes where it stopped.
  report : hit rate of p_up thresholds vs the base rate, calibration, IC.

Only data after the Kronos paper (2025-08) is used as out-of-sample, because the model's
pre-training window may cover anything before it.

  envs/kronos/bin/python backtests/kronos_filter_backtest.py run --out backtests/kronos_20261029
  envs/kronos/bin/python backtests/kronos_filter_backtest.py report --out backtests/kronos_20261029
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fetch_candles import cache_path, is_crypto  # noqa: E402

FIELDS = ["symbol", "timeframe", "kind", "asof", "horizon", "last_close", "p_up", "exp_ret",
          "q10", "q50", "q90", "actual_ret", "seconds"]
# (timeframe, horizon, step) per asset class
JOBS = {"stock": [("1d", 5, 5)], "crypto": [("1d", 5, 5), ("4h", 6, 12)]}


def load_universe() -> list[str]:
    import yaml

    u = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    return u["stocks"] + u["crypto"]


def run(args) -> None:
    from desks.research.kronos_filter import KronosFilter

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "results.csv"
    done = set()
    if path.exists():
        prev = pd.read_csv(path)
        done = set(zip(prev.symbol, prev.timeframe, prev["asof"]))

    kf = KronosFilter(device=args.device, lookback=args.lookback, n_paths=args.paths)
    start = pd.Timestamp(args.start, tz="UTC")
    symbols = args.symbols or load_universe()

    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not done:
            w.writeheader()
        for sym in symbols:
            kind = "crypto" if is_crypto(sym) else "stock"
            for tf, horizon, step in JOBS[kind]:
                df = pd.read_parquet(cache_path(sym, tf))
                origins = [i for i in range(args.lookback - 1, len(df) - horizon)
                           if df.index[i] >= start][::step]
                todo = [i for i in origins if (sym, tf, str(df.index[i])) not in done]
                print(f"{sym} {tf}: {len(origins)} origins, {len(todo)} to run", flush=True)
                for i in todo:
                    hist = df.iloc[: i + 1]  # nothing after the origin candle
                    fc = kf.forecast(sym, hist, horizon, kind)
                    actual = float(df["close"].iloc[i + horizon] / df["close"].iloc[i] - 1)
                    row = {k: getattr(fc, k) for k in FIELDS if hasattr(fc, k)}
                    row.update(symbol=sym, timeframe=tf, kind=kind, actual_ret=actual)
                    w.writerow(row)
                    f.flush()


def _z_pvalue(hits: int, n: int, p0: float) -> float:
    """One-sided normal-approx p-value that the hit rate exceeds p0."""
    if n == 0 or p0 in (0, 1):
        return float("nan")
    z = (hits / n - p0) / math.sqrt(p0 * (1 - p0) / n)
    return 0.5 * math.erfc(z / math.sqrt(2))


def report(args) -> str:
    df = pd.read_csv(Path(args.out) / "results.csv")
    df["up"] = df.actual_ret > 0
    lines = [f"# Kronos filter walk-forward — {args.out}", "",
             f"rows: {len(df)} | ช่วง asof: {df["asof"].min()[:10]} → {df["asof"].max()[:10]}", ""]

    for (kind, tf), g in df.groupby(["kind", "timeframe"]):
        base = g.up.mean()
        months = max((pd.to_datetime(g["asof"].max()) - pd.to_datetime(g["asof"].min())).days / 30.4, 1)
        ic = g.exp_ret.rank().corr(g.actual_ret.rank())  # Spearman without scipy
        lines += [f"## {kind} {tf} (horizon {g.horizon.iloc[0]}) — n={len(g)}, symbols={g.symbol.nunique()}",
                  f"base rate (ขึ้น): {base:.1%} | mean ret ทั้งหมด: {g.actual_ret.mean():+.2%} | Spearman IC(exp_ret, actual): {ic:+.3f}",
                  "",
                  "| เกณฑ์ | n สัญญาณ | สัญญาณ/เดือน | hit rate | base | edge | p-value | mean ret สัญญาณ |",
                  "|---|---|---|---|---|---|---|---|"]
        for th in (0.55, 0.60, 0.65, 0.70, 0.75):
            s = g[g.p_up >= th]
            hits = int(s.up.sum())
            hr = hits / len(s) if len(s) else float("nan")
            lines.append(f"| long p_up≥{th:.2f} | {len(s)} | {len(s)/months:.1f} | {hr:.1%} | {base:.1%} | "
                         f"{hr-base:+.1%} | {_z_pvalue(hits, len(s), base):.3f} | {s.actual_ret.mean():+.2%} |")
        for th in (0.30, 0.25):
            s = g[g.p_up <= th]
            hits = int((~s.up).sum())
            hr = hits / len(s) if len(s) else float("nan")
            lines.append(f"| short p_up≤{th:.2f} | {len(s)} | {len(s)/months:.1f} | {hr:.1%} | {1-base:.1%} | "
                         f"{hr-(1-base):+.1%} | {_z_pvalue(hits, len(s), 1-base):.3f} | {-s.actual_ret.mean():+.2%} |")
        bins = pd.cut(g.p_up, [0, .3, .4, .5, .6, .7, 1.0001], right=False)
        cal = g.groupby(bins, observed=True).agg(n=("up", "size"), realised_up=("up", "mean"))
        lines += ["", "calibration (p_up bucket → สัดส่วนที่ขึ้นจริง):", "",
                  "| p_up | n | ขึ้นจริง |", "|---|---|---|"]
        lines += [f"| {iv} | {int(r.n)} | {r.realised_up:.1%} |" for iv, r in cal.iterrows()]
        lines.append("")

    lines.append(f"เวลาเฉลี่ยต่อ forecast: {df.seconds.mean():.1f}s")
    text = "\n".join(lines)
    (Path(args.out) / "report.md").write_text(text)
    return text


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--start", default="2025-09-01")
    r.add_argument("--lookback", type=int, default=256)
    r.add_argument("--paths", type=int, default=100)
    r.add_argument("--device", default="cpu")
    r.add_argument("symbols", nargs="*")
    p = sub.add_parser("report")
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    run(a) if a.cmd == "run" else print(report(a))
