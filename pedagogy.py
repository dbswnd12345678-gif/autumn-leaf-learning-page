"""
Pedagogy matching module.

Loads pedagogy_db.json (teacher-question rules mapped to AI stages D-G) and
provides:
  1. score_observation(...)  - lightweight heuristic scoring of a single
     student observation turn (objectivity, vocabulary variety, spatial
     scope, scientific-term count). This is an MVP rule-based scorer meant
     to be replaced/tuned later with a better NLP pipeline; it exists so the
     agent has *something* concrete to react to today.
  2. match_pedagogy_rule(context) - picks the most relevant teacher-question
     rule for the current turn, given the scored context.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PEDAGOGY_DB_PATH = Path(__file__).parent / "pedagogy_db.json"

_QUANT_UNIT_PATTERN = re.compile(r"(\d+(\.\d+)?\s*(cm|mm|%|개|배|퍼센트|센티|밀리))")
_NUMBER_PATTERN = re.compile(r"\d")

_TOOL_WORDS = ["눈금자", "자로", "격자", "그리드", "측정", "저울", "온도계"]
_COMPARE_OBJECT_WORDS = ["동전", "손바닥", "지우개", "만큼", "보다 크", "보다 작", "정도의 크기"]
_HEDGE_WORDS = ["같다", "듯하다", "느낌이", "예쁘다", "아름답다", "귀엽다", "멋있다"]

_VARIETY_CATEGORIES: dict[str, list[str]] = {
    "color": ["색", "빨갛", "노랗", "주황", "갈색", "초록", "색깔"],
    "shape": ["모양", "둥글", "뾰족", "타원", "손바닥 모양", "갈래"],
    "vein": ["잎맥", "잎줄기", "잎자루"],
    "edge": ["가장자리", "톱니", "테두리"],
    "size": ["크기", "길이", "너비", "크다", "작다"],
    "smell": ["냄새", "향"],
    "texture": ["촉감", "만졌", "매끈", "거칠", "질감"],
}

_SCIENCE_TERMS = [
    "엽록소", "안토시아닌", "카로티노이드", "잎자루", "잎맥", "톱니",
    "광합성", "색소", "기공", "표피", "엽육", "탈리층", "단풍",
]

_WHOLE_WORDS = ["전체", "잎 전체", "전체적으로", "전체 모습"]
_PART_WORDS = ["부분", "일부", "가장자리", "잎맥", "끝부분", "중심부"]


@dataclass
class ObservationContext:
    turn_index: int  # number of PRIOR turns for this student (0 = very first turn)
    is_first_observation: bool
    comparison_mode: bool
    has_second_image_available: bool
    objectivity_score: int
    variety_count: int
    spatial_scope: str  # "whole" | "part" | "none"
    term_count: int


def score_observation(
    *,
    text: str,
    comparison_mode: bool,
    has_second_image_available: bool,
) -> dict[str, Any]:
    """Heuristic MVP scorer for a single observation sentence."""
    t = text or ""

    has_quant_unit = bool(_QUANT_UNIT_PATTERN.search(t))
    has_number = bool(_NUMBER_PATTERN.search(t))
    has_tool_word = any(w in t for w in _TOOL_WORDS)
    has_compare_object = any(w in t for w in _COMPARE_OBJECT_WORDS)
    has_hedge = any(w in t for w in _HEDGE_WORDS)

    if has_quant_unit or has_tool_word:
        objectivity_score = 2
    elif has_number or has_compare_object:
        objectivity_score = 1
    elif has_hedge:
        objectivity_score = 0
    else:
        objectivity_score = 1  # neutral/plain factual statement, no hedging detected

    variety_count = 0
    for _category, keywords in _VARIETY_CATEGORIES.items():
        if any(k in t for k in keywords):
            variety_count += 1

    term_count = sum(1 for term in _SCIENCE_TERMS if term in t)

    if any(w in t for w in _WHOLE_WORDS):
        spatial_scope = "whole"
    elif any(w in t for w in _PART_WORDS):
        spatial_scope = "part"
    else:
        spatial_scope = "none"

    return {
        "objectivity_score": objectivity_score,
        "variety_count": variety_count,
        "term_count": term_count,
        "spatial_scope": spatial_scope,
        "comparison_mode": comparison_mode,
        "has_second_image_available": has_second_image_available,
    }


_rules_cache: Optional[list[dict[str, Any]]] = None


def load_rules() -> list[dict[str, Any]]:
    global _rules_cache
    if _rules_cache is None:
        with open(PEDAGOGY_DB_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _rules_cache = data.get("rules", [])
    return _rules_cache


def _condition_matches(condition: dict[str, Any], ctx: ObservationContext) -> bool:
    if "note" in condition and len(condition) == 1:
        return False  # requires manual/teacher judgement, not auto-matchable
    if "turnIndex" in condition and ctx.turn_index != condition["turnIndex"]:
        return False
    if "isFirstObservation" in condition and ctx.is_first_observation != condition["isFirstObservation"]:
        return False
    if "objectivityScore" in condition and ctx.objectivity_score not in condition["objectivityScore"]:
        return False
    if "varietyCount" in condition and ctx.variety_count not in condition["varietyCount"]:
        return False
    if "spatialScope" in condition and ctx.spatial_scope not in condition["spatialScope"]:
        return False
    if "comparisonMode" in condition and ctx.comparison_mode != condition["comparisonMode"]:
        return False
    if "hasSecondImageAvailable" in condition and ctx.has_second_image_available != condition["hasSecondImageAvailable"]:
        return False
    return True


def match_pedagogy_rule(
    ctx: ObservationContext, previous_rule_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Pick the single most relevant teacher-question rule for this turn.

    Important: pedagogy_db.json is a *reference pool* of teacher questions
    grouped by category (aiStage is a label describing the type of
    guidance - free observation / method guidance / feedback / deepening -
    not a mandatory sequence). We do NOT march every student through
    D -> E -> F -> G in turn order. Instead, on every turn we look only at
    the *content* of the current observation (objectivity, variety,
    spatial scope, comparison mode) and pick whichever rule fits best,
    regardless of stage or how many turns have passed.

    The one deliberate exception is the very first message a student ever
    sends (turn_index == 0), where we surface the open-ended "free
    observation" rule (D-open-1) since there is no prior content yet to
    match against.
    """
    rules = load_rules()

    if ctx.turn_index == 0 and ctx.is_first_observation:
        for rule in rules:
            if rule["id"] == "D-open-1":
                return {**rule, "matchedStage": rule["aiStage"]}

    candidates = [
        rule
        for rule in rules
        if rule["id"] != "D-open-1" and _condition_matches(rule.get("triggerCondition", {}), ctx)
    ]
    if not candidates:
        return None

    # Avoid repeating the exact same rule two turns in a row when another
    # equally-valid option is available, since these are meant to be drawn
    # on flexibly rather than recited in a fixed script.
    if previous_rule_id and len(candidates) > 1:
        candidates = [r for r in candidates if r["id"] != previous_rule_id] or candidates

    rule = candidates[0]
    return {**rule, "matchedStage": rule["aiStage"]}


def build_context(
    *,
    turn_index: int,
    is_first_observation: bool,
    text: str,
    comparison_mode: bool,
    has_second_image_available: bool,
) -> ObservationContext:
    scored = score_observation(
        text=text,
        comparison_mode=comparison_mode,
        has_second_image_available=has_second_image_available,
    )
    return ObservationContext(
        turn_index=turn_index,
        is_first_observation=is_first_observation,
        comparison_mode=comparison_mode,
        has_second_image_available=has_second_image_available,
        objectivity_score=scored["objectivity_score"],
        variety_count=scored["variety_count"],
        spatial_scope=scored["spatial_scope"],
        term_count=scored["term_count"],
    )