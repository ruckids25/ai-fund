"""Offline tests for the committee's output parsing (runs in envs/ta only)."""
import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, LLMResult  # noqa: E402

from core.config import load_yaml  # noqa: E402
from desks.committee.ta_committee import TokenCounter, cost_usd, parse_state  # noqa: E402

TRADER = """**Action**: Buy

**Reasoning**: Momentum and earnings.

**Entry Price**: 1,189.50

**Stop Loss**: 172.0

**Position Sizing**: 5% of portfolio

FINAL TRANSACTION PROPOSAL: **BUY**"""

PM = """**Rating**: Overweight

**Executive Summary**: Scale in near support, stop below 172.

**Investment Thesis**: Long thesis text.

**Price Target**: 215.25

**Time Horizon**: 1-3 months"""


def test_parse_state_reads_levels_and_maps_rating():
    rmap = load_yaml("committee.yaml")["rating_map"]
    out = parse_state({"trader_investment_plan": TRADER, "final_trade_decision": PM}, "Overweight", rmap)
    assert out == {"action": "buy", "confidence": 0.6, "entry": 1189.5, "stop": 172.0,
                   "target": 215.25, "rationale": "Scale in near support, stop below 172."}


def test_parse_state_missing_levels_and_review():
    trader = TRADER.replace("172.0", "not provided").replace("1,189.50", "not provided")
    out = parse_state({"trader_investment_plan": trader, "final_trade_decision": ""}, "REVIEW", {})
    assert out["action"] == "review" and out["entry"] is None and out["stop"] is None
    assert out["target"] is None


def test_token_counter_and_cost():
    c = TokenCounter()
    msg = AIMessage("x", usage_metadata={"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200},
                    response_metadata={"model_name": "m1"})
    c.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))
    c.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))
    assert c.usage["m1"] == {"input": 2000, "output": 400, "calls": 2}
    assert cost_usd(dict(c.usage), {"m1": {"input": 3.0, "output": 15.0}}) == pytest.approx(0.012)
    assert cost_usd(dict(c.usage), {}) == 0.0
