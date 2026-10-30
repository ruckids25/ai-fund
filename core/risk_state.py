"""Snapshots shared between processes in different venvs, as JSON files (stdlib + core only).

freqtrade writes crypto_pnl.json; risk_monitor merges it with Alpaca and writes risk_state.json;
freqtrade reads that before every entry. A missing or stale risk state rejects the entry.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core.config import env, resolve
from core.risk_gate import AccountState, GateDecision, evaluate_order

MAX_AGE_S = 900        # three missed risk_monitor runs


def _path(name: str) -> Path:
    return resolve(env("RISK_STATE_DIR", "data")) / name


def write_snapshot(name: str, data: dict) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({**data, "ts": time.time()}))
    tmp.replace(path)        # readers in other processes never see a half-written file


def read_snapshot(name: str) -> dict | None:
    try:
        return json.loads(_path(name).read_text())
    except (OSError, ValueError):
        return None


def is_stale(snapshot: dict, now: float | None = None) -> bool:
    return (now if now is not None else time.time()) - snapshot.get("ts", 0) > MAX_AGE_S


def crypto_pnl() -> dict:
    """Latest crypto desk numbers in USD; zeros until freqtrade has written anything."""
    empty = {"realized_usd": 0.0, "unrealized_usd": 0.0, "daily_usd": 0.0, "open_positions": 0}
    return {**empty, **(read_snapshot("crypto_pnl.json") or {})}


def risk_level() -> str | None:
    snap = read_snapshot("risk_state.json")
    return snap.get("level") if snap else None


def approve_crypto_entry(side: str, entry: float, stop: float, leverage: float, amount: float,
                         cfg: dict | None = None) -> GateDecision:
    """The risk gate for one freqtrade entry, using the state risk_monitor last published."""
    snap = read_snapshot("risk_state.json")
    if snap is None or is_stale(snap):
        return GateDecision(False, reasons=["ไม่มีสถานะความเสี่ยงล่าสุด: risk_monitor อาจไม่ทำงาน"])
    state = AccountState(snap["total_pnl_thb"], snap["daily_pnl_thb"], snap["open_positions"],
                         snap.get("stocks_open_value_usd", 0.0))
    gate = evaluate_order("crypto", side, entry, stop, state, leverage=leverage, cfg=cfg)
    if gate.approved and amount > gate.qty * 1.02:   # 2%: freqtrade rounds to its own contract size
        return GateDecision(False, reasons=[f"จำนวน {amount} เกินที่อนุมัติ {gate.qty}"])
    return gate
