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
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
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
) -> int:
    conn = get_connection()
    try:
        turn_index = next_turn_index(conn, student_id)
        cur = conn.execute(
            """
            INSERT INTO observations (
                student_id, session_id, turn_index, timestamp, images,
                comparison_mode, question, answer, objectivity_score,
                term_count, variety_count, spatial_scope, pedagogy_rule_id, ai_stage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
