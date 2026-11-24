"""Advanced Time & Attendance reporting API.

Mounted under both ``/api/attendance/advanced`` (the UI location under the
Attendance heading) and ``/api/reports/advanced`` for API compatibility.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require
from app.database import get_db
from app.models import (
    CompOff, Department, Designation, Employee, Location,
    OnDutyRequest, Regularization, Shift,
)
from app.services.advanced_reports import REPORT_MAP, build_report, report_metadata
from app.services.attendance import recompute_records
from app.services.attendance_engine import (
    EngineFilters, get_engine_config, save_engine_config,
)
from app.services.report_formatters import (
    to_csv_bytes, to_json_bytes, to_pdf_bytes, to_xlsx_bytes,
)
from app.utils import parse_date

router = APIRouter(tags=["Advanced reports"])

MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "pdf": "application/pdf",
}


class EngineConfigIn(BaseModel):
    pairing_mode: Optional[str] = None
    punch_debounce_minutes: Optional[int] = None
    half_day_hours: Optional[float] = None
    full_day_hours: Optional[float] = None
    ot_min_minutes: Optional[int] = None
    ot_round_minutes: Optional[int] = None
    ot_multiplier: Optional[float] = None
    holiday_ot_multiplier: Optional[float] = None
    weekoff_ot_multiplier: Optional[float] = None
    comp_off_hours_per_day: Optional[float] = None
    sandwich_rule: Optional[bool] = None
    continuous_absence_days: Optional[int] = None
    late_penalty_instances: Optional[int] = None
    late_penalty_days: Optional[float] = None
    authorized_devices: Optional[list[str]] = None


class RegularizationIn(BaseModel):
    employee_id: int
    record_date: str
    new_check_in: Optional[str] = None
    new_check_out: Optional[str] = None
    new_status: Optional[str] = None
    reason: str


class OnDutyIn(BaseModel):
    employee_id: int
    from_date: str
    to_date: str
    reason: str


class CompOffIn(BaseModel):
    employee_id: int
    work_date: str
    days: float = 1.0
    reason: Optional[str] = None
    expiry_date: Optional[str] = None


def _filters(
    department_id: Optional[int],
    location_id: Optional[int],
    designation_id: Optional[int],
    shift_id: Optional[int],
    employee_code: Optional[str],
) -> EngineFilters:
    return EngineFilters(
        department_id=department_id,
        location_id=location_id,
        designation_id=designation_id,
        shift_id=shift_id,
        employee_code=employee_code or None,
    )


def _dates(from_date: Optional[str], to_date: Optional[str]) -> tuple[date, date]:
    today = date.today()
    start = parse_date(from_date, today.replace(day=1))
    end = parse_date(to_date, today)
    if not start or not end or start > end:
        raise HTTPException(400, "Invalid date range")
    if (end - start).days > 366:
        raise HTTPException(400, "Advanced reports support a maximum range of 366 days")
    return start, end


@router.get("/meta")
def advanced_meta(db: Session = Depends(get_db), _=Depends(require("report.view", "attendance.view"))):
    return {
        "reports": report_metadata(),
        "departments": [{"id": d.id, "name": d.name} for d in db.query(Department).order_by(Department.name).all()],
        "locations": [{"id": item.id, "name": item.name} for item in db.query(Location).order_by(Location.name).all()],
        "designations": [{"id": d.id, "name": d.name} for d in db.query(Designation).order_by(Designation.name).all()],
        "shifts": [{"id": s.id, "name": s.name} for s in db.query(Shift).order_by(Shift.name).all()],
    }


@router.get("/report")
def advanced_report(
    report: str = "daily_basic",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    department_id: Optional[int] = None,
    location_id: Optional[int] = None,
    designation_id: Optional[int] = None,
    shift_id: Optional[int] = None,
    employee_code: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.view")),
):
    if report not in REPORT_MAP:
        raise HTTPException(400, f"Unknown report '{report}'")
    start, end = _dates(from_date, to_date)
    try:
        return build_report(db, report, start, end, _filters(
            department_id, location_id, designation_id, shift_id, employee_code,
        ))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/export")
def advanced_export(
    report: str = "daily_basic",
    format: str = "xlsx",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    department_id: Optional[int] = None,
    location_id: Optional[int] = None,
    designation_id: Optional[int] = None,
    shift_id: Optional[int] = None,
    employee_code: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.export", "report.view")),
):
    if report not in REPORT_MAP:
        raise HTTPException(400, f"Unknown report '{report}'")
    if format not in MEDIA_TYPES:
        raise HTTPException(400, "format must be xlsx, csv, json or pdf")
    start, end = _dates(from_date, to_date)
    payload = build_report(db, report, start, end, _filters(
        department_id, location_id, designation_id, shift_id, employee_code,
    ))
    content = {
        "xlsx": to_xlsx_bytes,
        "csv": to_csv_bytes,
        "json": to_json_bytes,
        "pdf": to_pdf_bytes,
    }[format](payload)
    return Response(
        content=content,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{payload["filename"]}.{format}"'},
    )


@router.get("/config")
def advanced_config_get(db: Session = Depends(get_db), _=Depends(require("report.view", "attendance.view"))):
    return get_engine_config(db).as_dict()


@router.put("/config")
def advanced_config_put(
    payload: EngineConfigIn,
    db: Session = Depends(get_db),
    _=Depends(require("attendance.manage")),
):
    current = get_engine_config(db).as_dict()
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("pairing_mode") not in (None, "strict", "first_last"):
        raise HTTPException(400, "pairing_mode must be strict or first_last")
    current.update({key: value for key, value in updates.items() if value is not None})
    return save_engine_config(db, current).as_dict()


@router.post("/recompute")
def advanced_recompute(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require("attendance.manage")),
):
    start, end = _dates(from_date, to_date)
    count = recompute_records(db, start, end)
    return {"message": f"Recomputed {count} attendance records", "records": count}


# -- Overlay data management -------------------------------------------------
@router.get("/regularizations")
def list_regularizations(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require("report.view", "attendance.view")),
):
    query = db.query(Regularization)
    start = parse_date(from_date, date.today() - timedelta(days=365))
    end = parse_date(to_date, date.today())
    if start:
        query = query.filter(Regularization.record_date >= start)
    if end:
        query = query.filter(Regularization.record_date <= end)
    return query.order_by(Regularization.record_date.desc()).limit(1000).all()


@router.post("/regularizations", status_code=201)
def create_regularization(
    payload: RegularizationIn,
    db: Session = Depends(get_db),
    user=Depends(require("attendance.manage")),
):
    record_date = parse_date(payload.record_date)
    if not record_date:
        raise HTTPException(400, "Invalid record_date")
    if not db.query(Employee).get(payload.employee_id):
        raise HTTPException(404, "Employee not found")
    item = Regularization(
        employee_id=payload.employee_id, record_date=record_date,
        new_check_in=payload.new_check_in, new_check_out=payload.new_check_out,
        new_status=payload.new_status, reason=payload.reason,
        status="approved", requested_by=user.id, approved_by=user.id,
        decided_at=datetime.now(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    recompute_records(db, record_date, record_date, payload.employee_id)
    return item


@router.get("/on-duty")
def list_on_duty(db: Session = Depends(get_db), _=Depends(require("report.view", "attendance.view"))):
    return db.query(OnDutyRequest).order_by(OnDutyRequest.from_date.desc()).limit(1000).all()


@router.post("/on-duty", status_code=201)
def create_on_duty(
    payload: OnDutyIn,
    db: Session = Depends(get_db),
    user=Depends(require("attendance.manage")),
):
    start, end = parse_date(payload.from_date), parse_date(payload.to_date)
    if not start or not end or start > end:
        raise HTTPException(400, "Invalid date range")
    item = OnDutyRequest(
        employee_id=payload.employee_id, from_date=start, to_date=end,
        reason=payload.reason, status="approved", approved_by=user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    recompute_records(db, start, end, payload.employee_id)
    return item


@router.get("/comp-offs")
def list_comp_offs(db: Session = Depends(get_db), _=Depends(require("report.view", "attendance.view"))):
    return db.query(CompOff).order_by(CompOff.work_date.desc()).limit(1000).all()


@router.post("/comp-offs", status_code=201)
def create_comp_off(
    payload: CompOffIn,
    db: Session = Depends(get_db),
    user=Depends(require("attendance.manage")),
):
    work_date = parse_date(payload.work_date)
    if not work_date:
        raise HTTPException(400, "Invalid work_date")
    existing = db.query(CompOff).filter_by(employee_id=payload.employee_id, work_date=work_date).first()
    if existing:
        raise HTTPException(400, "Comp-off already exists for this employee and date")
    item = CompOff(
        employee_id=payload.employee_id, work_date=work_date, days=payload.days,
        reason=payload.reason, status="approved", approved_by=user.id,
        expiry_date=parse_date(payload.expiry_date),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    recompute_records(db, work_date, work_date, payload.employee_id)
    return item
