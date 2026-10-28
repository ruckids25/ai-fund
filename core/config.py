"""Load .env and config/*.yaml. Stdlib + pyyaml only."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    """Read KEY=VALUE lines into os.environ without overriding values already set."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(key: str, default: str | None = None) -> str | None:
    load_env()
    value = os.environ.get(key, default)
    return value if value != "" else default


def load_yaml(name: str) -> dict:
    with open(ROOT / "config" / name) as f:
        return yaml.safe_load(f)


def risk_config() -> dict:
    return load_yaml("risk.yaml")


def watchlist() -> dict:
    return load_yaml("watchlist.yaml")


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
