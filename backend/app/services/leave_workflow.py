"""Leave workflow, yearly quotas and HR verification helpers.

The workflow is deliberately additive: old ``approved`` / ``rejected`` rows keep
their meaning, while new requests move through manager approval, HR verification
and admin final approval.
"""

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import can, is_admin
from app.models import (
    AuditLog, Employee, LeaveQuota, LeaveRequest, LeaveType, PunchLog,
    RestrictedHoliday, User,
)

FINAL_STATUSES = {"approved"}
ACTIVE_STATUSES = {"pending", "manager_approved", "verified"}
DECIDED_STATUSES = {"approved", "rejected"}

CODE_BY_NAME = {
    "casual leave": "CL",
    "sick leave": "SL",
    "earned leave": "EL",
    "annual leave": "EL",
    "restricted holiday": "RH",
    "loss of pay": "LOP",
    "unpaid leave": "LOP",
    "leave without pay": "LOP",
    "lwp": "LOP",
}


def code_for(leave_type: LeaveType | None) -> str:
    if not leave_type:
        return ""
    if leave_type.code:
        return str(leave_type.code).strip().upper()
    return CODE_BY_NAME.get((leave_type.name or "").strip().casefold(), "")


def is_final_approved(leave: LeaveRequest) -> bool:
    return leave.status in FINAL_STATUSES


def is_active(leave: LeaveRequest) -> bool:
    return leave.status in ACTIVE_STATUSES


def date_span(leave: LeaveRequest) -> list[date]:
    days = []
    current = leave.from_date
    while current <= leave.to_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def leave_type_by_code(db: Session, code: str) -> LeaveType | None:
    upper = code.strip().upper()
    row = db.query(LeaveType).filter(LeaveType.code == upper).first()
    if row:
        return row
    for item in db.query(LeaveType).all():
        if code_for(item) == upper:
            return item
    return None


def quota_for(
    db: Session, employee: Employee, leave_type: LeaveType, year: int
) -> tuple[float, str]:
    """Return the effective quota and its source (employee / global / default)."""
    if employee and employee.id:
        row = (
            db.query(LeaveQuota)
            .filter(
                LeaveQuota.scope == "employee",
                LeaveQuota.scope_value == str(employee.id),
                LeaveQuota.leave_type_id == leave_type.id,
                LeaveQuota.year == year,
            )
            .first()
        )
        if row:
            return float(row.days or 0), "employee"

    row = (
        db.query(LeaveQuota)
        .filter(
            LeaveQuota.scope == "global",
            LeaveQuota.scope_value == "ALL",
            LeaveQuota.leave_type_id == leave_type.id,
            LeaveQuota.year == year,
        )
        .first()
    )
    if row:
        return float(row.days or 0), "global"
    return float(leave_type.max_days_per_year or 0), "default"


def _count_days(
    db: Session,
    employee_id: int,
    leave_type_id: int,
    year: int,
    statuses: set[str],
    exclude_id: int | None = None,
) -> float:
    rows = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.leave_type_id == leave_type_id,
            LeaveRequest.status.in_(statuses),
            LeaveRequest.from_date <= date(year, 12, 31),
            LeaveRequest.to_date >= date(year, 1, 1),
        )
        .all()
    )
    days: set[date] = set()
    for leave in rows:
        if exclude_id and leave.id == exclude_id:
            continue
        for day in date_span(leave):
            if day.year == year:
                days.add(day)
    return float(len(days))


def leave_balances(
    db: Session, employee: Employee, year: int, leave_type_id: int | None = None
) -> list[dict]:
    query = db.query(LeaveType)
    if leave_type_id:
        query = query.filter(LeaveType.id == leave_type_id)
    rows = []
    for leave_type in query.order_by(LeaveType.name).all():
        quota, source = quota_for(db, employee, leave_type, year)
        used = _count_days(db, employee.id, leave_type.id, year, FINAL_STATUSES)
        pending = _count_days(db, employee.id, leave_type.id, year, ACTIVE_STATUSES)
        code = code_for(leave_type)
        rows.append({
            "employee_id": employee.id,
            "employee_code": employee.employee_code,
            "employee_name": employee.full_name,
            "year": year,
            "leave_type_id": leave_type.id,
            "leave_type_name": leave_type.name,
            "leave_type_code": code,
            "is_paid": bool(leave_type.is_paid),
            "quota": quota,
            "used": used,
            "pending": pending,
            "remaining": max(0.0, quota - used - pending),
            "source": source,
        })
    return rows


def _ensure_quota(
    db: Session, employee: Employee, leave_type: LeaveType, days: float, year: int,
    exclude_id: int | None = None,
) -> None:
    code = code_for(leave_type)
    if code == "LOP":
        return  # Loss of pay is not quota-bound.
    quota, _ = quota_for(db, employee, leave_type, year)
    used = _count_days(db, employee.id, leave_type.id, year, FINAL_STATUSES, exclude_id)
    pending = _count_days(db, employee.id, leave_type.id, year, ACTIVE_STATUSES, exclude_id)
    if used + pending + days > quota:
        if code == "RH":
            raise HTTPException(400, f"Only {quota:g} restricted holidays are allowed per year")
        raise HTTPException(
            400,
            f"Insufficient {leave_type.name} balance: quota {quota:g}, "
            f"used {used:g}, pending {pending:g}, requested {days:g}",
        )


def _ensure_restricted_holiday(
    db: Session, employee: Employee, leave_type: LeaveType,
    from_date: date, to_date: date, restricted_holiday_id: int | None,
    exclude_id: int | None = None,
) -> RestrictedHoliday | None:
    if code_for(leave_type) != "RH":
        return None
    if not restricted_holiday_id:
        raise HTTPException(400, "Select a restricted holiday from the HR-maintained list")
    holiday = db.get(RestrictedHoliday, restricted_holiday_id)
    if not holiday or not holiday.is_active:
        raise HTTPException(400, "Selected restricted holiday is not available")
    if holiday.year != from_date.year or holiday.holiday_date != from_date or from_date != to_date:
        raise HTTPException(400, "RH leave must be a single day matching the selected holiday")
    quota, _ = quota_for(db, employee, leave_type, from_date.year)
    rows = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.leave_type_id == leave_type.id,
            LeaveRequest.status.in_(FINAL_STATUSES | ACTIVE_STATUSES),
            LeaveRequest.from_date >= date(from_date.year, 1, 1),
            LeaveRequest.to_date <= date(from_date.year, 12, 31),
        )
        .all()
    )
    if exclude_id:
        rows = [row for row in rows if row.id != exclude_id]
    if len(rows) >= quota:
        raise HTTPException(400, f"Only {quota:g} restricted holidays are allowed per year")
    return holiday


def validate_application(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    from_date: date,
    to_date: date,
    restricted_holiday_id: int | None = None,
    exclude_id: int | None = None,
) -> RestrictedHoliday | None:
    if to_date < from_date:
        raise HTTPException(400, "to_date must be on or after from_date")
    days = (to_date - from_date).days + 1
    if from_date.year != to_date.year:
        raise HTTPException(400, "Leave applications must stay within one calendar year")
    _ensure_quota(db, employee, leave_type, days, from_date.year, exclude_id)
    return _ensure_restricted_holiday(
        db, employee, leave_type, from_date, to_date, restricted_holiday_id, exclude_id
    )


def visible_employee_ids(db: Session, user: User) -> list[int] | None:
    """Employees whose leave data this user may see; None means all."""
    scoped = user.employee_id if user.employee_id and not can(user, "employee.view") else None
    if scoped:
        return [scoped]
    if is_admin(user) or can(user, "leave.final_approve") or can(user, "leave.verify"):
        return None
    if can(user, "leave.manager_approve") and user.employee_id:
        reports = [
            row.id for row in db.query(Employee)
            .filter(Employee.manager_id == user.employee_id).all()
        ]
        return sorted({user.employee_id, *reports})
    return None


def can_apply_for(db: Session, user: User, employee: Employee) -> bool:
    if is_admin(user) or can(user, "leave.final_approve") or can(user, "leave.verify"):
        return True
    if user.employee_id == employee.id:
        return True
    if can(user, "leave.manager_approve") and user.employee_id:
        return employee.manager_id == user.employee_id
    return False


def can_manager_approve(user: User, employee: Employee) -> bool:
    if is_admin(user) or can(user, "leave.final_approve"):
        return True
    return bool(
        can(user, "leave.manager_approve")
        and user.employee_id
        and employee.manager_id == user.employee_id
    )


def log_action(
    db: Session, user: User, action: str, leave: LeaveRequest, details: dict | None = None
) -> None:
    db.add(AuditLog(
        user_id=user.id,
        action=action,
        entity="leave_request",
        entity_id=leave.id,
        details={
            "employee_id": leave.employee_id,
            "status": leave.status,
            **(details or {}),
        },
    ))


def _attendance_notes(db: Session, leave: LeaveRequest) -> str:
    punches = (
        db.query(PunchLog)
        .filter(
            PunchLog.employee_id == leave.employee_id,
            PunchLog.punch_time >= leave.from_date,
            PunchLog.punch_time < leave.to_date + timedelta(days=1),
        )
        .order_by(PunchLog.punch_time)
        .all()
    )
    if not punches:
        return "No attendance punches found for the leave dates."
    days = sorted({punch.punch_time.date().isoformat() for punch in punches})
    return f"Attendance punches found on {', '.join(days)}; confirm before final approval."


def verify_leave(
    db: Session, leave: LeaveRequest, user: User, notes: str | None = None
) -> LeaveRequest:
    if leave.status in DECIDED_STATUSES:
        raise HTTPException(400, "Decided leave requests cannot be re-verified")
    employee = db.get(Employee, leave.employee_id)
    leave_type = db.get(LeaveType, leave.leave_type_id)
    if not employee or not leave_type:
        raise HTTPException(400, "Leave request has incomplete employee or leave type data")
    validate_application(
        db, employee, leave_type, leave.from_date, leave.to_date,
        leave.restricted_holiday_id, exclude_id=leave.id,
    )
    evidence = _attendance_notes(db, leave)
    leave.hr_verified_by = user.id
    leave.hr_verified_at = datetime.now()
    leave.verification_notes = " | ".join(
        part for part in (notes, evidence) if part
    )
    if leave.status == "manager_approved":
        leave.status = "verified"
    log_action(db, user, "leave.hr_verified", leave, {"notes": notes})
    return leave


def manager_approve(
    db: Session, leave: LeaveRequest, user: User
) -> LeaveRequest:
    if leave.status != "pending":
        raise HTTPException(400, "Only pending applications can be manager-approved")
    employee = db.get(Employee, leave.employee_id)
    if not employee or not can_manager_approve(user, employee):
        raise HTTPException(403, "You can only approve leave for your direct reports")
    leave.manager_approved_by = user.id
    leave.manager_approved_at = datetime.now()
    leave.status = "verified" if leave.hr_verified_at else "manager_approved"
    log_action(db, user, "leave.manager_approved", leave)
    return leave


def final_approve(
    db: Session, leave: LeaveRequest, user: User
) -> LeaveRequest:
    if leave.status in ("approved", "rejected"):
        raise HTTPException(400, "This leave request is already decided")
    if leave.status not in ("manager_approved", "verified"):
        raise HTTPException(400, "Manager approval is required before final approval")
    if not leave.manager_approved_at:
        raise HTTPException(400, "Manager approval is required before final approval")
    if not leave.hr_verified_at:
        raise HTTPException(400, "HR must verify attendance and leave balance first")
    employee = db.get(Employee, leave.employee_id)
    leave_type = db.get(LeaveType, leave.leave_type_id)
    if not employee or not leave_type:
        raise HTTPException(400, "Leave request has incomplete employee or leave type data")
    validate_application(
        db, employee, leave_type, leave.from_date, leave.to_date,
        leave.restricted_holiday_id, exclude_id=leave.id,
    )
    now = datetime.now()
    leave.status = "approved"
    leave.approved_by = user.id
    leave.final_approved_by = user.id
    leave.final_approved_at = now
    leave.decided_at = now
    log_action(db, user, "leave.final_approved", leave)
    return leave


def reject_leave(
    db: Session, leave: LeaveRequest, user: User, reason: str
) -> LeaveRequest:
    if leave.status in DECIDED_STATUSES:
        raise HTTPException(400, "This leave request is already decided")
    if not reason or not reason.strip():
        raise HTTPException(400, "A rejection reason is required")
    leave.status = "rejected"
    leave.rejected_by = user.id
    leave.reject_reason = reason.strip()
    leave.decided_at = datetime.now()
    log_action(db, user, "leave.rejected", leave, {"reason": reason.strip()})
    return leave
