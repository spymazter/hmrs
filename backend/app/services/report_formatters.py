"""Formatters for advanced attendance reports.

Data access, calculation and formatting stay separate: every formatter accepts
the payload returned by ``advanced_reports.build_report``.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STATUS_FILLS = {
    "P": "DCFCE7", "present": "DCFCE7",
    "HD": "FEF3C7", "half_day": "FEF3C7", "MIS": "FEF3C7", "missed_punch": "FEF3C7",
    "A": "FEE2E2", "absent": "FEE2E2",
    "L": "DBEAFE", "CL": "DBEAFE", "SL": "DBEAFE", "EL": "DBEAFE", "LWP": "FEE2E2",
    "OD": "E0E7FF", "CO": "E0E7FF",
    "WO": "F1F5F9", "week_off": "F1F5F9",
    "HL": "F3E8FF", "holiday": "F3E8FF",
}


def _columns(payload: dict) -> list[tuple[str, str]]:
    return [(c["key"], c["label"]) for c in payload.get("columns", [])]


def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def to_csv_bytes(payload: dict) -> bytes:
    columns = _columns(payload)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[label for _, label in columns],
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in payload.get("rows", []):
        writer.writerow({label: _csv_value(row.get(key)) for key, label in columns})
    return output.getvalue().encode("utf-8-sig")


def to_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def _autosize(worksheet, columns: int) -> None:
    for index in range(1, columns + 1):
        letter = get_column_letter(index)
        longest = 0
        for cell in worksheet[letter]:
            value = "" if cell.value is None else str(cell.value)
            longest = max(longest, min(len(value), 60))
        worksheet.column_dimensions[letter].width = max(11, min(42, longest + 3))


def _write_table(worksheet, headers: list[str], rows: list[list], status_column: int | None = None) -> None:
    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    worksheet.append(headers)
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    for row in rows:
        worksheet.append(row)
    for row_index in range(2, worksheet.max_row + 1):
        for cell in worksheet[row_index]:
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=False)
        if status_column:
            value = str(worksheet.cell(row=row_index, column=status_column).value or "")
            fill = STATUS_FILLS.get(value)
            if fill:
                worksheet.cell(row=row_index, column=status_column).fill = PatternFill("solid", fgColor=fill)

    worksheet.freeze_panes = "B2" if len(headers) > 1 else "A2"
    if worksheet.max_row >= 1 and worksheet.max_column >= 1:
        worksheet.auto_filter.ref = (
            f"A1:{get_column_letter(worksheet.max_column)}{worksheet.max_row}"
        )
    _autosize(worksheet, len(headers))


def _add_totals_row(worksheet, columns: list[tuple[str, str]], rows: list[dict]) -> None:
    numeric_indexes = []
    for index, (key, _label) in enumerate(columns, 1):
        values = [row.get(key) for row in rows]
        if values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            numeric_indexes.append((index, key))
    if not numeric_indexes:
        return
    worksheet.append([])
    total_row = worksheet.max_row + 1
    worksheet.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True, color="1E293B")
    for index, key in numeric_indexes:
        cell = worksheet.cell(row=total_row, column=index)
        cell.value = round(sum(float(row.get(key) or 0) for row in rows), 2)
        cell.font = Font(bold=True, color="1E293B")
        cell.fill = PatternFill("solid", fgColor="E2E8F0")


def to_xlsx_bytes(payload: dict) -> bytes:
    columns = _columns(payload)
    rows = payload.get("rows", [])
    workbook = Workbook()

    sheet = workbook.active
    sheet.title = "Report"
    status_index = next(
        (index for index, (key, _) in enumerate(columns, 1)
         if key in ("status_code", "status", "current_state")),
        None,
    )
    _write_table(
        sheet,
        [label for _, label in columns],
        [[_csv_value(row.get(key)) for key, _ in columns] for row in rows],
        status_column=status_index,
    )
    _add_totals_row(sheet, columns, rows)

    summary = workbook.create_sheet("Summary")
    summary_rows = []
    for key, value in (payload.get("summary") or {}).items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                summary_rows.append([f"{key}.{sub_key}", _csv_value(sub_value)])
        else:
            summary_rows.append([key, _csv_value(value)])
    _write_table(summary, ["Metric", "Value"], summary_rows)

    params = workbook.create_sheet("Parameters")
    param_rows = [
        ["Report", payload.get("title", "")],
        ["Period", payload.get("period_label", "")],
        ["From", payload.get("start", "")],
        ["To", payload.get("end", "")],
        ["Generated", payload.get("generated_at", "")],
        ["Notes", payload.get("notes", "")],
    ]
    param_rows += [[f"Filter {index}", value] for index, value in enumerate(payload.get("params", []), 1)]
    for key, value in (payload.get("config") or {}).items():
        param_rows.append([f"Engine: {key}", _csv_value(value)])
    _write_table(params, ["Parameter", "Value"], param_rows)

    charts = payload.get("charts") or {}
    status_sheet = workbook.create_sheet("Status counts")
    _write_table(
        status_sheet, ["Status", "Count"],
        [[key, value] for key, value in (charts.get("status_counts") or {}).items()],
    )
    hours_sheet = workbook.create_sheet("Daily hours")
    _write_table(
        hours_sheet, ["Date", "Hours"],
        [[row.get("date"), row.get("hours")] for row in charts.get("daily_hours", [])],
    )
    dept_sheet = workbook.create_sheet("Department hours")
    _write_table(
        dept_sheet, ["Department", "Hours"],
        [[row.get("department"), row.get("hours")] for row in charts.get("department_hours", [])],
    )

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _pdf_cell(value, style) -> Paragraph:
    text = _csv_value(value).replace("&", "&amp;").replace("<", "&lt;")
    return Paragraph(text, style)


def to_pdf_bytes(payload: dict) -> bytes:
    buffer = io.BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buffer, pagesize=page_size,
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=payload.get("title", "Advanced attendance report"), author="HRMS",
    )
    width = page_size[0] - 24 * mm
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=15, spaceAfter=2,
                                 textColor=colors.HexColor("#0F172A"))
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=9,
                                    textColor=colors.HexColor("#475569"), spaceAfter=2)
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=7.5,
                                 textColor=colors.HexColor("#64748B"))
    head_style = ParagraphStyle("Head", parent=styles["Normal"], fontSize=6.2, leading=7.4,
                                textColor=colors.white, fontName="Helvetica-Bold")
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=6, leading=7.2,
                                textColor=colors.HexColor("#1E293B"))

    def decorate(canvas, document):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#1E293B"))
        canvas.rect(0, page_size[1] - 9 * mm, page_size[0], 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(12 * mm, page_size[1] - 6 * mm, "HRMS · TIME & ATTENDANCE")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(page_size[0] - 12 * mm, page_size[1] - 6 * mm,
                               payload.get("title", "Advanced report"))
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(12 * mm, 7 * mm, "Prepared by: ____________________    Approved by: ____________________")
        canvas.drawRightString(page_size[0] - 12 * mm, 7 * mm, f"Page {document.page}")
        canvas.restoreState()

    story = [
        Paragraph(payload.get("title", "Advanced report"), title_style),
        Paragraph(
            f"{payload.get('period_label', '')} &nbsp;·&nbsp; "
            + ("; ".join(payload.get("params", [])) or "All filters"),
            subtitle_style,
        ),
        Paragraph(
            f"Generated {payload.get('generated_at', datetime.now().isoformat(timespec='seconds'))}"
            f" · {len(payload.get('rows', []))} rows"
            + (f" · {payload['notes']}" if payload.get("notes") else ""),
            small_style,
        ),
        Spacer(1, 7),
    ]

    summary = payload.get("summary") or {}
    summary_items = [(key, value) for key, value in summary.items() if not isinstance(value, dict)]
    if summary_items:
        data = [
            [_pdf_cell(key.replace("_", " ").title(), head_style) for key, _ in summary_items],
            [_pdf_cell(value, cell_style) for _, value in summary_items],
        ]
        table = Table(data, colWidths=[width / len(summary_items)] * len(summary_items), rowHeights=[16, 20])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F1F5F9")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        story += [table, Spacer(1, 9)]

    columns = _columns(payload)
    if columns:
        data = [[_pdf_cell(label, head_style) for _, label in columns]]
        for row in payload.get("rows", []):
            data.append([_pdf_cell(row.get(key), cell_style) for key, _ in columns])
        col_width = width / len(columns)
        table = Table(data, colWidths=[col_width] * len(columns), repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for index in range(1, len(data)):
            if index % 2 == 0:
                style.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#F8FAFC")))
        table.setStyle(TableStyle(style))
        story.append(table)
    else:
        story.append(Paragraph("No rows to display.", small_style))

    story.append(Spacer(1, 12))
    signature = Table(
        [[Paragraph("Prepared by: ____________________<br/>Name: ____________________<br/>Date: __________", small_style),
          Paragraph("Approved by: ____________________<br/>Name: ____________________<br/>Date: __________", small_style)]],
        colWidths=[width / 2, width / 2],
    )
    story.append(signature)

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
