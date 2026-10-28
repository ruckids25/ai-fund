"""SQLite ledger for every decision, order, API cost and daily PnL.

WAL mode so fund.py, freqtrade hooks and risk_monitor can write concurrently.
All timestamps are UTC ISO-8601.
"""
from __future__ import annotations

import json
import sqlite3
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

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_api_costs_ts ON api_costs(ts);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: str | Path | None = None):
        self.path = resolve(str(path or env("LEDGER_PATH", "data/ledger.sqlite")))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

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
        })

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
                         fx_usdthb: float | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO daily_pnl VALUES (?, ?, ?, ?, ?, ?)",
                (date, desk, realized_thb, unrealized_thb, equity_thb, fx_usdthb),
            )

    def open_orders(self, desk: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM orders WHERE status IN ('submitted', 'filled')"
        args: tuple = ()
        if desk:
            q += " AND desk = ?"
            args = (desk,)
        with self._conn() as c:
            return c.execute(q, args).fetchall()

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
