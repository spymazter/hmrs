from datetime import date, datetime, time

from conftest import sample_db
from app.models import Employee, PunchLog, Shift, ShiftGroup, ShiftRoster
from app.services.attendance_engine import AttendanceData, AttendanceEngine

DAY = date(2026, 10, 6)
START = date(2026, 10, 5)
END = date(2026, 10, 11)


def _housekeeping_group(db):
    """Return (employee, morning shift, second shift, night shift, group)."""
    employee = db.query(Employee).filter_by(employee_code="SMP001").one()
    db.query(PunchLog).filter(
        PunchLog.employee_id == employee.id,
        PunchLog.punch_time >= datetime.combine(DAY, time.min),
        PunchLog.punch_time < datetime.combine(DAY.replace(day=DAY.day + 2), time.min),
    ).delete(synchronize_session=False)

    morning = Shift(name="HK MS", start_time=time(7, 30), end_time=time(16, 30),
                    grace_minutes=15, min_hours_for_full_day=8, half_day_hours=4)
    second = Shift(name="HK SS", start_time=time(11, 0), end_time=time(20, 0),
                   grace_minutes=5, min_hours_for_full_day=10, half_day_hours=5)
    night = Shift(name="HK NS", start_time=time(20, 0), end_time=time(8, 0),
                  grace_minutes=5, min_hours_for_full_day=12, half_day_hours=6,
                  shift_type="night")
    db.add_all([morning, second, night])
    db.flush()
    group = ShiftGroup(name="House Keeping")
    db.add(group)
    db.flush()
    group.shifts = [morning, second, night]
    group.employees = [employee]
    db.commit()
    return employee, morning, second, night, group


def _punch(db, employee, when, punch_type="in"):
    db.add(PunchLog(
        employee_id=employee.id, device_user_id=employee.device_user_id,
        punch_time=when, punch_type=punch_type, source="device",
    ))
    db.commit()


def _resolve(db, employee, day=DAY):
    data = AttendanceData(db, START, END)
    return AttendanceEngine(db)._resolve_shift(employee, day, data)


def test_second_shift_punch_selects_second_shift_and_removes_late():
    _, Session = sample_db()
    db = Session()
    try:
        employee, morning, second, _night, _group = _housekeeping_group(db)
        _punch(db, employee, datetime.combine(DAY, time(10, 52)))

        assert _resolve(db, employee).id == second.id
        calc = next(
            row for row in AttendanceEngine(db).calculate_range(START, END)
            if row.employee_id == employee.id and row.date == DAY.isoformat()
        )
        assert calc.shift == "HK SS"
        assert calc.late_by == 0
        assert morning.name == "HK MS"  # the rotation-only choice is no longer used
    finally:
        db.close()


def test_explicit_roster_still_overrides_auto_detection():
    _, Session = sample_db()
    db = Session()
    try:
        employee, morning, second, _night, _group = _housekeeping_group(db)
        _punch(db, employee, datetime.combine(DAY, time(10, 52)))
        db.add(ShiftRoster(employee_id=employee.id, roster_date=DAY, shift_id=morning.id))
        db.commit()

        assert _resolve(db, employee).id == morning.id
        assert second.name == "HK SS"
    finally:
        db.close()


def test_no_punches_keeps_weekly_rotation():
    _, Session = sample_db()
    db = Session()
    try:
        employee, morning, second, _night, _group = _housekeeping_group(db)
        shifts = sorted([morning, second, _night], key=lambda s: s.id)
        expected = shifts[((DAY - date(2026, 1, 5)).days // 7) % len(shifts)]

        assert _resolve(db, employee).id == expected.id
    finally:
        db.close()


def test_night_shift_punches_select_night_shift():
    _, Session = sample_db()
    db = Session()
    try:
        employee, _morning, _second, night, _group = _housekeeping_group(db)
        _punch(db, employee, datetime.combine(DAY, time(22, 0)))
        _punch(db, employee, datetime.combine(date(2026, 10, 7), time(6, 0)), "out")

        assert _resolve(db, employee).id == night.id
    finally:
        db.close()
