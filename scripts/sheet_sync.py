"""Copy the ledger into the journal Google Sheet, one way. Never reads the Sheet back.

  envs/data/bin/python scripts/sheet_sync.py

Every bot tab is cleared and rewritten from the ledger, opened read-only, so reruns give the same
Sheet. Values go in RAW so text from the LLM can never become a formula. The Notes tab and any
other tab are left alone. Exit code 1 on any failure; nothing is written if the rows can't be built.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import env, resolve, risk_config  # noqa: E402

log = logging.getLogger("sheet_sync")
TH = timezone(timedelta(hours=7))
MAX_TEXT = 300
BENCHMARK = "SPY"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

TRADES = ["order_id", "broker_id", "decision_id", "strategy_version", "symbol", "status",
          "submitted_ts_th", "filled_ts_th", "closed_ts_th", "qty", "filled_qty", "entry_limit",
          "fill_price", "stop", "target", "exit_price", "exit_reason", "risk_thb", "pnl_thb",
          "r_multiple", "hold_days", "rationale_short", "submitted_ts_utc"]
DECISIONS = ["decision_id", "run_id", "strategy_version", "date", "symbol", "rating", "action",
             "confidence", "entry", "stop", "target", "gate_result", "gate_reason", "api_cost_usd",
             "close0", "ret5", "ret10", "max_up10", "max_dn10", "spy_ret5", "spy_ret10", "rationale_short"]
DAILY = ["date", "equity_usd", "equity_thb", "daily_pnl_thb", "total_pnl_thb", "dist_to_soft_thb",
         "dist_to_hard_thb", "open_positions", "api_cost_usd_today", "api_cost_usd_mtd", "spy_ret_day", "halted"]
RUNS = ["run_id", "ts_th", "ts_utc", "script", "git_commit", "strategy_version", "quick_model", "deep_model",
        "committee_yaml_sha", "risk_yaml_sha", "tickers", "n_decisions", "api_cost_usd", "errors"]
SUMMARY = ["strategy_version", "trades", "win_rate", "avg_r", "profit_factor", "max_dd_thb",
           "cum_pnl_thb", "spy_ret_same_period", "api_cost_usd_month"]


def to_th(ts: str | None) -> str | None:
    return datetime.fromisoformat(ts).astimezone(TH).strftime("%Y-%m-%d %H:%M:%S") if ts else None


def short(text: str | None) -> str | None:
    return text[:MAX_TEXT] if text else text


def _payload(row: dict) -> dict:
    try:
        return json.loads(row["payload"]) or {}
    except (TypeError, ValueError):
        return {}


def _table(columns: list[str], rows: list[dict]) -> list[list]:
    # v != v is NaN, which the Sheets API refuses and JSON payloads can carry
    return [columns] + [["" if r.get(c) is None or r[c] != r[c] else r[c] for c in columns] for r in rows]


def _committee_of(decisions: list[dict]) -> dict[int, dict]:
    """Gate decision id -> the committee decision just before it for the same symbol."""
    last, out = {}, {}
    for d in sorted(decisions, key=lambda d: d["id"]):
        if d["stage"] == "committee":
            last[d["symbol"]] = d
        elif d["stage"] == "risk_gate" and d["symbol"] in last:
            out[d["id"]] = last[d["symbol"]]
    return out


def trade_rows(orders: list[dict], decisions: list[dict], versions: dict[str, str]) -> list[list]:
    by_id = {d["id"]: d for d in decisions}
    committee = _committee_of(decisions)
    rows = []
    for o in sorted(orders, key=lambda o: o["id"]):
        gate = by_id.get(o["decision_id"]) or {}
        rows.append({
            **o, "order_id": o["id"], "strategy_version": versions.get(gate.get("run_id")),
            "submitted_ts_th": to_th(o["ts"]), "filled_ts_th": to_th(o.get("filled_ts")),
            "closed_ts_th": to_th(o.get("closed_ts")), "entry_limit": o["entry"],
            "rationale_short": short(committee.get(o["decision_id"], {}).get("reason")),
            "submitted_ts_utc": o["ts"]})
    return _table(TRADES, rows)


def decision_rows(decisions: list[dict], outcomes: dict[int, dict], versions: dict[str, str]) -> list[list]:
    gates = {}
    committee = _committee_of(decisions)
    for d in decisions:
        if d["id"] in committee:
            gates[committee[d["id"]]["id"]] = d
    rows = []
    for d in sorted(decisions, key=lambda d: d["id"]):
        if d["stage"] != "committee":
            continue
        p, gate = _payload(d), gates.get(d["id"], {})
        rows.append({
            **outcomes.get(d["id"], {}), **d, "decision_id": d["id"],
            "strategy_version": versions.get(d.get("run_id")), "date": p.get("date"),
            "rating": p.get("rating"), "gate_result": gate.get("action"), "gate_reason": gate.get("reason"),
            "api_cost_usd": p.get("cost_usd"), "rationale_short": short(d.get("reason"))})
    return _table(DECISIONS, rows)


def daily_rows(pnl: list[dict], costs: list[dict], spy: dict[date, float], cfg: dict) -> list[list]:
    """One row per UTC date. Total PnL adds the desks; open_positions and halted come from the stocks row."""
    days: dict[str, list[dict]] = {}
    for p in pnl:
        days.setdefault(p["date"], []).append(p)
    budget = cfg["loss_budget"]
    closes = sorted(spy)
    rows, prev = [], 0.0
    for day in sorted(days):
        total = sum(p["realized_thb"] + p["unrealized_thb"] for p in days[day])
        stocks = next((p for p in days[day] if p["desk"] == "stocks"), {})
        equity, fx = stocks.get("equity_thb"), stocks.get("fx_usdthb")
        when = date.fromisoformat(day)
        before = [d for d in closes if d < when]
        halted = stocks.get("halted")
        rows.append({
            "date": day, "equity_thb": equity, "equity_usd": equity / fx if equity and fx else None,
            "daily_pnl_thb": total - prev, "total_pnl_thb": total,
            "dist_to_soft_thb": total - budget["soft_stop"], "dist_to_hard_thb": total - budget["hard_stop"],
            "open_positions": stocks.get("open_positions"),
            "api_cost_usd_today": sum(c["cost_usd"] for c in costs if c["ts"][:10] == day),
            "api_cost_usd_mtd": sum(c["cost_usd"] for c in costs if day[:7] == c["ts"][:7] and c["ts"][:10] <= day),
            "spy_ret_day": spy[when] / spy[before[-1]] - 1 if when in spy and before else None,
            "halted": None if halted is None else bool(halted)})
        prev = total
    return _table(DAILY, rows)


def run_rows(runs: list[dict]) -> list[list]:
    rows = [{**r, "ts_th": to_th(r["ts"]), "ts_utc": r["ts"]} for r in sorted(runs, key=lambda r: r["ts"])]
    return _table(RUNS, rows)


def _stats(name: str, trades: list[dict], cost: float, spy: dict[date, float]) -> dict:
    closed = sorted((t for t in trades if t["status"] == "closed" and t.get("pnl_thb") is not None),
                    key=lambda t: t["closed_ts"])
    pnl = [t["pnl_thb"] for t in closed]
    wins, losses = sum(p for p in pnl if p > 0), -sum(p for p in pnl if p < 0)
    r = [t["r_multiple"] for t in closed if t.get("r_multiple") is not None]
    peak = cum = drawdown = 0.0
    for p in pnl:
        cum += p
        peak = max(peak, cum)
        drawdown = max(drawdown, peak - cum)
    spy_ret = None
    if closed:
        start = date.fromisoformat(min(t["filled_ts"] for t in closed)[:10])
        window = [d for d in sorted(spy) if d >= start]
        if window:
            spy_ret = spy[window[-1]] / spy[window[0]] - 1
    return {"strategy_version": name, "trades": len(closed),
            "win_rate": sum(p > 0 for p in pnl) / len(pnl) if pnl else None,
            "avg_r": sum(r) / len(r) if r else None,
            "profit_factor": wins / losses if losses else None,
            "max_dd_thb": drawdown, "cum_pnl_thb": cum, "spy_ret_same_period": spy_ret,
            "api_cost_usd_month": cost}


def summary_rows(orders: list[dict], decisions: list[dict], runs: list[dict], spy: dict[date, float],
                 today: date) -> list[list]:
    """One row per strategy_version plus ALL. Closed trades only. API cost from runs of this month."""
    versions = {r["run_id"]: r.get("strategy_version") or "unknown" for r in runs}
    by_id = {d["id"]: d for d in decisions}
    of = {}
    for o in orders:
        run_id = by_id.get(o["decision_id"], {}).get("run_id")
        of[o["id"]] = versions.get(run_id, "unknown")
    month = today.isoformat()[:7]
    def cost(selected):
        return sum(r.get("api_cost_usd") or 0 for r in selected if r["ts"][:7] == month)
    rows = [_stats(v, [o for o in orders if of[o["id"]] == v],
                   cost([r for r in runs if versions[r["run_id"]] == v]), spy)
            for v in sorted(set(versions.values()) | set(of.values()))]
    rows.append(_stats("ALL", orders, cost(runs), spy))
    return _table(SUMMARY, rows)


def read_ledger(path: Path) -> dict[str, list[dict]]:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        def rows(q):
            return [dict(r) for r in c.execute(q)]
        return {"orders": rows("SELECT * FROM orders WHERE desk = 'stocks'"),
                "decisions": rows("SELECT * FROM decisions WHERE desk = 'stocks'"),
                "outcomes": rows("SELECT * FROM decision_outcomes"),
                "runs": rows("SELECT * FROM runs"),
                "pnl": rows("SELECT * FROM daily_pnl"),
                "costs": rows("SELECT ts, cost_usd FROM api_costs")}
    finally:
        c.close()


def build_tabs(data: dict[str, list[dict]], spy: dict[date, float], cfg: dict, today: date) -> dict[str, list[list]]:
    versions = {r["run_id"]: r.get("strategy_version") for r in data["runs"]}
    outcomes = {o["decision_id"]: {k: v for k, v in o.items() if k != "decision_id"} for o in data["outcomes"]}
    return {
        "Trades": trade_rows(data["orders"], data["decisions"], versions),
        "Decisions": decision_rows(data["decisions"], outcomes, versions),
        "Daily": daily_rows(data["pnl"], data["costs"], spy, cfg),
        "Runs": run_rows(data["runs"]),
        "Summary": summary_rows(data["orders"], data["decisions"], data["runs"], spy, today),
    }


def write_tabs(spreadsheet, tabs: dict[str, list[list]]) -> None:
    existing = {w.title: w for w in spreadsheet.worksheets()}
    for title, rows in tabs.items():
        sheet = existing.get(title) or spreadsheet.add_worksheet(title, rows=len(rows) + 1, cols=len(rows[0]))
        if sheet.row_count < len(rows) or sheet.col_count < len(rows[0]):
            sheet.resize(rows=max(sheet.row_count, len(rows)), cols=max(sheet.col_count, len(rows[0])))
    spreadsheet.values_batch_clear(body={"ranges": list(tabs)})
    spreadsheet.values_batch_update(body={
        "valueInputOption": "RAW",
        "data": [{"range": f"{title}!A1", "values": rows} for title, rows in tabs.items()]})


def _spy_closes(days: int) -> dict[date, float]:
    from core.data import get_stock_daily  # envs/data only

    return {t.date(): float(r.close) for t, r in get_stock_daily(BENCHMARK, days).iterrows()}


def _spreadsheet():
    import gspread  # envs/data only

    client = gspread.service_account(filename=env("GOOGLE_SA_JSON_PATH"), scopes=SCOPES)
    return client.open_by_key(env("JOURNAL_SHEET_ID"))


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        path = resolve(env("LEDGER_PATH", "data/ledger.sqlite"))
        data = read_ledger(path)
        today = datetime.now(timezone.utc).date()
        oldest = min((p["date"] for p in data["pnl"]), default=today.isoformat())
        spy = _spy_closes((today - date.fromisoformat(oldest)).days + 15)
        tabs = build_tabs(data, spy, risk_config(), today)
        write_tabs(_spreadsheet(), tabs)
    except Exception as e:  # type and status only: messages from auth libraries are not for logs
        log.error("sync failed: %s %s", type(e).__name__, getattr(e, "code", ""))
        return 1
    print("synced " + ", ".join(f"{t} {len(r) - 1}" for t, r in tabs.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
