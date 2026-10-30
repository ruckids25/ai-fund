import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("backup_ledger", ROOT / "scripts" / "backup_ledger.py")
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)


def _db(path):
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    return c


def test_backup_includes_uncheckpointed_wal_data(tmp_path):
    src = tmp_path / "ledger.sqlite"
    writer = _db(src)        # still open, so the row may live only in the WAL
    dest = bl.backup(src, tmp_path / "b", "2026-10-30")
    writer.close()
    assert dest.name == "ledger_2026-10-30.sqlite"
    assert sqlite3.connect(dest).execute("SELECT x FROM t").fetchone()[0] == 1


def test_prune_keeps_newest_per_database(tmp_path):
    for i in range(1, 21):
        (tmp_path / f"ledger_2026-10-{i:02d}.sqlite").touch()
    (tmp_path / "freqtrade_dry_2026-10-01.sqlite").touch()
    bl.prune(tmp_path, "ledger")
    left = sorted(p.name for p in tmp_path.glob("ledger_*"))
    assert len(left) == 14 and left[0] == "ledger_2026-10-07.sqlite"
    assert (tmp_path / "freqtrade_dry_2026-10-01.sqlite").exists()
