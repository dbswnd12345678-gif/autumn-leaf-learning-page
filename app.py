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


def build_context_blocks(history: list[dict], ctx, rule: Optional[dict]) -> str:
    blocks: list[str] = []
    if history:
        last = history[-1]
        blocks.append(
            "[과거 관찰 이력] 이 학생은 지금까지 총 {0}번 관찰을 기록했습니다. "
            "가장 최근 관찰(턴 {1}, {2}): \"{3}\"".format(
                len(history),
                last.get("turn_index"),
                last.get("timestamp"),
                (last.get("question") or "")[:200],
            )
        )
    else:
        blocks.append("[과거 관찰 이력] 이 학생의 첫 관찰입니다. 과거 기록이 없습니다.")

    if rule:
        blocks.append(
            "[교육학 안내 - 단계 {0}, 규칙 {1}] {2}".format(
                rule.get("matchedStage"), rule.get("id"), rule.get("adaptedForVisual")
            )
        )

    if ctx.comparison_mode:
        blocks.append("[관찰 모드] 학생이 사진 2장을 선택해서 비교 관찰을 진행하고 있습니다.")

    blocks.append(
        "[현재 관찰 참고 채점 - 절대적 기준 아님] 객관성 점수 {0}/2, 관찰 다양성 {1}종류, "
        "과학 용어 사용 {2}회, 공간 범위: {3}".format(
            ctx.objectivity_score, ctx.variety_count, ctx.term_count, ctx.spatial_scope
        )
    )
    return "\n".join(blocks)


def build_agent_message(student_message: str, context_block: str) -> str:
    # Developer API only triggers Agent Flow (knowledge-graph tool) when the
    # message is prefixed with "@agent".
    return f"@agent {context_block}\n\n학생 질문: {student_message}"


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
    # Treat the first couple of turns as the student's "first observation"
    # phase (turn 0 -> free observation/D, turn 1 -> method guidance/E),
    # then move on to feedback stages F/G from turn 2 onward.
    is_first_observation = turn_index < 2

    ctx = build_context(
        turn_index=turn_index,
        is_first_observation=is_first_observation,
        text=message,
        comparison_mode=comparison_mode,
        has_second_image_available=len(images) >= 1,
    )
    previous_rule_id = history[-1].get("pedagogy_rule_id") if history else None
    rule = match_pedagogy_rule(ctx, previous_rule_id)

    context_block = build_context_blocks(history, ctx, rule)
    agent_message = build_agent_message(message, context_block)

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
        pedagogy_rule_id=(rule or {}).get("id"),
        ai_stage=(rule or {}).get("matchedStage"),
    )

    return {"answer": answer}


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
    fmt = format.lower()
    if fmt == "docx":
        buf = reports.build_admin_docx(students, rows_by_student)
        return Response(
            content=buf,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="autumn-leaf-chat-all-students.docx"'},
        )

    buf = reports.build_admin_xlsx(students, rows_by_student)
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