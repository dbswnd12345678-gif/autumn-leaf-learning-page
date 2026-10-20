"""
단풍 관찰 학습 페이지의 FastAPI 서버 (3모드 개편판).

학습 페이지는 3개 탭(모드)으로 나뉜다. 각 모드는 AnythingLLM 워크스페이스가 따로 있다.

  assess  (탭 1) 관찰력 진단   AI 없이 10분 동안 관찰 문장을 쓰고 최종 제출한다.
  offload (탭 2) 오프로딩 진단  AI에게 자유롭게 묻고 요청하며 관찰 문장을 쓰고 제출한다.
  support (탭 3) AI Agent 지원  앞선 진단으로 정한 지원 수준에 맞춰 Agent가 돕는다.

하는 일:
  - public/ 아래 학습 페이지(HTML/CSS/JS, 단풍 사진)를 제공한다.
  - /api/session/*   모드별 10분 세션(서버 기준 시작·마감 시각)을 관리한다.
  - /api/chat        탭 2·3의 대화를 모드에 맞는 AnythingLLM 워크스페이스로 보낸다.
  - /api/submit      최종 관찰 문장을 저장하고 진단(관찰력 수준/오프로딩 단계)을 계산한다.
  - /api/tools/*     AnythingLLM Agent Flow가 부르는 조회 주소다. 호출마다 tool_calls에 기록한다.
  - 대화와 진단은 학번(studentId) 기준으로 SQLite에 쌓인다.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

if sys.platform == "win32":
    # Windows 로컬 개발 환경에서 uvicorn + httpx 조합으로 AnythingLLM에 https 요청을
    # 보낼 때 간헐적으로 ConnectError가 발생하는 문제가 있어 Proactor 루프로 강제한다.
    # (Railway 배포 환경은 Linux라 이 코드는 실행되지 않는다.)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import diagnosis
import reports

load_dotenv()

ANYTHINGLLM_BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "")
ANYTHINGLLM_API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "")
# 예전 단일 워크스페이스 설정. 모드별 slug를 따로 지정하지 않으면 이 값을 대신 쓴다.
LEGACY_WORKSPACE_SLUG = os.environ.get("ANYTHINGLLM_WORKSPACE_SLUG", "")
# 모드별 워크스페이스 slug. judge는 진단 채점 전용이며, 없으면 assess를 쓴다.
WORKSPACE_SLUGS = {
    "assess": os.environ.get("WS_SLUG_ASSESS", ""),
    "offload": os.environ.get("WS_SLUG_OFFLOAD", ""),
    "support": os.environ.get("WS_SLUG_SUPPORT", ""),
    "judge": os.environ.get("WS_SLUG_JUDGE", ""),
}
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
# AnythingLLM Agent Flow의 "API Call"이 /api/tools/*를 호출할 때 X-Tool-Key 헤더로 보내는 비밀 키.
TOOL_API_KEY = os.environ.get("TOOL_API_KEY", "")
PORT = int(os.environ.get("PORT", "3000"))

# 한 모드의 제한 시간(초). 시연이나 점검 때는 SESSION_SECONDS=60처럼 줄여서 쓴다.
SESSION_SECONDS = int(os.environ.get("SESSION_SECONDS", "600"))
# 마감 직후 도착한 요청도 받아 주는 여유(초).
SESSION_GRACE_SECONDS = int(os.environ.get("SESSION_GRACE_SECONDS", "20"))
# 1이면 탭 1·2 진단이 없어도 탭 3을 연다(개발·점검용).
UNLOCK_ALL = os.environ.get("UNLOCK_ALL", "") == "1"

MODES = ("assess", "offload", "support")
MODE_LABELS = {"assess": "관찰력 진단", "offload": "오프로딩 진단", "support": "AI Agent 지원"}

BASE_DIR = Path(__file__).parent
PUBLIC_DIR = BASE_DIR / "public"
IMAGES_DIR = PUBLIC_DIR / "images"
ALLOWED_IMAGES = [
    "l1-01.jpg", "l1-02.jpg", "l1-03.jpg", "l1-04.jpg", "l1-05.jpg",
    "l2-01.jpg", "l2-02.jpg", "l2-03.jpg", "l2-04.jpg", "l2-05.jpg",
    "l3-01.jpg", "l3-02.jpg", "l3-03.jpg", "l3-04.jpg", "l3-05.jpg",
    "l4-01.jpg", "l4-02.jpg", "l4-03.jpg", "l4-04.jpg", "l4-05.jpg",
]
# 모드(탭)마다 사진 5장 중에서 골라 관찰한다. 20장 중 15장을 쓰고, 탭끼리 난이도가 비슷하도록
# 같은 종류를 탭마다 한 장씩 넣었다. 목록 안의 순서는 비슷한 사진이 이어지지 않게 섞은 것이다.
#   종류 A: 빨강·주황 단풍잎 한 장    종류 B: 은행잎         종류 C: 잎 여러 장·나뭇가지 배경
#   종류 D: 색이 섞여 변하는 잎 한 장  종류 E: 초록·노랑 단풍잎 한 장
# 쓰지 않는 사진: l1-01, l2-02, l2-04, l3-04, l3-05
MODE_IMAGES = {
    "assess": ["l2-05.jpg", "l1-04.jpg", "l3-01.jpg", "l1-03.jpg", "l4-05.jpg"],   # A, B, C, D, E
    "offload": ["l2-03.jpg", "l1-02.jpg", "l4-04.jpg", "l3-02.jpg", "l4-03.jpg"],  # A, D, B, C, E
    "support": ["l2-01.jpg", "l1-05.jpg", "l3-03.jpg", "l4-01.jpg", "l4-02.jpg"],  # A, B, C, D, E
}

if not (ANYTHINGLLM_BASE_URL and ANYTHINGLLM_API_KEY):
    print("[경고] ANYTHINGLLM_BASE_URL / ANYTHINGLLM_API_KEY 가 설정되지 않았습니다.")
for _mode in ("offload", "support"):
    if not (WORKSPACE_SLUGS[_mode] or LEGACY_WORKSPACE_SLUG):
        print(f"[경고] WS_SLUG_{_mode.upper()} 가 설정되지 않아 {_mode} 모드 대화를 쓸 수 없습니다.")
if not ADMIN_KEY:
    print("[경고] ADMIN_KEY 환경변수가 설정되지 않았습니다. /api/admin/* 를 쓸 수 없습니다.")

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
# 도우미 함수
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
    """허용된 파일 이름만 읽어, 경로 조작으로 다른 파일을 열지 못하게 한다."""
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def workspace_slug(mode: str) -> str:
    """모드에 맞는 워크스페이스 slug. 모드별 설정이 없으면 예전 단일 slug를 쓴다."""
    return WORKSPACE_SLUGS.get(mode) or LEGACY_WORKSPACE_SLUG


def judge_slug() -> str:
    """오프로딩 진단 채점 전용 워크스페이스. 관찰력 진단(assess)은 자기 워크스페이스의 Agent가 채점한다."""
    return WORKSPACE_SLUGS["judge"]


def judge_slug_for(mode: str) -> str:
    if mode == "assess":
        return workspace_slug("assess")
    if mode == "offload":
        return judge_slug()
    return ""


async def call_anythingllm(
    slug: str,
    message: str,
    session_id: str,
    attachments: Optional[list[dict]] = None,
    timeout: float = 120.0,
) -> str:
    """AnythingLLM 워크스페이스에 메시지를 보내고 답변 문장을 돌려준다.
    Railway 쪽 연결이 간헐적으로 불안정해서 같은 요청을 한 번 더 시도한다."""
    if not (ANYTHINGLLM_BASE_URL and ANYTHINGLLM_API_KEY and slug):
        raise HTTPException(500, "서버에 AnythingLLM 연결 정보(환경변수)가 설정되지 않았습니다.")

    target_url = f"{normalize_base_url(ANYTHINGLLM_BASE_URL)}/api/v1/workspace/{slug}/chat"
    payload = {
        "message": message,
        "mode": "chat",
        "sessionId": session_id,
        "attachments": attachments or [],
    }

    resp = None
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
    return str(data.get("textResponse") or "")


# ---------------------------------------------------------------------------
# 모드별 10분 세션
# ---------------------------------------------------------------------------

def is_support_unlocked(student_id: str) -> bool:
    """탭 3은 탭 1(관찰력)과 탭 2(오프로딩) 진단이 모두 있어야 열린다."""
    if UNLOCK_ALL:
        return True
    return bool(db.get_diagnosis(student_id, "assess") and db.get_diagnosis(student_id, "offload"))


def remaining_seconds(session: dict[str, Any]) -> int:
    return max(0, int((parse_iso(session["deadline_at"]) - utc_now()).total_seconds()))


def mode_status(student_id: str, mode: str) -> dict[str, Any]:
    session = db.get_session(student_id, mode)
    status = "not_started"
    remaining = SESSION_SECONDS
    submitted = False
    if mode == "support" and not session and not is_support_unlocked(student_id):
        status = "locked"
    if session:
        submitted = bool(session.get("submitted_at"))
        remaining = remaining_seconds(session)
        if submitted:
            status = "submitted"
        elif remaining <= 0:
            status = "expired"
        else:
            status = "in_progress"
    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "status": status,
        "remainingSeconds": remaining,
        "durationSeconds": SESSION_SECONDS,
        "submitted": submitted,
        "images": MODE_IMAGES[mode],
    }


def require_active_session(student_id: str, mode: str) -> dict[str, Any]:
    session = db.get_session(student_id, mode)
    if not session:
        raise HTTPException(403, "먼저 시작 버튼을 눌러 주세요.")
    if session.get("submitted_at"):
        raise HTTPException(403, "이미 제출했습니다.")
    if (utc_now() - parse_iso(session["deadline_at"])).total_seconds() > SESSION_GRACE_SECONDS:
        raise HTTPException(403, "제한 시간이 끝났습니다. 관찰 문장을 제출해 주세요.")
    return session


def validate_mode(mode: str) -> str:
    if mode not in MODES:
        raise HTTPException(400, "mode는 assess, offload, support 중 하나여야 합니다.")
    return mode


@app.get("/api/session/status")
def session_status(studentId: str = Query(...)):
    student_id = sanitize_id(studentId)
    if not student_id:
        raise HTTPException(400, "studentId가 필요합니다.")
    return {
        "studentId": student_id,
        "durationSeconds": SESSION_SECONDS,
        "modes": {mode: mode_status(student_id, mode) for mode in MODES},
    }


class SessionStartRequest(BaseModel):
    studentId: str
    mode: str


@app.post("/api/session/start")
def session_start(req: SessionStartRequest):
    student_id = sanitize_id(req.studentId)
    if not student_id:
        raise HTTPException(400, "studentId가 필요합니다.")
    mode = validate_mode(req.mode)
    if mode == "support" and not is_support_unlocked(student_id):
        raise HTTPException(403, "탭 1과 탭 2를 먼저 마쳐야 탭 3을 시작할 수 있습니다.")
    now = utc_now()
    db.start_session(
        student_id,
        mode,
        started_at=now.isoformat(),
        deadline_at=(now + timedelta(seconds=SESSION_SECONDS)).isoformat(),
        images=MODE_IMAGES[mode],
    )
    return mode_status(student_id, mode)


# ---------------------------------------------------------------------------
# /api/chat (탭 2, 탭 3)
# ---------------------------------------------------------------------------

def student_levels(student_id: str) -> tuple[Optional[int], Optional[int]]:
    """저장된 진단에서 (관찰력 수준, 오프로딩 단계)를 꺼낸다. 없으면 None."""
    assess = db.get_diagnosis(student_id, "assess")
    offload = db.get_diagnosis(student_id, "offload")
    obs_level = (assess or {}).get("payload", {}).get("level")
    off_stage = (offload or {}).get("payload", {}).get("stage")
    return obs_level, off_stage


def build_support_message(
    student_id: str,
    student_message: str,
    input_kind: str,
    off_stage: Optional[int],
    observation: dict[str, Any],
) -> str:
    # AnythingLLM은 메시지 앞에 "@agent"가 있어야 도구(Agent Flow)를 호출한다.
    # 관찰 진단과 오프로딩 단계는 숫자로 합치지 않고 각각 적는다.
    stage = off_stage if off_stage in (1, 2, 3, 4) else "없음"
    tried = ", ".join(observation.get("typesUsed") or []) or "없음"
    if observation.get("nextType"):
        nxt = f"[nextType: {observation['nextType']}] [question: {observation.get('question') or ''}]"
    else:
        nxt = "[nextType: 없음]"
    tag = (
        f"[studentId: {student_id}] [offloadingStage: {stage}] "
        f"[input: {input_kind}] [tried: {tried}] {nxt}"
    )
    return f"@agent {tag}\n\n{student_message}"


class ChatRequest(BaseModel):
    message: str
    studentId: str
    sessionId: str
    mode: str
    # question: 학생이 AI에게 한 질문·요청, sentence: 탭 3에서 입력한 관찰 문장
    kind: str = "question"
    # 학생이 지금 보고 있는 사진 파일 이름. 이 탭의 사진 목록에 없으면 첫 사진으로 본다.
    image: Optional[str] = None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "message가 필요합니다.")
    message = message[:2000]

    student_id = sanitize_id(req.studentId)
    session_id = sanitize_id(req.sessionId)
    if not student_id:
        raise HTTPException(400, "studentId가 필요합니다.")
    if not session_id:
        raise HTTPException(400, "sessionId가 필요합니다.")
    mode = validate_mode(req.mode)
    if mode == "assess":
        raise HTTPException(400, "관찰력 진단(탭 1)에서는 AI를 쓰지 않습니다.")
    input_kind = "sentence" if req.kind == "sentence" else "question"

    session = require_active_session(student_id, mode)
    slug = workspace_slug(mode)
    if not slug:
        raise HTTPException(500, "이 모드의 AnythingLLM 워크스페이스 slug가 설정되지 않았습니다.")

    # 학생이 고른 사진 한 장을 AI에게 보여 준다. 이 탭에서 허용한 사진만 받는다.
    mode_images = [img for img in MODE_IMAGES[mode] if img in ALLOWED_IMAGES]
    chosen = req.image if req.image in mode_images else (mode_images[0] if mode_images else None)
    images = [chosen] if chosen else []
    attachments = [a for a in (load_image_attachment(name) for name in images) if a]

    support_level: Optional[int] = None
    last_tool_id = 0
    if mode == "support":
        _obs_level, off_stage = student_levels(student_id)
        assess_payload = (db.get_diagnosis(student_id, "assess") or {}).get("payload", {})
        observation = diagnosis.observation_support_state(assess_payload)
        agent_message = build_support_message(
            student_id, message, input_kind, off_stage, observation
        )
        last_tool_id = db.get_max_tool_call_id(student_id)
    else:
        # 탭 2는 학생이 평소 쓰는 AI에 가깝게 두기 위해, 태그나 @agent 없이 질문 그대로 보낸다.
        agent_message = message

    answer = sanitize_answer(
        await call_anythingllm(slug, agent_message, f"{mode}-{session_id}", attachments)
        or "(응답이 비어 있습니다)"
    )

    tools_called: Optional[str] = None
    tool_skipped: Optional[bool] = None
    if mode == "support":
        # Agent가 이번 턴에 지원 방법 조회를 실제로 불렀는지 확인한다.
        new_calls = db.get_tool_calls_after(student_id, last_tool_id)
        names = [c["tool_name"] for c in new_calls]
        tools_called = ",".join(names)
        tool_skipped = not any(n in ("support_methods", "observation_methods") for n in names)
        if tool_skipped:
            db.log_tool_call(
                student_id=student_id,
                tool_name="tool_skipped",
                input_text=message,
                result_summary=f"offloadingStage={off_stage}, input={input_kind}",
            )

    db.add_observation(
        student_id=student_id,
        session_id=session_id,
        images=images,
        comparison_mode=False,
        question=message,
        answer=answer,
        objectivity_score=None,
        term_count=None,
        variety_count=None,
        spatial_scope=None,
        pedagogy_rule_id=None,
        ai_stage=None,
        mode=mode,
        input_kind=input_kind,
        support_level=support_level,
        tools_called=tools_called,
        tool_skipped=tool_skipped,
    )

    return {"answer": answer, "remainingSeconds": remaining_seconds(session)}


# ---------------------------------------------------------------------------
# /api/submit: 최종 제출과 진단
# ---------------------------------------------------------------------------

class SubmitRequest(BaseModel):
    studentId: str
    mode: str
    # 문자열 목록 또는 {text, t(시작 후 경과 초)} 목록
    sentences: list[Any] = Field(default_factory=list)
    # 시간이 다 되어 화면이 자동으로 제출한 경우 true
    auto: bool = False


async def run_judge(
    student_id: str,
    mode: str,
    keyword_payload: dict[str, Any],
    sentences: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    image_names: list[str],
) -> None:
    """LLM 판정을 받아 진단 결과에 덧붙인다. 관찰력 진단이 실패하면 문장은 분류 전으로 남는다."""
    slug = judge_slug_for(mode)
    try:
        if mode == "assess":
            # 관찰력 진단: Agent가 기준 조회 Flow와 결과 기록 Flow를 불러 DB에 직접 기록한다.
            # 서버는 답변 문장을 쓰지 않고, 기록이 실제로 남았는지만 확인한다.
            prompt = diagnosis.build_observation_agent_message(student_id, sentences)
            attachments = [a for a in (load_image_attachment(n) for n in image_names) if a]
            await call_anythingllm(
                slug, prompt, f"judge-{student_id}-{mode}-{int(utc_now().timestamp())}",
                attachments, timeout=150.0,
            )
            record = db.get_diagnosis(student_id, "assess")
            current = (record or {}).get("payload") or keyword_payload
            if current.get("judgeStatus") != "done":
                raise ValueError("Agent가 결과 기록 Flow를 부르지 않았습니다.")
            return
        else:
            prompt = diagnosis.build_offloading_judge_prompt(turns, sentences)
            attachments = []
        text = await call_anythingllm(
            slug, prompt, f"judge-{student_id}-{mode}-{int(utc_now().timestamp())}",
            attachments, timeout=90.0,
        )
        judge = diagnosis.extract_json(text)
        if judge is None:
            raise ValueError("판정 응답에서 JSON을 읽지 못했습니다.")
        # 탭 1(assess)은 위에서 Agent 기록 확인 후 이미 반환했으므로 여기에는 오프로딩만 온다.
        merged = diagnosis.merge_offloading_judge(keyword_payload, judge)
        merged["judgeStatus"] = "done"
        db.save_diagnosis(student_id, mode, mode_kind(mode), merged)
    except Exception as exc:  # noqa: BLE001 - 채점 실패가 제출을 막으면 안 된다.
        print(f"[LLM 판정 실패] {student_id}/{mode}: {exc}")
        failed = dict(keyword_payload)
        failed["judgeStatus"] = "failed"
        failed["judgeError"] = str(exc)[:200]
        db.save_diagnosis(student_id, mode, mode_kind(mode), failed)


def mode_kind(mode: str) -> str:
    return {"assess": "observation", "offload": "offloading", "support": "support_outcome"}[mode]


@app.post("/api/submit")
async def submit(req: SubmitRequest, background: BackgroundTasks):
    student_id = sanitize_id(req.studentId)
    if not student_id:
        raise HTTPException(400, "studentId가 필요합니다.")
    mode = validate_mode(req.mode)

    session = db.get_session(student_id, mode)
    if not session:
        raise HTTPException(403, "시작하지 않은 모드입니다.")
    if session.get("submitted_at"):
        return {"ok": True, "alreadySubmitted": True}

    sentences = diagnosis.normalize_sentences(req.sentences)
    # 문장마다 학생이 보고 있던 사진을 적어 둔다. 이 탭의 사진이 아니면 지운다.
    mode_images = [img for img in MODE_IMAGES[mode] if img in ALLOWED_IMAGES]
    for s in sentences:
        if s.get("image") not in mode_images:
            s["image"] = None
    if not db.submit_session(student_id, mode, sentences, req.auto):
        return {"ok": True, "alreadySubmitted": True}

    turns = db.get_mode_observations(student_id, mode)
    # LLM 판정에는 학생이 실제로 문장을 쓴 사진만 보낸다. 사진 정보가 없으면 시작할 때 저장한 사진을 쓴다.
    image_names = diagnosis.images_used(sentences) or [
        img for img in session.get("images", []) if img in ALLOWED_IMAGES
    ][:1]

    if mode == "assess":
        payload = diagnosis.unclassified_observation(sentences)
    elif mode == "offload":
        payload = diagnosis.score_offloading(turns, sentences, session.get("started_at"))
    else:
        # 탭 3은 진단이 아니라 지원 후 관찰 결과를 기록한다.
        payload = diagnosis.unclassified_observation(sentences)
        payload["turnCount"] = len(turns)
        payload["toolSkippedTurns"] = sum(1 for t in turns if t.get("tool_skipped"))
        payload["supportLevels"] = sorted({t["support_level"] for t in turns if t.get("support_level")})

    # 탭 1은 제출 문장이 없으면 Agent가 분류할 문장이 없으므로 분류 전 기록만 남긴다.
    needs_judge = bool(judge_slug_for(mode)) and not (mode == "assess" and not sentences)
    payload["judgeStatus"] = "pending" if needs_judge else "skipped"
    db.save_diagnosis(student_id, mode, mode_kind(mode), payload)

    if payload["judgeStatus"] == "pending":
        background.add_task(run_judge, student_id, mode, payload, sentences, turns, image_names)

    return {"ok": True, "alreadySubmitted": False, "sentenceCount": len(sentences)}


# ---------------------------------------------------------------------------
# AnythingLLM Agent Flow용 조회 주소 (/api/tools/*)
# 모든 호출은 db.tool_calls에 기록한다.
# ---------------------------------------------------------------------------

def require_tool_key(x_tool_key: Optional[str]) -> None:
    if not TOOL_API_KEY:
        raise HTTPException(500, "서버에 TOOL_API_KEY 환경변수가 설정되지 않았습니다.")
    if not x_tool_key or x_tool_key != TOOL_API_KEY:
        raise HTTPException(403, "tool 인증 키가 올바르지 않습니다.")


def tool_student(student_id: str) -> str:
    sid = sanitize_id(student_id)
    if not sid:
        raise HTTPException(400, "studentId가 필요합니다.")
    return sid


@app.get("/api/tools/observation-criteria")
def tool_observation_criteria(
    studentId: str = Query(""),
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """관찰력 진단 기준 조회. 관찰력 진단 Agent가 채점 전에 부른다."""
    require_tool_key(x_tool_key)
    student_id = sanitize_id(studentId) or "unknown"
    rubric = diagnosis.load_knowledge("observation_rubric")
    db.log_tool_call(
        student_id=student_id,
        tool_name="observation_criteria",
        result_summary="진단 기준 조회",
    )
    return {
        "rubricVersion": rubric.get("version"),
        "informationUnit": rubric["informationUnit"],
        "classification": {
            "fixed": rubric["classification"]["fixed"],
            "dimensions": rubric["classification"]["dimensions"],
            "examples": rubric["classification"]["examples"],
        },
        "outOfScope": rubric["outOfScope"],
        "observationLevel": {
            "definition": rubric["observationLevel"]["definition"],
            "levels": rubric["observationLevel"]["levels"],
            "note": rubric["observationLevel"]["note"],
        },
        "objectivity": {
            "scale": rubric["objectivity"]["scale"],
            "scoringNotes": rubric["objectivity"]["scoringNotes"],
        },
        "photoMatchValues": rubric["photoMatchValues"],
        "recordFormat": rubric["recordFormat"],
        "howToUse": (
            "제출된 문장마다 정보 단위로 나누고, 단위마다 객관도(0~3)와 측정, 비교, 범위를 정하세요. "
            "시각 이외 감각이나 시간 흐름이 들어간 단위는 OOS로 표시하세요. 문장마다 LE를 정하세요. "
            "그 결과를 recordFormat 형식의 messages 한 줄로 observation-result 로 기록하세요. "
            "OQ_A, D, 수준 계산은 서버가 하니 직접 계산하지 마세요. 학생에게 답변하지 마세요."
        ),
    }


class ObservationResult(BaseModel):
    """Agent Flow가 보내는 값은 모두 문자열일 수 있어 느슨하게 받는다."""

    studentId: str
    # 문장별 분류. 형식은 observation_rubric.json의 recordFormat 참고.
    messages: Any = ""
    # 이전 형식(level만 기록) 호환용. messages가 비어 있을 때만 쓴다.
    level: Any = None
    categories: Any = ""
    photoMatch: Any = "unknown"
    rationale: Any = ""


@app.post("/api/tools/observation-result")
def tool_observation_result(
    body: ObservationResult,
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """관찰력 진단 결과 기록. Agent가 분류한 문장별 정보를 받아 서버가 지수를 계산해 diagnoses에 저장한다."""
    require_tool_key(x_tool_key)
    student_id = tool_student(body.studentId)

    record = db.get_diagnosis(student_id, "assess")
    if not record:
        raise HTTPException(404, "제출된 관찰력 진단이 없습니다.")
    stored = dict(record["payload"])

    match = str(body.photoMatch or "unknown").strip().lower()
    if match not in ("match", "partly", "mismatch", "unknown"):
        match = "unknown"
    rationale = str(body.rationale or "")

    parsed = diagnosis.parse_agent_messages(body.messages)
    legacy_level: Optional[int] = None
    try:
        legacy_level = int(str(body.level).strip())
    except (TypeError, ValueError):
        legacy_level = None

    if parsed:
        merged = diagnosis.apply_agent_observation(stored, parsed, match, rationale)
        sentence_count = merged.get("sentenceCount", 0)
        recorded = [i for i in parsed if 1 <= i <= sentence_count]
        # 이번 호출까지 합쳐서 Agent가 아직 기록하지 않은 문장 번호
        missing = [
            i for i, m in enumerate(merged.get("messages", []), start=1) if m.get("source") != "agent"
        ]
        summary = (
            f"기록 완료: 문장 {len(recorded)}/{sentence_count}, "
            f"OQ_A {stored.get('oqA')} -> {merged.get('oqA')}, D={merged.get('D')}, 수준={merged.get('level')}"
        )
        response: dict[str, Any] = {
            "ok": True,
            "recorded": True,
            "recordedCount": len(recorded),
            "sentenceCount": sentence_count,
            "missingIndexes": missing,
        }
    elif legacy_level in (1, 2, 3):
        merged = diagnosis.apply_legacy_level(stored, legacy_level, match, rationale)
        summary = f"이전 형식(level만) 기록: 수준 {stored.get('level')} -> {legacy_level}"
        response = {"ok": True, "recorded": True, "legacy": True}
    else:
        raise HTTPException(
            400,
            "messages 형식을 읽지 못했습니다. 예: 1:2:2-정성-단수-부분,2-정성-단수-부분;2:1:3-정량-단수-전체;3:1:OOS-감각",
        )

    merged["judgeStatus"] = "done"
    db.save_diagnosis(student_id, "assess", mode_kind("assess"), merged)
    db.log_tool_call(
        student_id=student_id,
        tool_name="observation_result",
        input_text=f"messages={str(body.messages)[:300]}, photoMatch={match}",
        result_summary=summary,
    )
    return response


@app.get("/api/tools/observation-assessment")
def tool_observation_assessment(
    studentId: str = Query(...),
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """관찰력 평가 데이터 조회. 평가 기준과 이 학생의 탭 1 진단 결과를 돌려준다."""
    require_tool_key(x_tool_key)
    student_id = tool_student(studentId)

    rubric = diagnosis.load_knowledge("observation_rubric")
    record = db.get_diagnosis(student_id, "assess")
    result = (record or {}).get("payload")

    summary = None
    if result:
        summary = {
            "level": result.get("level"),
            "levelLabel": result.get("levelLabel"),
            "oqA": result.get("oqA"),
            "diversityD": result.get("D"),
            "typesUsed": result.get("typesUsed"),
            "typesMissing": result.get("typesMissing"),
            "sentenceCount": result.get("sentenceCount"),
            "outOfScopeCounts": result.get("outOfScopeCounts"),
            "quantitativeMessageCount": result.get("quantitativeMessageCount"),
            "method": result.get("method"),
            "photoMatchRate": (result.get("judge") or {}).get("photoMatchRate"),
            "rationale": (result.get("judge") or {}).get("rationale"),
        }

    db.log_tool_call(
        student_id=student_id,
        tool_name="observation_assessment",
        result_summary=(
            f"level={summary['level']}, oqA={summary['oqA']}, D={summary['diversityD']}"
            if summary
            else "진단 없음"
        ),
    )
    return {
        "assessment": summary,
        "found": summary is not None,
        "criteria": {
            "observationTypes": diagnosis.all_type_ids(),
            "levels": rubric["levelThresholds"]["levels"],
        },
        "howToUse": "이 학생의 관찰력 수준과 아직 쓰지 않은 관찰 유형을 파악하는 데만 쓰세요. 학생에게 점수를 말하지 마세요.",
    }

@app.get("/api/tools/offloading-diagnosis")
def tool_offloading_diagnosis(
    studentId: str = Query(...),
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """오프로딩 단계 진단 조회. 단계 정의와 이 학생의 탭 2 진단 결과를 돌려준다."""
    require_tool_key(x_tool_key)
    student_id = tool_student(studentId)

    stages = diagnosis.load_knowledge("offloading_stages")
    record = db.get_diagnosis(student_id, "offload")
    result = (record or {}).get("payload")

    summary = None
    if result:
        summary = {
            "stage": result.get("stage"),
            "stageLabel": result.get("stageLabel"),
            "requestCount": result.get("requestCount"),
            "requestTypeCounts": result.get("requestTypeCounts"),
            "delegateShare": result.get("delegateShare"),
            "reuseRatio": result.get("reuseRatio"),
            "rationale": (result.get("judge") or {}).get("rationale"),
        }

    db.log_tool_call(
        student_id=student_id,
        tool_name="offloading_diagnosis",
        result_summary=f"stage={summary['stage']}" if summary else "진단 없음",
    )
    return {
        "diagnosis": summary,
        "found": summary is not None,
        "stages": [
            {"stage": s["stage"], "label": s["label"], "meaning": s["meaning"]}
            for s in stages["stages"]
        ],
        "howToUse": "이 학생이 AI에 얼마나 의존하는지 파악하는 데만 쓰세요. 학생에게 단계를 말하지 마세요.",
    }


@app.get("/api/tools/support-methods")
def tool_support_methods(
    studentId: str = Query(...),
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """관찰 진단과 오프로딩 단계를 각각 돌려준다. 둘을 하나의 지원 수준으로 합치지 않는다."""
    require_tool_key(x_tool_key)
    student_id = tool_student(studentId)

    _obs_level, off_stage = student_levels(student_id)
    assess_payload = (db.get_diagnosis(student_id, "assess") or {}).get("payload", {})
    observation = diagnosis.observation_support_state(assess_payload)
    offloading = diagnosis.offloading_support(off_stage)
    support = diagnosis.load_knowledge("support_methods")

    db.log_tool_call(
        student_id=student_id,
        tool_name="support_methods",
        result_summary=(
            f"observation={observation['rule']['id']}, nextType={observation.get('nextType')}, "
            f"offloadingStage={off_stage}"
        ),
    )
    return {
        "observation": observation,
        "offloading": offloading,
        "principles": support["principles"],
        "howToUse": (
            "관찰 규칙으로 무엇을 물을지 하나만 정하세요. 방금 문장이 관찰이 아니거나 막연하면 "
            "nextType 대신 not_observation 또는 vague 규칙을 쓰세요. "
            "오프로딩 단계의 methods로 그 질문을 어떻게 말할지 정하세요. "
            "두 축을 하나의 수준으로 합치지 말고, 학생에게 단계 숫자를 말하지 마세요."
        ),
    }


@app.get("/api/tools/observation-methods")
def tool_observation_methods(
    studentId: str = Query(...),
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """단풍잎 관찰 시 관찰 유형 및 방법 조회. 이 학생이 아직 쓰지 않은 유형을 돌려준다."""
    require_tool_key(x_tool_key)
    student_id = tool_student(studentId)

    # 시도한 유형은 Agent가 분류해 둔 탭 1 진단만 본다. 단어로 문장을 다시 나누지 않는다.
    assess = (db.get_diagnosis(student_id, "assess") or {}).get("payload", {})
    classified = assess.get("method") in ("agent", "partial")
    used_now = list(assess.get("typesUsed") or []) if classified else []
    remaining = diagnosis.remaining_observation_types(used_now) if classified else []
    latest_flags: list[str] = []

    types = diagnosis.load_knowledge("observation_types")
    guidance = types.get("outOfScopeGuidance", {})
    db.log_tool_call(
        student_id=student_id,
        tool_name="observation_methods",
        result_summary=(
            f"used={','.join(used_now)}; offered={','.join(t['id'] for t in remaining[:3])}"
            + (f"; outOfScope={','.join(latest_flags)}" if latest_flags else "")
        ),
    )
    return {
        "classificationReady": classified,
        "usedTypes": used_now,
        "suggestedTypes": remaining[:3],
        "outOfScopeGuidance": {f: guidance.get(f) for f in latest_flags} or None,
        "avoid": types["avoid"],
        "howToUse": (
            "classificationReady가 아니면 새 관찰 유형을 제안하지 마세요. "
            "준비되면 suggestedTypes에서 하나만 고르세요. 학생이 직접 사진에서 찾고 한 문장 쓰게 하세요."
        ),
    }

@app.get("/api/tools/dialogue-log")
def tool_dialogue_log(
    studentId: str = Query(...),
    mode: Optional[str] = None,
    limit: int = 10,
    x_tool_key: Optional[str] = Header(None, alias="x-tool-key"),
):
    """개인별 대화 로그 조회. 기록은 서버가 /api/chat에서 항상 저장하고, Agent는 읽기만 한다."""
    require_tool_key(x_tool_key)
    student_id = tool_student(studentId)
    if mode and mode not in MODES:
        raise HTTPException(400, "mode는 assess, offload, support 중 하나여야 합니다.")

    rows = db.get_mode_observations(student_id, mode) if mode else db.get_student_history(student_id)
    rows = [r for r in rows if r.get("mode")]
    rows = rows[-max(1, min(limit, 30)):]
    turns = [
        {
            "mode": r.get("mode"),
            "kind": r.get("input_kind"),
            "student": r.get("question"),
            "ai": (r.get("answer") or "")[:300],
            "timestamp": r.get("timestamp"),
        }
        for r in rows
    ]
    db.log_tool_call(
        student_id=student_id,
        tool_name="dialogue_log",
        result_summary=f"mode={mode or 'all'}, turns={len(turns)}",
    )
    return {
        "turns": turns,
        "turnCount": len(turns),
        "howToUse": "이전에 한 말을 반복해서 묻지 않도록 확인하는 데만 쓰세요.",
    }


# ---------------------------------------------------------------------------
# 학생용 관찰 기록 내보내기
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
# 연구자용 관리 주소. ?key=ADMIN_KEY 또는 X-Admin-Key 헤더가 필요하다.
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
    return {"students": db.list_students(), "modeSessions": db.list_sessions()}


@app.get("/api/admin/diagnoses")
def admin_diagnoses(
    studentId: Optional[str] = None,
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None, alias="x-admin-key"),
):
    """모드별 진단 결과(관찰력 수준, 오프로딩 단계 등) 원본."""
    require_admin_key(key, x_admin_key)
    rows = db.get_all_diagnoses()
    if studentId:
        sid = sanitize_id(studentId)
        rows = [r for r in rows if r["student_id"] == sid]
    return {"diagnoses": rows}


@app.get("/api/admin/tool-calls")
def admin_tool_calls(
    studentId: Optional[str] = None,
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None, alias="x-admin-key"),
):
    """Agent가 /api/tools/*를 부른 원본 기록. 도구를 실제로 얼마나 썼는지 확인할 수 있다."""
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
    diagnoses = db.get_all_diagnoses()
    mode_sessions = db.list_sessions()
    if not students and not diagnoses:
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

    buf = reports.build_admin_xlsx(
        students, rows_by_student, tool_calls, diagnoses=diagnoses, mode_sessions=mode_sessions
    )
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="autumn-leaf-chat-all-students.xlsx"'},
    )


@app.get("/api/admin/db-backup")
def admin_db_backup(
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None, alias="x-admin-key"),
):
    """observations.db의 읽기 전용 스냅샷을 내려준다. 서버 데이터는 바꾸지 않는다."""
    require_admin_key(key, x_admin_key)
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    return Response(
        content=db.backup_bytes(),
        media_type="application/vnd.sqlite3",
        headers={"Content-Disposition": f'attachment; filename="observations-{stamp}.db"'},
    )


@app.get("/api/health")
def health():
    return {"ok": True}


# 학습 페이지(public/)는 마지막에 연결한다. 그래야 /api/*가 먼저 처리된다.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)