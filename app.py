"""
FastAPI backend for the autumn-leaf observation learning page.

Replaces the previous Node.js/Express server (see legacy_node/server.js).
Key differences from the legacy version:
  - PhenoVisionL integration has been removed entirely (leaf classification
    is no longer part of the pipeline).
  - Conversation history is now keyed by a persistent studentId (not just
    the browser sessionId), stored in SQLite (see db.py) so a student's
    history survives across the 3 separate class sessions.
  - Before calling AnythingLLM, the server looks up the student's past
    observations and matches a pedagogy rule (see pedagogy.py /
    pedagogy_db.json), then injects both as context blocks into the
    message sent to the AnythingLLM Agent Flow.
  - Up to 2 images can be attached per turn to support comparison
    observation (관찰범위 > 비교관찰).
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    # Windows 로컬 개발 환경에서 uvicorn + httpx 조합으로 AnythingLLM에 https 요청을
    # 보낼 때 간헐적으로 ConnectError("All connection attempts failed")가 발생하는
    # 문제가 있었다. Proactor 이벤트 루프로 강제 전환하면 안정적으로 연결된다.
    # (Railway 배포 환경은 Linux라 이 코드는 실행되지 않는다.)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import reports
from pedagogy import build_context, match_pedagogy_rule

load_dotenv()

ANYTHINGLLM_BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "")
ANYTHINGLLM_API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "")
ANYTHINGLLM_WORKSPACE_SLUG = os.environ.get("ANYTHINGLLM_WORKSPACE_SLUG", "")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
# Shared secret that the AnythingLLM Agent Flow "API Call" blocks must send
# (as an "X-Tool-Key" header) when calling our /api/tools/* endpoints. These
# endpoints are public (Railway needs to reach them from AnythingLLM), so
# this key keeps randos from calling them directly.
TOOL_API_KEY = os.environ.get("TOOL_API_KEY", "")
PORT = int(os.environ.get("PORT", "3000"))

BASE_DIR = Path(__file__).parent
PUBLIC_DIR = BASE_DIR / "public"
IMAGES_DIR = PUBLIC_DIR / "images"
ALLOWED_IMAGES = ["leaf1.jpg", "leaf2.jpg", "leaf3.webp", "leaf4.jpg", "leaf5.png"]

if not (ANYTHINGLLM_BASE_URL and ANYTHINGLLM_API_KEY and ANYTHINGLLM_WORKSPACE_SLUG):
    print(
        "[경고] .env 파일(또는 Railway 환경변수)에 ANYTHINGLLM_BASE_URL / "
        "ANYTHINGLLM_API_KEY / ANYTHINGLLM_WORKSPACE_SLUG 가 설정되지 않았습니다."
    )
if not ADMIN_KEY:
    print(
        "[경고] ADMIN_KEY 환경변수가 설정되지 않았습니다. "
        "연구자용 전체 대화 기록 다운로드(/api/admin/*)를 쓸 수 없습니다."
    )

app = FastAPI(title="단풍 관찰 학습 서버")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    print(f"[예외 발생] {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"error": f"서버 내부 오류: {exc}"})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def normalize_base_url(raw_url: str) -> str:
    trimmed = raw_url.strip().rstrip("/")
    return trimmed if re.match(r"^https?://", trimmed, re.I) else f"https://{trimmed}"


def mime_from_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    return "image/jpeg"


def load_image_attachment(image_name: str) -> Optional[dict]:
    """Whitelist-only image loading to prevent path traversal."""
    if not image_name or image_name not in ALLOWED_IMAGES:
        return None
    image_path = IMAGES_DIR / image_name
    if not image_path.exists():
        return None
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    mime = mime_from_ext(image_name)
    return {"name": image_name, "mime": mime, "contentString": f"data:{mime};base64,{b64}"}


_ID_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")


def sanitize_id(value: str) -> str:
    return _ID_SAFE_PATTERN.sub("", str(value or ""))


def to_filename_safe(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value))


_EXIT_PATTERNS = [
    re.compile(r"\s*/exit\b", re.I),
    re.compile(r"['\"`]?/?exit['\"`]?\s*입력을?\s*확인했어요\.?\s*", re.I),
    re.compile(r"['\"`]?edit['\"`]?\s*입력을?\s*확인했어요\.?\s*", re.I),
    re.compile(r"\s*관찰을\s*마칠게요\.?\s*", re.I),
]


def sanitize_answer(text: str) -> str:
    result = str(text or "")
    for pattern in _EXIT_PATTERNS:
        result = pattern.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def build_agent_message(student_id: str, student_message: str, comparison_mode: bool) -> str:
    # The Developer API only enters Agent (tool-calling) mode when the
    # message is prefixed with "@agent". We deliberately keep the message
    # itself thin now: the AI Agent is expected to decide for itself
    # (based on the system prompt + its own tool set) whether to call the
    # "학생 관찰 이력 조회", "교육학 안내 조회", or "단풍 지식그래프 조회" tools -
    # we are no longer pre-computing/pre-injecting that content here.
    # The one thing the agent *cannot* infer on its own is the student's
    # persistent ID, so we tag it at the front in a fixed, parseable format
    # so the "학생 관찰 이력 조회"/"교육학 안내 조회" tools can be called with it.
    tag = f"[학번: {student_id}]"
    if comparison_mode:
        tag += " [관찰 모드: 사진 2장 비교관찰]"
    return f"@agent {tag}\n\n학생 관찰: {student_message}"


# ---------------------------------------------------------------------------
# /api/chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    images: list[str] = Field(default_factory=list)
    studentId: str
    sessionId: str
    comparisonMode: bool = False


@app.post("/api/chat")
async def chat(req: ChatRequest):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "message가 필요합니다.")

    student_id = sanitize_id(req.studentId)
    session_id = sanitize_id(req.sessionId)
    if not student_id:
        raise HTTPException(400, "studentId가 필요합니다.")
    if not session_id:
        raise HTTPException(400, "sessionId가 필요합니다.")
    if not (ANYTHINGLLM_BASE_URL and ANYTHINGLLM_API_KEY and ANYTHINGLLM_WORKSPACE_SLUG):
        raise HTTPException(500, "서버에 AnythingLLM 연결 정보(환경변수)가 설정되지 않았습니다.")

    images = [img for img in (req.images or []) if img in ALLOWED_IMAGES][:2]
    attachments = [a for a in (load_image_attachment(name) for name in images) if a]
    comparison_mode = bool(req.comparisonMode) and len(images) >= 2

    history = db.get_student_history(student_id)
    turn_index = len(history)  # 0-based count of PRIOR turns
    is_first_observation = turn_index < 2

    # We still score the raw text ourselves (objectivity/variety/term/spatial)
    # purely so the researcher export keeps these analytics columns - this is
    # independent of pedagogy guidance now. We no longer match a pedagogy
    # rule or build a context block here: whether/which rule gets surfaced is
    # entirely up to the AI Agent's own tool call to "교육학 안내 조회" (see
    # /api/tools/pedagogy-hint below), not something this server injects.
    ctx = build_context(
        turn_index=turn_index,
        is_first_observation=is_first_observation,
        text=message,
        comparison_mode=comparison_mode,
        has_second_image_available=len(images) >= 1,
    )

    agent_message = build_agent_message(student_id, message, comparison_mode)

    target_url = (
        f"{normalize_base_url(ANYTHINGLLM_BASE_URL)}/api/v1/workspace/"
        f"{ANYTHINGLLM_WORKSPACE_SLUG}/chat"
    )
    payload = {
        "message": agent_message,
        "mode": "chat",
        "sessionId": session_id,
        "attachments": attachments,
    }

    # Railway 쪽 연결이 간헐적으로 불안정해서 ConnectError가 한 번씩 발생할 수 있으므로
    # 같은 요청을 한 번 더 시도해본다 (이미지+Agent Flow 처리는 20~30초 이상 걸릴 수 있어
    # 타임아웃도 넉넉하게 잡는다).
    resp = None
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    target_url,
                    headers={
                        "Authorization": f"Bearer {ANYTHINGLLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            print(f"[AnythingLLM 호출 시도 {attempt + 1} 실패] {exc}")
    if resp is None:
        raise HTTPException(502, f"AnythingLLM 호출 실패: {last_exc}")

    if resp.status_code >= 400:
        raise HTTPException(
            502, f"AnythingLLM 응답 오류 ({resp.status_code}): {resp.text[:200]}"
        )

    data = resp.json()
    answer = sanitize_answer(data.get("textResponse") or "(응답이 비어 있습니다)")

    # Best-effort attribution: if the agent called the "교육학 안내 조회" tool
    # while handling *this* request, it will have just logged a row in
    # tool_calls (see /api/tools/pedagogy-hint). We attach that rule id/stage
    # to this observation row for convenience in the researcher export, but
    # this is informational only - the authoritative, complete record of
    # every tool call (including turns where the agent called it 0 or 2+
    # times) lives in the tool_calls table itself.
    last_pedagogy_call = db.get_last_tool_call(student_id, "pedagogy_hint")

    db.add_observation(
        student_id=student_id,
        session_id=session_id,
        images=images,
        comparison_mode=comparison_mode,
        question=message,
        answer=answer,
        objectivity_score=ctx.objectivity_score,
        term_count=ctx.term_count,
        variety_count=ctx.variety_count,
        spatial_scope=ctx.spatial_scope,
        pedagogy_rule_id=(last_pedagogy_call or {}).get("pedagogy_rule_id"),
        ai_stage=(last_pedagogy_call or {}).get("ai_stage"),
    )

    return {"answer": answer}


# ---------------------------------------------------------------------------
# Tools for the AnythingLLM Agent (called from Agent Flow "API Call" blocks,
# NOT by our own frontend). The Agent itself decides, per turn, whether to
# call these - see the workspace system prompt. Every call is logged to
# db.tool_calls regardless of outcome, so we can measure how often the
# agent actually consults each source (this is the "true" tool-calling
# design the pedagogy previously replaced with server-side pre-injection).
# ---------------------------------------------------------------------------

def require_tool_key(x_tool_key: Optional[str]) -> None:
    if not TOOL_API_KEY:
        raise HTTPException(500, "서버에 TOOL_API_KEY 환경변수가 설정되지 않았습니다.")
    if not x_tool_key or x_tool_key != TOOL_API_KEY:
        raise HTTPException(403, "tool 인증 키가 올바르지 않습니다.")


class PedagogyHintRequest(BaseModel):
    studentId: str
    observationText: str
    comparisonMode: bool = False
    hasSecondImageAvailable: bool = False


@app.post("/api/tools/pedagogy-hint")
def tool_pedagogy_hint(
    req: PedagogyHintRequest,
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """Called by the "교육학 안내 조회" Agent Flow. Given the student's current
    observation sentence, scores it and returns the single most relevant
    teacher-question hint from pedagogy_db.json (see pedagogy.py). This is
    the *only* place pedagogy_db.json gets consulted now - it is entirely
    up to the calling agent whether/when to invoke this tool."""
    require_tool_key(x_tool_key)

    student_id = sanitize_id(req.studentId)
    if not student_id:
        raise HTTPException(400, "studentId가 필요합니다.")
    observation_text = (req.observationText or "").strip()
    if not observation_text:
        raise HTTPException(400, "observationText가 필요합니다.")

    history = db.get_student_history(student_id)
    turn_index = len(history)
    is_first_observation = turn_index < 2
    previous_call = db.get_last_tool_call(student_id, "pedagogy_hint")
    previous_rule_id = (previous_call or {}).get("pedagogy_rule_id")

    ctx = build_context(
        turn_index=turn_index,
        is_first_observation=is_first_observation,
        text=observation_text,
        comparison_mode=bool(req.comparisonMode),
        has_second_image_available=bool(req.hasSecondImageAvailable),
    )
    rule = match_pedagogy_rule(ctx, previous_rule_id)
    hint = (rule or {}).get(
        "adaptedForVisual",
        "지금은 추가로 제안할 교육학적 힌트가 없습니다. 학생의 관찰을 있는 그대로 인정하고 격려해주세요.",
    )

    db.log_tool_call(
        student_id=student_id,
        tool_name="pedagogy_hint",
        input_text=observation_text,
        pedagogy_rule_id=(rule or {}).get("id"),
        ai_stage=(rule or {}).get("matchedStage"),
        result_summary=hint,
    )

    return {
        "hint": hint,
        "stage": (rule or {}).get("matchedStage"),
        "ruleId": (rule or {}).get("id"),
        "scoring": {
            "objectivityScore": ctx.objectivity_score,
            "varietyCount": ctx.variety_count,
            "termCount": ctx.term_count,
            "spatialScope": ctx.spatial_scope,
        },
    }


@app.get("/api/tools/history-lookup")
def tool_history_lookup(
    studentId: str = Query(...),
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """Called by the "학생 관찰 이력 조회" Agent Flow. Returns a short summary of
    this student's past observation turns (count + most recent turn), so the
    agent can decide how to react (first-time vs. repeat, notice progress,
    compare with earlier observations, etc.)."""
    require_tool_key(x_tool_key)

    student_id = sanitize_id(studentId)
    if not student_id:
        raise HTTPException(400, "studentId가 필요합니다.")

    history = db.get_student_history(student_id)
    if not history:
        summary = "이 학생은 과거 관찰 기록이 없습니다. 오늘이 첫 관찰입니다."
    else:
        last = history[-1]
        summary = (
            f"지금까지 총 {len(history)}번 관찰을 기록했습니다. "
            f"가장 최근 관찰(턴 {last.get('turn_index')}, {last.get('timestamp')}): "
            f"\"{(last.get('question') or '')[:200]}\""
        )

    db.log_tool_call(
        student_id=student_id,
        tool_name="history_lookup",
        input_text=None,
        result_summary=summary,
    )

    return {"summary": summary, "turnCount": len(history)}


# ---------------------------------------------------------------------------
# student-facing history export
# ---------------------------------------------------------------------------

@app.get("/api/history/{student_id}/export")
def export_history(student_id: str, format: str = Query("xlsx")):
    rows = db.get_student_history(student_id)
    if not rows:
        raise HTTPException(404, "저장된 대화 기록이 없습니다.")

    filename_base = f"autumn-leaf-chat-{to_filename_safe(student_id)}"
    fmt = format.lower()
    if fmt == "docx":
        buf = reports.build_student_docx(student_id, rows)
        return Response(
            content=buf,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.docx"'},
        )

    buf = reports.build_student_xlsx(student_id, rows)
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
    )


# ---------------------------------------------------------------------------
# admin (researcher) endpoints - require ?key=ADMIN_KEY or X-Admin-Key header
# ---------------------------------------------------------------------------

def require_admin_key(key: Optional[str], x_admin_key: Optional[str]) -> None:
    if not ADMIN_KEY:
        raise HTTPException(500, "서버에 ADMIN_KEY 환경변수가 설정되지 않았습니다.")
    provided = key or x_admin_key
    if not provided or provided != ADMIN_KEY:
        raise HTTPException(403, "관리자 키가 올바르지 않습니다.")


@app.get("/api/admin/sessions")
def admin_sessions(
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None, alias="x-admin-key"),
):
    require_admin_key(key, x_admin_key)
    students = db.list_students()
    return {"students": students}


@app.get("/api/admin/tool-calls")
def admin_tool_calls(
    studentId: Optional[str] = None,
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None, alias="x-admin-key"),
):
    """Raw log of every time the AI Agent called '학생 관찰 이력 조회' or
    '교육학 안내 조회' (see /api/tools/* in this file). Lets the researcher
    check whether/how often the agent is actually consulting each source,
    independent of what ended up in the final answer text."""
    require_admin_key(key, x_admin_key)
    student_id = sanitize_id(studentId) if studentId else None
    calls = db.get_tool_calls(student_id) if student_id else db.get_all_tool_calls()
    return {"toolCalls": calls}


@app.get("/api/admin/export")
def admin_export(
    format: str = Query("xlsx"),
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None, alias="x-admin-key"),
):
    require_admin_key(key, x_admin_key)
    students = db.list_students()
    if not students:
        raise HTTPException(404, "저장된 대화 기록이 없습니다.")

    rows_by_student = {s["student_id"]: db.get_student_history(s["student_id"]) for s in students}
    tool_calls = db.get_all_tool_calls()
    fmt = format.lower()
    if fmt == "docx":
        buf = reports.build_admin_docx(students, rows_by_student, tool_calls)
        return Response(
            content=buf,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="autumn-leaf-chat-all-students.docx"'},
        )

    buf = reports.build_admin_xlsx(students, rows_by_student, tool_calls)
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="autumn-leaf-chat-all-students.xlsx"'},
    )


@app.get("/api/health")
def health():
    return {"ok": True}


# Static frontend (public/) mounted last so /api/* routes above take priority.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)