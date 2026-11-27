from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user, require, scoped_employee_id
from app.config import settings
from app.database import get_db
from app.models import AttendanceRecord, Designation, Employee, PunchLog, User
from app.schemas import AttendanceListOut, AttendanceOut, PunchCreate, PunchListOut, PunchOut
from app.services.attendance import recompute_records
from app.services.report_formatters import to_pdf_bytes, to_xlsx_bytes
from app.utils import parse_date

router = APIRouter(prefix="/api/attendance", tags=["Attendance"])

EXPORT_LIMIT = 10000
EXPORT_MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _date_range(from_date: str | None, to_date: str | None, logs: bool = False):
    if logs:
        start = parse_date(from_date, date.today() - timedelta(days=settings.LOG_RETENTION_DAYS))
        end = parse_date(to_date, date.today() + timedelta(days=1))
    else:
        start = parse_date(from_date, date.today() - timedelta(days=30))
        end = parse_date(to_date, date.today())
    return start, end


def _log_query(
    db: Session, user: User, start, end, employee_id: int | None,
    designation_id: int | None = None,
):
    query = db.query(PunchLog)
    if designation_id:
        query = query.join(PunchLog.employee).filter(Employee.designation_id == designation_id)
    if start:
        query = query.filter(PunchLog.punch_time >= datetime.combine(start, time.min))
    if end:
        query = query.filter(PunchLog.punch_time < datetime.combine(end + timedelta(days=1), time.min))
    scoped = scoped_employee_id(user)
    if scoped:
        query = query.filter(PunchLog.employee_id == scoped)
    elif employee_id:
        query = query.filter(PunchLog.employee_id == employee_id)
    return query


def _record_query(
    db: Session, user: User, start, end, employee_id: int | None,
    department_id: int | None, status: str | None,
    designation_id: int | None = None,
):
    query = db.query(AttendanceRecord).join(Employee)
    if start:
        query = query.filter(AttendanceRecord.record_date >= start)
    if end:
        query = query.filter(AttendanceRecord.record_date <= end)
    scoped = scoped_employee_id(user)
    if scoped:
        query = query.filter(AttendanceRecord.employee_id == scoped)
    elif employee_id:
        query = query.filter(AttendanceRecord.employee_id == employee_id)
    if department_id:
        query = query.filter(Employee.department_id == department_id)
    if designation_id:
        query = query.filter(Employee.designation_id == designation_id)
    if status:
        # "attended" matches the dashboard's Present today KPI (present + half day).
        if status == "attended":
            query = query.filter(AttendanceRecord.status.in_(("present", "half_day")))
        elif status == "late":
            # Late arrivals are records with late minutes above the shift grace,
            # whatever their final status.
            query = query.filter(AttendanceRecord.late_minutes > 0)
        else:
            query = query.filter(AttendanceRecord.status == status)
    return query


def _employee_name_order():
    """Stable A–Z ordering for the Attendance page's Employee column."""
    return (
        func.lower(Employee.first_name).asc(),
        func.lower(Employee.last_name).asc(),
        Employee.employee_code.asc(),
    )


@router.get("/logs", response_model=PunchListOut)
def list_logs(
    from_date: str | None = None,
    to_date: str | None = None,
    employee_id: int | None = None,
    designation_id: int | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(require("attendance.view", "self.portal")),
):
    start, end = _date_range(from_date, to_date, logs=True)
    query = _log_query(db, user, start, end, employee_id, designation_id)
    total = query.count()
    items = query.order_by(PunchLog.punch_time.desc()).offset(skip).limit(min(limit, 1000)).all()
    return {"items": items, "total": total}


@router.post("/logs", response_model=PunchOut, status_code=201)
def create_punch(payload: PunchCreate, db: Session = Depends(get_db), _=Depends(require("attendance.manage"))):
    emp = db.query(Employee).get(payload.employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    punch = PunchLog(
        employee_id=emp.id,
        device_user_id=emp.device_user_id or f"EMP-{emp.id}",
        punch_time=payload.punch_time.replace(second=0, microsecond=0),
        punch_type=payload.punch_type,
        source=payload.source or "manual",
    )
    db.add(punch)
    db.commit()
    db.refresh(punch)
    recompute_records(db, punch.punch_time.date(), punch.punch_time.date(), employee_id=emp.id)
    return punch


@router.delete("/logs/{punch_id}", status_code=204)
def delete_punch(punch_id: int, db: Session = Depends(get_db), _=Depends(require("attendance.manage"))):
    punch = db.query(PunchLog).get(punch_id)
    if not punch:
        raise HTTPException(404, "Punch not found")
    punch_date = punch.punch_time.date()
    emp_id = punch.employee_id
    db.delete(punch)
    db.commit()
    if emp_id:
        recompute_records(db, punch_date, punch_date, employee_id=emp_id)


@router.get("/records", response_model=AttendanceListOut)
def list_records(
    from_date: str | None = None,
    to_date: str | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(require("attendance.view", "self.portal")),
):
    start, end = _date_range(from_date, to_date)
    query = _record_query(db, user, start, end, employee_id, department_id, status, designation_id)
    total = query.count()
    items = query.order_by(*_employee_name_order(), AttendanceRecord.record_date.desc()).offset(skip).limit(min(limit, 1000)).all()
    return {"items": items, "total": total}


@router.get("/export")
def export_attendance(
    view: str = "records",
    format: str = "xlsx",
    from_date: str | None = None,
    to_date: str | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    designation_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("attendance.view", "self.portal")),
):
    """Download the currently filtered Attendance page view as XLSX or PDF."""
    if view not in ("records", "logs"):
        raise HTTPException(400, "view must be records or logs")
    if format not in EXPORT_MEDIA_TYPES:
        raise HTTPException(400, "format must be xlsx or pdf")

    is_logs = view == "logs"
    start, end = _date_range(from_date, to_date, logs=is_logs)
    params = []
    if is_logs:
        query = _log_query(db, user, start, end, employee_id, designation_id).options(joinedload(PunchLog.employee))
        total = query.count()
        items = query.order_by(PunchLog.punch_time.desc()).limit(EXPORT_LIMIT).all()
        columns = [
            {"key": "punch_time", "label": "Time"},
            {"key": "employee", "label": "Employee"},
            {"key": "device_user_id", "label": "Device UID"},
            {"key": "punch_type", "label": "Type"},
            {"key": "source", "label": "Source"},
        ]
        rows = [{
            "punch_time": item.punch_time.strftime("%Y-%m-%d %H:%M") if item.punch_time else "",
            "employee": item.employee_name or f"Unmapped UID {item.device_user_id}",
            "device_user_id": item.device_user_id or "",
            "punch_type": item.punch_type.replace("_", " "),
            "source": item.source or "",
        } for item in items]
        title = "Raw punch logs"
    else:
        query = _record_query(db, user, start, end, employee_id, department_id, status, designation_id)
        total = query.count()
        items = query.order_by(
            *_employee_name_order(), AttendanceRecord.record_date.desc()
        ).limit(EXPORT_LIMIT).all()
        columns = [
            {"key": "record_date", "label": "Date"},
            {"key": "employee", "label": "Employee"},
            {"key": "shift_name", "label": "Shift"},
            {"key": "check_in", "label": "Check in"},
            {"key": "lunch_out", "label": "Lunch check out"},
            {"key": "lunch_in", "label": "Lunch check in"},
            {"key": "check_out", "label": "Check out"},
            {"key": "total_hours", "label": "Hours"},
            {"key": "overtime_hours", "label": "OT"},
            {"key": "late_minutes", "label": "Late (min)"},
            {"key": "status", "label": "Status"},
        ]
        rows = [{
            "record_date": item.record_date.isoformat() if item.record_date else "",
            "employee": f"{item.employee_name or ''} ({item.employee_code or ''})".strip(),
            "shift_name": item.shift_name or "",
            "check_in": item.check_in.strftime("%H:%M") if item.check_in else "",
            "lunch_out": item.lunch_out.strftime("%H:%M") if item.lunch_out else "",
            "lunch_in": item.lunch_in.strftime("%H:%M") if item.lunch_in else "",
            "check_out": item.check_out.strftime("%H:%M") if item.check_out else "",
            "total_hours": item.total_hours or 0,
            "overtime_hours": item.overtime_hours or 0,
            "late_minutes": item.late_minutes or 0,
            "status": item.status or "",
        } for item in items]
        title = "Daily attendance records"
        if department_id:
            params.append(f"Department ID: {department_id}")
        if status:
            params.append(f"Status: {status}")

    if employee_id:
        params.append(f"Employee ID: {employee_id}")
    if designation_id:
        designation = db.get(Designation, designation_id)
        params.append(f"Designation: {designation.name if designation else designation_id}")
    notes = ""
    if total > len(rows):
        notes = f"Showing first {len(rows):,} of {total:,} matching rows."

    payload = {
        "title": title,
        "period_label": f"{start or 'beginning'} – {end or 'today'}",
        "start": str(start or ""),
        "end": str(end or ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "columns": columns,
        "rows": rows,
        "summary": {"matching rows": total, "exported rows": len(rows)},
        "params": params,
        "notes": notes,
    }
    content = to_xlsx_bytes(payload) if format == "xlsx" else to_pdf_bytes(payload)
    filename = f"attendance_{view}_{start or 'from'}_{end or 'to'}"
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}.{format}"'},
    )


@router.post("/recompute")
def recompute(
    from_date: str,
    to_date: str,
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("attendance.manage")),
):
    start = parse_date(from_date)
    end = parse_date(to_date)
    if not start or not end:
        raise HTTPException(400, "from_date and to_date are required")
    count = recompute_records(db, start, end, employee_id)
    return {"message": f"Recomputed {count} attendance records", "records": count}


@router.post("/recompute-all")
def recompute_all(db: Session = Depends(get_db), _=Depends(require("attendance.manage"))):
    """Rebuild every stored attendance record from the raw punch history.

    Useful after changing punch-pairing rules or importing historical punches.
    """
    from sqlalchemy import func

    from app.models import PunchLog

    first_punch = db.query(func.min(PunchLog.punch_time)).scalar()
    if not first_punch:
        return {"message": "No punches available to recompute", "records": 0}
    count = recompute_records(db, first_punch.date(), date.today())
    return {
        "message": f"Recomputed {count} attendance records from {first_punch.date()}",
        "records": count,
    }


@router.get("/today", response_model=dict)
def today_summary(db: Session = Depends(get_db), user: User = Depends(require("attendance.view", "self.portal"))):
    today = date.today()
    query = db.query(AttendanceRecord).filter(AttendanceRecord.record_date == today)
    scoped = scoped_employee_id(user)
    if scoped:
        query = query.filter(AttendanceRecord.employee_id == scoped)
    records = query.all()
    return {
        "date": today.isoformat(),
        "present": sum(1 for r in records if r.status == "present"),
        "absent": sum(1 for r in records if r.status == "absent"),
        "half_day": sum(1 for r in records if r.status == "half_day"),
        "late": sum(1 for r in records if r.late_minutes > 0),
        "on_leave": sum(1 for r in records if r.status == "leave"),
        "total_hours": round(sum(r.total_hours or 0 for r in records), 2),
    }
