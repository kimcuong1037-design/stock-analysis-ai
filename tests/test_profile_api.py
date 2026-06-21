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
