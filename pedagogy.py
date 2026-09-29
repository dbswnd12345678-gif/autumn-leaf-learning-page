"""
교육학 규칙 매칭 모듈.

pedagogy_db.json(교사 발문을 AI 단계 D~G에 대응한 규칙)을 읽고 다음을 제공한다.
  1. score_observation(...) - 학생 관찰문 한 턴을 가벼운 규칙으로 채점한다
     (객관성, 관찰 다양성, 공간 범위, 과학 용어 수). 지금은 MVP용 키워드 채점이며,
     이후 더 나은 분석으로 교체할 수 있다. 에이전트가 당장 반응할 근거를 주기 위해 둔다.
  2. match_pedagogy_rule(context) - 이번 문장을 중심에 두고, 과거 이력 요약으로
     이미 한 관찰은 빼면서 교사 발문 규칙 하나를 고른다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

PEDAGOGY_DB_PATH = Path(__file__).parent / "pedagogy_db.json"

_QUANT_UNIT_PATTERN = re.compile(r"(\d+(\.\d+)?\s*(cm|mm|%|개|배|퍼센트|센티|밀리))")
_NUMBER_PATTERN = re.compile(r"\d")

_TOOL_WORDS = ["눈금자", "자로", "각도기", "상대 길이", "측정"]
_COMPARE_OBJECT_WORDS = ["보다 크", "보다 작", "만큼", "정도의 크기", "더 길", "더 짧"]
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
    turn_index: int  # 이 학생의 이전 대화 턴 수 (0이면 첫 메시지)
    is_first_observation: bool
    comparison_mode: bool
    has_second_image_available: bool
    objectivity_score: int  # 매칭용: 이번 문장과 이력 중 높은 객관성
    variety_count: int  # 매칭용: 이번 문장+이력에서 나온 관찰 종류 수
    spatial_scope: str  # "whole"(전체) | "part"(부분) | "none"(구분 없음)
    term_count: int
    current_objectivity_score: int = 1  # 이번 문장만의 객관성
    already_quantified: bool = False  # 이력에 숫자·측정이 있었는지
    already_used_tools: bool = False  # 이력에 자·각도기 표현이 있었는지


def score_observation(
    *,
    text: str,
    comparison_mode: bool,
    has_second_image_available: bool,
) -> dict[str, Any]:
    """학생 관찰문 한 줄을 키워드 규칙으로 채점한다(MVP)."""
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
        objectivity_score = 1  # 사실만 말한 평범한 문장. 주관적 표현도 정량 단서도 없음

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


def _variety_hits(text: str) -> set[str]:
    hits: set[str] = set()
    for category, keywords in _VARIETY_CATEGORIES.items():
        if any(k in (text or "") for k in keywords):
            hits.add(category)
    return hits


def summarize_history(history: Optional[list[dict[str, Any]]]) -> dict[str, Any]:
    """과거 관찰문을 모아, 이미 한 관찰을 빼는 필터로 쓸 요약을 만든다."""
    rows = history or []
    questions = [(row.get("question") or "").strip() for row in rows]
    questions = [q for q in questions if q]
    if not questions:
        return {
            "turn_count": 0,
            "objectivity_max": 0,
            "variety_union": 0,
            "spatial_scope": "none",
            "already_quantified": False,
            "already_used_tools": False,
            "recent_questions": [],
        }

    scored = [
        score_observation(
            text=q,
            comparison_mode=False,
            has_second_image_available=True,
        )
        for q in questions
    ]
    obj_max = max(s["objectivity_score"] for s in scored)
    variety: set[str] = set()
    for q in questions:
        variety |= _variety_hits(q)
    spatial = "none"
    for s in scored:
        if s["spatial_scope"] == "whole":
            spatial = "whole"
        elif s["spatial_scope"] == "part" and spatial != "whole":
            spatial = "part"

    already_used_tools = any(any(w in q for w in _TOOL_WORDS) for q in questions)
    already_quantified = obj_max >= 2 or any(bool(_NUMBER_PATTERN.search(q)) for q in questions)
    return {
        "turn_count": len(questions),
        "objectivity_max": obj_max,
        "variety_union": len(variety),
        "spatial_scope": spatial,
        "already_quantified": already_quantified,
        "already_used_tools": already_used_tools,
        "recent_questions": questions[-5:],
    }


def format_history_summary(history: Optional[list[dict[str, Any]]]) -> str:
    """에이전트에게 줄 이력 요약 문장."""
    info = summarize_history(history)
    if info["turn_count"] == 0:
        return "이 학생은 과거 관찰 기록이 없습니다. 오늘이 첫 관찰입니다. 이번 문장만 중심에 두고 안내하세요."

    lines = [
        f"지금까지 총 {info['turn_count']}번 관찰을 기록했습니다.",
        "이 이력은 이미 한 관찰을 반복 제안하지 않기 위한 필터입니다. 답변의 중심은 반드시 이번 관찰문입니다.",
    ]
    if info["already_quantified"]:
        lines.append("이력에 숫자·개수·측정 표현이 있습니다. 정성관찰로 되돌리지 마세요.")
    if info["already_used_tools"]:
        lines.append("이력에 자·각도기 사용 흔적이 있습니다. 도구를 처음 소개하는 발문은 반복하지 마세요.")
    recent = info["recent_questions"]
    if recent:
        quoted = " / ".join(f"\"{q[:80]}\"" for q in recent)
        lines.append("최근 관찰: " + quoted)
    return " ".join(lines)


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
        return False  # 교사 판단이 필요한 메모만 있는 규칙이라 자동 매칭하지 않음
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
    ctx: ObservationContext, previous_rule_ids: Optional[list[str]] = None
) -> Optional[dict[str, Any]]:
    """이번 턴에 쓸 교사 발문 규칙 하나를 고른다.

    pedagogy_db.json은 카테고리별로 모아 둔 교사 발문 *참고 풀*이다.
    aiStage는 안내 성격(자유관찰 / 방법안내 / 피드백 / 심화)을 나타내는 라벨일 뿐,
    모든 학생이 반드시 밟아야 하는 순서가 아니다.

    매칭은 이번 관찰문을 중심에 두고, 이력 요약으로 이미 한 관찰은 뺀다.
    유일한 예외는 학생의 첫 메시지(turn_index == 0)로, 개방형 자유관찰 규칙을 낸다.
    """
    rules = load_rules()
    skip_ids = [rid for rid in (previous_rule_ids or []) if rid]

    if ctx.turn_index == 0 and ctx.is_first_observation:
        for rule in rules:
            if rule["id"] == "자유관찰":
                return {**rule, "matchedStage": rule["aiStage"]}

    candidates = [
        rule
        for rule in rules
        if rule["id"] != "자유관찰" and _condition_matches(rule.get("triggerCondition", {}), ctx)
    ]

    exclude: set[str] = set()
    if ctx.already_quantified:
        exclude.add("정성관찰")
    if ctx.already_used_tools:
        exclude.add("정량-자, 각도기")
    if exclude:
        filtered = [r for r in candidates if r["id"] not in exclude]
        if filtered:
            candidates = filtered

    if skip_ids and len(candidates) > 1:
        skipped = [r for r in candidates if r["id"] not in skip_ids]
        if skipped:
            candidates = skipped

    if not candidates:
        return None

    rule = candidates[0]
    return {**rule, "matchedStage": rule["aiStage"]}


def build_context(
    *,
    turn_index: int,
    is_first_observation: bool,
    text: str,
    comparison_mode: bool,
    has_second_image_available: bool,
    history: Optional[list[dict[str, Any]]] = None,
) -> ObservationContext:
    current = score_observation(
        text=text,
        comparison_mode=comparison_mode,
        has_second_image_available=has_second_image_available,
    )
    past = summarize_history(history)
    variety = _variety_hits(text)
    for q in past.get("recent_questions") or []:
        variety |= _variety_hits(q)
    if history:
        for row in history:
            variety |= _variety_hits(row.get("question") or "")

    spatial = current["spatial_scope"]
    if spatial == "none":
        spatial = past["spatial_scope"]

    return ObservationContext(
        turn_index=turn_index,
        is_first_observation=is_first_observation,
        comparison_mode=comparison_mode,
        has_second_image_available=has_second_image_available,
        objectivity_score=max(current["objectivity_score"], past["objectivity_max"]),
        variety_count=len(variety) if variety else current["variety_count"],
        spatial_scope=spatial,
        term_count=current["term_count"],
        current_objectivity_score=current["objectivity_score"],
        already_quantified=past["already_quantified"]
        or current["objectivity_score"] >= 2
        or bool(_NUMBER_PATTERN.search(text or "")),
        already_used_tools=past["already_used_tools"] or any(w in (text or "") for w in _TOOL_WORDS),
    )