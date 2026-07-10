# tests/test_profile_recommender.py
from src.agent.skills.base import Skill
from src.agent.skills.profile_recommender import recommend_skills


def _skill(name, **kw):
    base = dict(name=name, display_name=name, description="d", instructions="i", user_invocable=True)
    base.update(kw)
    return Skill(**base)


SKILLS = [
    _skill("bull_trend", profile_tags={"style": ["trend"], "horizon": ["swing"], "risk": ["balanced"]}),
    _skill("hot_theme", profile_tags={"style": ["theme"], "horizon": ["ultra_short"], "risk": ["aggressive"]}),
    _skill("growth_quality", profile_tags={"style": ["value"], "horizon": ["long"], "risk": ["conservative"]}),
]


def test_aggressive_theme_picks_hot_theme_first():
    answers = {"horizon": "ultra_short", "risk": "aggressive", "style": "theme", "watch": "high"}
    result = recommend_skills(answers, SKILLS, max_count=2)
    assert result[0] == "hot_theme"


def test_conservative_long_picks_growth_quality_first():
    answers = {"horizon": "long", "risk": "conservative", "style": "value", "watch": "low"}
    result = recommend_skills(answers, SKILLS, max_count=2)
    assert result[0] == "growth_quality"


def test_respects_max_count_and_cap():
    answers = {"horizon": "swing", "risk": "balanced", "style": "trend", "watch": "medium"}
    result = recommend_skills(answers, SKILLS, max_count=10)
    assert 1 <= len(result) <= 5


def test_excludes_non_invocable():
    skills = SKILLS + [_skill("internal", user_invocable=False,
                              profile_tags={"style": ["trend"], "horizon": ["swing"], "risk": ["balanced"]})]
    answers = {"horizon": "swing", "risk": "balanced", "style": "trend", "watch": "medium"}
    result = recommend_skills(answers, skills, max_count=5)
    assert "internal" not in result


def test_tiebreak_by_default_priority_then_name():
    # All three skills have no matching profile_tags -> score == 0 for any answers.
    # Expected sort: lower default_priority first; when equal priority, alphabetical by name.
    skill_b_pri10 = _skill("bravo", default_priority=10, profile_tags={})
    skill_a_pri10 = _skill("alpha", default_priority=10, profile_tags={})
    skill_z_pri5 = _skill("zeta", default_priority=5, profile_tags={})
    skills = [skill_b_pri10, skill_a_pri10, skill_z_pri5]
    answers = {"horizon": "long", "risk": "conservative", "style": "value", "watch": "low"}
    result = recommend_skills(answers, skills, max_count=5)
    # zeta(pri=5) < alpha(pri=10, name="alpha") < bravo(pri=10, name="bravo")
    assert result == ["zeta", "alpha", "bravo"]


def test_value_style_interview_recommends_value_undervalued_from_real_skills():
    from src.agent.factory import get_skill_manager

    skills = get_skill_manager().list_skills()
    answers = {"horizon": "long", "risk": "balanced", "style": "value", "watch": "low"}
    result = recommend_skills(answers, skills, max_count=3)
    assert "value_undervalued" in result
