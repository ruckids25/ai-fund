"""TradingAgents committee: one ticker + date → standard decision JSON.

Run in envs/ta. The committee only recommends; it never places orders — every
decision goes through core/risk_gate.py later.

Output: {ticker, action, entry, stop, target, confidence, rationale, cost_usd}
plus rating / tokens / seconds for the backtest. Token usage per model is logged
to the ledger's api_costs (component "ta_committee").

  envs/ta/bin/python -m desks.committee.ta_committee NVDA --date 2026-10-29 [--no-ledger]
"""
from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.config import load_env, load_yaml  # noqa: E402

COMPONENT = "ta_committee"


@dataclass
class CommitteeDecision:
    ticker: str
    date: str
    action: str                  # buy / hold / sell / review
    entry: float | None
    stop: float | None
    target: float | None
    confidence: float | None
    rationale: str
    cost_usd: float
    rating: str                  # TradingAgents 5-tier rating or REVIEW
    tokens: dict = field(default_factory=dict)   # model → {input, output, calls}
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class TokenCounter(BaseCallbackHandler):
    """Sum input/output tokens per model across every LLM call in a run."""

    def __init__(self):
        self.usage: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0, "calls": 0})

    def on_llm_end(self, response, **kwargs) -> None:
        for gens in response.generations:
            for g in gens:
                msg = getattr(g, "message", None)
                meta = getattr(msg, "usage_metadata", None) or {}
                model = (getattr(msg, "response_metadata", None) or {}).get("model_name") or "unknown"
                u = self.usage[model]
                u["input"] += meta.get("input_tokens", 0)
                u["output"] += meta.get("output_tokens", 0)
                u["calls"] += 1


def _num(label: str, text: str) -> float | None:
    """Read '**Label**: 123.4' from TradingAgents' rendered markdown."""
    m = re.search(rf"\*\*{label}\*\*:\s*\$?([0-9][0-9,]*\.?[0-9]*)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def _field(label: str, text: str) -> str:
    m = re.search(rf"\*\*{label}\*\*:\s*(.+?)(?:\n\s*\n|\Z)", text or "", re.S)
    return m.group(1).strip() if m else ""


def parse_state(final_state: dict, rating: str, rating_map: dict) -> dict:
    """Map TradingAgents' final state onto our decision fields."""
    trader = final_state.get("trader_investment_plan", "")
    pm = final_state.get("final_trade_decision", "")
    mapped = rating_map.get(rating, {"action": "review", "confidence": None})
    return {
        "action": mapped["action"],
        "confidence": mapped["confidence"],
        "entry": _num("Entry Price", trader),
        "stop": _num("Stop Loss", trader),
        "target": _num("Price Target", pm),
        "rationale": _field("Executive Summary", pm) or pm[:1000],
    }


def cost_usd(usage: dict, prices: dict) -> float:
    total = 0.0
    for model, u in usage.items():
        p = prices.get(model, {"input": 0.0, "output": 0.0})
        total += u["input"] / 1e6 * p["input"] + u["output"] / 1e6 * p["output"]
    return round(total, 6)


def build_config(cfg: dict, results_dir: Path) -> dict:
    from tradingagents.default_config import build_default_config

    c = build_default_config()
    llm = cfg["llm"]
    c.update(
        llm_provider=llm["provider"], quick_think_llm=llm["quick_model"], deep_think_llm=llm["deep_model"],
        llm_max_retries=llm["max_retries"], temperature=llm["temperature"],
        max_debate_rounds=cfg["debate"]["max_debate_rounds"],
        max_risk_discuss_rounds=cfg["debate"]["max_risk_discuss_rounds"],
        # keep TradingAgents' logs/cache/memory inside the repo's ignored data dir, not ~/.tradingagents
        results_dir=str(results_dir / "logs"), data_cache_dir=str(results_dir / "cache"),
        memory_log_path=str(results_dir / "memory" / "trading_memory.md"),
    )
    return c


def run_committee(ticker: str, date: str, *, asset_type: str = "stock", ledger=None,
                  results_dir: Path | None = None) -> CommitteeDecision:
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    load_env()
    cfg = load_yaml("committee.yaml")
    counter = TokenCounter()
    graph = TradingAgentsGraph(debug=False, config=build_config(cfg, results_dir or ROOT / "data" / "ta"),
                               callbacks=[counter])
    t0 = time.perf_counter()
    final_state, rating = graph.propagate(ticker, date, asset_type=asset_type)
    seconds = round(time.perf_counter() - t0, 1)

    usage = dict(counter.usage)
    dec = CommitteeDecision(
        ticker=ticker, date=date, rating=rating, cost_usd=cost_usd(usage, cfg["prices"]),
        tokens=usage, seconds=seconds, **parse_state(final_state, rating, cfg["rating_map"]),
    )
    if ledger is not None:
        for model, u in usage.items():
            ledger.log_api_cost(COMPONENT, model, symbol=ticker, input_tokens=u["input"],
                                output_tokens=u["output"],
                                cost_usd=cost_usd({model: u}, cfg["prices"]))
        ledger.log_decision("crypto" if asset_type == "crypto" else "stocks", ticker, "committee",
                            dec.action, confidence=dec.confidence, entry=dec.entry, stop=dec.stop,
                            target=dec.target, reason=dec.rationale, payload=dec.to_dict())
    return dec


if __name__ == "__main__":
    import argparse
    import json
    from datetime import date as _date

    ap = argparse.ArgumentParser(description="Run the TradingAgents committee on one ticker")
    ap.add_argument("ticker")
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--crypto", action="store_true")
    ap.add_argument("--no-ledger", action="store_true")
    args = ap.parse_args()

    led = None
    if not args.no_ledger:
        from core.ledger import Ledger
        led = Ledger()
    d = run_committee(args.ticker, args.date, asset_type="crypto" if args.crypto else "stock", ledger=led)
    print(json.dumps(d.to_dict(), indent=2, ensure_ascii=False))
