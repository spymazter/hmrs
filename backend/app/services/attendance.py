"""Convert raw punch logs into daily attendance records.

The rules live in :mod:`app.services.attendance_engine`; this module persists
the engine output into the legacy ``attendance_records`` table used by the main
Attendance page, payroll and the standard reports.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models import AttendanceRecord, Employee
from app.services.attendance_engine import AttendanceEngine, EngineFilters
from app.utils import round2

# Advanced engine states mapped onto the statuses understood by the rest of
# the application.  The advanced reports still see the original status_code.
STATUS_MAP = {
    "present": "present",
    "half_day": "half_day",
    "absent": "absent",
    "week_off": "week_off",
    "holiday": "holiday",
    "leave": "leave",
    "od": "od",
    "comp_off": "week_off",
    "missed_punch": "half_day",
}


def _clock(value: str, day: date) -> datetime | None:
    if not value:
        return None
    try:
        hour, minute = (int(part) for part in value.split(":")[:2])
        return datetime.combine(day, time(hour, minute))
    except (ValueError, TypeError):
        return None


def recompute_records(
    db: Session,
    start_date: date,
    end_date: date,
    employee_id: int | None = None,
) -> int:
    if start_date > end_date:
        return 0

    filters = EngineFilters(employee_ids=[employee_id] if employee_id else None)
    calculations = AttendanceEngine(db).calculate_range(start_date, end_date, filters)
    if not calculations:
        return 0

    employee_ids = {calc.employee_id for calc in calculations}
    db.query(AttendanceRecord).filter(
        AttendanceRecord.employee_id.in_(employee_ids),
        AttendanceRecord.record_date >= start_date,
        AttendanceRecord.record_date <= end_date,
    ).delete(synchronize_session=False)

    records = []
    for calc in calculations:
        day = date.fromisoformat(calc.date)
        overtime = round2(
            calc.regular_ot_hours + calc.holiday_ot_hours + calc.weekoff_ot_hours
        )
        records.append(AttendanceRecord(
            employee_id=calc.employee_id,
            record_date=day,
            shift_id=calc.shift_id,
            check_in=_clock(calc.first_in, day),
            check_out=_clock(calc.last_out, day),
            total_hours=calc.net_hours,
            overtime_hours=overtime,
            late_minutes=calc.late_by,
            early_departure_minutes=calc.early_exit_by,
            status=STATUS_MAP.get(calc.status, "absent"),
            remarks=calc.remarks or None,
            source="auto",
        ))

    db.bulk_save_objects(records)
    db.commit()
    return len(records)


# Backwards-compatible helper used by older code/tests.
def paired_day_stats(day_punches):
    """Return first-in, last-out, net hours and whether a complete pair exists."""
    from app.services.attendance_engine import NormalizedPunch, pair_punches

    punches = [
        NormalizedPunch(
            id=getattr(p, "id", index),
            employee_id=getattr(p, "employee_id", None),
            punch_time=p.punch_time,
            punch_type=p.punch_type or "in",
        )
        for index, p in enumerate(day_punches)
    ]
    sessions, net_hours, _ = pair_punches(punches, "strict")
    if not punches:
        return None, None, 0.0, False
    return (
        punches[0].punch_time,
        punches[-1].punch_time,
        net_hours,
        bool(sessions),
    )
