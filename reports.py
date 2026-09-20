"""
Excel (.xlsx) and Word (.docx) report generation for student observation
history, using openpyxl and python-docx.
"""

from __future__ import annotations

import io
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from docx import Document

HEADERS = [
    "차시(세션 ID)",
    "턴",
    "시간(UTC)",
    "이미지",
    "비교모드",
    "학생 질문",
    "AI 답변",
    "객관성 점수",
    "관찰 다양성",
    "과학 용어 수",
    "공간 범위",
    "적용 규칙 ID",
    "AI 단계",
]


def sanitize_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", name or "sheet")
    cleaned = cleaned.strip() or "sheet"
    return cleaned[:31]


def _row_values(row: dict[str, Any]) -> list[Any]:
    images = row.get("images") or []
    return [
        row.get("session_id"),
        row.get("turn_index"),
        row.get("timestamp"),
        ", ".join(images) if isinstance(images, list) else images,
        "예" if row.get("comparison_mode") else "아니오",
        row.get("question"),
        row.get("answer"),
        row.get("objectivity_score"),
        row.get("variety_count"),
        row.get("term_count"),
        row.get("spatial_scope"),
        row.get("pedagogy_rule_id"),
        row.get("ai_stage"),
    ]


def _autosize(ws) -> None:
    widths: dict[str, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            length = len(str(cell.value))
            col = cell.column_letter
            widths[col] = max(widths.get(col, 8), min(length + 2, 60))
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def _add_sheet(wb: Workbook, title: str, rows: list[dict[str, Any]]):
    ws = wb.create_sheet(title=sanitize_sheet_name(title))
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(_row_values(row))
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws)
    return ws


def build_student_xlsx(student_id: str, rows: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    _add_sheet(wb, student_id, rows)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_admin_xlsx(
    summary: list[dict[str, Any]],
    rows_by_student: dict[str, list[dict[str, Any]]],
) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    ws_summary = wb.create_sheet(title="학생목록")
    ws_summary.append(["학번", "대화 턴 수", "참여 세션 수", "첫 대화", "마지막 대화"])
    for cell in ws_summary[1]:
        cell.font = Font(bold=True)
    for s in summary:
        ws_summary.append(
            [s.get("student_id"), s.get("turn_count"), s.get("session_count"), s.get("first_at"), s.get("last_at")]
        )
    _autosize(ws_summary)
    for student_id, rows in rows_by_student.items():
        _add_sheet(wb, student_id, rows)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _add_student_section(doc: Document, student_id: str, rows: list[dict[str, Any]]) -> None:
    doc.add_heading(f"학생 {student_id} 관찰 대화 기록", level=1)
    if not rows:
        doc.add_paragraph("저장된 대화 기록이 없습니다.")
        return
    for row in rows:
        images = row.get("images") or []
        images_text = ", ".join(images) if isinstance(images, list) else (images or "-")
        doc.add_heading(
            f"[{row.get('session_id')}] 턴 {row.get('turn_index')} · {row.get('timestamp')}",
            level=2,
        )
        doc.add_paragraph(
            f"이미지: {images_text}  |  비교모드: {'예' if row.get('comparison_mode') else '아니오'}"
        )
        doc.add_paragraph(
            "객관성 점수: {0}  |  관찰 다양성: {1}  |  과학 용어 수: {2}  |  공간 범위: {3}  |  적용 규칙: {4} ({5}단계)".format(
                row.get("objectivity_score"),
                row.get("variety_count"),
                row.get("term_count"),
                row.get("spatial_scope"),
                row.get("pedagogy_rule_id") or "-",
                row.get("ai_stage") or "-",
            )
        )
        p = doc.add_paragraph()
        p.add_run("학생 질문: ").bold = True
        p.add_run(row.get("question") or "")
        p2 = doc.add_paragraph()
        p2.add_run("AI 답변: ").bold = True
        p2.add_run(row.get("answer") or "")
        doc.add_paragraph("")


def build_student_docx(student_id: str, rows: list[dict[str, Any]]) -> bytes:
    doc = Document()
    _add_student_section(doc, student_id, rows)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_admin_docx(
    summary: list[dict[str, Any]],
    rows_by_student: dict[str, list[dict[str, Any]]],
) -> bytes:
    doc = Document()
    doc.add_heading("전체 학생 관찰 대화 기록", level=0)
    for s in summary:
        doc.add_paragraph(
            "학번 {0}: 총 {1}턴, {2}개 세션 참여 (첫 대화 {3} ~ 마지막 대화 {4})".format(
                s.get("student_id"), s.get("turn_count"), s.get("session_count"), s.get("first_at"), s.get("last_at")
            )
        )
    doc.add_page_break()
    student_ids = list(rows_by_student.keys())
    for idx, student_id in enumerate(student_ids):
        _add_student_section(doc, student_id, rows_by_student[student_id])
        if idx < len(student_ids) - 1:
            doc.add_page_break()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()