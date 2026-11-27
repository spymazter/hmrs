from datetime import date, datetime, time, timedelta

from conftest import sample_db
from app.models import Employee, PunchLog, Shift, ShiftGroup
from app.services.attendance_engine import AttendanceEngine, EngineFilters

DAY = date(2026, 10, 9)
NEXT_DAY = DAY + timedelta(days=1)


def _equip_nursing_group(db):
    employee = db.query(Employee).filter_by(employee_code="SMP001").one()
    db.query(PunchLog).filter(PunchLog.employee_id == employee.id).delete(
        synchronize_session=False
    )
    evening = Shift(
        name="Nursing 4S", start_time=time(11, 0), end_time=time(20, 0),
        grace_minutes=15, min_hours_for_full_day=8, half_day_hours=4,
    )
    morning = Shift(
        name="Nursing SS", start_time=time(8, 0), end_time=time(17, 0),
        grace_minutes=15, min_hours_for_full_day=8, half_day_hours=4,
    )
    night = Shift(
        name="Nursing NS", start_time=time(20, 0), end_time=time(8, 0),
        grace_minutes=15, min_hours_for_full_day=10, half_day_hours=5,
    )
    db.add_all([evening, morning, night])
    db.flush()
    group = ShiftGroup(name="Nursing Staff Group")
    db.add(group)
    db.flush()
    group.shifts = [evening, morning, night]
    employee.shift_group_id = group.id
    return employee


def _punch(db, employee, stamp, direction):
    db.add(PunchLog(
        employee_id=employee.id,
        device_user_id=employee.device_user_id,
        punch_time=stamp,
        punch_type=direction,
        source="device",
    ))


def _at(day, clock):
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime.combine(day, time(hour, minute))


def _calculate(db, employee):
    return AttendanceEngine(db).calculate_range(
        DAY, NEXT_DAY, EngineFilters(employee_ids=[employee.id])
    )


def test_day_shift_exit_is_not_claimed_by_night_shift():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _equip_nursing_group(db)
        for clock, direction in (
            ("10:54", "in"), ("14:44", "in"), ("15:42", "out"), ("20:04", "out"),
        ):
            _punch(db, employee, _at(DAY, clock), direction)
        for clock, direction in (
            ("07:49", "out"), ("13:21", "in"), ("14:19", "in"),
        ):
            _punch(db, employee, _at(NEXT_DAY, clock), direction)
        db.commit()

        rows = {row.date: row for row in _calculate(db, employee)}
        today = rows[DAY.isoformat()]
        assert today.shift == "Nursing 4S"
        assert today.first_in == "10:54"
        assert today.last_out == "20:04"
        assert today.lunch_out_at.strftime("%H:%M") == "14:44"
        assert today.lunch_in_at.strftime("%H:%M") == "15:42"
        assert today.net_hours == 8.17
        assert "07:49" in rows[NEXT_DAY.isoformat()].all_punches
    finally:
        db.close()


def test_evening_only_punch_still_selects_night_shift():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _equip_nursing_group(db)
        _punch(db, employee, _at(DAY, "19:54"), "out")
        _punch(db, employee, _at(NEXT_DAY, "08:00"), "out")
        db.commit()

        rows = {row.date: row for row in _calculate(db, employee)}
        today = rows[DAY.isoformat()]
        assert today.shift == "Nursing NS"
        assert today.first_in == "19:54"
        assert today.last_out == "08:00"
        assert today.net_hours == 12.1
    finally:
        db.close()
