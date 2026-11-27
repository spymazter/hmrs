from datetime import date, datetime, time

from conftest import sample_db
from app.models import Employee, PunchLog, Shift, ShiftGroup, ShiftRoster
from app.services.attendance_engine import AttendanceEngine, EngineFilters

PREVIOUS = date(2026, 10, 8)  # night shift start date
DAY = date(2026, 10, 9)       # morning the night shift finished


def _setup_group(db):
    """Group with a night and a day shift; day shift is rostered on DAY."""
    employee = db.query(Employee).filter_by(employee_code="SMP001").one()
    db.query(PunchLog).filter(PunchLog.employee_id == employee.id).delete(synchronize_session=False)
    db.query(ShiftRoster).filter(ShiftRoster.employee_id == employee.id).delete(synchronize_session=False)

    night = Shift(name="Nursing NS", start_time=time(20, 0), end_time=time(8, 0),
                  grace_minutes=5, min_hours_for_full_day=10, half_day_hours=5,
                  shift_type="night")
    day = Shift(name="Nursing SS", start_time=time(8, 0), end_time=time(17, 0),
                grace_minutes=5, min_hours_for_full_day=8, half_day_hours=4)
    db.add_all([night, day])
    db.flush()
    group = ShiftGroup(name="Nursing Staff Group")
    db.add(group)
    db.flush()
    group.shifts = [night, day]
    employee.shift_group_id = group.id
    db.add(ShiftRoster(employee_id=employee.id, roster_date=DAY, shift_id=day.id))
    db.commit()
    return employee, night, day


def _punch(db, employee, when, punch_type="in"):
    db.add(PunchLog(
        employee_id=employee.id, device_user_id=employee.device_user_id,
        punch_time=when, punch_type=punch_type, source="device",
    ))
    db.commit()


def _calc(db, employee, start, end, day):
    calculations = AttendanceEngine(db).calculate_range(
        start, end, EngineFilters(employee_ids=[employee.id])
    )
    return next(c for c in calculations if c.date == day.isoformat())


def _night_shift_punches(db, employee):
    # Device direction label for the 20:04 IN is unreliably reported as OUT;
    # the engine pairs by time/position, so label is irrelevant here.
    _punch(db, employee, datetime.combine(PREVIOUS, time(20, 4)), "out")
    _punch(db, employee, datetime.combine(DAY, time(7, 49)), "out")
    _punch(db, employee, datetime.combine(DAY, time(13, 21)), "in")


def test_night_shift_finished_in_morning_exempts_following_day_late():
    _, Session = sample_db()
    db = Session()
    try:
        employee, _night, _day = _setup_group(db)
        _night_shift_punches(db, employee)

        previous = _calc(db, employee, PREVIOUS, DAY, PREVIOUS)
        current = _calc(db, employee, PREVIOUS, DAY, DAY)

        assert previous.shift_type == "night"
        assert previous.first_in == "20:04"
        assert previous.last_out == "07:49"
        assert current.shift == "Nursing SS"
        assert current.first_in == "13:21"
        assert current.late_by == 0
    finally:
        db.close()


def test_no_worked_night_shift_still_marks_late():
    _, Session = sample_db()
    db = Session()
    try:
        employee, _night, _day = _setup_group(db)
        # No punch on PREVIOUS, so the rostered night shift was not worked.
        _punch(db, employee, datetime.combine(DAY, time(13, 21)), "in")

        current = _calc(db, employee, PREVIOUS, DAY, DAY)

        assert current.first_in == "13:21"
        assert current.late_by == 316  # 13:21 vs 08:00, 5 minute grace
    finally:
        db.close()


def test_exemption_applies_when_recompute_starts_on_following_day():
    _, Session = sample_db()
    db = Session()
    try:
        employee, _night, _day = _setup_group(db)
        _night_shift_punches(db, employee)

        # Sync/manual punch recomputes only the punch date; the previous
        # night shift still has to be recognised from the loaded punches.
        current = _calc(db, employee, DAY, DAY, DAY)

        assert current.first_in == "13:21"
        assert current.late_by == 0
    finally:
        db.close()
