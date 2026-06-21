# src/agent/skills/profile_recommender.py
# -*- coding: utf-8 -*-
"""Rule-based interview -> recommended skills (deterministic, no LLM)."""
from __future__ import annotations
from typing import Dict, List

from src.agent.skills.profile_tags import resolve_profile_tags

_DIMENSION_WEIGHTS = {"style": 3.0, "risk": 2.0, "horizon": 2.0}
_MAX_PROFILE_SKILLS = 5
# Low watch-time penalises ultra-short skills; high watch-time rewards them.
_WATCH_ULTRA_SHORT_ADJ = {"high": 1.0, "medium": 0.0, "low": -1.5}


def _score(answers: Dict[str, str], tags: Dict[str, List[str]]) -> float:
    score = 0.0
    for dim, weight in _DIMENSION_WEIGHTS.items():
        ans = answers.get(dim)
        if ans and ans in (tags.get(dim) or []):
            score += weight
    if "ultra_short" in (tags.get("horizon") or []):
        score += _WATCH_ULTRA_SHORT_ADJ.get(answers.get("watch", "medium"), 0.0)
    return score


def recommend_skills(answers: Dict[str, str], skills: List, max_count: int = 3) -> List[str]:
    cap = min(max_count, _MAX_PROFILE_SKILLS)
    scored = []
    for skill in skills:
        if not getattr(skill, "user_invocable", True):
            continue
        tags = resolve_profile_tags(skill)
        scored.append((_score(answers, tags), int(getattr(skill, "default_priority", 100)), skill.name))
    # Higher score first; tie-break by lower default_priority then name for determinism.
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return [name for _, _, name in scored[:cap]]
