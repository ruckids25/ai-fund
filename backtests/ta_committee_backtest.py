"""Small walk-forward grid of the TradingAgents committee (envs/ta).

  run    : committee on every (date, ticker) cell, oldest date first; appends to
           decisions.csv and skips cells already there. Failed cells go to errors.csv.
  report : 5-day forward return per action vs buy-and-hold of the same cells, and how
           the buy signals' stop/target would have played out over 10 trading days.

TradingAgents serves data point-in-time for past dates (no live profile, statements
as filed, news limited to its window). What it cannot remove is the LLM's own
training data, so use dates as recent as possible.

  envs/ta/bin/python backtests/ta_committee_backtest.py run --out backtests/ta_20261030
  envs/ta/bin/python backtests/ta_committee_backtest.py report --out backtests/ta_20261030
"""
from __future__ import annotations

import argparse
import csv
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TICKERS = ["NVDA", "AAPL", "MSFT", "JPM", "XOM"]
DATES = ["2026-08-31", "2026-09-08", "2026-09-14", "2026-09-21",
         "2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]   # Mondays (09-07 Labor Day → Tue)
FIELDS = ["date", "ticker", "action", "rating", "entry", "stop", "target", "confidence",
          "seconds", "input_tokens", "output_tokens", "calls", "rationale"]
HORIZON, PATH_DAYS = 5, 10


def run(args) -> None:
    from desks.committee.ta_committee import run_committee

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path, err_path = out / "decisions.csv", out / "errors.csv"
    done = set()
    if path.exists():
        with open(path) as f:
            done = {(r["date"], r["ticker"]) for r in csv.DictReader(f)}

    cells = [(d, t) for d in args.dates for t in args.tickers if (d, t) not in done]
    print(f"{len(cells)} cells to run", flush=True)
    for i, (d, t) in enumerate(cells, 1):
        try:
            dec = run_committee(t, d, results_dir=out / "ta")
        except Exception as e:  # keep going; a free-tier 429 should not kill the grid
            with open(err_path, "a", newline="") as f:
                csv.writer(f).writerow([d, t, type(e).__name__, str(e)[:300]])
            print(f"[{i}/{len(cells)}] {d} {t} ERROR {type(e).__name__}: {str(e)[:120]}", flush=True)
            continue
        tok = dec.tokens.values()
        row = {"date": d, "ticker": t, "action": dec.action, "rating": dec.rating, "entry": dec.entry,
               "stop": dec.stop, "target": dec.target, "confidence": dec.confidence, "seconds": dec.seconds,
               "input_tokens": sum(u["input"] for u in tok), "output_tokens": sum(u["output"] for u in tok),
               "calls": sum(u["calls"] for u in tok), "rationale": dec.rationale}
        new = not path.exists()
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        print(f"[{i}/{len(cells)}] {d} {t} {dec.rating} ({dec.seconds:.0f}s)", flush=True)


def _prices(tickers, start, end):
    import pandas as pd
    import yfinance as yf

    px = {}
    for t in tickers:
        h = yf.Ticker(t).history(start=start, end=end, auto_adjust=True)
        h.index = pd.to_datetime(h.index.date)
        px[t] = h[["High", "Low", "Close"]]
    return px


def _path_outcome(h, entry, stop, target) -> str:
    """First of stop/target touched over PATH_DAYS sessions (stop first on the same day)."""
    for _, r in h.iterrows():
        if stop and r.Low <= stop:
            return "stop"
        if target and r.High >= target:
            return "target"
    return "open"


def report(args) -> str:
    import pandas as pd

    out = Path(args.out)
    df = pd.read_csv(out / "decisions.csv")
    df["date"] = pd.to_datetime(df["date"])
    px = _prices(df.ticker.unique(), df.date.min() - pd.Timedelta(days=7),
                 df.date.max() + pd.Timedelta(days=25))

    rets, outcomes, base_close = [], [], []
    for r in df.itertuples():
        h = px[r.ticker]
        before = h[h.index <= r.date]           # decision uses the last close on/before the date
        after = h[h.index > r.date]
        c0 = before.Close.iloc[-1]
        base_close.append(c0)
        rets.append(after.Close.iloc[HORIZON - 1] / c0 - 1 if len(after) >= HORIZON else float("nan"))
        outcomes.append(_path_outcome(after.head(PATH_DAYS), r.entry, r.stop, r.target)
                        if r.action == "buy" else "")
    df["close0"], df["ret5"], df["path"] = base_close, rets, outcomes

    lines = [f"# TradingAgents committee grid — {args.out}", "",
             f"cells: {len(df)} | tickers: {', '.join(df.ticker.unique())} | dates: "
             f"{df.date.min():%Y-%m-%d} → {df.date.max():%Y-%m-%d} | horizon {HORIZON} sessions", "",
             f"buy-and-hold (ทุก cell): mean {df.ret5.mean():+.2%}, ขึ้น {(df.ret5 > 0).mean():.0%}", "",
             "| action | n | mean ret5 | ขึ้น | edge vs ทุก cell |", "|---|---|---|---|---|"]
    for a, g in df.groupby("action"):
        lines.append(f"| {a} | {len(g)} | {g.ret5.mean():+.2%} | {(g.ret5 > 0).mean():.0%} | "
                     f"{g.ret5.mean() - df.ret5.mean():+.2%} |")
    lines += ["", "| rating | n | mean ret5 |", "|---|---|---|"]
    lines += [f"| {k} | {len(g)} | {g.ret5.mean():+.2%} |" for k, g in df.groupby("rating")]

    b = df[df.action == "buy"]
    if len(b):
        has_stop = b.stop.notna().mean()
        risk = ((b.close0 - b.stop) / b.close0).dropna()
        lines += ["", f"buy signals: {len(b)} | มี stop {has_stop:.0%} | ระยะ stop เฉลี่ย {risk.mean():.1%} "
                  f"| {PATH_DAYS} sessions: " + ", ".join(f"{k} {v}" for k, v in b.path.value_counts().items())]
    long_only = df.ret5.where(df.action == "buy", 0.0)
    lines += ["", f"long-only ตาม buy (cell อื่นถือเงินสด): mean ต่อ cell {long_only.mean():+.2%} "
              f"vs ถือทุก cell {df.ret5.mean():+.2%}",
              "", f"เวลาเฉลี่ย {df.seconds.mean():.0f}s/cell | token เฉลี่ย in {df.input_tokens.mean():,.0f} / "
              f"out {df.output_tokens.mean():,.0f} | calls {df.calls.mean():.0f}"]
    err = out / "errors.csv"
    if err.exists():
        lines.append(f"errors: {sum(1 for _ in open(err))} (ดู errors.csv)")
    text = "\n".join(lines)
    (out / "report.md").write_text(text)
    df.to_csv(out / "scored.csv", index=False)
    return text


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--tickers", nargs="+", default=TICKERS)
    r.add_argument("--dates", nargs="+", default=DATES)
    p = sub.add_parser("report")
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    run(a) if a.cmd == "run" else print(report(a))
