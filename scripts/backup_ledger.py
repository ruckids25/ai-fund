"""Daily copy of the ledger and freqtrade databases, keeping the last 14 days.

Uses SQLite's backup API, which is safe while other processes are writing (a plain cp of a
WAL database is not). The copies stay on the VPS, so they guard against corruption or a bad
write, not against losing the server. Exits non-zero and alerts Telegram if a copy fails.

  .venv/bin/python scripts/backup_ledger.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import notify  # noqa: E402
from core.config import env, resolve  # noqa: E402

KEEP = 14


def backup(source: Path, dest_dir: Path, stamp: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{source.stem}_{stamp}.sqlite"
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
        ok = out.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        src.close()
        out.close()
    if ok != "ok":
        raise sqlite3.DatabaseError(f"integrity_check on {dest.name}: {ok}")
    return dest


def prune(dest_dir: Path, stem: str, keep: int = KEEP) -> None:
    for old in sorted(dest_dir.glob(f"{stem}_*.sqlite"))[:-keep]:
        old.unlink()


def main() -> int:
    dest_dir = resolve("data/backups")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    failed = []
    for source in (resolve(env("LEDGER_PATH", "data/ledger.sqlite")), resolve("data/freqtrade_dry.sqlite")):
        if not source.exists():
            continue          # not created yet on this machine
        try:
            print(backup(source, dest_dir, stamp))
            prune(dest_dir, source.stem)
        except sqlite3.Error as e:
            failed.append(f"{source.name}: {e}")
    if failed:
        notify.send("⚠️ ai-fund: backup ล้มเหลว — " + "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
