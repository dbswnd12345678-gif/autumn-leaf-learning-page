"""
3모드 개편용 진단 로직.

하는 일:
  - knowledge/*.json(코드북, 지원 규칙표)을 읽는다.
  - 탭 1(관찰력): Agent가 문장을 정보 단위로 분류하면, 서버가 객관도 합, 다양도 D, 지수 OQ_A를 계산한다.
  - 탭 2(오프로딩): 학생 요청 유형, AI 답변이 제출 문장에 반영된 정도로 단계(1~4)를 계산한다.
  - 탭 3(지원): 사용한 관찰 유형과 오프로딩 단계를 각각 본다.
  - LLM 판정용 프롬프트를 만들고, 돌아온 JSON을 안전하게 읽는다.

관찰 문장의 분류는 Agent만 한다. Agent 기록이 오기 전에는 문장 원문만 두고, 단어 규칙으로 유형이나 객관도를 채우지 않는다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
# 관찰 기준은 v5만 읽는다. observation_rubric.json(1.0)은 사용하지 않는다.
OBSERVATION_RUBRIC = "observation_rubric_v5.draft"

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
        image_right = None
        if isinstance(item, str):
            text, t = item, None
        elif isinstance(item, dict):
            text, t = item.get("text", ""), item.get("t")
            image = item.get("image")
            image_right = item.get("imageRight")
        else:
            continue
        text = str(text or "").strip()
        if not text:
            continue
        right = image_right if isinstance(image_right, str) else None
        left = image if isinstance(image, str) else None
        if right and right == left:
            right = None
        result.append(
            {
                "text": text[:500],
                "t": t if isinstance(t, (int, float)) else None,
                "image": left,
                "imageRight": right,
            }
        )
    return result[:60]


def images_used(sentences: list[dict[str, Any]]) -> list[str]:
    """문장에 적힌 사진 파일 이름을 처음 나온 순서대로, 중복 없이 돌려준다."""
    seen: list[str] = []
    for s in sentences:
        for key in ("image", "imageRight"):
            name = s.get(key)
            if name and name not in seen:
                seen.append(name)
    return seen


def photo_number(image: Optional[str], ordered_images: list[str]) -> Optional[int]:
    """화면 썸네일 순서의 사진 번호. 맨 왼쪽이 1이다."""
    if image and image in ordered_images:
        return ordered_images.index(image) + 1
    return None


# 문장마다 적는 사진 일치. partly는 예전 제출 전체 값이라 문장 값으로는 받지 않고 알 수 없음으로 본다.
_SENTENCE_PHOTO_MATCH = {
    "match": "match",
    "일치": "match",
    "mismatch": "mismatch",
    "불일치": "mismatch",
    "unknown": "unknown",
    "알수없음": "unknown",
    "partly": "unknown",
}


def sentence_photo_match(token: str) -> Optional[str]:
    """문장 하나의 사진 일치 표기를 match, mismatch, unknown 중 하나로 읽는다."""
    key = re.sub(r"\s+", "", token or "").lower()
    return _SENTENCE_PHOTO_MATCH.get(key)


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


# ---------------------------------------------------------------------------
# 탭 1: 관찰력 진단 (관찰의 수준 LE, 객관도 DO, 다양도 D, 관찰력 지수 OQ_A)
#
# 문장(채팅 메시지 한 번) -> 정보 단위로 나눔 -> 단위마다 객관도(0~3)와 측정/비교/범위 분류,
# 범위 밖(시각 이외 감각, 시간 흐름) 표시 -> 서버가 지수를 계산한다.
# 분류는 Agent가 기록 Flow로 보내 준다. 서버는 그 분류로만 칸을 채우고 지수를 계산한다.
# ---------------------------------------------------------------------------

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
    return [t["id"] for t in load_knowledge(OBSERVATION_RUBRIC)["diversity"]["types"]]


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
    """기록 Flow의 messages 문자열을 {문장번호: {le, units, photoMatch}}로 바꾼다.

    현재 형식: "1:2:match:2-정성-단수-부분;2:1:mismatch:0;3:1:unknown:3-정량-단수-전체"
    이전 형식: "1:2:2-정성-단수-부분,2-정성-단수-부분;2:1:3-정량-단수-전체"
    일치값이 없는 이전 형식은 photoMatch가 None이다.
    따옴표나 줄바꿈이 섞여도 읽을 수 있게 느슨하게 처리한다.
    """
    text = str(raw or "").replace("；", ";").replace("：", ":").replace("，", ",")
    result: dict[int, dict[str, Any]] = {}
    for chunk in re.split(r"[;\n]+", text):
        chunk = chunk.strip().strip("\"'` ")
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) < 2:
            continue
        digits = re.sub(r"\D", "", parts[0])
        if not digits:
            continue
        index = int(digits)
        photo: Optional[str] = None
        if len(parts) >= 4 and sentence_photo_match(parts[2]):
            le_digits = re.sub(r"\D", "", parts[1])
            photo = sentence_photo_match(parts[2])
            units_raw = ":".join(parts[3:])
        elif len(parts) == 3 and sentence_photo_match(parts[2]):
            le_digits = re.sub(r"\D", "", parts[1])
            photo = sentence_photo_match(parts[2])
            units_raw = "0" if photo == "mismatch" else ""
        elif len(parts) >= 3:
            le_digits = re.sub(r"\D", "", parts[1])
            units_raw = ":".join(parts[2:])
        else:
            le_digits = ""
            units_raw = parts[1]
        le = int(le_digits) if le_digits else 1
        le = le if 1 <= le <= 10 else 1
        units = [u for u in (parse_unit(x) for x in units_raw.split(",")) if u]
        result[index] = {"le": le, "units": units, "photoMatch": photo}
    return result


def compute_observation_index(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """분류가 끝난 문장 목록으로 객관도 합, 다양도 D, OQ_A를 계산한다.

    messages의 각 원소는 {le, units, ...}이다. 계산 결과를 담은 새 목록과 요약을 돌려준다.
    범위 밖(outOfScope)으로 표시된 단위와 객관도 0인 단위는 합계와 D에서 뺀다.
    """
    computed: list[dict[str, Any]] = []
    types_used: set[str] = set()
    total = 0
    flag_counts: dict[str, int] = {}
    quantitative_messages = 0
    for m in messages:
        row = dict(m)
        if m.get("source") != "agent":
            row.update({"sumDO": None, "contribution": None, "outOfScope": []})
            computed.append(row)
            continue
        units = m.get("units") or []
        in_scope = [u for u in units if not u.get("outOfScope")]
        sum_do = sum(int(u.get("do") or 0) for u in in_scope)
        le = m.get("le") if isinstance(m.get("le"), int) else None
        contribution = (le * sum_do) if le is not None else 0
        total += contribution
        for u in in_scope:
            if (u.get("do") or 0) > 0:
                types_used.add(type_id(u["measurement"], u["comparison"], u["scope"]))
        flags = sorted({u["outOfScope"] for u in units if u.get("outOfScope")})
        for f in flags:
            flag_counts[f] = flag_counts.get(f, 0) + 1
        if any(u.get("measurement") == "quantitative" for u in in_scope if (u.get("do") or 0) > 0):
            quantitative_messages += 1
        row.update({"le": le, "sumDO": sum_do, "contribution": contribution, "outOfScope": flags})
        computed.append(row)

    d = len(types_used)
    oq = total * d
    ordered = [t for t in all_type_ids() if t in types_used]
    return {
        "messages": computed,
        "contributionSum": total,
        "D": d,
        "typesUsed": ordered,
        "typesMissing": [t for t in all_type_ids() if t not in types_used],
        "oqA": oq,
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
        "rubricVersion": load_knowledge(OBSERVATION_RUBRIC).get("version"),
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


def unclassified_observation(
    sentences: list[dict[str, Any]], ordered_images: Optional[list[str]] = None
) -> dict[str, Any]:
    """제출 직후 기록. 문장 원문만 남기고 유형, 객관도, 수준은 비워 둔다."""
    ordered = ordered_images or []
    messages = [
        {
            "text": s["text"],
            "t": s.get("t"),
            "image": s.get("image"),
            "imageRight": s.get("imageRight"),
            "photoNumber": photo_number(s.get("image"), ordered),
            "photoNumberRight": photo_number(s.get("imageRight"), ordered),
            "photoMatch": None,
            "le": None,
            "units": [],
            "source": "pending",
            "sumDO": None,
            "contribution": None,
            "outOfScope": [],
        }
        for s in sentences
    ]
    return {
        "method": "unclassified",
        "rubricVersion": load_knowledge(OBSERVATION_RUBRIC).get("version"),
        "sentenceCount": len(messages),
        "messages": messages,
        "typesUsed": [],
        "typesMissing": all_type_ids(),
        "D": None,
        "oqA": None,
        "varietyCount": None,
        "quantitySentenceCount": None,
        "score": None,
        "contributionSum": None,
        "judge": None,
        "outOfScopeCounts": {},
        "outOfScopeMessageCount": 0,
        "quantitativeMessageCount": None,
    }


def apply_agent_observation(
    stored: dict[str, Any],
    agent_messages: dict[int, dict[str, Any]],
    photo_match: str,
) -> dict[str, Any]:
    """Agent가 기록한 분류를 제출 문장에 입히고 지수를 다시 계산한다.

    Agent가 빼먹은 문장은 분류 전으로 남긴다. 유형이나 객관도를 단어로 채우지 않는다.
    모든 문장이 분류되기 전에는 수준과 OQ_A를 확정하지 않는다.
    """
    messages = [dict(m) for m in stored.get("messages", [])]
    for i, m in enumerate(messages, start=1):
        rec = agent_messages.get(i)
        if rec is None:
            continue
        units = rec["units"]
        sentence_match = rec.get("photoMatch")
        # 사진과 다른 문장은 분류 내용과 관계없이 관찰이 아닌 것으로 남긴다.
        if sentence_match == "mismatch":
            units = [make_unit(0)]
        m["le"] = rec["le"]
        m["units"] = units
        m["photoMatch"] = sentence_match
        m["source"] = "agent"
    # 기록을 두 번에 나누어 보내도 합쳐서 센다.
    covered = sum(1 for m in messages if m.get("source") == "agent")
    ignored = sorted(i for i in agent_messages if i < 1 or i > len(messages))

    if not messages or covered == 0:
        method = "unclassified"
    elif covered == len(messages):
        method = "agent"
    else:
        method = "partial"

    overall, rate, counts, by_image = _photo_match_summary(messages, photo_match)
    judge = {
        "recordedBy": "agent",
        "photoMatch": overall,
        "photoMatchRate": rate,
        "photoMatchCounts": counts,
        "photoMatchByImage": by_image,
        "agentMessageCount": covered,
        "ignoredIndexes": ignored,
    }
    payload = _observation_payload(
        messages,
        method,
        {
            "judge": judge,
            **{k: stored[k] for k in ("sentencesTruncated",) if k in stored},
        },
    )
    if method != "agent":
        payload["oqA"] = None
        payload["score"] = None
    return payload


def _photo_match_summary(
    messages: list[dict[str, Any]], fallback: str
) -> tuple[str, Optional[float], dict[str, int], dict[str, dict[str, Any]]]:
    """문장별 사진 일치를 모아 전체 값, 일치율, 개수, 사진별 개수를 만든다.

    알 수 없음은 일치율에서 빼며, 그 문장의 관찰 분류는 유지된 상태이다.
    문장별 값이 하나도 없으면 제출 전체에 대해 넘어온 이전 값을 쓴다.
    """
    counts = {"match": 0, "mismatch": 0, "unknown": 0}
    by_image: dict[str, dict[str, Any]] = {}
    for m in messages:
        token = m.get("photoMatch")
        if token not in counts:
            continue
        counts[token] += 1
        name = m.get("image") or ""
        bucket = by_image.setdefault(
            name,
            {
                "photoNumber": m.get("photoNumber"),
                "match": 0,
                "mismatch": 0,
                "unknown": 0,
            },
        )
        bucket[token] += 1
    if not any(counts.values()):
        overall = fallback if fallback in ("match", "partly", "mismatch", "unknown") else "unknown"
        rate = {"match": 1.0, "partly": 0.5, "mismatch": 0.0}.get(overall)
        return overall, rate, counts, by_image
    if counts["match"] and counts["mismatch"]:
        overall = "partly"
    elif counts["mismatch"]:
        overall = "mismatch"
    elif counts["match"]:
        overall = "match"
    else:
        overall = "unknown"
    decided = counts["match"] + counts["mismatch"]
    rate = (counts["match"] / decided) if decided else None
    return overall, rate, counts, by_image


def apply_legacy_level(stored: dict[str, Any], _level: int, photo_match: str) -> dict[str, Any]:
    """이전 형식(level만 기록)을 받았을 때의 처리. 학생 수준 1~3은 저장하지 않는다."""
    result = dict(stored)
    result.pop("level", None)
    result.pop("levelLabel", None)
    result.pop("finalLevelSource", None)
    result["judge"] = {
        "recordedBy": "agent",
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

def observation_support_state(assess_payload: Optional[dict[str, Any]]) -> dict[str, Any]:
    """탭 1 진단에서 이번 답의 관찰 쪽 제안만 고른다. 오프로딩 단계와 합치지 않는다."""
    support = load_knowledge("support_methods")["observationSupport"]
    payload = assess_payload or {}
    classified = payload.get("method") in ("agent", "partial")
    used = list(payload.get("typesUsed") or []) if classified else []
    missing = [t for t in support["suggestionOrder"] if classified and t not in used]
    next_type = missing[0] if missing else None
    if not classified:
        rule_id = "not_classified"
    elif next_type:
        rule_id = "missing_type"
    else:
        rule_id = "all_tried"
    rule = next(r for r in support["rules"] if r["id"] == rule_id)
    question = None
    if next_type:
        question = next(
            (t.get("question") for t in load_knowledge("observation_types")["types"] if t["id"] == next_type),
            None,
        )
    return {
        "classified": classified,
        "typesUsed": used,
        "typesMissing": missing,
        "nextType": next_type,
        "question": question,
        "rule": rule,
    }


def offloading_support(stage: Optional[int]) -> Optional[dict[str, Any]]:
    """오프로딩 단계의 말하는 방식만 돌려준다. 단계가 없으면 None."""
    if stage not in (1, 2, 3, 4):
        return None
    return next(
        (s for s in load_knowledge("support_methods")["byOffloadingStage"] if s["stage"] == stage),
        None,
    )


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


def build_observation_agent_message(
    student_id: str,
    sentences: list[dict[str, Any]],
    ordered_images: Optional[list[str]] = None,
    attached_images: Optional[list[str]] = None,
) -> str:
    """관찰력 진단 워크스페이스의 Agent에게 보내는 메시지. 절차는 시스템 프롬프트에 있다.

    [사진N]의 N은 화면 썸네일 번호와 같다. ordered_images가 그 순서이다.
    attached_images는 실제로 첨부한 파일이며, 안내 문장에서 몇 번째 첨부인지 알려 준다.
    """
    catalog = list(ordered_images or [])
    attached = list(catalog if attached_images is None else attached_images)

    def label(s: dict[str, Any]) -> str:
        left = photo_number(s.get("image"), catalog)
        right = photo_number(s.get("imageRight"), catalog)
        if left and right:
            return f"[왼쪽 사진{left}, 오른쪽 사진{right}] "
        return f"[사진{left}] " if left else ""

    numbered = (
        "\n".join(f"{i + 1}. {label(s)}{s['text']}" for i, s in enumerate(sentences))
        or "(제출 문장 없음)"
    )
    pairs = [
        f"사진 {catalog.index(name) + 1}=첨부 {i}"
        for i, name in enumerate(attached, start=1)
        if name in catalog
    ]
    pair_note = ""
    if any(s.get("imageRight") for s in sentences):
        pair_note = (
            " 왼쪽 사진과 오른쪽 사진이 함께 적힌 문장은 그 두 장을 나란히 본 관찰입니다. "
            "1번째와 첫번째는 왼쪽 사진, 2번째와 두번째는 오른쪽 사진입니다."
        )
    photo_note = (
        "\n\n[사진 안내] 문장의 사진 번호는 화면 썸네일 번호와 같습니다. "
        f"첨부 대응: {', '.join(pairs)}. 그 번호의 사진과 그 문장을 비교하세요."
        f"{pair_note}"
        if pairs
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