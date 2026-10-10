"""
3모드 개편용 진단 로직.

하는 일:
  - knowledge/*.json(코드북, 지원 규칙표)을 읽는다.
  - 탭 1(관찰력): 관찰 문장을 키워드로 범주 분류하고 점수·수준(1~3)을 계산한다.
  - 탭 2(오프로딩): 학생 요청 유형, AI 답변이 제출 문장에 반영된 정도로 단계(1~4)를 계산한다.
  - 탭 3(지원): 관찰력 수준 x 오프로딩 단계로 지원 수준(1~3)을 정한다.
  - LLM 판정용 프롬프트를 만들고, 돌아온 JSON을 안전하게 읽는다.

키워드 채점은 항상 계산해 두는 기본값이다. LLM 판정이 성공하면 수준/단계는
LLM 값을 우선하되, 두 결과를 모두 저장해 연구자가 비교할 수 있게 한다.
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
    """제출된 문장 목록을 [{text, t}] 형태로 맞춘다. t는 시작 후 경과 초(없으면 None)."""
    result: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, str):
            text, t = item, None
        elif isinstance(item, dict):
            text, t = item.get("text", ""), item.get("t")
        else:
            continue
        text = str(text or "").strip()
        if not text:
            continue
        result.append({"text": text[:500], "t": t if isinstance(t, (int, float)) else None})
    return result[:60]


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


# ---------------------------------------------------------------------------
# 탭 1: 관찰력
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d+(\.\d+)?|[한두세네다섯여섯일곱여덟아홉열]\s*(개|갈래|장|줄|쌍)")


def classify_sentence(text: str, rubric: dict[str, Any]) -> list[str]:
    cats: list[str] = []
    for cat in rubric["categories"]:
        if any(k in text for k in cat["keywords"]):
            cats.append(cat["id"])
    # 숫자나 "두 개" 같은 수량 표현이 있으면 수량 범주로 본다.
    if _NUMBER.search(text) and "quantity" not in cats:
        cats.append("quantity")
    return cats


def score_observation(sentences: list[dict[str, Any]]) -> dict[str, Any]:
    """탭 1 키워드 채점. 반환값은 그대로 diagnoses.payload에 들어간다."""
    rubric = load_knowledge("observation_rubric")
    obs_ids = set(rubric["observationCategoryIds"])
    rules = rubric["sentenceRules"]
    weights = rubric["scoreWeights"]

    per_sentence = []
    observation_sentences = 0
    quantity_sentences = 0
    specific_sentences = 0
    inference_sentences = 0
    used_categories: set[str] = set()

    for s in sentences:
        text = s["text"]
        cats = classify_sentence(text, rubric)
        obs_cats = [c for c in cats if c in obs_ids]
        is_inference = "inference" in cats
        is_observation = bool(obs_cats) and len(text) >= rules["minCharsForObservation"]
        if is_inference:
            inference_sentences += 1
        if is_observation:
            observation_sentences += 1
            used_categories.update(obs_cats)
            if "quantity" in obs_cats:
                quantity_sentences += 1
            if len(obs_cats) >= rules["specificMinCategories"] or "quantity" in obs_cats:
                specific_sentences += 1
        per_sentence.append(
            {
                "text": text,
                "t": s.get("t"),
                "categories": cats,
                "isObservation": is_observation,
                "isInference": is_inference,
            }
        )

    total = len(sentences)
    specificity_ratio = (specific_sentences / observation_sentences) if observation_sentences else 0.0
    inference_ratio = (inference_sentences / total) if total else 0.0

    score = (
        min(observation_sentences, weights["countCap"]) / weights["countCap"] * weights["countWeight"]
        + min(len(used_categories), weights["varietyCap"]) / weights["varietyCap"] * weights["varietyWeight"]
        + min(quantity_sentences, weights["quantityCap"]) / weights["quantityCap"] * weights["quantityWeight"]
        + specificity_ratio * weights["specificityWeight"]
        + (1 - inference_ratio) * weights["nonInferenceWeight"] * (1 if total else 0)
    )
    score = round(score, 1)

    level_row = rubric["levels"][0]
    for row in rubric["levels"]:
        if score >= row["minScore"]:
            level_row = row

    return {
        "method": "keyword",
        "sentenceCount": total,
        "observationSentenceCount": observation_sentences,
        "varietyCount": len(used_categories),
        "categoriesUsed": sorted(used_categories),
        "quantitySentenceCount": quantity_sentences,
        "specificSentenceCount": specific_sentences,
        "inferenceSentenceCount": inference_sentences,
        "inferenceRatio": round(inference_ratio, 2),
        "score": score,
        "level": level_row["level"],
        "levelLabel": level_row["label"],
        "sentences": per_sentence,
    }


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


def remaining_observation_types(used_categories: list[str]) -> list[dict[str, Any]]:
    types = load_knowledge("observation_types")["types"]
    used = set(used_categories)
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


def build_observation_judge_prompt(sentences: list[dict[str, Any]]) -> str:
    rubric = load_knowledge("observation_rubric")
    cats = "\n".join(
        f"- {c['id']} ({c['label']}): {c['definition']}" for c in rubric["categories"]
    )
    levels = "\n".join(
        f"- {l['level']} ({l['label']}): {l['meaning']}" for l in rubric["levels"]
    )
    numbered = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(sentences))
    return (
        "[task: judge_observation]\n"
        "당신은 연구용 채점자입니다. 학생에게 말하지 말고 JSON 한 개만 출력하세요. 설명 문장은 쓰지 마세요.\n"
        "첨부한 단풍잎 사진과 학생의 관찰 문장을 비교해 채점합니다.\n\n"
        f"[범주]\n{cats}\n\n[관찰력 수준]\n{levels}\n\n"
        "[사진 일치 값] match(사진에서 확인됨), partly(일부만 맞음), mismatch(사진과 다름), "
        "unknown(사진이 모호해 판단 불가). 모호하면 unknown으로 두세요.\n\n"
        f"[학생 관찰 문장]\n{numbered}\n\n"
        "[출력 JSON 형식]\n"
        '{"sentences":[{"index":1,"categories":["color"],"photoMatch":"match"}],'
        '"level":2,"rationale":"한두 문장으로 근거"}'
    )


def build_observation_agent_message(student_id: str, sentences: list[dict[str, Any]]) -> str:
    """관찰력 진단 워크스페이스의 Agent에게 보내는 메시지. 절차는 시스템 프롬프트에 있다."""
    numbered = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(sentences)) or "(제출 문장 없음)"
    return f"@agent [studentId: {student_id}]\n\n[학생 관찰 문장]\n{numbered}"


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


def merge_observation_judge(
    keyword: dict[str, Any], judge: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """키워드 채점 위에 LLM 판정을 얹어 최종 수준을 정한다."""
    result = dict(keyword)
    result["judge"] = None
    result["finalLevelSource"] = "keyword"
    if not judge:
        return result
    level = judge.get("level")
    if isinstance(level, int) and level in (1, 2, 3):
        rubric = load_knowledge("observation_rubric")
        result["level"] = level
        result["levelLabel"] = next(l["label"] for l in rubric["levels"] if l["level"] == level)
        result["finalLevelSource"] = "llm"
    matches = [
        s.get("photoMatch") for s in judge.get("sentences", []) if isinstance(s, dict)
    ]
    known = [m for m in matches if m in ("match", "partly", "mismatch")]
    rate = None
    if known:
        rate = round(sum(1 for m in known if m == "match") / len(known), 2)
    elif judge.get("photoMatchRate") is not None:
        rate = judge.get("photoMatchRate")
    result["judge"] = {
        "level": level,
        "rationale": judge.get("rationale"),
        "sentences": judge.get("sentences"),
        "categories": judge.get("categories"),
        "recordedBy": judge.get("recordedBy"),
        "photoMatchRate": rate,
    }
    return result


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