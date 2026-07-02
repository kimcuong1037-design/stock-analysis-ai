# -*- coding: utf-8 -*-
"""Tests for investor profile API endpoints (Task 4)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager


def _make_client(tmp_path: Path):
    DatabaseManager.reset_instance()
    Config.reset_instance()
    DatabaseManager(db_url=f"sqlite:///{tmp_path / 'profile_test.db'}")
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False):
        return TestClient(create_app(static_dir=tmp_path / "static"))


@pytest.fixture(autouse=True)
def reset_singletons():
    yield
    DatabaseManager.reset_instance()
    Config.reset_instance()


def test_get_profile_empty(tmp_path: Path):
    client = _make_client(tmp_path)
    r = client.get("/api/v1/agent/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["skill_ids"] == []
    assert body["source"] is None
    assert body["updated_at"] is None


def test_put_then_get_profile(tmp_path: Path):
    client = _make_client(tmp_path)
    r = client.put("/api/v1/agent/profile", json={"skill_ids": ["bull_trend"], "source": "manual"})
    assert r.status_code == 200
    assert r.json()["skill_ids"] == ["bull_trend"]
    g = client.get("/api/v1/agent/profile")
    assert g.status_code == 200
    assert g.json()["skill_ids"] == ["bull_trend"]


def test_put_dedupes_and_caps_at_5(tmp_path: Path):
    client = _make_client(tmp_path)
    ids = ["a", "b", "a", "c", "d", "e", "f"]  # 7 items, 'a' duplicated
    r = client.put("/api/v1/agent/profile", json={"skill_ids": ids})
    assert r.status_code == 200
    result = r.json()["skill_ids"]
    assert result == ["a", "b", "c", "d", "e"]  # deduped 'a', capped at 5


def test_interview_returns_recommendations_without_saving(tmp_path: Path):
    client = _make_client(tmp_path)
    # Establish a known saved profile
    client.put("/api/v1/agent/profile", json={"skill_ids": ["bull_trend"]})
    r = client.post("/api/v1/agent/profile/interview", json={
        "answers": {"horizon": "ultra_short", "risk": "aggressive", "style": "theme", "watch": "high"}
    })
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["recommended"], list) and len(body["recommended"]) >= 1
    assert isinstance(body["explanation"], str) and len(body["explanation"]) > 0
    # interview MUST NOT mutate the saved profile
    saved = client.get("/api/v1/agent/profile").json()
    assert saved["skill_ids"] == ["bull_trend"]


def test_interview_explanation_is_string(tmp_path: Path):
    """Explanation falls back to static text when no LLM is configured."""
    client = _make_client(tmp_path)
    r = client.post("/api/v1/agent/profile/interview", json={
        "answers": {"horizon": "short", "risk": "moderate", "style": "value", "watch": "medium"}
    })
    assert r.status_code == 200
    explanation = r.json()["explanation"]
    assert isinstance(explanation, str) and len(explanation) > 0


# ---------------------------------------------------------------------------
# Task 6: skill_breakdown surfacing + default skills from profile + compare cap
# ---------------------------------------------------------------------------

def test_chat_response_has_skill_breakdown_field():
    """ChatResponse must always carry skill_breakdown (empty in non-skill paths)."""
    from api.v1.endpoints.agent import ChatResponse
    assert "skill_breakdown" in ChatResponse.model_fields


def test_skills_endpoint_exposes_category_and_profile_tags(tmp_path: Path):
    """StrategyCenter groups by category; getSkills must expose category + profile_tags."""
    client = _make_client(tmp_path)
    r = client.get("/api/v1/agent/skills")
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert len(skills) >= 1
    for s in skills:
        assert "category" in s and isinstance(s["category"], str) and s["category"]
        assert "profile_tags" in s and isinstance(s["profile_tags"], dict)


def test_compare_max_config_default(tmp_path: Path):
    DatabaseManager.reset_instance()
    Config.reset_instance()
    from src.config import get_config
    assert 1 <= getattr(get_config(), "agent_compare_max", 3) <= 5


def test_resolve_effective_skills_falls_back_to_profile_and_caps(tmp_path: Path):
    DatabaseManager.reset_instance()
    Config.reset_instance()
    DatabaseManager(db_url=f"sqlite:///{tmp_path / 'rs.db'}")
    from src.config import get_config
    from src.storage import get_db
    from api.v1.endpoints.agent import _resolve_effective_skills

    config = get_config()
    cap = config.agent_compare_max
    get_db().upsert_investor_profile(["a", "b", "c", "d", "e", "f"])  # 6 saved ids

    # No request skills -> fall back to the saved profile, capped at agent_compare_max.
    resolved = _resolve_effective_skills(config, None)
    assert resolved == ["a", "b", "c", "d", "e", "f"][:cap]
    assert len(resolved) == cap

    # Explicit request skills bypass the profile (and stay under the cap here).
    assert _resolve_effective_skills(config, ["x", "y"]) == ["x", "y"]

    # Explicit empty list is honored verbatim (clear), NOT overridden by profile.
    assert _resolve_effective_skills(config, []) == []

    # No skills field + no profile -> None (preserves existing default behavior).
    get_db().clear_investor_profile()
    assert _resolve_effective_skills(config, None) is None


def test_orchestrator_chat_preserves_skill_breakdown():
    """Regression: orchestrator.chat() must copy skill_breakdown from the
    pipeline result into the AgentResult it returns (otherwise the API never
    sees it in multi-agent mode)."""
    from unittest.mock import MagicMock, patch

    from src.agent.orchestrator import AgentOrchestrator, OrchestratorResult
    from src.agent.executor import AgentResult
    from src.agent.protocols import AgentContext

    breakdown = [{
        "skill_id": "bull_trend", "display_name": "bull_trend", "signal": "buy",
        "confidence": 0.8, "score_adjustment": 12, "reasoning": "x", "key_levels": {},
    }]

    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.config = MagicMock()
    orch.llm_adapter = MagicMock()
    orch._build_context = MagicMock(return_value=AgentContext())
    orch._execute_pipeline = MagicMock(return_value=OrchestratorResult(
        success=True, content="hello", skill_breakdown=breakdown))

    with patch("src.agent.orchestrator.build_visible_chat_history", return_value=[]), \
            patch("src.agent.conversation.conversation_manager"):
        result = orch.chat("q", "sess")

    assert isinstance(result, AgentResult)
    assert result.skill_breakdown == breakdown


# ---------------------------------------------------------------------------
# Task 12: skill_consensus flow-through (additive, mirrors skill_breakdown)
# ---------------------------------------------------------------------------

_CONSENSUS = {
    "signal": "hold",
    "confidence": 0.72,
    "score_adjustment": 4,
    "reasoning": "weighted aggregate",
    "skill_count": 2,
}


def test_chat_response_has_skill_consensus_field():
    """ChatResponse must always carry skill_consensus (None when absent)."""
    from api.v1.endpoints.agent import ChatResponse
    assert "skill_consensus" in ChatResponse.model_fields


def test_orchestrator_chat_preserves_skill_consensus():
    """Regression: orchestrator.chat() must copy skill_consensus from the
    pipeline result into the AgentResult it returns (same flow as
    skill_breakdown), otherwise the API never sees it in multi-agent mode."""
    from unittest.mock import MagicMock, patch

    from src.agent.orchestrator import AgentOrchestrator, OrchestratorResult
    from src.agent.executor import AgentResult
    from src.agent.protocols import AgentContext

    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.config = MagicMock()
    orch.llm_adapter = MagicMock()
    orch._build_context = MagicMock(return_value=AgentContext())
    orch._execute_pipeline = MagicMock(return_value=OrchestratorResult(
        success=True, content="hello", skill_consensus=_CONSENSUS))

    with patch("src.agent.orchestrator.build_visible_chat_history", return_value=[]), \
            patch("src.agent.conversation.conversation_manager"):
        result = orch.chat("q", "sess")

    assert isinstance(result, AgentResult)
    assert result.skill_consensus == _CONSENSUS


def test_orchestrator_chat_skill_consensus_absent_is_none():
    """When the pipeline produced no consensus (single-skill/no-skill run),
    orchestrator.chat() must not fabricate one."""
    from unittest.mock import MagicMock, patch

    from src.agent.orchestrator import AgentOrchestrator, OrchestratorResult
    from src.agent.executor import AgentResult
    from src.agent.protocols import AgentContext

    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.config = MagicMock()
    orch.llm_adapter = MagicMock()
    orch._build_context = MagicMock(return_value=AgentContext())
    orch._execute_pipeline = MagicMock(return_value=OrchestratorResult(success=True, content="hello"))

    with patch("src.agent.orchestrator.build_visible_chat_history", return_value=[]), \
            patch("src.agent.conversation.conversation_manager"):
        result = orch.chat("q", "sess")

    assert isinstance(result, AgentResult)
    assert result.skill_consensus is None


class _ImmediateLoop:
    """Runs run_in_executor synchronously so sync agent_chat tests need no thread pool."""

    def __init__(self, loop):
        self._loop = loop

    def run_in_executor(self, _executor, func):
        future = self._loop.create_future()
        future.set_result(func())
        return future


def test_agent_chat_sync_surfaces_skill_consensus():
    """POST /chat surfaces the orchestrator's skill_consensus additively."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from api.v1.endpoints.agent import agent_chat, ChatRequest

    breakdown = [{
        "skill_id": "bull_trend", "display_name": "bull_trend", "signal": "buy",
        "confidence": 0.8, "score_adjustment": 12, "reasoning": "x", "key_levels": {},
    }]
    executor = MagicMock()
    executor.chat.return_value = SimpleNamespace(
        success=True, content="ok", error=None,
        skill_breakdown=breakdown, skill_consensus=_CONSENSUS,
    )
    config = SimpleNamespace(is_agent_available=lambda: True, agent_compare_max=3)
    request = ChatRequest(message="hi", skills=["bull_trend", "box_oscillation"])
    real_get_running_loop = asyncio.get_running_loop

    with patch("api.v1.endpoints.agent.get_config", return_value=config), \
            patch("api.v1.endpoints.agent._build_executor", return_value=executor), \
            patch(
                "api.v1.endpoints.agent.asyncio.get_running_loop",
                side_effect=lambda: _ImmediateLoop(real_get_running_loop()),
            ):
        response = asyncio.run(agent_chat(request))

    assert response.skill_consensus == _CONSENSUS


def test_agent_chat_sync_skill_consensus_absent_when_none():
    """Single-skill / no-skill chat: skill_consensus stays None — additive
    field, never fabricated when the orchestrator didn't compute one."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from api.v1.endpoints.agent import agent_chat, ChatRequest

    executor = MagicMock()
    executor.chat.return_value = SimpleNamespace(success=True, content="ok", error=None)
    config = SimpleNamespace(is_agent_available=lambda: True, agent_compare_max=3)
    # Explicit empty skills list = "clear" (bypasses profile lookup / DB access).
    request = ChatRequest(message="hi", skills=[])
    real_get_running_loop = asyncio.get_running_loop

    with patch("api.v1.endpoints.agent.get_config", return_value=config), \
            patch("api.v1.endpoints.agent._build_executor", return_value=executor), \
            patch(
                "api.v1.endpoints.agent.asyncio.get_running_loop",
                side_effect=lambda: _ImmediateLoop(real_get_running_loop()),
            ):
        response = asyncio.run(agent_chat(request))

    assert response.skill_consensus is None


async def _collect_sse_events(response) -> list:
    import json as json_mod

    events = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
        for part in text.split("\n\n"):
            part = part.strip()
            if part.startswith("data: "):
                events.append(json_mod.loads(part[len("data: "):]))
    return events


def test_agent_chat_stream_done_event_includes_skill_consensus():
    """SSE 'done' event carries skill_consensus additively (mirrors skill_breakdown)."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from api.v1.endpoints.agent import agent_chat_stream, ChatRequest

    executor = MagicMock()
    executor.chat.return_value = SimpleNamespace(
        success=True, content="ok", error=None, total_steps=3,
        skill_breakdown=[], skill_consensus=_CONSENSUS,
    )
    config = SimpleNamespace(is_agent_available=lambda: True, agent_compare_max=3)
    request = ChatRequest(
        message="hi", skills=["bull_trend", "box_oscillation"], session_id="sse-consensus-test",
    )

    async def run():
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
                patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_chat_stream(request)
            return await _collect_sse_events(response)

    events = asyncio.run(run())
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["skill_consensus"] == _CONSENSUS


def test_agent_chat_stream_done_event_skill_consensus_absent_is_none():
    """Single-skill / no-skill stream: SSE done.skill_consensus stays None."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from api.v1.endpoints.agent import agent_chat_stream, ChatRequest

    executor = MagicMock()
    executor.chat.return_value = SimpleNamespace(success=True, content="ok", error=None, total_steps=1)
    config = SimpleNamespace(is_agent_available=lambda: True, agent_compare_max=3)
    request = ChatRequest(message="hi", skills=[], session_id="sse-consensus-absent-test")

    async def run():
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
                patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_chat_stream(request)
            return await _collect_sse_events(response)

    events = asyncio.run(run())
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["skill_consensus"] is None
