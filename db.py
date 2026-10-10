"""
SQLite storage for per-student observation history.

Design notes:
- The old Node.js version wrote one JSONL file per browser session_id.
  Students now attend 3 separate class sessions (possibly different
  browsers/devices), so we key history by a persistent student_id that
  the student types in once per session (see public/script.js).
- session_id is still stored alongside each row so we can tell which
  class session / browser session a given turn came from.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(os.environ.get("DATA_DIR", "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "observations.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    images TEXT,
    comparison_mode INTEGER NOT NULL DEFAULT 0,
    question TEXT,
    answer TEXT,
    objectivity_score INTEGER,
    term_count INTEGER,
    variety_count INTEGER,
    spatial_scope TEXT,
    pedagogy_rule_id TEXT,
    ai_stage TEXT
);

CREATE INDEX IF NOT EXISTS idx_observations_student ON observations(student_id);
CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(session_id);

-- Every call the AnythingLLM Agent makes to one of our /api/tools/* endpoints
-- gets logged here, regardless of what it decides to do with the result.
-- This is how we verify (for the thesis) whether/how often the agent
-- actually chose to consult pedagogy/history/knowledge-graph tools, instead
-- of assuming it always does.
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    input_text TEXT,
    pedagogy_rule_id TEXT,
    ai_stage TEXT,
    result_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_student ON tool_calls(student_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name);

-- 3모드 개편: 학생 x 모드(assess/offload/support)마다 10분 세션 한 줄.
-- 시작·마감 시각은 서버 기준이라 새로고침해도 남은 시간이 이어진다.
CREATE TABLE IF NOT EXISTS mode_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    deadline_at TEXT NOT NULL,
    submitted_at TEXT,
    auto_submitted INTEGER NOT NULL DEFAULT 0,
    images TEXT,
    sentences TEXT,
    UNIQUE (student_id, mode)
);

-- 진단 결과(관찰력 수준, 오프로딩 단계 등)를 JSON 문자열로 저장한다.
-- 구조가 바뀌어도 표를 고치지 않도록 payload 한 칼럼에 담는다.
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (student_id, mode)
);
"""

# 기존 observations 표에 3모드용 칼럼을 덧붙인다(이미 있으면 건너뜀).
_OBSERVATION_EXTRA_COLUMNS = {
    "mode": "TEXT",
    "input_kind": "TEXT",
    "support_level": "INTEGER",
    "tools_called": "TEXT",
    "tool_skipped": "INTEGER",
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(observations)")}
        for name, col_type in _OBSERVATION_EXTRA_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE observations ADD COLUMN {name} {col_type}")
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_turn_index(conn: sqlite3.Connection, student_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM observations WHERE student_id = ?",
        (student_id,),
    ).fetchone()
    return int(row["c"]) + 1


def add_observation(
    *,
    student_id: str,
    session_id: str,
    images: list[str],
    comparison_mode: bool,
    question: str,
    answer: str,
    objectivity_score: Optional[int],
    term_count: Optional[int],
    variety_count: Optional[int],
    spatial_scope: Optional[str],
    pedagogy_rule_id: Optional[str],
    ai_stage: Optional[str],
    mode: Optional[str] = None,
    input_kind: Optional[str] = None,
    support_level: Optional[int] = None,
    tools_called: Optional[str] = None,
    tool_skipped: Optional[bool] = None,
) -> int:
    conn = get_connection()
    try:
        turn_index = next_turn_index(conn, student_id)
        cur = conn.execute(
            """
            INSERT INTO observations (
                student_id, session_id, turn_index, timestamp, images,
                comparison_mode, question, answer, objectivity_score,
                term_count, variety_count, spatial_scope, pedagogy_rule_id, ai_stage,
                mode, input_kind, support_level, tools_called, tool_skipped
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                session_id,
                turn_index,
                now_iso(),
                json.dumps(images, ensure_ascii=False),
                1 if comparison_mode else 0,
                question,
                answer,
                objectivity_score,
                term_count,
                variety_count,
                spatial_scope,
                pedagogy_rule_id,
                ai_stage,
                mode,
                input_kind,
                support_level,
                tools_called,
                None if tool_skipped is None else (1 if tool_skipped else 0),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["images"] = json.loads(d.get("images") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["images"] = []
    d["comparison_mode"] = bool(d.get("comparison_mode"))
    return d


def get_student_history(student_id: str, limit: Optional[int] = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM observations WHERE student_id = ? ORDER BY id ASC"
        params: tuple = (student_id,)
        if limit:
            sql += " LIMIT ?"
            params = (student_id, limit)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_last_observation(student_id: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM observations WHERE student_id = ? ORDER BY id DESC LIMIT 1",
            (student_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_students() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                student_id,
                COUNT(*) AS turn_count,
                COUNT(DISTINCT session_id) AS session_count,
                MIN(timestamp) AS first_at,
                MAX(timestamp) AS last_at
            FROM observations
            GROUP BY student_id
            ORDER BY student_id ASC
            """
        ).fetchall()
        students = [dict(r) for r in rows]

        # Merge in tool-call counts per student per tool, so the admin page
        # can show (at a glance) whether the agent is actually calling
        # "학생 관찰 이력 조회" / "교육학 안내 조회" - not just how many chat
        # turns happened.
        tool_rows = conn.execute(
            "SELECT student_id, tool_name, COUNT(*) AS c FROM tool_calls "
            "GROUP BY student_id, tool_name"
        ).fetchall()
        counts_by_student: dict[str, dict[str, int]] = {}
        for r in tool_rows:
            counts_by_student.setdefault(r["student_id"], {})[r["tool_name"]] = int(r["c"])

        for s in students:
            counts = counts_by_student.get(s["student_id"], {})
            s["history_lookup_calls"] = counts.get("history_lookup", 0)
            s["pedagogy_hint_calls"] = counts.get("pedagogy_hint", 0)

        return students
    finally:
        conn.close()


def get_all_observations() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM observations ORDER BY student_id ASC, id ASC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def log_tool_call(
    *,
    student_id: str,
    tool_name: str,
    input_text: Optional[str] = None,
    pedagogy_rule_id: Optional[str] = None,
    ai_stage: Optional[str] = None,
    result_summary: Optional[str] = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO tool_calls (
                student_id, tool_name, timestamp, input_text,
                pedagogy_rule_id, ai_stage, result_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                tool_name,
                now_iso(),
                input_text,
                pedagogy_rule_id,
                ai_stage,
                result_summary,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_recent_pedagogy_rule_ids(student_id: str, limit: int = 3) -> list[str]:
    """최근 교육학 안내에서 고른 규칙 id. 같은 발문 반복을 줄일 때 쓴다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT pedagogy_rule_id FROM tool_calls "
            "WHERE student_id = ? AND tool_name = 'pedagogy_hint' "
            "AND pedagogy_rule_id IS NOT NULL AND pedagogy_rule_id != '' "
            "ORDER BY id DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
        return [r["pedagogy_rule_id"] for r in rows]
    finally:
        conn.close()


def get_last_tool_call(student_id: str, tool_name: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM tool_calls WHERE student_id = ? AND tool_name = ? "
            "ORDER BY id DESC LIMIT 1",
            (student_id, tool_name),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_tool_calls(student_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM tool_calls WHERE student_id = ? ORDER BY id ASC",
            (student_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_tool_calls() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM tool_calls ORDER BY student_id ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_tool_call_counts(student_id: str) -> dict[str, int]:
    """{tool_name: call_count} for this student - used to check compliance
    (are pedagogy/history tools actually being called every turn?)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT tool_name, COUNT(*) AS c FROM tool_calls WHERE student_id = ? "
            "GROUP BY tool_name",
            (student_id,),
        ).fetchall()
        return {r["tool_name"]: int(r["c"]) for r in rows}
    finally:
        conn.close()


def get_max_tool_call_id(student_id: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM tool_calls WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        return int(row["m"])
    finally:
        conn.close()


def get_tool_calls_after(student_id: str, after_id: int) -> list[dict[str, Any]]:
    """after_id보다 나중에 기록된 도구 호출. 한 턴 동안 Agent가 무엇을 불렀는지 볼 때 쓴다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM tool_calls WHERE student_id = ? AND id > ? ORDER BY id ASC",
            (student_id, after_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_mode_observations(student_id: str, mode: str) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM observations WHERE student_id = ? AND mode = ? ORDER BY id ASC",
            (student_id, mode),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 모드별 10분 세션
# ---------------------------------------------------------------------------

def _session_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("images", "sentences"):
        try:
            d[key] = json.loads(d.get(key) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[key] = []
    d["auto_submitted"] = bool(d.get("auto_submitted"))
    return d


def get_session(student_id: str, mode: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM mode_sessions WHERE student_id = ? AND mode = ?",
            (student_id, mode),
        ).fetchone()
        return _session_to_dict(row) if row else None
    finally:
        conn.close()


def list_sessions(student_id: Optional[str] = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        if student_id:
            rows = conn.execute(
                "SELECT * FROM mode_sessions WHERE student_id = ? ORDER BY id ASC",
                (student_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mode_sessions ORDER BY student_id ASC, id ASC"
            ).fetchall()
        return [_session_to_dict(r) for r in rows]
    finally:
        conn.close()


def start_session(
    student_id: str, mode: str, started_at: str, deadline_at: str, images: list[str]
) -> dict[str, Any]:
    """이미 시작한 세션이면 새로 만들지 않고 기존 것을 돌려준다."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO mode_sessions
                (student_id, mode, started_at, deadline_at, images, sentences)
            VALUES (?, ?, ?, ?, ?, '[]')
            """,
            (student_id, mode, started_at, deadline_at, json.dumps(images, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return get_session(student_id, mode)  # type: ignore[return-value]


def submit_session(
    student_id: str, mode: str, sentences: list[dict[str, Any]], auto: bool
) -> bool:
    """처음 한 번만 제출로 인정한다. 이미 제출한 세션이면 False."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE mode_sessions
               SET submitted_at = ?, auto_submitted = ?, sentences = ?
             WHERE student_id = ? AND mode = ? AND submitted_at IS NULL
            """,
            (
                now_iso(),
                1 if auto else 0,
                json.dumps(sentences, ensure_ascii=False),
                student_id,
                mode,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 진단 결과
# ---------------------------------------------------------------------------

def save_diagnosis(student_id: str, mode: str, kind: str, payload: dict[str, Any]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO diagnoses (student_id, mode, kind, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, mode) DO UPDATE SET
                kind = excluded.kind,
                created_at = excluded.created_at,
                payload = excluded.payload
            """,
            (student_id, mode, kind, now_iso(), json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _diagnosis_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["payload"] = json.loads(d.get("payload") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["payload"] = {}
    return d


def get_diagnosis(student_id: str, mode: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM diagnoses WHERE student_id = ? AND mode = ?",
            (student_id, mode),
        ).fetchone()
        return _diagnosis_to_dict(row) if row else None
    finally:
        conn.close()


def get_all_diagnoses() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM diagnoses ORDER BY student_id ASC, id ASC"
        ).fetchall()
        return [_diagnosis_to_dict(r) for r in rows]
    finally:
        conn.close()
