"""
3모드 개편용 진단 로직.

하는 일:
  - knowledge/*.json(코드북, 지원 규칙표)을 읽는다.
  - 탭 1(관찰력): 문장을 정보 단위로 나눠 객관도(0~3), 측정/비교/범위, 범위 밖 표시를 정하고 LE x ΣDO, 다양도 D, 지수 OQ_A, 수준(1~3)을 계산한다.
  - 탭 2(오프로딩): 학생 요청 유형, AI 답변이 제출 문장에 반영된 정도로 단계(1~4)를 계산한다.
  - 탭 3(지원): 관찰력 수준 x 오프로딩 단계로 지원 수준(1~3)을 정한다.
  - LLM 판정용 프롬프트를 만들고, 돌아온 JSON을 안전하게 읽는다.

키워드 채점은 항상 계산해 두는 기본값이다. LLM(Agent) 판정이 성공하면 그 값을 우선하되,
키워드 결과도 함께 저장해 연구자가 비교할 수 있게 한다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

_cache: dict[str, Any] = {}


def load_knowledge(name: str) -> dict[str, Any]:
    """knowledge/<name>.json을 읽는다. 연구자가 파일을 고치면 서버 재시작 때 반영된다."""
    if name not in _cache:
        with open(KNOWLEDGE_DIR / f"{name}.json", encoding="utf-8") as f:
            _cache[name] = json.load(f)
    return _cache[name]


def reload_knowledge() -> None:
    _cache.clear()


# ---------------------------------------------------------------------------
# 입력 정리
# ---------------------------------------------------------------------------

def normalize_sentences(raw: list[Any]) -> list[dict[str, Any]]:
    """제출된 문장 목록을 [{text, t, image}] 형태로 맞춘다.

    t는 시작 후 경과 초(없으면 None), image는 학생이 그 문장을 쓸 때 보던 사진 파일 이름(없으면 None).
    image가 이 탭의 사진인지는 호출하는 쪽(app.py)에서 확인한다.
    """
    result: list[dict[str, Any]] = []
    for item in raw or []:
        image = None
        if isinstance(item, str):
            text, t = item, None
        elif isinstance(item, dict):
            text, t = item.get("text", ""), item.get("t")
            image = item.get("image")
        else:
            continue
        text = str(text or "").strip()
        if not text:
            continue
        result.append(
            {
                "text": text[:500],
                "t": t if isinstance(t, (int, float)) else None,
                "image": image if isinstance(image, str) else None,
            }
        )
    return result[:60]


def images_used(sentences: list[dict[str, Any]]) -> list[str]:
    """문장에 적힌 사진 파일 이름을 처음 나온 순서대로, 중복 없이 돌려준다."""
    seen: list[str] = []
    for s in sentences:
        name = s.get("image")
        if name and name not in seen:
            seen.append(name)
    return seen


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


# ---------------------------------------------------------------------------
# 탭 1: 관찰력 진단 (관찰의 수준 LE, 객관도 DO, 다양도 D, 관찰력 지수 OQ_A)
#
# 문장(채팅 메시지 한 번) -> 정보 단위로 나눔 -> 단위마다 객관도(0~3)와 측정/비교/범위 분류,
# 범위 밖(시각 이외 감각, 시간 흐름) 표시 -> 서버가 지수를 계산한다.
# 분류는 Agent가 기록 Flow로 보내 주고, 기록이 없으면 아래 키워드 규칙으로 대신한다.
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d+(\.\d+)?|[한두세네다섯여섯일곱여덟아홉열]\s*(개|갈래|장|줄|쌍|배)")
_CLAUSE_SPLIT = re.compile(r"[.!?,;\n]+|\s+(?:그리고|그런데|하지만|그러나)\s+")

MEASUREMENT_KO = {"qualitative": "정성", "quantitative": "정량"}
COMPARISON_KO = {"single": "단수", "multiple": "다수"}
SCOPE_KO = {"whole": "전체", "part": "부분"}

# Agent가 쓴 표기 -> (차원, 값). 영어 표기도 받는다.
_UNIT_TOKENS: dict[str, tuple[str, str]] = {
    "정성": ("measurement", "qualitative"), "qual": ("measurement", "qualitative"),
    "qualitative": ("measurement", "qualitative"),
    "정량": ("measurement", "quantitative"), "quant": ("measurement", "quantitative"),
    "quantitative": ("measurement", "quantitative"),
    "단수": ("comparison", "single"), "single": ("comparison", "single"),
    "다수": ("comparison", "multiple"), "multi": ("comparison", "multiple"),
    "multiple": ("comparison", "multiple"),
    "전체": ("scope", "whole"), "whole": ("scope", "whole"),
    "부분": ("scope", "part"), "part": ("scope", "part"),
}


def type_id(measurement: str, comparison: str, scope: str) -> str:
    """관찰 유형 id. 예: 정성-단수-부분"""
    return f"{MEASUREMENT_KO[measurement]}-{COMPARISON_KO[comparison]}-{SCOPE_KO[scope]}"


def all_type_ids() -> list[str]:
    return [t["id"] for t in load_knowledge("observation_rubric")["diversity"]["types"]]


def make_unit(
    do: int,
    measurement: Optional[str] = None,
    comparison: Optional[str] = None,
    scope: Optional[str] = None,
    out_of_scope: Optional[str] = None,
) -> dict[str, Any]:
    if out_of_scope:
        return {"do": 0, "measurement": None, "comparison": None, "scope": None, "outOfScope": out_of_scope}
    if do <= 0:
        return {"do": 0, "measurement": None, "comparison": None, "scope": None, "outOfScope": None}
    do = min(do, 3)
    # 객관도 3점은 정량 관찰 사실이다.
    measurement = "quantitative" if do == 3 else (measurement or "qualitative")
    return {
        "do": do,
        "measurement": measurement,
        "comparison": comparison or "single",
        "scope": scope or "whole",
        "outOfScope": None,
    }


def parse_unit(token: str) -> Optional[dict[str, Any]]:
    """Agent가 쓴 정보 단위 하나('2-정성-단수-부분', '0', 'OOS-감각')를 읽는다. 읽을 수 없으면 None."""
    text = re.sub(r"[–—－]", "-", token or "").strip()
    parts = [p.strip() for p in text.split("-") if p.strip()]
    if not parts:
        return None
    head = parts[0].upper()
    if head == "OOS":
        word = (parts[1] if len(parts) > 1 else "").lower()
        flag = "timeFlow" if word in ("시간", "time", "timeflow") else "nonVisualSense"
        return make_unit(0, out_of_scope=flag)
    if not head.isdigit():
        return None
    do = int(head)
    if do > 3:
        return None
    chosen: dict[str, str] = {}
    for p in parts[1:]:
        hit = _UNIT_TOKENS.get(p.lower())
        if hit:
            chosen[hit[0]] = hit[1]
    return make_unit(do, chosen.get("measurement"), chosen.get("comparison"), chosen.get("scope"))


def parse_agent_messages(raw: Any) -> dict[int, dict[str, Any]]:
    """기록 Flow의 messages 문자열을 {문장번호: {le, units}}로 바꾼다.

    형식: "1:2:2-정성-단수-부분,2-정성-단수-부분;2:1:3-정량-단수-전체;3:1:OOS-감각;4:1:0"
    따옴표나 줄바꿈이 섞여도 읽을 수 있게 느슨하게 처리한다.
    """
    text = str(raw or "").replace("；", ";").replace("：", ":").replace("，", ",")
    result: dict[int, dict[str, Any]] = {}
    for chunk in re.split(r"[;\n]+", text):
        chunk = chunk.strip().strip("\"'` ")
        if not chunk:
            continue
        parts = chunk.split(":", 2)
        if len(parts) < 2:
            continue
        digits = re.sub(r"\D", "", parts[0])
        if not digits:
            continue
        index = int(digits)
        if len(parts) == 3:
            le_digits = re.sub(r"\D", "", parts[1])
            units_raw = parts[2]
        else:
            le_digits = ""
            units_raw = parts[1]
        le = int(le_digits) if le_digits else 1
        le = le if 1 <= le <= 10 else 1
        units = [u for u in (parse_unit(x) for x in units_raw.split(",")) if u]
        result[index] = {"le": le, "units": units}
    return result


def _has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def classify_clause_keyword(clause: str, rubric: dict[str, Any]) -> Optional[dict[str, Any]]:
    """절 하나를 키워드로 분류해 정보 단위 하나로 만든다. 판단할 거리가 없으면 None."""
    cfg = rubric["keywordFallback"]
    if len(clause.strip()) < cfg["minClauseChars"]:
        return None
    for flag in rubric["outOfScope"]["flags"]:
        if _has_any(clause, flag["cueWords"]):
            return make_unit(0, out_of_scope=flag["id"])
    if _has_any(clause, cfg["inferenceCues"]):
        return make_unit(0)

    quantitative = bool(_NUMBER.search(clause)) or _has_any(clause, cfg["quantityWords"])
    specific = _has_any(clause, cfg["specificWords"])
    vague = _has_any(clause, cfg["vagueWords"])
    if quantitative and (specific or vague or "잎" in clause or "갈래" in clause):
        do = 3
    elif specific:
        do = 2
    elif vague:
        do = 1
    else:
        do = 0
    comparison = "multiple" if _has_any(clause, cfg["comparisonCues"]) else "single"
    scope = "part" if _has_any(clause, cfg["partWords"]) else "whole"
    return make_unit(do, "quantitative" if quantitative else "qualitative", comparison, scope)


def classify_message_keyword(text: str, rubric: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """문장(메시지) 하나를 키워드로 분류한다. LE는 판단하지 못해 1로 둔다."""
    rubric = rubric or load_knowledge("observation_rubric")
    units = []
    for clause in _CLAUSE_SPLIT.split(text or ""):
        unit = classify_clause_keyword(clause, rubric)
        if unit:
            units.append(unit)
    if not units:
        units = [make_unit(0)]
    return {"le": 1, "units": units}


def level_from_oq(oq: float) -> dict[str, Any]:
    rows = load_knowledge("observation_rubric")["levelThresholds"]["levels"]
    chosen = rows[0]
    for row in rows:
        if oq >= row["minOQ"]:
            chosen = row
    return chosen


def compute_observation_index(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """분류가 끝난 문장 목록으로 객관도 합, 다양도 D, OQ_A, 수준을 계산한다.

    messages의 각 원소는 {le, units, ...}이다. 계산 결과를 담은 새 목록과 요약을 돌려준다.
    범위 밖(outOfScope)으로 표시된 단위와 객관도 0인 단위는 합계와 D에서 뺀다.
    """
    computed: list[dict[str, Any]] = []
    types_used: set[str] = set()
    total = 0
    flag_counts: dict[str, int] = {}
    quantitative_messages = 0
    for m in messages:
        units = m.get("units") or []
        in_scope = [u for u in units if not u.get("outOfScope")]
        sum_do = sum(int(u.get("do") or 0) for u in in_scope)
        le = int(m.get("le") or 1)
        contribution = le * sum_do
        total += contribution
        for u in in_scope:
            if (u.get("do") or 0) > 0:
                types_used.add(type_id(u["measurement"], u["comparison"], u["scope"]))
        flags = sorted({u["outOfScope"] for u in units if u.get("outOfScope")})
        for f in flags:
            flag_counts[f] = flag_counts.get(f, 0) + 1
        if any(u.get("measurement") == "quantitative" for u in in_scope if (u.get("do") or 0) > 0):
            quantitative_messages += 1
        row = dict(m)
        row.update({"le": le, "sumDO": sum_do, "contribution": contribution, "outOfScope": flags})
        computed.append(row)

    d = len(types_used)
    oq = total * d
    level_row = level_from_oq(oq)
    ordered = [t for t in all_type_ids() if t in types_used]
    return {
        "messages": computed,
        "contributionSum": total,
        "D": d,
        "typesUsed": ordered,
        "typesMissing": [t for t in all_type_ids() if t not in types_used],
        "oqA": oq,
        "level": level_row["level"],
        "levelLabel": level_row["label"],
        "outOfScopeCounts": flag_counts,
        "outOfScopeMessageCount": sum(1 for m in computed if m["outOfScope"]),
        "quantitativeMessageCount": quantitative_messages,
    }


def _observation_payload(
    base_messages: list[dict[str, Any]], method: str, extra: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    summary = compute_observation_index(base_messages)
    payload = {
        "method": method,
        "rubricVersion": load_knowledge("observation_rubric").get("version"),
        "sentenceCount": len(base_messages),
        # 아래 세 값은 이전 형식과 같은 이름을 유지한다(엑셀, 탭 3 조회에서 사용).
        "varietyCount": summary["D"],
        "quantitySentenceCount": summary["quantitativeMessageCount"],
        "score": summary["oqA"],
    }
    payload.update(summary)
    if extra:
        payload.update(extra)
    return payload


def score_observation(sentences: list[dict[str, Any]]) -> dict[str, Any]:
    """탭 1 키워드 대체 채점. 제출 직후 먼저 저장하고, Agent 기록이 오면 덮어쓴다."""
    rubric = load_knowledge("observation_rubric")
    base = []
    for s in sentences:
        cls = classify_message_keyword(s["text"], rubric)
        base.append(
            {
                "text": s["text"],
                "t": s.get("t"),
                "image": s.get("image"),
                "le": cls["le"],
                "units": cls["units"],
                "source": "keyword",
            }
        )
    return _observation_payload(base, "keyword", {"finalLevelSource": "keyword", "judge": None})


def apply_agent_observation(
    stored: dict[str, Any],
    agent_messages: dict[int, dict[str, Any]],
    photo_match: str,
    rationale: str,
) -> dict[str, Any]:
    """Agent가 기록한 분류를 제출 문장에 입히고 지수를 다시 계산한다.

    Agent가 빼먹은 문장은 키워드 분류를 그대로 쓰고, 어느 문장이 그런지 source로 남긴다.
    """
    messages = [dict(m) for m in stored.get("messages", [])]
    for i, m in enumerate(messages, start=1):
        rec = agent_messages.get(i)
        if rec is None:
            continue
        m["le"] = rec["le"]
        m["units"] = rec["units"]
        m["source"] = "agent"
    # 기록을 두 번에 나누어 보내도 합쳐서 센다.
    covered = sum(1 for m in messages if m.get("source") == "agent")
    ignored = sorted(i for i in agent_messages if i < 1 or i > len(messages))

    if not messages or covered == 0:
        method = "keyword"
    elif covered == len(messages):
        method = "agent"
    else:
        method = "mixed"

    rate = {"match": 1.0, "partly": 0.5, "mismatch": 0.0}.get(photo_match)
    keyword_summary = stored.get("keywordBaseline") or {
        "oqA": stored.get("oqA"),
        "D": stored.get("D"),
        "level": stored.get("level"),
    }
    judge = {
        "recordedBy": "agent",
        "rationale": (rationale or "")[:500],
        "photoMatch": photo_match,
        "photoMatchRate": rate,
        "agentMessageCount": covered,
        "ignoredIndexes": ignored,
    }
    return _observation_payload(
        messages,
        method,
        {
            "finalLevelSource": method,
            "judge": judge,
            "keywordBaseline": keyword_summary,
            **{k: stored[k] for k in ("sentencesTruncated",) if k in stored},
        },
    )


def apply_legacy_level(stored: dict[str, Any], level: int, photo_match: str, rationale: str) -> dict[str, Any]:
    """이전 형식(level만 기록)을 받았을 때의 호환 처리. 지수는 키워드 값을 그대로 두고 수준만 바꾼다."""
    result = dict(stored)
    rows = load_knowledge("observation_rubric")["levelThresholds"]["levels"]
    result["keywordBaseline"] = stored.get("keywordBaseline") or {
        "oqA": stored.get("oqA"),
        "D": stored.get("D"),
        "level": stored.get("level"),
    }
    result["level"] = level
    result["levelLabel"] = next((r["label"] for r in rows if r["level"] == level), "")
    result["finalLevelSource"] = "agent_level_only"
    result["judge"] = {
        "recordedBy": "agent",
        "rationale": (rationale or "")[:500],
        "photoMatch": photo_match,
        "photoMatchRate": {"match": 1.0, "partly": 0.5, "mismatch": 0.0}.get(photo_match),
        "legacyLevelOnly": True,
    }
    return result

# ---------------------------------------------------------------------------
# 탭 2: 오프로딩
# ---------------------------------------------------------------------------

def classify_request(text: str, stages: dict[str, Any]) -> str:
    """요청 한 건을 대행/방법/확인/설명/기타(other)로 분류한다. 먼저 맞는 유형을 쓴다."""
    for rtype in stages["requestTypes"]:
        if any(k in text for k in rtype["keywords"]):
            return rtype["id"]
    return "other"


def _containment(sentence: str, reply_bigrams: set[str]) -> float:
    grams = _bigrams(sentence)
    if not grams:
        return 0.0
    return len(grams & reply_bigrams) / len(grams)


def score_offloading(
    turns: list[dict[str, Any]],
    sentences: list[dict[str, Any]],
    session_started_at: Optional[str] = None,
) -> dict[str, Any]:
    """탭 2 키워드 채점. turns는 observations 행(question, answer, timestamp)이다."""
    stages = load_knowledge("offloading_stages")
    reuse_cfg = stages["reuse"]

    type_counts: dict[str, int] = {}
    classified = []
    reply_bigrams: set[str] = set()
    for turn in turns:
        question = turn.get("question") or ""
        answer = turn.get("answer") or ""
        rtype = classify_request(question, stages)
        type_counts[rtype] = type_counts.get(rtype, 0) + 1
        reply_bigrams |= _bigrams(answer)
        classified.append({"question": question, "type": rtype, "timestamp": turn.get("timestamp")})

    request_count = len(turns)
    delegate_share = (type_counts.get("delegate", 0) / request_count) if request_count else 0.0

    copied = 0
    novel = 0
    sentence_overlaps = []
    for s in sentences:
        overlap = _containment(s["text"], reply_bigrams) if reply_bigrams else 0.0
        sentence_overlaps.append({"text": s["text"], "overlap": round(overlap, 2)})
        if overlap >= reuse_cfg["copiedThreshold"]:
            copied += 1
        if overlap < reuse_cfg["novelThreshold"]:
            novel += 1
    total_sentences = len(sentences)
    reuse_ratio = (copied / total_sentences) if total_sentences else 0.0
    novel_ratio = (novel / total_sentences) if total_sentences else 0.0

    if delegate_share >= 0.6 or reuse_ratio >= 0.6:
        stage = 4
    elif delegate_share < 0.25 and reuse_ratio < 0.3:
        stage = 1
    elif delegate_share < 0.25 and reuse_ratio < 0.45:
        stage = 2
    else:
        stage = 3
    label = next(s["label"] for s in stages["stages"] if s["stage"] == stage)

    first_request_seconds = None
    if turns and session_started_at:
        try:
            t0 = datetime.fromisoformat(session_started_at)
            t1 = datetime.fromisoformat(turns[0]["timestamp"])
            first_request_seconds = max(0, int((t1 - t0).total_seconds()))
        except (ValueError, KeyError, TypeError):
            first_request_seconds = None

    return {
        "method": "keyword",
        "requestCount": request_count,
        "requestTypeCounts": type_counts,
        "delegateShare": round(delegate_share, 2),
        "reuseRatio": round(reuse_ratio, 2),
        "novelRatio": round(novel_ratio, 2),
        "firstRequestSeconds": first_request_seconds,
        "submittedSentenceCount": total_sentences,
        "stage": stage,
        "stageLabel": label,
        "requests": classified,
        "sentenceOverlaps": sentence_overlaps,
    }


# ---------------------------------------------------------------------------
# 탭 3: 지원 수준
# ---------------------------------------------------------------------------

def compute_support_level(
    observation_level: Optional[int], offloading_stage: Optional[int]
) -> dict[str, Any]:
    """관찰력 수준 x 오프로딩 단계 → 지원 수준. 진단이 없으면 기본값을 쓴다."""
    methods = load_knowledge("support_methods")
    default = methods["defaultSupportLevel"]
    matrix = methods["supportRules"]["matrix"]
    level = default
    source = "default"
    if observation_level and offloading_stage:
        try:
            level = int(matrix[str(observation_level)][str(offloading_stage)])
            source = "matrix"
        except (KeyError, ValueError, TypeError):
            level = default
    label = next((l["label"] for l in methods["supportLevels"] if l["level"] == level), "")
    return {
        "supportLevel": level,
        "supportLabel": label,
        "source": source,
        "observationLevel": observation_level,
        "offloadingStage": offloading_stage,
    }


def get_support_level_methods(level: int) -> Optional[dict[str, Any]]:
    methods = load_knowledge("support_methods")
    return next((l for l in methods["supportLevels"] if l["level"] == level), None)


def remaining_observation_types(used_types: list[str]) -> list[dict[str, Any]]:
    """학생이 아직 쓰지 않은 관찰 유형(측정 x 비교 x 범위 8가지)을 knowledge/observation_types.json에서 돌려준다."""
    types = load_knowledge("observation_types")["types"]
    used = set(used_types)
    return [t for t in types if t["id"] not in used]


# ---------------------------------------------------------------------------
# LLM 판정
# ---------------------------------------------------------------------------

def extract_json(text: str) -> Optional[dict[str, Any]]:
    """LLM 답변에서 첫 JSON 객체를 꺼낸다. 코드펜스나 앞뒤 설명이 있어도 읽는다."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def build_observation_agent_message(student_id: str, sentences: list[dict[str, Any]]) -> str:
    """관찰력 진단 워크스페이스의 Agent에게 보내는 메시지. 절차는 시스템 프롬프트에 있다."""
    # 사진이 여러 장이면 문장마다 [사진N]을 붙인다. N은 첨부한 사진의 순서(images_used)와 같다.
    used = images_used(sentences)
    multi = len(used) > 1

    def label(s: dict[str, Any]) -> str:
        if multi and s.get("image") in used:
            return f"[사진{used.index(s['image']) + 1}] "
        return ""

    numbered = (
        "\n".join(f"{i + 1}. {label(s)}{s['text']}" for i, s in enumerate(sentences))
        or "(제출 문장 없음)"
    )
    photo_note = (
        f"\n\n[사진 안내] 첨부한 사진은 모두 {len(used)}장이며 [사진1]부터 순서대로입니다. "
        "각 문장은 앞에 적힌 번호의 사진과 비교하세요."
        if multi
        else ""
    )
    count_note = (
        f"\n\n[제출 문장 수] {len(sentences)}개. 번호 1부터 {len(sentences)}까지 모두 기록하세요."
        if sentences
        else ""
    )
    return f"@agent [studentId: {student_id}]\n\n[학생 관찰 문장]\n{numbered}{photo_note}{count_note}"


def build_offloading_judge_prompt(
    turns: list[dict[str, Any]], sentences: list[dict[str, Any]]
) -> str:
    stages = load_knowledge("offloading_stages")
    rtypes = "\n".join(
        f"- {r['id']} ({r['label']}): {r['definition']}" for r in stages["requestTypes"]
    )
    stage_lines = "\n".join(
        f"- {s['stage']} ({s['label']}): {s['meaning']}" for s in stages["stages"]
    )
    log_lines = []
    for i, t in enumerate(turns, start=1):
        log_lines.append(
            f"[요청 {i}] {t.get('question', '')}\n[AI 답변 {i}] {(t.get('answer') or '')[:600]}"
        )
    log = "\n\n".join(log_lines) if log_lines else "(AI 요청 없음)"
    numbered = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(sentences)) or "(제출 문장 없음)"
    return (
        "[task: judge_offloading]\n"
        "당신은 연구용 채점자입니다. 학생에게 말하지 말고 JSON 한 개만 출력하세요. 설명 문장은 쓰지 마세요.\n"
        "학생이 AI를 쓰며 단풍잎 관찰 과제를 수행했습니다. 요청, AI 답변, 최종 제출 문장을 함께 보고 "
        "인지적 오프로딩(관찰을 AI에게 넘긴 정도)을 판정하세요.\n\n"
        f"[요청 유형]\n{rtypes}\n\n[오프로딩 단계]\n{stage_lines}\n\n"
        f"[대화 기록]\n{log}\n\n[최종 제출 문장]\n{numbered}\n\n"
        "[출력 JSON 형식]\n"
        '{"requests":[{"index":1,"type":"delegate"}],'
        '"sentences":[{"index":1,"source":"student|ai_copied|ai_edited"}],'
        '"stage":2,"rationale":"한두 문장으로 근거"}'
    )


def merge_offloading_judge(
    keyword: dict[str, Any], judge: Optional[dict[str, Any]]
) -> dict[str, Any]:
    result = dict(keyword)
    result["judge"] = None
    result["finalStageSource"] = "keyword"
    if not judge:
        return result
    stage = judge.get("stage")
    if isinstance(stage, int) and stage in (1, 2, 3, 4):
        stages = load_knowledge("offloading_stages")
        result["stage"] = stage
        result["stageLabel"] = next(s["label"] for s in stages["stages"] if s["stage"] == stage)
        result["finalStageSource"] = "llm"
    result["judge"] = {
        "stage": stage,
        "rationale": judge.get("rationale"),
        "requests": judge.get("requests"),
        "sentences": judge.get("sentences"),
    }
    return result