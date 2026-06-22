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
