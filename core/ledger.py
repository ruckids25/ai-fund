"""SQLite ledger for every decision, order, API cost and daily PnL.

WAL mode so fund.py, freqtrade hooks and risk_monitor can write concurrently.
All timestamps are UTC ISO-8601.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.config import env, resolve

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    desk        TEXT NOT NULL CHECK (desk IN ('stocks', 'crypto')),
    symbol      TEXT NOT NULL,
    stage       TEXT NOT NULL,          -- kronos / committee / risk_gate
    action      TEXT NOT NULL,          -- buy / sell / hold / reject / pass
    confidence  REAL,
    entry       REAL,
    stop        REAL,
    target      REAL,
    reason      TEXT,
    payload     TEXT                    -- JSON (raw model output etc.)
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    decision_id  INTEGER REFERENCES decisions(id),
    desk         TEXT NOT NULL CHECK (desk IN ('stocks', 'crypto')),
    venue        TEXT NOT NULL,         -- alpaca_paper / okx_dry / ...
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    qty          REAL NOT NULL,
    entry        REAL,
    stop         REAL NOT NULL,         -- RISK_RULES 3: every order has a stop
    target       REAL,
    leverage     REAL NOT NULL DEFAULT 1,
    risk_thb     REAL NOT NULL,
    status       TEXT NOT NULL,         -- submitted / filled / closed / cancelled / rejected
    broker_id    TEXT,
    fill_price   REAL,
    exit_price   REAL,
    pnl_thb      REAL,
    closed_ts    TEXT
);

CREATE TABLE IF NOT EXISTS api_costs (
    id             INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    component      TEXT NOT NULL,       -- ta_committee / ...
    model          TEXT NOT NULL,
    symbol         TEXT,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date            TEXT NOT NULL,      -- YYYY-MM-DD (UTC)
    desk            TEXT NOT NULL CHECK (desk IN ('stocks', 'crypto', 'total')),
    realized_thb    REAL NOT NULL,
    unrealized_thb  REAL NOT NULL,
    equity_thb      REAL,
    fx_usdthb       REAL,
    PRIMARY KEY (date, desk)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    ts                  TEXT NOT NULL,
    script              TEXT NOT NULL,  -- fund / fund_dry / backtest
    git_commit          TEXT,
    strategy_version    TEXT,
    quick_model         TEXT,
    deep_model          TEXT,
    committee_yaml_sha  TEXT,
    risk_yaml_sha       TEXT,
    tickers             TEXT,           -- JSON
    n_decisions         INTEGER,
    api_cost_usd        REAL,
    errors              TEXT            -- JSON
);

CREATE TABLE IF NOT EXISTS decision_outcomes (
    decision_id  INTEGER PRIMARY KEY REFERENCES decisions(id),
    close0       REAL,
    ret5         REAL,
    ret10        REAL,
    max_up10     REAL,
    max_dn10     REAL,
    spy_ret5     REAL,
    spy_ret10    REAL,
    labeled_ts   TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_api_costs_ts ON api_costs(ts);
"""

# Additive only: columns added after the first deploy, applied to existing databases on open.
ADDED_COLUMNS = {
    "decisions": {"run_id": "TEXT"},
    "daily_pnl": {"open_positions": "INTEGER", "halted": "INTEGER"},
    "orders": {
        "filled_qty": "REAL", "filled_ts": "TEXT", "exit_reason": "TEXT",   # stop / target / manual / close_all
        "r_multiple": "REAL", "hold_days": "REAL", "fees_usd": "REAL",
        "fx_usdthb": "REAL",                                                # fx used for pnl_thb
        "last_sync_ts": "TEXT",
    },
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: str | Path | None = None):
        self.path = resolve(str(path or env("LEDGER_PATH", "data/ledger.sqlite")))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id: str | None = None     # set by start_run; tags every later log_decision
        with self._conn() as c:
            c.executescript(SCHEMA)
            self._migrate(c)

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        for table, columns in ADDED_COLUMNS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name in have:
                    continue
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e):   # another process just added it
                        raise

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _insert(self, table: str, row: dict[str, Any]) -> int:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._conn() as c:
            cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
            return cur.lastrowid

    def log_decision(self, desk: str, symbol: str, stage: str, action: str, *,
                     confidence: float | None = None, entry: float | None = None,
                     stop: float | None = None, target: float | None = None,
                     reason: str | None = None, payload: dict | None = None) -> int:
        return self._insert("decisions", {
            "ts": utcnow(), "desk": desk, "symbol": symbol, "stage": stage, "action": action,
            "confidence": confidence, "entry": entry, "stop": stop, "target": target,
            "reason": reason, "payload": json.dumps(payload) if payload is not None else None,
            "run_id": self.run_id,
        })

    def start_run(self, script: str, **metadata: Any) -> str:
        """Open a run; decisions logged through this Ledger object carry its run_id from now on."""
        run_id = uuid.uuid4().hex[:12]
        self._insert("runs", {"run_id": run_id, "ts": utcnow(), "script": script, **metadata})
        self.run_id = run_id
        return run_id

    def finish_run(self, run_id: str, api_cost_usd: float, errors: list[str]) -> None:
        with self._conn() as c:
            n = c.execute("SELECT COUNT(*) FROM decisions WHERE run_id = ?", (run_id,)).fetchone()[0]
            c.execute("UPDATE runs SET n_decisions = ?, api_cost_usd = ?, errors = ? WHERE run_id = ?",
                      (n, api_cost_usd, json.dumps(errors, ensure_ascii=False), run_id))
        self.run_id = None

    def decisions_to_label(self) -> list[sqlite3.Row]:
        """Stock committee decisions of every action whose outcome is still incomplete."""
        with self._conn() as c:
            return c.execute(
                "SELECT d.id, d.symbol, d.payload FROM decisions d "
                "LEFT JOIN decision_outcomes o ON o.decision_id = d.id "
                "WHERE d.stage = 'committee' AND d.desk = 'stocks' AND ("
                "o.decision_id IS NULL OR o.ret5 IS NULL OR o.ret10 IS NULL "
                "OR o.spy_ret5 IS NULL OR o.spy_ret10 IS NULL)").fetchall()

    def save_outcome(self, decision_id: int, values: dict[str, float]) -> bool:
        """Fill columns that are still empty and never change a stored value. True if anything was added."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM decision_outcomes WHERE decision_id = ?", (decision_id,)).fetchone()
            new = {k: v for k, v in values.items() if v is not None and (row is None or row[k] is None)}
            if not new:
                return False
            if row is None:
                c.execute("INSERT INTO decision_outcomes (decision_id) VALUES (?)", (decision_id,))
            sets = ", ".join(f"{k} = ?" for k in new)
            c.execute(f"UPDATE decision_outcomes SET {sets}, labeled_ts = ? WHERE decision_id = ?",
                      (*new.values(), utcnow(), decision_id))
            return True

    def log_order(self, desk: str, venue: str, symbol: str, side: str, qty: float, *,
                  stop: float, risk_thb: float, status: str = "submitted",
                  entry: float | None = None, target: float | None = None,
                  leverage: float = 1, decision_id: int | None = None,
                  broker_id: str | None = None) -> int:
        return self._insert("orders", {
            "ts": utcnow(), "decision_id": decision_id, "desk": desk, "venue": venue,
            "symbol": symbol, "side": side, "qty": qty, "entry": entry, "stop": stop,
            "target": target, "leverage": leverage, "risk_thb": risk_thb,
            "status": status, "broker_id": broker_id,
        })

    def update_order(self, order_id: int, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE orders SET {sets} WHERE id = ?", (*fields.values(), order_id))

    def log_api_cost(self, component: str, model: str, cost_usd: float, *,
                     symbol: str | None = None, input_tokens: int = 0,
                     output_tokens: int = 0) -> int:
        return self._insert("api_costs", {
            "ts": utcnow(), "component": component, "model": model, "symbol": symbol,
            "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost_usd,
        })

    def record_daily_pnl(self, date: str, desk: str, realized_thb: float,
                         unrealized_thb: float, *, equity_thb: float | None = None,
                         fx_usdthb: float | None = None, open_positions: int | None = None,
                         halted: bool | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO daily_pnl (date, desk, realized_thb, unrealized_thb, "
                "equity_thb, fx_usdthb, open_positions, halted) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (date, desk, realized_thb, unrealized_thb, equity_thb, fx_usdthb, open_positions,
                 None if halted is None else int(halted)),
            )

    def open_orders(self, desk: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM orders WHERE status IN ('submitted', 'filled')"
        args: tuple = ()
        if desk:
            q += " AND desk = ?"
            args = (desk,)
        with self._conn() as c:
            return c.execute(q, args).fetchall()

    def orders_to_reconcile(self, venue: str) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT * FROM orders WHERE venue = ? AND status IN ('submitted', 'filled')",
                             (venue,)).fetchall()

    def realized_pnl_thb(self, since: str | None = None) -> float:
        q = "SELECT COALESCE(SUM(pnl_thb), 0) FROM orders WHERE status = 'closed'"
        args: tuple = ()
        if since:
            q += " AND closed_ts >= ?"
            args = (since,)
        with self._conn() as c:
            return c.execute(q, args).fetchone()[0]

    def api_cost_usd(self, since: str) -> float:
        with self._conn() as c:
            return c.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE ts >= ?", (since,)
            ).fetchone()[0]


if __name__ == "__main__":
    led = Ledger()
    print(f"ledger ready: {led.path}")
