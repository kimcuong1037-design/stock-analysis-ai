import pytest
from src.storage import get_db


@pytest.fixture
def db():
    return get_db()


def test_empty_profile_returns_none(db):
    db.clear_investor_profile(owner_key="test_owner")
    assert db.get_investor_profile(owner_key="test_owner") is None


def test_upsert_then_get(db):
    db.upsert_investor_profile(["bull_trend", "chan_theory"], source="interview", owner_key="test_owner")
    prof = db.get_investor_profile(owner_key="test_owner")
    assert prof["skill_ids"] == ["bull_trend", "chan_theory"]
    assert prof["source"] == "interview"


def test_upsert_is_single_row(db):
    db.upsert_investor_profile(["bull_trend"], owner_key="test_owner")
    db.upsert_investor_profile(["box_oscillation"], owner_key="test_owner")
    prof = db.get_investor_profile(owner_key="test_owner")
    assert prof["skill_ids"] == ["box_oscillation"]
    db.clear_investor_profile(owner_key="test_owner")
