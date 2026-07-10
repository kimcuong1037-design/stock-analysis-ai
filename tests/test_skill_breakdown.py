# -*- coding: utf-8 -*-
"""Tests for build_skill_breakdown/build_skill_consensus — per-skill opinion
extraction (pre-consensus) and the aggregated consensus (post-aggregation)."""

from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.orchestrator import build_skill_breakdown, build_skill_consensus


def test_breakdown_extracts_individual_skill_opinions():
    ctx = AgentContext(stock_code="600519")
    ctx.opinions.append(AgentOpinion(agent_name="technical", signal="buy", confidence=0.7, reasoning="t"))
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_bull_trend", signal="buy", confidence=0.8,
        reasoning="bullish", raw_data={"score_adjustment": 12}))
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_box_oscillation", signal="sell", confidence=0.6,
        reasoning="range top", raw_data={"score_adjustment": -8}))

    breakdown = build_skill_breakdown(ctx)
    ids = {b["skill_id"] for b in breakdown}
    assert ids == {"bull_trend", "box_oscillation"}        # technical excluded
    bull = next(b for b in breakdown if b["skill_id"] == "bull_trend")
    assert bull["signal"] == "buy"
    assert bull["score_adjustment"] == 12


def test_breakdown_empty_when_no_skill_opinions():
    ctx = AgentContext(stock_code="600519")
    ctx.opinions.append(AgentOpinion(agent_name="technical", signal="hold", confidence=0.5, reasoning="t"))
    assert build_skill_breakdown(ctx) == []


def test_breakdown_excludes_skill_consensus():
    """Regression: skill_consensus must be excluded even though it has the skill_ prefix."""
    ctx = AgentContext(stock_code="600519")
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_bull_trend", signal="buy", confidence=0.8,
        reasoning="bullish", raw_data={"score_adjustment": 12}))
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_box_oscillation", signal="sell", confidence=0.6,
        reasoning="range top", raw_data={"score_adjustment": -8}))
    # This simulates what _aggregate_skill_opinions() does: append consensus AFTER individuals
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_consensus", signal="hold", confidence=0.7,
        reasoning="weighted aggregate", raw_data={}))

    breakdown = build_skill_breakdown(ctx)
    ids = {b["skill_id"] for b in breakdown}

    # consensus must be excluded; only the two real skill opinions included
    assert "consensus" not in ids, "skill_consensus must be excluded from breakdown"
    assert ids == {"bull_trend", "box_oscillation"}


def test_consensus_extracts_signal_confidence_score_reasoning():
    ctx = AgentContext(stock_code="600519")
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_bull_trend", signal="buy", confidence=0.8,
        reasoning="bullish", raw_data={"score_adjustment": 12}))
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_box_oscillation", signal="sell", confidence=0.6,
        reasoning="range top", raw_data={"score_adjustment": -8}))
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_consensus", signal="hold", confidence=0.72,
        reasoning="weighted aggregate",
        raw_data={"total_adjustment": 4, "skill_count": 2, "weighted_score": 3.1}))

    consensus = build_skill_consensus(ctx)
    assert consensus == {
        "signal": "hold",
        "confidence": 0.72,
        "score_adjustment": 4,
        "reasoning": "weighted aggregate",
        "skill_count": 2,
    }


def test_consensus_none_when_no_consensus_opinion():
    """No skill agents ran (or aggregation failed silently) -> None, mirroring
    the empty-list semantics of build_skill_breakdown."""
    ctx = AgentContext(stock_code="600519")
    ctx.opinions.append(AgentOpinion(agent_name="technical", signal="hold", confidence=0.5, reasoning="t"))
    assert build_skill_consensus(ctx) is None
