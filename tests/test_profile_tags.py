# tests/test_profile_tags.py
from src.agent.skills.base import Skill
from src.agent.skills.profile_tags import resolve_profile_tags


def _skill(**kw):
    base = dict(name="x", display_name="X", description="d", instructions="i")
    base.update(kw)
    return Skill(**base)


def test_explicit_profile_tags_take_precedence():
    s = _skill(profile_tags={"horizon": ["swing"], "risk": ["aggressive"], "style": ["theme"]})
    tags = resolve_profile_tags(s)
    assert tags["style"] == ["theme"]
    assert tags["risk"] == ["aggressive"]


def test_derived_from_category_when_missing():
    s = _skill(category="reversal")
    tags = resolve_profile_tags(s)
    assert "reversal" in tags["style"]


def test_derived_from_market_regimes_theme():
    s = _skill(category="trend", market_regimes=["sector_hot"])
    tags = resolve_profile_tags(s)
    assert "theme" in tags["style"]


def test_value_category_derives_value_style():
    s = _skill(category="value")
    tags = resolve_profile_tags(s)
    assert tags["style"] == ["value"]
    assert tags["horizon"] == ["long"]
    assert set(tags["risk"]) == {"conservative", "balanced"}
