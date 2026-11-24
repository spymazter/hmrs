"""PDF rendering for attendance reports (tables, KPI summary and charts)."""

import io
from datetime import datetime

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

STATUS_KEYS = [
    ("present", "Present", "#16a34a"),
    ("half_day", "Half day", "#f59e0b"),
    ("absent", "Absent", "#dc2626"),
    ("leave", "Leave", "#0ea5e9"),
    ("week_off", "Week off", "#94a3b8"),
    ("holiday", "Holiday", "#8b5cf6"),
    ("no_data", "No data", "#cbd5e1"),
]


def _fmt(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _cell(value, style) -> Paragraph:
    return Paragraph(str(_fmt(value)).replace("&", "&amp;").replace("<", "&lt;"), style)


def _page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawRightString(landscape(A4)[0] - 14 * mm, 7 * mm, f"Page {doc.page}")
    canvas.drawString(14 * mm, 7 * mm, "HRMS · Attendance report")
    canvas.restoreState()


def _summary_table(summary: dict, styles, width: float) -> Table:
    labels = [
        ("Employees", summary.get("total")),
        ("Present / days", summary.get("present")),
        ("Absent / days", summary.get("absent")),
        ("Half days", summary.get("half_days")),
        ("Overtime hrs", summary.get("overtime_hours")),
        ("Total hours", summary.get("total_hours")),
    ]
    data = [[_cell(label, styles["head"]) for label, _ in labels],
            [_cell(value, styles["value"]) for _, value in labels]]
    table = Table(data, colWidths=[width / len(labels)] * len(labels), rowHeights=[18, 24])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _status_chart(counts: dict, styles) -> Drawing:
    drawing = Drawing(330, 175)
    drawing.add(String(8, 160, "Attendance status breakdown", fontName="Helvetica-Bold", fontSize=9.5,
                       fillColor=colors.HexColor("#0f172a")))
    values = [float(counts.get(key, 0) or 0) for key, _, _ in STATUS_KEYS]
    if sum(values) == 0:
        drawing.add(String(120, 80, "No data for this period", fontName="Helvetica", fontSize=9,
                           fillColor=colors.HexColor("#64748b")))
        return drawing

    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 92, 12, 140, 140
    pie.data = values
    pie.labels = [label for _, label, _ in STATUS_KEYS]
    pie.sideLabels = 1
    pie.slices.strokeWidth = 0.5
    pie.slices.strokeColor = colors.white
    for index, (_, _, hex_color) in enumerate(STATUS_KEYS):
        pie.slices[index].fillColor = colors.HexColor(hex_color)
    drawing.add(pie)
    return drawing


def _hours_chart(rows: list[dict], styles) -> Drawing:
    drawing = Drawing(390, 175)
    drawing.add(String(8, 160, "Top employees by total hours", fontName="Helvetica-Bold", fontSize=9.5,
                       fillColor=colors.HexColor("#0f172a")))
    top = sorted(rows, key=lambda r: float(r.get("total_hours") or 0), reverse=True)[:7]
    top = [r for r in top if float(r.get("total_hours") or 0) > 0]
    if not top:
        drawing.add(String(130, 80, "No hours recorded", fontName="Helvetica", fontSize=9,
                           fillColor=colors.HexColor("#64748b")))
        return drawing

    chart = HorizontalBarChart()
    chart.x, chart.y, chart.width, chart.height = 115, 15, 255, 135
    chart.data = [[float(r.get("total_hours") or 0) for r in top]]
    chart.categoryAxis.categoryNames = [
        str(r.get("employee_name") or r.get("employee_code") or "")[:20] for r in top
    ]
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.dx = -2
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontSize = 6.5
    chart.bars[0].fillColor = colors.HexColor("#4f46e5")
    chart.barSpacing = 2
    drawing.add(chart)
    return drawing


def build_report_pdf(report: dict) -> bytes:
    buffer = io.BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
        title="HRMS Attendance Report",
        author="HRMS",
    )
    width = page_size[0] - 28 * mm

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=16, spaceAfter=2,
                                 textColor=colors.HexColor("#0f172a"))
    subtitle_style = ParagraphStyle("ReportSubtitle", parent=styles["Normal"], fontSize=9.5,
                                    textColor=colors.HexColor("#475569"), spaceAfter=2)
    small_style = ParagraphStyle("ReportSmall", parent=styles["Normal"], fontSize=7.5,
                                 textColor=colors.HexColor("#64748b"))
    head_style = ParagraphStyle("CellHead", parent=styles["Normal"], fontSize=7, leading=8,
                                textColor=colors.white, fontName="Helvetica-Bold")
    value_style = ParagraphStyle("CellValue", parent=styles["Normal"], fontSize=12, leading=13,
                                 textColor=colors.HexColor("#0f172a"), fontName="Helvetica-Bold")
    data_head_style = ParagraphStyle("DataHead", parent=styles["Normal"], fontSize=6.8, leading=8,
                                     textColor=colors.white, fontName="Helvetica-Bold")
    data_style = ParagraphStyle("DataCell", parent=styles["Normal"], fontSize=6.4, leading=7.6,
                                textColor=colors.HexColor("#1e293b"))

    story = [
        Paragraph("Attendance report", title_style),
        Paragraph(f"{_fmt(report.get('period_label'))} &nbsp;·&nbsp; {_fmt(report.get('department_label'))}", subtitle_style),
        Paragraph(f"Generated {datetime.now().strftime('%d %b %Y, %I:%M %p')} · {len(report.get('rows', []))} employee rows", small_style),
        Spacer(1, 7),
        _summary_table(report.get("summary", {}), {"head": head_style, "value": value_style}, width),
        Spacer(1, 9),
        Table(
            [[_status_chart(report.get("status_counts", {}), styles),
              _hours_chart(report.get("rows", []), styles)]],
            colWidths=[width * 0.46, width * 0.54],
        ),
        PageBreak(),
    ]

    columns = report.get("columns", [])
    data = [[_cell(label, data_head_style) for _, label in columns]]
    for row in report.get("rows", []):
        data.append([_cell(row.get(key), data_style) for key, _ in columns])

    if columns:
        col_width = width / len(columns)
        table = Table(data, colWidths=[col_width] * len(columns), repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]
        for index in range(1, len(data)):
            if index % 2 == 0:
                style.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#f8fafc")))
        table.setStyle(TableStyle(style))
        story.append(table)
    else:
        story.append(Paragraph("No rows to display.", small_style))

    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return buffer.getvalue()
