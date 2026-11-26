"""Automatic compensatory-off accrual from extra worked hours.

Rule agreed with HR: every 9 extra hours worked earns 1 comp-off day. Extra
hours are taken from the attendance engine (regular + holiday + weekly-off
overtime), carried forward across dates, and never re-created for the same
employee/date/source.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import CompOff, CompOffAccrualState, Employee, PunchLog
from app.services.attendance import recompute_records
from app.services.attendance_engine import AttendanceEngine, EngineFilters
from app.utils import round2

EXTRA_HOURS_PER_DAY = 9.0
AUTO_SOURCE = "auto_9h"
AUTO_RULE = "1 day per 9 extra hours"


def _employee_ids(db: Session) -> list[int]:
    return [row.id for row in db.query(Employee.id).order_by(Employee.id).all()]


def _first_punch_date(db: Session) -> date | None:
    row = db.query(PunchLog.punch_time).order_by(PunchLog.punch_time).first()
    return row[0].date() if row else None


def _extra_hours(calculation) -> float:
    return round2(
        (calculation.regular_ot_hours or 0)
        + (calculation.holiday_ot_hours or 0)
        + (calculation.weekoff_ot_hours or 0)
    )


def accrue_comp_offs(
    db: Session,
    start: date,
    end: date,
    user_id: int | None = None,
    force: bool = False,
) -> dict:
    """Accrue comp-off days for a date range and return an idempotent summary."""
    if start > end:
        raise ValueError("start must be on or before end")

    employee_ids = _employee_ids(db)
    if not employee_ids:
        return {"processed": 0, "earned_days": 0, "message": "No employees to process"}

    if force:
        # Rebuild all automatic accrual from the first punch so the carried
        # balance stays exact. Manual comp-offs are never touched.
        first = _first_punch_date(db)
        start = min(first or start, start)
        db.query(CompOff).filter(CompOff.source == AUTO_SOURCE).delete(synchronize_session=False)
        db.query(CompOffAccrualState).delete(synchronize_session=False)
        db.flush()

    states = {
        row.employee_id: row
        for row in db.query(CompOffAccrualState).all()
    }
    for employee_id in employee_ids:
        if employee_id not in states:
            states[employee_id] = CompOffAccrualState(
                employee_id=employee_id, extra_hours_balance=0
            )
            db.add(states[employee_id])

    if not force:
        # Never accrue the same date twice on a repeat run.
        earliest_pending = start
        moved = False
        for state in states.values():
            if state.last_accrual_date and state.last_accrual_date >= earliest_pending:
                earliest_pending = state.last_accrual_date + timedelta(days=1)
                moved = True
        if moved:
            if earliest_pending > end:
                return {
                    "processed": 0,
                    "earned_days": 0,
                    "message": "Comp-offs are already accrued through this range",
                }
            start = earliest_pending

    calculations = AttendanceEngine(db).calculate_range(
        start, end, EngineFilters(employee_ids=employee_ids)
    )
    by_key: dict[tuple[int, date], object] = {}
    for calculation in calculations:
        by_key[(calculation.employee_id, date.fromisoformat(calculation.date))] = calculation

    earned_days = 0.0
    processed = 0
    accrual_dates: set[tuple[int, date]] = set()
    for key in sorted(by_key):
        employee_id, work_date = key
        extra = _extra_hours(by_key[key])
        processed += 1
        state = states[employee_id]
        previous = round2(state.extra_hours_balance or 0)
        if extra <= 0:
            state.last_accrual_date = work_date
            continue
        balance = round2(previous + extra)
        earned = int(balance // EXTRA_HOURS_PER_DAY)
        balance = round2(balance - earned * EXTRA_HOURS_PER_DAY)
        state.extra_hours_balance = balance
        state.last_accrual_date = work_date
        if earned <= 0:
            continue

        earned_days += earned
        accrual_dates.add((employee_id, work_date))
        existing = (
            db.query(CompOff)
            .filter(
                CompOff.employee_id == employee_id,
                CompOff.work_date == work_date,
                CompOff.source == AUTO_SOURCE,
            )
            .first()
        )
        if existing:
            existing.days = round2((existing.days or 0) + earned)
            existing.extra_hours = round2((existing.extra_hours or 0) + extra)
            existing.extra_hours_balance = balance
        else:
            db.add(CompOff(
                employee_id=employee_id,
                work_date=work_date,
                days=float(earned),
                reason=f"Earned from {extra:g} extra hours",
                status="approved",
                approved_by=user_id,
                source=AUTO_SOURCE,
                rule=AUTO_RULE,
                extra_hours=extra,
                extra_hours_balance=balance,
            ))

    db.commit()
    for employee_id, work_date in accrual_dates:
        recompute_records(db, work_date, work_date, employee_id=employee_id)
    return {
        "processed": processed,
        "earned_days": round2(earned_days),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rule": AUTO_RULE,
    }


def accrued_rows(db: Session, employee_id: int | None = None) -> list[CompOff]:
    query = db.query(CompOff).filter(CompOff.source == AUTO_SOURCE)
    if employee_id:
        query = query.filter(CompOff.employee_id == employee_id)
    return query.order_by(CompOff.work_date.desc()).all()


def balance_for(db: Session, employee_id: int) -> dict:
    rows = accrued_rows(db, employee_id)
    state = db.get(CompOffAccrualState, employee_id)
    return {
        "employee_id": employee_id,
        "earned_days": round2(sum(row.days or 0 for row in rows)),
        "extra_hours_balance": round2((state.extra_hours_balance if state else 0) or 0),
        "last_accrual_date": state.last_accrual_date.isoformat() if state and state.last_accrual_date else None,
    }
