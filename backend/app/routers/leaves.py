import csv
import io
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from app.auth import can, is_admin, require
from app.database import get_db
from app.models import (
    CompOff, Employee, LeaveQuota, LeaveRequest, LeaveType, RestrictedHoliday, User,
)
from app.schemas import (
    LeaveBalanceOut, LeaveQuotaIn, LeaveQuotaOut, LeaveRejectIn, LeaveRequestCreate,
    LeaveRequestOut, LeaveVerifyIn, RestrictedHolidayIn, RestrictedHolidayOut,
)
from app.services.attendance import recompute_records
from app.services.comp_off import balance_for, accrued_rows
from app.services.leave_workflow import (
    can_apply_for, code_for, leave_balances, leave_type_by_code, log_action,
    manager_approve, final_approve, reject_leave, validate_application,
    verify_leave, visible_employee_ids,
)
from app.utils import parse_date, round2, to_csv

router = APIRouter(prefix="/api/leaves", tags=["Leaves"])

QUOTA_HEADERS = ["Employee Code", "Employee Name", "Leave Type", "Leave Code", "Year", "Days"]
RH_HEADERS = ["Date", "Name", "Year", "Reason"]


def _norm(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


async def _read_rows(file: UploadFile) -> list[dict]:
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = book.active
        values = list(sheet.iter_rows(values_only=True))
        if not values:
            return []
        headers = [str(value).strip() if value is not None else "" for value in values[0]]
        return [
            dict(zip(headers, row))
            for row in values[1:]
            if any(value not in (None, "") for value in row)
        ]
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [
            row for row in csv.DictReader(io.StringIO(text))
            if any(value not in (None, "") for value in row.values())
        ]
    raise HTTPException(400, "Unsupported file type — upload a .csv or .xlsx file")


def _value(row: dict, *names: str):
    lookup = {_norm(key): value for key, value in row.items()}
    for name in names:
        value = lookup.get(_norm(name))
        if value not in (None, ""):
            return value
    return None


def _find_employee(db: Session, row: dict) -> Employee | None:
    code = str(_value(row, "Employee Code", "Employee ID", "Code", "UID") or "").strip()
    if not code:
        return None
    employee = db.query(Employee).filter(Employee.employee_code.ilike(code)).first()
    if employee:
        return employee
    if code.isdigit():
        return db.query(Employee).filter(Employee.device_user_id == str(int(code))).first()
    return None


def _find_leave_type(db: Session, row: dict) -> LeaveType | None:
    code = str(_value(row, "Leave Code", "Code", "Leave Type") or "").strip()
    label = str(_value(row, "Leave Type", "Name") or "").strip()
    found = leave_type_by_code(db, code) if code else None
    if found and found.is_active:
        return found
    if label:
        return db.query(LeaveType).filter(
            LeaveType.name.ilike(label), LeaveType.is_active.is_(True)
        ).first()
    return None


def _template(headers: list[str], filename: str, file_format: str):
    rows = [{header: "" for header in headers}]
    if file_format == "xlsx":
        book = Workbook()
        sheet = book.active
        sheet.title = "Template"
        sheet.append(headers)
        output = io.BytesIO()
        book.save(output)
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
        )
    return to_csv(rows, f"{filename}.csv", headers)


def _visible(db: Session, user: User, employee_id: int | None) -> None:
    ids = visible_employee_ids(db, user)
    if ids is not None and employee_id not in ids:
        raise HTTPException(403, "You do not have access to this employee's leave data")


@router.get("/requests", response_model=list[LeaveRequestOut])
def list_requests(
    status: str | None = None,
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.view", "self.portal")),
):
    query = db.query(LeaveRequest)
    ids = visible_employee_ids(db, user)
    if ids is not None:
        query = query.filter(LeaveRequest.employee_id.in_(ids or [-1]))
    if employee_id:
        _visible(db, user, employee_id)
        query = query.filter(LeaveRequest.employee_id == employee_id)
    if status:
        query = query.filter(LeaveRequest.status == status)
    return query.order_by(LeaveRequest.from_date.desc()).all()


@router.post("/requests", response_model=LeaveRequestOut, status_code=201)
def apply_leave(
    payload: LeaveRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.manage", "self.portal")),
):
    employee = db.get(Employee, payload.employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")
    if not can_apply_for(db, user, employee):
        raise HTTPException(403, "You can only apply for yourself or your direct reports")
    leave_type = db.get(LeaveType, payload.leave_type_id)
    if not leave_type or not leave_type.is_active:
        raise HTTPException(404, "Leave type not found")
    validate_application(
        db, employee, leave_type, payload.from_date, payload.to_date,
        payload.restricted_holiday_id,
    )
    values = payload.model_dump()
    values["status"] = "pending"
    leave = LeaveRequest(**values)
    db.add(leave)
    db.commit()
    db.refresh(leave)
    log_action(db, user, "leave.applied", leave)
    db.commit()
    return leave


@router.get("/balances", response_model=list[LeaveBalanceOut])
def list_balances(
    year: int = Query(default_factory=lambda: date.today().year),
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.view", "self.portal")),
):
    if employee_id is None:
        employee_id = user.employee_id
    if not employee_id:
        raise HTTPException(400, "employee_id is required")
    _visible(db, user, employee_id)
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")
    return leave_balances(db, employee, year)


@router.get("/quotas", response_model=list[LeaveQuotaOut])
def list_quotas(
    year: int = Query(default_factory=lambda: date.today().year),
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(require("leave.view", "self.portal")),
):
    query = (
        db.query(LeaveQuota)
        .join(LeaveType, LeaveType.id == LeaveQuota.leave_type_id)
        .filter(LeaveQuota.year == year, LeaveType.is_active.is_(True))
    )
    if employee_id:
        query = query.filter(
            ((LeaveQuota.scope == "employee") & (LeaveQuota.scope_value == str(employee_id)))
            | (LeaveQuota.scope == "global")
        )
    return query.order_by(LeaveQuota.scope, LeaveQuota.scope_value, LeaveQuota.leave_type_id).all()


@router.post("/quotas", response_model=LeaveQuotaOut, status_code=201)
def upsert_quota(
    payload: LeaveQuotaIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.quota.manage")),
):
    if payload.year < 2000 or payload.year > 2100:
        raise HTTPException(400, "Invalid year")
    if payload.days < 0:
        raise HTTPException(400, "Days cannot be negative")
    leave_type = db.get(LeaveType, payload.leave_type_id)
    if not leave_type or not leave_type.is_active:
        raise HTTPException(404, "Leave type not found")
    scope = "global"
    scope_value = "ALL"
    if payload.employee_id:
        if not db.get(Employee, payload.employee_id):
            raise HTTPException(404, "Employee not found")
        scope = "employee"
        scope_value = str(payload.employee_id)
    row = (
        db.query(LeaveQuota)
        .filter(
            LeaveQuota.scope == scope,
            LeaveQuota.scope_value == scope_value,
            LeaveQuota.leave_type_id == payload.leave_type_id,
            LeaveQuota.year == payload.year,
        )
        .first()
    )
    if not row:
        row = LeaveQuota(
            scope=scope, scope_value=scope_value, leave_type_id=payload.leave_type_id,
            year=payload.year, employee_id=payload.employee_id,
        )
        db.add(row)
    row.days = payload.days
    row.employee_id = payload.employee_id
    row.updated_by = user.id
    db.commit()
    db.refresh(row)
    return row


@router.get("/quotas/template")
def quota_template(file_format: str = "csv", _=Depends(require("leave.quota.manage"))):
    return _template(QUOTA_HEADERS, "leave_quotas_template", file_format)


@router.post("/quotas/upload")
async def upload_quotas(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.quota.manage")),
):
    rows = await _read_rows(file)
    created = 0
    skipped: list[str] = []
    for index, row in enumerate(rows, 2):
        employee = _find_employee(db, row)
        leave_type = _find_leave_type(db, row)
        try:
            year = int(float(_value(row, "Year") or date.today().year))
            days = float(_value(row, "Days", "Quota") or 0)
        except (TypeError, ValueError):
            skipped.append(f"Row {index}: invalid year or days")
            continue
        if not leave_type or year < 2000 or year > 2100 or days < 0:
            skipped.append(f"Row {index}: invalid leave type, year or days")
            continue
        scope = "global"
        scope_value = "ALL"
        if employee:
            scope = "employee"
            scope_value = str(employee.id)
        existing = (
            db.query(LeaveQuota)
            .filter(
                LeaveQuota.scope == scope,
                LeaveQuota.scope_value == scope_value,
                LeaveQuota.leave_type_id == leave_type.id,
                LeaveQuota.year == year,
            )
            .first()
        )
        if not existing:
            existing = LeaveQuota(
                scope=scope, scope_value=scope_value, leave_type_id=leave_type.id,
                year=year, employee_id=employee.id if employee else None,
            )
            db.add(existing)
            created += 1
        existing.days = days
        existing.updated_by = user.id
    db.commit()
    return {
        "rows": len(rows), "created": created, "updated": len(rows) - len(skipped) - created,
        "skipped": skipped[:20],
    }


@router.get("/restricted-holidays", response_model=list[RestrictedHolidayOut])
def list_restricted_holidays(
    year: int = Query(default_factory=lambda: date.today().year),
    db: Session = Depends(get_db),
    _=Depends(require("leave.view", "self.portal")),
):
    return (
        db.query(RestrictedHoliday)
        .filter(RestrictedHoliday.year == year)
        .order_by(RestrictedHoliday.holiday_date)
        .all()
    )


@router.post("/restricted-holidays", response_model=RestrictedHolidayOut, status_code=201)
def create_restricted_holiday(
    payload: RestrictedHolidayIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.quota.manage")),
):
    if db.query(RestrictedHoliday).filter(RestrictedHoliday.holiday_date == payload.holiday_date).first():
        raise HTTPException(400, "A restricted holiday already exists on that date")
    item = RestrictedHoliday(**payload.model_dump(), created_by=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/restricted-holidays/template")
def restricted_holiday_template(file_format: str = "csv", _=Depends(require("leave.quota.manage"))):
    return _template(RH_HEADERS, "restricted_holidays_template", file_format)


@router.post("/restricted-holidays/upload")
async def upload_restricted_holidays(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.quota.manage")),
):
    rows = await _read_rows(file)
    created = 0
    updated = 0
    skipped: list[str] = []
    for index, row in enumerate(rows, 2):
        try:
            holiday_date = parse_date(str(_value(row, "Date", "Holiday Date", "RH Date")))
        except (ValueError, TypeError):
            holiday_date = None
        name = str(_value(row, "Name", "Holiday Name") or "").strip()
        if not holiday_date or not name:
            skipped.append(f"Row {index}: date and name are required")
            continue
        try:
            year = int(float(_value(row, "Year") or holiday_date.year))
        except (TypeError, ValueError):
            year = holiday_date.year
        item = db.query(RestrictedHoliday).filter(
            RestrictedHoliday.holiday_date == holiday_date
        ).first()
        if not item:
            item = RestrictedHoliday(holiday_date=holiday_date, name=name, year=year, created_by=user.id)
            db.add(item)
            created += 1
        else:
            item.name = name
            item.year = year
            item.is_active = True
            updated += 1
        item.reason = _value(row, "Reason")
    db.commit()
    return {"rows": len(rows), "created": created, "updated": updated, "skipped": skipped[:20]}


@router.get("/comp-offs")
def list_comp_offs(
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.view", "self.portal")),
):
    if employee_id is None:
        employee_id = user.employee_id
    if employee_id:
        _visible(db, user, employee_id)
    rows = accrued_rows(db, employee_id)
    return [{
        "id": row.id,
        "employee_id": row.employee_id,
        "work_date": row.work_date,
        "days": row.days,
        "status": row.status,
        "source": row.source,
        "reason": row.reason,
        "balance": balance_for(db, row.employee_id),
    } for row in rows[:500]]


@router.post("/requests/{leave_id}/manager-approve", response_model=LeaveRequestOut)
def manager_approve_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.manager_approve")),
):
    leave = db.get(LeaveRequest, leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    manager_approve(db, leave, user)
    db.commit()
    db.refresh(leave)
    recompute_records(db, leave.from_date, leave.to_date, employee_id=leave.employee_id)
    return leave


@router.post("/requests/{leave_id}/verify", response_model=LeaveRequestOut)
def verify_leave_request(
    leave_id: int,
    payload: LeaveVerifyIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.verify")),
):
    leave = db.get(LeaveRequest, leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    verify_leave(db, leave, user, payload.notes if payload else None)
    db.commit()
    db.refresh(leave)
    return leave


@router.post("/requests/{leave_id}/final-approve", response_model=LeaveRequestOut)
def final_approve_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.final_approve")),
):
    leave = db.get(LeaveRequest, leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    final_approve(db, leave, user)
    db.commit()
    db.refresh(leave)
    recompute_records(db, leave.from_date, leave.to_date, employee_id=leave.employee_id)
    return leave


@router.post("/requests/{leave_id}/reject", response_model=LeaveRequestOut)
def reject_leave_request(
    leave_id: int,
    payload: LeaveRejectIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.manager_approve", "leave.verify", "leave.final_approve", "leave.approve")),
):
    leave = db.get(LeaveRequest, leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    employee = db.get(Employee, leave.employee_id)
    if not is_admin(user) and not can(user, "leave.verify") and not can(user, "leave.final_approve"):
        if not employee or not user.employee_id or employee.manager_id != user.employee_id:
            raise HTTPException(403, "You can only reject leave for your direct reports")
    reject_leave(db, leave, user, payload.reason)
    db.commit()
    db.refresh(leave)
    recompute_records(db, leave.from_date, leave.to_date, employee_id=leave.employee_id)
    return leave


@router.post("/requests/{leave_id}/action", response_model=LeaveRequestOut)
def action_leave(
    leave_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.approve", "leave.manager_approve", "leave.verify", "leave.final_approve")),
):
    """Legacy single-action endpoint kept for older clients."""
    leave = db.get(LeaveRequest, leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    status = str(payload.get("status") or "").strip()
    reason = payload.get("reason")
    if status == "rejected":
        return reject_leave_request(leave_id, LeaveRejectIn(reason=reason or "Rejected"), db, user)
    if status != "approved":
        raise HTTPException(400, "status must be approved or rejected")
    if is_admin(user) or can(user, "leave.final_approve"):
        return final_approve_leave(leave_id, db, user)
    if can(user, "leave.manager_approve"):
        return manager_approve_leave(leave_id, db, user)
    raise HTTPException(403, "Use the manager, verification or final approval action")


@router.delete("/requests/{leave_id}", status_code=204)
def delete_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.manage", "self.portal")),
):
    leave = db.get(LeaveRequest, leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    if not is_admin(user) and not can(user, "leave.verify"):
        if user.employee_id != leave.employee_id:
            raise HTTPException(403, "Not allowed")
        if leave.status not in ("pending", "rejected"):
            raise HTTPException(400, "Only pending applications can be withdrawn")
    db.delete(leave)
    db.commit()
    recompute_records(db, leave.from_date, leave.to_date, employee_id=leave.employee_id)
