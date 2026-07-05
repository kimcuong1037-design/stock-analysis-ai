# -*- coding: utf-8 -*-
"""Loader-level contract tests for the value_undervalued strategy YAML."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent.factory import get_skill_manager


def _skill():
    return get_skill_manager().get("value_undervalued")


def test_skill_loads_with_value_category():
    skill = _skill()
    assert skill is not None
    assert skill.display_name == "价值低估"
    assert skill.category == "value"


def test_skill_declares_explicit_value_profile_tags():
    skill = _skill()
    assert skill.profile_tags.get("style") == ["value"]
    assert skill.profile_tags.get("horizon") == ["long"]
    assert set(skill.profile_tags.get("risk", [])) == {"conservative", "balanced"}


def test_skill_requires_valuation_tool():
    skill = _skill()
    assert "estimate_intrinsic_value" in skill.required_tools


def test_skill_instructions_mandate_tool_call():
    skill = _skill()
    assert "estimate_intrinsic_value" in skill.instructions
    assert "安全边际" in skill.instructions
