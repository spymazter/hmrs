"""Salary slip PDF generation."""

import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import settings
from app.utils import round2


def _money(value) -> str:
    return f"{round2(value):,.2f}"


def generate_payslip_pdf(payslip, db) -> str:
    os.makedirs(settings.PDF_DIR, exist_ok=True)
    emp = payslip.employee
    period = payslip.period
    safe_code = (emp.employee_code if emp else "EMP").replace("/", "-")
    filename = f"payslip_{safe_code}_{period.year}{period.month:02d}_{payslip.id}.pdf"
    path = os.path.join(settings.PDF_DIR, filename)

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleCustom", parent=styles["Title"], fontSize=18,
        textColor=colors.HexColor("#312e81"), spaceAfter=2,
    )
    subtitle = ParagraphStyle(
        "Sub", parent=styles["Normal"], fontSize=9,
        textColor=colors.HexColor("#64748b"), alignment=1,
    )
    normal = ParagraphStyle("NormalSmall", parent=styles["Normal"], fontSize=9)
    heading = ParagraphStyle(
        "HeadingSmall", parent=styles["Normal"], fontSize=11,
        textColor=colors.HexColor("#312e81"), spaceBefore=8, spaceAfter=4,
    )

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Salary Slip - {safe_code} - {period.name}",
    )
    story = [
        Paragraph("HRMS PAYROLL", title),
        Paragraph("Salary Slip / Payslip", subtitle),
        Spacer(1, 8 * mm),
    ]

    info = [
        ["Employee Name", emp.full_name if emp else "-", "Employee Code", emp.employee_code if emp else "-"],
        ["Department", emp.department_name if emp and emp.department_name else "-", "Designation", emp.designation_name if emp and emp.designation_name else "-"],
        ["Pay Period", period.name, "Working Days", str(payslip.working_days)],
        ["Days Present", str(payslip.days_present), "Paid Days", str(payslip.paid_days)],
    ]
    info_table = Table(info, colWidths=[32 * mm, 55 * mm, 32 * mm, 55 * mm])
    info_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [info_table, Paragraph("Earnings & Deductions", heading)]

    earnings = [
        ("Basic Salary", payslip.basic),
        ("House Rent Allowance", payslip.hra),
        ("Allowances", payslip.allowances),
    ]
    deductions = [
        ("Provident Fund", payslip.provident_fund),
        ("ESI", payslip.esi),
        ("Professional Tax", payslip.professional_tax),
        ("Income Tax", payslip.income_tax),
        ("Other Deductions", payslip.other_deductions),
    ]
    rows = [["Earnings", "Amount", "Deductions", "Amount"]]
    for index in range(max(len(earnings), len(deductions))):
        e_name, e_amount = earnings[index] if index < len(earnings) else ("", "")
        d_name, d_amount = deductions[index] if index < len(deductions) else ("", "")
        rows.append([
            e_name, _money(e_amount) if e_name else "",
            d_name, _money(d_amount) if d_name else "",
        ])
    rows.append(["Gross Salary", _money(payslip.gross_salary), "Total Deductions", _money(payslip.total_deductions)])

    table = Table(rows, colWidths=[52 * mm, 35 * mm, 52 * mm, 35 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#312e81")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2ff")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    net_table = Table(
        [[Paragraph("<b>NET PAY FOR THE MONTH</b>", normal), Paragraph(f"<b>Rs. {_money(payslip.net_salary)}</b>", normal)]],
        colWidths=[110 * mm, 64 * mm],
    )
    net_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#dcfce7")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#16a34a")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [
        net_table,
        Spacer(1, 16 * mm),
        Paragraph("This is a computer-generated salary slip and does not require a signature.", normal),
        Spacer(1, 10 * mm),
        Table([["Authorised Signatory", "Employee Signature"]], colWidths=[87 * mm, 87 * mm]),
    ]
    doc.build(story)

    payslip.pdf_filename = filename
    return filename
