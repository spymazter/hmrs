from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import require
from app.database import get_db
from app.models import AttendanceRecord, Department, Designation, Employee
from app.services.attendance import recompute_records
from app.services.attendance_engine import EngineFilters
from app.services.report_pdf import STATUS_KEYS, build_report_pdf
from app.utils import month_bounds, parse_date, to_csv, week_bounds

router = APIRouter(prefix="/api/reports", tags=["Reports"])

DAILY_COLUMNS = [
    ("employee_code", "Code"), ("employee_name", "Employee"), ("department", "Department"),
    ("date", "Date"), ("shift", "Shift"), ("check_in", "In"), ("check_out", "Out"),
    ("total_hours", "Hours"), ("overtime_hours", "OT"), ("late_minutes", "Late"),
    ("status", "Status"),
]
AGGREGATE_COLUMNS = [
    ("employee_code", "Code"), ("employee_name", "Employee"), ("department", "Department"),
    ("days_present", "Present days"), ("days_absent", "Absent"), ("half_days", "Half days"),
    ("leave_days", "Leave"), ("week_offs", "Week offs"), ("holiday_days", "Holidays"),
    ("total_hours", "Total hours"), ("overtime_hours", "OT hours"),
    ("late_minutes", "Late min"), ("status", "Data"),
]


def _records(
    db: Session, start: date, end: date, department_id: int | None,
    designation_id: int | None = None, employee_id: int | None = None,
):
    query = (
        db.query(AttendanceRecord)
        .join(Employee)
        .filter(AttendanceRecord.record_date >= start, AttendanceRecord.record_date <= end)
    )
    if department_id:
        query = query.filter(Employee.department_id == department_id)
    if designation_id:
        query = query.filter(Employee.designation_id == designation_id)
    if employee_id:
        query = query.filter(AttendanceRecord.employee_id == employee_id)
    return query.order_by(Employee.employee_code, AttendanceRecord.record_date).all()


def _employees(
    db: Session, start: date, end: date, department_id: int | None,
    designation_id: int | None = None,
) -> list[Employee]:
    """All current employees for the filter, plus anyone with records in the period.

    Including employees with no attendance rows is what makes a department or
    designation report list everyone in scope, not only those who punched.
    """
    with_records = (
        db.query(AttendanceRecord.employee_id)
        .join(Employee)
        .filter(AttendanceRecord.record_date >= start, AttendanceRecord.record_date <= end)
    )
    if department_id:
        with_records = with_records.filter(Employee.department_id == department_id)
    if designation_id:
        with_records = with_records.filter(Employee.designation_id == designation_id)

    query = db.query(Employee).filter(
        or_(Employee.status == "active", Employee.id.in_(select(with_records.subquery().c.employee_id)))
    )
    if department_id:
        query = query.filter(Employee.department_id == department_id)
    if designation_id:
        query = query.filter(Employee.designation_id == designation_id)
    return query.order_by(Employee.employee_code).all()


def _daily_rows(employees, records_by_employee, day: date) -> list[dict]:
    rows = []
    for emp in employees:
        record = (records_by_employee.get(emp.id) or [None])[0]
        rows.append({
            "employee_code": emp.employee_code,
            "employee_name": emp.full_name,
            "department": emp.department_name or "",
            "date": day.isoformat(),
            "shift": record.shift_name if record and record.shift_name else (emp.shift_name or ""),
            "check_in": record.check_in.strftime("%H:%M") if record and record.check_in else "",
            "check_out": record.check_out.strftime("%H:%M") if record and record.check_out else "",
            "total_hours": record.total_hours if record else 0,
            "overtime_hours": record.overtime_hours if record else 0,
            "late_minutes": record.late_minutes if record else 0,
            "status": record.status if record else "no_data",
            "remarks": record.remarks if record else "",
            "joined_on": emp.date_of_joining.isoformat() if emp.date_of_joining else "",
            "has_data": bool(record),
        })
    return rows


def _aggregate_rows(employees, records_by_employee) -> list[dict]:
    rows = []
    for emp in employees:
        records = records_by_employee.get(emp.id, [])
        row = {
            "employee_code": emp.employee_code,
            "employee_name": emp.full_name,
            "department": emp.department_name or "",
            "days_present": 0.0, "days_absent": 0, "half_days": 0,
            "leave_days": 0, "week_offs": 0, "holiday_days": 0,
            "total_hours": 0.0, "overtime_hours": 0.0, "late_minutes": 0,
            "joined_on": emp.date_of_joining.isoformat() if emp.date_of_joining else "",
            "has_data": bool(records),
            "status": "ok" if records else "no_data",
        }
        for r in records:
            if r.status == "present":
                row["days_present"] += 1
            elif r.status == "half_day":
                row["days_present"] += 0.5
                row["half_days"] += 1
            elif r.status == "absent":
                row["days_absent"] += 1
            elif r.status == "week_off":
                row["week_offs"] += 1
            elif r.status == "leave":
                row["leave_days"] += 1
            elif r.status == "holiday":
                row["holiday_days"] += 1
            row["total_hours"] += r.total_hours or 0
            row["overtime_hours"] += r.overtime_hours or 0
            row["late_minutes"] += r.late_minutes or 0

        row["total_hours"] = round(row["total_hours"], 2)
        row["overtime_hours"] = round(row["overtime_hours"], 2)
        row["days_present"] = round(row["days_present"], 1)
        rows.append(row)
    return rows


def _summary(rows: list[dict], records: list, daily: bool, status_counts: dict) -> dict:
    total_hours = round(sum(float(r.get("total_hours") or 0) for r in rows), 2)
    overtime = round(sum(float(r.get("overtime_hours") or 0) for r in rows), 2)
    if daily:
        present = round(sum(
            1 if r["status"] == "present" else 0.5 if r["status"] == "half_day" else 0
            for r in rows
        ), 1)
        absent = status_counts.get("absent", 0)
        late = sum(1 for r in rows if r.get("late_minutes", 0) > 0)
    else:
        present = round(sum(float(r.get("days_present") or 0) for r in rows), 1)
        absent = sum(int(r.get("days_absent") or 0) for r in rows)
        late = sum(1 for r in records if r.late_minutes and r.late_minutes > 0)

    return {
        "total": len(rows),
        "with_data": sum(1 for r in rows if r.get("has_data")),
        "present": present,
        "absent": absent,
        "half_days": status_counts.get("half_day", 0),
        "leave": status_counts.get("leave", 0),
        "week_offs": status_counts.get("week_off", 0),
        "holidays": status_counts.get("holiday", 0),
        "late": late,
        "late_minutes": sum(int(r.get("late_minutes") or 0) for r in rows),
        "total_hours": total_hours,
        "overtime_hours": overtime,
        "avg_hours": round(total_hours / len(rows), 2) if rows else 0,
    }


def _period_bounds(
    report_type: str,
    date_str: str | None,
    year: int | None,
    month: int | None,
    week: int | None,
) -> tuple[date, date, str, str]:
    today = date.today()
    if report_type == "daily":
        day = parse_date(date_str, today)
        return (
            day, day, day.strftime("%d %B %Y"), f"attendance_daily_{day.isoformat()}"
        )
    if report_type == "monthly":
        year = year or today.year
        month = month or today.month
        start, end = month_bounds(year, month)
        return (
            start, end, start.strftime("%B %Y"), f"attendance_monthly_{year}{month:02d}"
        )
    if report_type == "weekly":
        year = year or today.isocalendar().year
        week = week or today.isocalendar().week
        start, end = week_bounds(year, week)
        return (
            start, end, f"ISO Week {week}, {year}", f"attendance_weekly_{year}W{week:02d}"
        )
    raise HTTPException(400, "type must be daily, weekly or monthly")


def _build_payload(
    db: Session,
    report_type: str,
    date_str: str | None,
    year: int | None,
    month: int | None,
    week: int | None,
    department_id: int | None,
    designation_id: int | None = None,
) -> dict:
    start, end, period_label, filename = _period_bounds(
        report_type, date_str, year, month, week
    )

    department = db.query(Department).get(department_id) if department_id else None
    department_label = department.name if department else "All departments"
    designation = db.query(Designation).get(designation_id) if designation_id else None
    designation_label = designation.name if designation else "All designations"

    records = _records(db, start, end, department_id, designation_id)
    records_by_employee = defaultdict(list)
    for record in records:
        records_by_employee[record.employee_id].append(record)

    employees = _employees(db, start, end, department_id, designation_id)
    daily = report_type == "daily"
    rows = (_daily_rows(employees, records_by_employee, start) if daily
            else _aggregate_rows(employees, records_by_employee))

    status_counts = {key: 0 for key, _, _ in STATUS_KEYS}
    for record in records:
        if record.status in status_counts:
            status_counts[record.status] += 1
    status_counts["no_data"] = sum(1 for r in rows if not r.get("has_data"))

    return {
        "type": report_type,
        "date": start.isoformat() if daily else None,
        "period": period_label,
        "period_label": period_label,
        "department_label": department_label,
        "designation_label": designation_label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "daily": daily,
        "rows": rows,
        "summary": _summary(rows, records, daily, status_counts),
        "status_counts": status_counts,
        "columns": DAILY_COLUMNS if daily else AGGREGATE_COLUMNS,
        "filename": filename,
    }


@router.post("/recompute")
def recompute_report(
    report_type: str,
    date_str: str | None = None,
    year: int | None = None,
    month: int | None = None,
    week: int | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("attendance.manage")),
):
    """Rebuild stored attendance for the exact period shown by the report."""
    try:
        start, end, _, _ = _period_bounds(report_type, date_str, year, month, week)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid report period: {exc}")
    count = recompute_records(
        db, start, end,
        filters=EngineFilters(department_id=department_id, designation_id=designation_id),
    )
    return {
        "message": f"Recomputed {count} attendance records for {start} to {end}",
        "records": count,
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
    }


@router.get("/daily")
def daily_report(
    date_str: str | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.view")),
):
    return _build_payload(db, "daily", date_str, None, None, None, department_id, designation_id)


@router.get("/weekly")
def weekly_report(
    year: int | None = None,
    week: int | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.view")),
):
    return _build_payload(db, "weekly", None, year, None, week, department_id, designation_id)


@router.get("/monthly")
def monthly_report(
    year: int | None = None,
    month: int | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.view")),
):
    return _build_payload(db, "monthly", None, year, month, None, department_id, designation_id)


@router.get("/export")
def export_report(
    type: str = "daily",
    date_str: str | None = None,
    year: int | None = None,
    month: int | None = None,
    week: int | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.export", "report.view")),
):
    payload = _build_payload(db, type, date_str, year, month, week, department_id, designation_id)
    columns = payload["columns"]
    labeled_rows = [
        {label: row.get(key, "") for key, label in columns}
        for row in payload["rows"]
    ]
    return to_csv(labeled_rows, f"{payload['filename']}.csv", [label for _, label in columns])


@router.get("/pdf")
def export_report_pdf(
    type: str = "daily",
    date_str: str | None = None,
    year: int | None = None,
    month: int | None = None,
    week: int | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.export", "report.view")),
):
    payload = _build_payload(db, type, date_str, year, month, week, department_id, designation_id)
    content = build_report_pdf(payload)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{payload["filename"]}.pdf"'},
    )
