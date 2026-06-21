# src/agent/skills/profile_tags.py
# -*- coding: utf-8 -*-
"""Resolve a skill's profile_tags, deriving sensible defaults when absent."""
from __future__ import annotations
from typing import Dict, List

HORIZON_VALUES = ("ultra_short", "swing", "long")
RISK_VALUES = ("conservative", "balanced", "aggressive")
STYLE_VALUES = ("trend", "reversal", "theme", "value", "framework")

_CATEGORY_DEFAULTS: Dict[str, Dict[str, List[str]]] = {
    "trend": {"style": ["trend"], "horizon": ["swing"], "risk": ["balanced"]},
    "pattern": {"style": ["framework"], "horizon": ["swing"], "risk": ["balanced"]},
    "reversal": {"style": ["reversal"], "horizon": ["swing"], "risk": ["aggressive"]},
    "framework": {"style": ["framework"], "horizon": ["swing", "long"], "risk": ["balanced"]},
}

_THEME_REGIMES = {"sector_hot", "theme", "hot_theme", "emotion", "event"}


def resolve_profile_tags(skill) -> Dict[str, List[str]]:
    explicit = getattr(skill, "profile_tags", None) or {}
    if explicit:
        return {k: list(v) for k, v in explicit.items()}

    category = (getattr(skill, "category", "") or "trend").strip().lower()
    derived = {
        k: list(v) for k, v in _CATEGORY_DEFAULTS.get(category, _CATEGORY_DEFAULTS["trend"]).items()
    }

    regimes = {str(r).strip().lower() for r in (getattr(skill, "market_regimes", None) or [])}
    if regimes & _THEME_REGIMES:
        derived["style"] = sorted(set(derived.get("style", [])) | {"theme"})
        derived.setdefault("risk", ["balanced"])
        derived["risk"] = sorted(set(derived["risk"]) | {"aggressive"})
        derived["horizon"] = sorted(set(derived.get("horizon", [])) | {"ultra_short"})
    return derived
