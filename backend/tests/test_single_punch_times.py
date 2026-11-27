from datetime import date, datetime, time

from conftest import sample_db
from app.models import AttendanceRecord, Employee, PunchLog
from app.services.attendance import recompute_records

DAY = date(2026, 10, 6)


def _employee_without_punches(db):
    employee = db.query(Employee).filter_by(employee_code="SMP001").one()
    db.query(PunchLog).filter(
        PunchLog.employee_id == employee.id,
        PunchLog.punch_time >= datetime.combine(DAY, time.min),
        PunchLog.punch_time < datetime.combine(date(2026, 10, 7), time.min),
    ).delete(synchronize_session=False)
    db.commit()
    return employee


def _add_punch(db, employee, when, punch_type="in"):
    db.add(PunchLog(
        employee_id=employee.id, device_user_id=employee.device_user_id,
        punch_time=when, punch_type=punch_type, source="device",
    ))
    db.commit()


def _record(db, employee_id):
    return db.query(AttendanceRecord).filter_by(
        employee_id=employee_id, record_date=DAY
    ).one()


def test_single_in_punch_leaves_check_out_blank():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _employee_without_punches(db)
        _add_punch(db, employee, datetime.combine(DAY, time(10, 52)), "in")
        recompute_records(db, DAY, DAY, employee_id=employee.id)

        record = _record(db, employee.id)
        assert record.check_in == datetime.combine(DAY, time(10, 52))
        assert record.check_out is None
        assert record.total_hours == 0
    finally:
        db.close()


def test_single_out_punch_leaves_check_in_blank():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _employee_without_punches(db)
        _add_punch(db, employee, datetime.combine(DAY, time(19, 4)), "out")
        recompute_records(db, DAY, DAY, employee_id=employee.id)

        record = _record(db, employee.id)
        assert record.check_in is None
        assert record.check_out == datetime.combine(DAY, time(19, 4))
    finally:
        db.close()


def test_duplicate_punches_inside_debounce_do_not_repeat_timestamps():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _employee_without_punches(db)
        _add_punch(db, employee, datetime.combine(DAY, time(9, 0)), "in")
        # Same-direction punch one minute later is dropped by the 2-minute
        # debounce, leaving a single IN punch with no OUT time.
        _add_punch(db, employee, datetime.combine(DAY, time(9, 1)), "in")
        recompute_records(db, DAY, DAY, employee_id=employee.id)

        record = _record(db, employee.id)
        assert record.check_in == datetime.combine(DAY, time(9, 0))
        assert record.check_out is None
    finally:
        db.close()


def test_quick_out_after_in_is_dropped_and_check_out_stays_blank():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _employee_without_punches(db)
        _add_punch(db, employee, datetime.combine(DAY, time(10, 52)), "in")
        _add_punch(db, employee, datetime.combine(DAY, time(10, 52)), "out")
        recompute_records(db, DAY, DAY, employee_id=employee.id)

        record = _record(db, employee.id)
        assert record.check_in == datetime.combine(DAY, time(10, 52))
        assert record.check_out is None
        assert record.total_hours == 0
    finally:
        db.close()


def test_two_minute_gap_keeps_the_real_out_punch():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _employee_without_punches(db)
        _add_punch(db, employee, datetime.combine(DAY, time(9, 0)), "in")
        _add_punch(db, employee, datetime.combine(DAY, time(9, 2)), "out")
        recompute_records(db, DAY, DAY, employee_id=employee.id)

        record = _record(db, employee.id)
        assert record.check_in == datetime.combine(DAY, time(9, 0))
        assert record.check_out == datetime.combine(DAY, time(9, 2))
    finally:
        db.close()
