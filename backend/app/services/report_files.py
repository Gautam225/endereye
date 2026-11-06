"""The files of a report: one PDF with a section per kept answer, and one Excel workbook with a
sheet per kept answer. Nothing here runs SQL; the caller hands over the results."""

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.conversations import MAX_SHEET_WIDTH, csv_cell

WIDE_FROM = 6  # a result with this many columns is printed on a landscape page
SHEET_NAME_LIMIT = 31
_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


@dataclass(slots=True)
class Section:
    title: str
    question: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str = ""  # set when the answer could not be refreshed: the section says so


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.0f}" if value == int(value) and abs(value) < 1e15 else f"{value:,.2f}"
    return str(value)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)  # text is data, never markup


def build_pdf(
    name: str, sections: list[Section], generated_at: datetime, *, max_rows: int
) -> bytes:
    sheet = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=sheet["BodyText"], fontSize=9, leading=12)
    note = ParagraphStyle("note", parent=body, textColor=colors.HexColor("#5b6472"), fontSize=8)
    cell = ParagraphStyle("cell", parent=body, fontSize=7.5, leading=9)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    wide = any(len(s.columns) >= WIDE_FROM for s in sections)
    page = landscape(A4) if wide else A4
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=page,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=name[:120],
        author="Eye of Ender",
    )
    width = page[0] - 28 * mm
    story: list[Any] = [
        _p(name, sheet["Title"]),
        _p(f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}", note),
        Spacer(1, 6 * mm),
    ]
    for section in sections:
        story.append(_p(section.title, sheet["Heading2"]))
        story.append(_p(f"Question: {section.question}", note))
        story.append(Spacer(1, 2 * mm))
        if section.error:
            story.append(_p(f"This section could not be refreshed: {section.error}", body))
        elif not section.rows:
            story.append(_p("The query returned no rows.", body))
        else:
            shown = section.rows[:max_rows]
            data = [[_p(c, head) for c in section.columns]] + [
                [_p(_cell_text(v), cell) for v in row] for row in shown
            ]
            table = Table(
                data,
                colWidths=[width / len(section.columns)] * len(section.columns),
                repeatRows=1,
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dae2")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(table)
            counted = f"{section.row_count:,} row{'s' if section.row_count != 1 else ''}"
            more = (
                f" ({len(shown):,} shown; the Excel file has more)"
                if len(shown) < section.row_count
                else ""
            )
            story.append(
                _p(counted + more + (", more than the limit" if section.truncated else ""), note)
            )
        story.append(Spacer(1, 7 * mm))
    doc.build(story)
    return out.getvalue()


def _sheet_name(title: str, taken: set[str]) -> str:
    base = _SHEET_BAD.sub(" ", title).strip()[:SHEET_NAME_LIMIT] or "Sheet"
    name, n = base, 2
    while name.lower() in taken:
        suffix = f" {n}"
        name, n = base[: SHEET_NAME_LIMIT - len(suffix)] + suffix, n + 1
    taken.add(name.lower())
    return name


def build_xlsx(name: str, sections: list[Section], generated_at: datetime) -> bytes:
    book = Workbook()
    summary = book.active
    summary.title = "Summary"
    summary.append(["Report", csv_cell(name)])
    summary.append(["Generated", generated_at.strftime("%Y-%m-%d %H:%M UTC")])
    summary.append([])
    summary.append(["Sheet", "Question", "Rows", "Note"])
    for cell in summary[4]:
        cell.font = Font(bold=True)
    taken = {"summary"}
    for section in sections:
        sheet_name = _sheet_name(section.title, taken)
        sheet = book.create_sheet(sheet_name)
        note = section.error or ("more rows than the limit" if section.truncated else "")
        summary.append([sheet_name, csv_cell(section.question), section.row_count, csv_cell(note)])
        if section.error:
            sheet.append(["This section could not be refreshed", csv_cell(section.error)])
            continue
        sheet.append([csv_cell(c) for c in section.columns])
        for row in section.rows:
            sheet.append([csv_cell(v) if isinstance(v, str) or v is None else v for v in row])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        for index, column in enumerate(section.columns, start=1):
            longest = max([len(column)] + [len(str(r[index - 1])) for r in section.rows[:200]])
            sheet.column_dimensions[get_column_letter(index)].width = min(
                MAX_SHEET_WIDTH, longest + 2
            )
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 70
    summary.column_dimensions["D"].width = 50
    for line in summary.iter_rows(min_row=5):
        line[1].alignment = Alignment(wrap_text=True, vertical="top")
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
