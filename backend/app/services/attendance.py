"""Convert raw punch logs into daily attendance records.

The rules live in :mod:`app.services.attendance_engine`; this module persists
the engine output into the legacy ``attendance_records`` table used by the main
Attendance page, payroll and the standard reports.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models import AttendanceRecord, Employee, Shift
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


def _lunch_times(calc):
    """Return the lunch pair used by the engine for this day.

    The same pair drives the stored columns and the hour deduction, so they
    can never disagree.  Days without a plausible break return no times.
    """
    lunch_out = getattr(calc, "lunch_out_at", None)
    lunch_in = getattr(calc, "lunch_in_at", None)
    if not lunch_out or not lunch_in or lunch_out >= lunch_in:
        return None, None
    return lunch_out, lunch_in


def recompute_records(
    db: Session,
    start_date: date,
    end_date: date,
    employee_id: int | None = None,
    filters: EngineFilters | None = None,
) -> int:
    if start_date > end_date:
        return 0

    engine_filters = filters or EngineFilters()
    if employee_id:
        engine_filters = replace(engine_filters, employee_ids=[employee_id])
    calculations = AttendanceEngine(db).calculate_range(start_date, end_date, engine_filters)
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
        lunch_out, lunch_in = _lunch_times(calc)
        records.append(AttendanceRecord(
            employee_id=calc.employee_id,
            record_date=day,
            shift_id=calc.shift_id,
            check_in=_clock(calc.first_in, day),
            check_out=_clock(calc.last_out, day),
            lunch_out=lunch_out,
            lunch_in=lunch_in,
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


# Fields shown in the Daily records change preview and applied on confirmation.
COMPARE_FIELDS = (
    ("shift_id", "Shift"),
    ("check_in", "Check in"),
    ("check_out", "Check out"),
    ("lunch_out", "Lunch out"),
    ("lunch_in", "Lunch in"),
    ("total_hours", "Hours"),
    ("overtime_hours", "OT"),
    ("late_minutes", "Late"),
    ("early_departure_minutes", "Early exit"),
    ("status", "Status"),
    ("remarks", "Remarks"),
)


def _calc_values(calc, day: date) -> dict:
    """Values written to attendance_records for one engine calculation."""
    overtime = round2(
        calc.regular_ot_hours + calc.holiday_ot_hours + calc.weekoff_ot_hours
    )
    lunch_out, lunch_in = _lunch_times(calc)
    return {
        "shift_id": calc.shift_id,
        "check_in": _clock(calc.first_in, day),
        "check_out": _clock(calc.last_out, day),
        "lunch_out": lunch_out,
        "lunch_in": lunch_in,
        "total_hours": calc.net_hours,
        "overtime_hours": overtime,
        "late_minutes": calc.late_by,
        "early_departure_minutes": calc.early_exit_by,
        "status": STATUS_MAP.get(calc.status, "absent"),
        "remarks": calc.remarks or None,
        "source": "auto",
    }


def _shown(column: str, value, shift_names: dict) -> str:
    if column == "shift_id":
        return shift_names.get(value, "—") if value else "—"
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if value is None or value == "":
        return "—"
    return str(value)


def plan_recompute(
    db: Session,
    start_date: date,
    end_date: date,
    filters: EngineFilters | None = None,
    status_filter: str | None = None,
    max_changes: int = 100,
) -> dict:
    """Compare stored attendance with the engine using current groups/rosters.

    Calculations begin one day earlier so a night shift that started before
    the visible range still claims its next-morning punches.  Only rows dated
    inside the requested range are reported and applied.
    """
    calculations = AttendanceEngine(db).calculate_range(
        start_date - timedelta(days=1), end_date,
        replace(filters or EngineFilters()),
    )
    scoped = [
        calc for calc in calculations
        if start_date <= date.fromisoformat(calc.date) <= end_date
    ]
    employee_ids = sorted({calc.employee_id for calc in scoped})
    stored = {}
    if employee_ids:
        stored = {
            (row.employee_id, row.record_date): row
            for row in db.query(AttendanceRecord).filter(
                AttendanceRecord.employee_id.in_(employee_ids),
                AttendanceRecord.record_date >= start_date,
                AttendanceRecord.record_date <= end_date,
            ).all()
        }
    employees = {}
    if employee_ids:
        employees = {
            e.id: e for e in db.query(Employee)
            .filter(Employee.id.in_(employee_ids)).all()
        }
    shift_names = {s.id: s.name for s in db.query(Shift).all()}

    changes: list[dict] = []
    row_updates: dict[tuple[int, date], dict] = {}
    checked = 0
    for calc in scoped:
        day = date.fromisoformat(calc.date)
        row = stored.get((calc.employee_id, day))
        if status_filter:
            if status_filter == "attended":
                if not row or row.status not in ("present", "half_day"):
                    continue
            elif status_filter == "late":
                if not row or row.late_minutes <= 0:
                    continue
            elif not row or row.status != status_filter:
                continue
        checked += 1

        values = _calc_values(calc, day)
        if row is None:
            diffs = [("Record", "missing", "create")]
        else:
            diffs = []
            for column, label in COMPARE_FIELDS:
                before, after = getattr(row, column), values[column]
                if column in ("check_in", "check_out", "lunch_out", "lunch_in", "shift_id"):
                    equal = _shown(column, before, shift_names) == _shown(column, after, shift_names)
                elif column in ("total_hours", "overtime_hours"):
                    equal = round2(float(before or 0)) == round2(float(after or 0))
                else:
                    equal = (before or None) == (after or None)
                if not equal:
                    diffs.append((
                        label,
                        _shown(column, before, shift_names),
                        _shown(column, after, shift_names),
                    ))
        if diffs:
            employee = employees.get(calc.employee_id)
            changes.append({
                "employee_id": calc.employee_id,
                "employee_code": employee.employee_code if employee else "",
                "employee_name": employee.full_name if employee else "",
                "date": day.isoformat(),
                "shift": calc.shift or "",
                "fields": diffs,
            })
            row_updates[(calc.employee_id, day)] = values

    preview = changes[:max_changes]
    return {
        "checked": checked,
        "changed": len(changes),
        "unchanged": checked - len(changes),
        "changes": preview,
        "truncated": len(changes) > len(preview),
        "row_updates": row_updates,
    }


def apply_recompute(db: Session, plan: dict) -> int:
    """Persist only the rows that differ, leaving all other records intact."""
    applied = 0
    for (employee_id, day), values in plan["row_updates"].items():
        row = db.query(AttendanceRecord).filter_by(
            employee_id=employee_id, record_date=day
        ).first()
        if row:
            for column, value in values.items():
                setattr(row, column, value)
        else:
            db.add(AttendanceRecord(
                employee_id=employee_id, record_date=day, **values
            ))
        applied += 1
    db.commit()
    return applied


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
