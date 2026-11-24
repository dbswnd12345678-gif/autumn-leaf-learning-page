"""탭 2 소크라테스식 질문 기록: 응답 끝 태그 해석과 다음 요청에 붙일 이력 글.

Agent는 [현재 검토 문장]이 있는 턴마다 '소크라테스 질문 기록' Flow를 한 번 호출해
응답 종류, 질문 유형, 목표, 같은 목표 여부, 직전 목표 달성을 서버에 알린다(/api/tools/socratic-record).
Flow를 부르지 못했을 때를 대비해, 응답 끝에 [질문기록: ...] 태그가 있으면 같은 값으로 읽고 학생 화면에서는 지운다.
같은 문장의 다음 요청에는 저장한 이력을 [현재 문장 질문 이력]으로 붙여, Agent가 횟수를 세지 않게 한다.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# 같은 목표로 물을 수 있는 최대 질문 횟수. 시스템 프롬프트 규칙과 같다.
GOAL_RUN_LIMIT = 3

QUESTION_TYPE_LABELS = {
    "clarification": "명료화",
    "assumptions": "가정 탐색",
    "reasons_evidence": "이유와 증거 탐색",
    "implications_consequences": "함의와 결과 탐색",
    "alternative_perspectives": "대안적 관점 탐색",
}

# Agent가 id 대신 한글 이름이나 비슷한 말로 적어도 받아 준다.
_TYPE_ALIASES = {
    "명료화": "clarification",
    "명료화 질문": "clarification",
    "가정 탐색": "assumptions",
    "가정탐색": "assumptions",
    "이유와 증거 탐색": "reasons_evidence",
    "이유와증거탐색": "reasons_evidence",
    "이유와 증거": "reasons_evidence",
    "함의와 결과 탐색": "implications_consequences",
    "함의와결과탐색": "implications_consequences",
    "함의와 결과": "implications_consequences",
    "대안적 관점 탐색": "alternative_perspectives",
    "대안적관점탐색": "alternative_perspectives",
    "대안적 관점": "alternative_perspectives",
}

_KIND_ALIASES = {
    "질문": "question",
    "question": "question",
    "기록안내": "record_guide",
    "기록 안내": "record_guide",
    "record_guide": "record_guide",
    "기타": "other",
    "other": "other",
}

_ACHIEVED_ALIASES = {
    "예": "yes",
    "달성": "yes",
    "yes": "yes",
    "부분": "partial",
    "부분달성": "partial",
    "partial": "partial",
    "아니오": "no",
    "아니요": "no",
    "미달성": "no",
    "no": "no",
    "해당없음": "na",
    "해당 없음": "na",
    "없음": "na",
    "na": "na",
}

ACHIEVED_LABELS = {"yes": "예", "partial": "부분", "no": "아니오", "na": "해당없음"}
KIND_LABELS = {"question": "질문", "record_guide": "기록 안내", "other": "기타"}

# 학생 화면에 태그가 남지 않도록, 형식이 조금 틀려도 지운다.
_TAG_RE = re.compile(r"\[\s*질문\s*기록\s*[:：]?([^\]]*)\]")


def strip_question_tag(text: str) -> str:
    """응답에서 질문 기록 태그를 모두 지운다."""
    cleaned = _TAG_RE.sub("", str(text or ""))
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _split_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in re.split(r"[;；]", body):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = re.sub(r"\s+", "", key)
        if key:
            fields[key] = value.strip()
    return fields


def tag_from_values(
    kind: Any = "",
    question_type: Any = "",
    goal: Any = "",
    same_goal: Any = "",
    previous_achieved: Any = "",
) -> dict[str, Any]:
    """Flow 호출 값이나 응답 끝 태그의 값을 같은 규칙으로 정리한다.

    반환값 키: kind, question_type, goal, same_goal, previous_achieved, valid.
    valid가 False이면 응답 종류를 알 수 없다.
    """
    kind_raw = str(kind or "").strip().lower()
    kind_norm = _KIND_ALIASES.get(kind_raw) or _KIND_ALIASES.get(re.sub(r"\s+", "", kind_raw))
    raw_type = str(question_type or "").strip()
    qtype = None
    if raw_type:
        key = raw_type.lower().replace(" ", "_")
        if key in QUESTION_TYPE_LABELS:
            qtype = key
        else:
            qtype = _TYPE_ALIASES.get(raw_type) or _TYPE_ALIASES.get(raw_type.replace(" ", ""))
    goal_text = re.sub(r"\s+", " ", str(goal or "")).strip()[:120] or None
    same_raw = re.sub(r"\s+", "", str(same_goal or "")).lower()
    same: Optional[bool] = None
    if same_raw in ("예", "yes", "true", "y"):
        same = True
    elif same_raw in ("아니오", "아니요", "no", "false", "n"):
        same = False
    achieved_raw = str(previous_achieved or "").strip().lower()
    achieved = _ACHIEVED_ALIASES.get(achieved_raw) or _ACHIEVED_ALIASES.get(achieved_raw.replace(" ", ""))
    return {
        "kind": kind_norm,
        "question_type": qtype,
        "goal": goal_text,
        "same_goal": same,
        "previous_achieved": achieved,
        "valid": kind_norm is not None,
    }


def parse_question_tag(text: str) -> Optional[dict[str, Any]]:
    """응답 끝 [질문기록: ...] 태그를 해석한다(Flow를 쓰지 못했을 때의 보조 수단). 없으면 None. 마지막 태그를 쓴다."""
    matches = _TAG_RE.findall(str(text or ""))
    if not matches:
        return None
    fields = _split_fields(matches[-1])
    return tag_from_values(
        fields.get("응답"), fields.get("유형"), fields.get("목표"), fields.get("같은목표"), fields.get("직전목표달성")
    )


def current_round(records: list[dict[str, Any]], is_review: bool) -> int:
    """이번 요청이 속하는 검토 라운드. 'AI Agent 검토하기'를 새로 누르면 라운드가 하나 늘어난다."""
    latest = max((int(r.get("review_round") or 1) for r in records), default=0)
    if latest == 0:
        return 1
    return latest + 1 if is_review else latest


def next_goal_run(round_records: list[dict[str, Any]], tag: dict[str, Any]) -> int:
    """이 질문이 같은 목표로 몇 번째인지. 새 목표이거나 이어 갈 직전 질문이 없으면 1."""
    last_question = next((r for r in reversed(round_records) if r.get("response_kind") == "question"), None)
    if tag.get("same_goal") and last_question:
        return int(last_question.get("goal_run") or 1) + 1
    return 1


def _type_label(code: Optional[str]) -> str:
    return QUESTION_TYPE_LABELS.get(code or "", "유형 미기록")


def history_block(records: list[dict[str, Any]], is_review: bool) -> str:
    """[현재 문장 질문 이력]. 현재 검토 문장이 있을 때만 붙인다."""
    round_no = current_round(records, is_review)
    prior_rounds = [r for r in records if int(r.get("review_round") or 1) < round_no]
    this_round = [r for r in records if int(r.get("review_round") or 1) == round_no]
    questions = [r for r in this_round if r.get("response_kind") == "question"]
    last_question = questions[-1] if questions else None
    run = int(last_question.get("goal_run") or 1) if last_question else 0

    lines = ["[현재 문장 질문 이력]"]
    lines.append("서버가 저장한 기록이다. 질문 횟수와 유형을 직접 세지 말고 이 기록을 그대로 따른다.")
    lines.append(f"검토 라운드: {round_no}회째" + (" (이번 요청이 새 검토 요청이므로 같은 목표 횟수는 0에서 시작한다)" if is_review and records else ""))
    if prior_rounds:
        prior_q = sum(1 for r in prior_rounds if r.get("response_kind") == "question")
        lines.append(f"이전 라운드: {prior_q}회 질문")
    if not this_round:
        lines.append("이번 라운드 질문 이력: 아직 없다.")
    else:
        lines.append("이번 라운드 이력(오래된 순):")
        for i, r in enumerate(this_round, 1):
            if r.get("response_kind") == "question":
                achieved = ACHIEVED_LABELS.get(r.get("goal_achieved") or "", "미평가")
                lines.append(
                    f"{i}. 질문 / 유형={_type_label(r.get('question_type'))} / 목표={r.get('goal') or '미기록'}"
                    f" / 같은 목표 {int(r.get('goal_run') or 1)}회째 / 목표 달성={achieved}"
                )
            else:
                lines.append(f"{i}. {KIND_LABELS.get(r.get('response_kind'), '기타')}")
        counts: dict[str, int] = {}
        for r in questions:
            label = _type_label(r.get("question_type"))
            counts[label] = counts.get(label, 0) + 1
        if counts:
            lines.append("사용한 유형: " + ", ".join(f"{label} {n}회" for label, n in counts.items()))
        if last_question:
            lines.append(
                f"현재 같은 목표 연속 질문 횟수: {run}회 (목표: {last_question.get('goal') or '미기록'})"
            )

    if run >= GOAL_RUN_LIMIT:
        lines.append(
            f"지시: 같은 목표 질문이 상한({GOAL_RUN_LIMIT}회)에 도달했다. 이번 응답에서는 같은 목표의 새 질문을 하지 않는다. "
            "학생이 지금까지 관찰한 내용을 하단 관찰 기록란에 직접 작성·수정하도록 안내하고, 필요하면 관찰할 범위를 좁혀 제안한다. "
            "문장은 대신 써 주지 않는다. 학생이 전혀 다른 관찰 목표를 새로 묻는 경우에만 새 목표로 시작한다."
        )
    elif run == GOAL_RUN_LIMIT - 1:
        lines.append(
            f"지시: 같은 목표 질문이 {run}회 진행되었다. 이번 질문이 같은 목표의 마지막({GOAL_RUN_LIMIT}번째)이다. "
            "목표가 달성되지 않아도 이후에는 같은 목표의 질문을 반복하지 않는다."
        )
    return "\n".join(lines) + "\n\n"
