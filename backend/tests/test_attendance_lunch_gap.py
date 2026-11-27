from datetime import date, datetime, time, timedelta

from conftest import sample_db
from app.models import AttendanceRecord, Employee, PunchLog
from app.services.attendance import recompute_records
from app.services.attendance_engine import (
    NormalizedPunch,
    detect_lunch_pair,
    pair_punches,
    save_lunch_break_config,
)

DAY = date(2026, 10, 6)


def _punch(index, clock, direction="in"):
    hour, minute = (int(part) for part in clock.split(":"))
    return NormalizedPunch(
        index, 1, datetime.combine(DAY, time(hour, minute)), direction
    )


def _pair_times(pair):
    if pair is None:
        return None
    return pair[0].punch_time.strftime("%H:%M"), pair[1].punch_time.strftime("%H:%M")


def _set_punches(db, code, day, specs):
    employee = db.query(Employee).filter_by(employee_code=code).one()
    start = datetime.combine(day, time.min)
    end = datetime.combine(day + timedelta(days=1), time.min)
    db.query(PunchLog).filter(
        PunchLog.employee_id == employee.id,
        PunchLog.punch_time >= start,
        PunchLog.punch_time < end,
    ).delete(synchronize_session=False)
    for index, (clock, direction) in enumerate(specs, 1):
        hour, minute = (int(part) for part in clock.split(":"))
        db.add(PunchLog(
            employee_id=employee.id,
            device_user_id=employee.device_user_id,
            punch_time=datetime.combine(day, time(hour, minute)),
            punch_type=direction,
            source="device",
        ))
    db.commit()


def _record(db, code, day):
    return (
        db.query(AttendanceRecord)
        .join(Employee)
        .filter(
            AttendanceRecord.record_date == day,
            Employee.employee_code == code,
        )
        .one()
    )


def test_duplicate_only_day_has_no_lunch_pair():
    punches = [
        _punch(1, "08:59"), _punch(2, "09:03"),
        _punch(3, "18:01", "out"), _punch(4, "19:17", "out"),
    ]
    assert detect_lunch_pair(punches, 60) is None


def test_lunch_pair_is_found_among_duplicate_punches():
    punches = [
        _punch(1, "09:01"), _punch(2, "13:23"), _punch(3, "14:04"),
        _punch(4, "17:59", "out"), _punch(5, "18:03", "out"),
    ]
    pair = detect_lunch_pair(punches, 60)
    assert _pair_times(pair) == ("13:23", "14:04")

    sessions, net_hours, break_hours = pair_punches(
        punches, "strict", lunch_minutes=60, lunch_pair=pair
    )
    assert net_hours == 8.03
    assert break_hours == 1.0
    assert len(sessions) == 2
    assert sessions[0]["out"]["time"] == "13:23:00"
    assert sessions[1]["in"]["time"] == "14:04:00"


def test_six_punch_day_ignores_short_duplicate_gaps():
    punches = [
        _punch(1, "09:08"), _punch(2, "10:07"),
        _punch(3, "14:10"), _punch(4, "15:14"),
        _punch(5, "19:00", "out"), _punch(6, "19:02", "out"),
    ]
    assert _pair_times(detect_lunch_pair(punches, 60)) == ("14:10", "15:14")


def test_configured_duration_selects_the_closest_gap():
    punches = [
        _punch(1, "09:00"), _punch(2, "11:00"), _punch(3, "12:00"),
        _punch(4, "12:45"), _punch(5, "18:00", "out"),
    ]
    assert _pair_times(detect_lunch_pair(punches, 45)) == ("12:00", "12:45")
    assert _pair_times(detect_lunch_pair(punches, 60)) == ("11:00", "12:00")


def test_zero_duration_or_reversed_sequence_disables_detection():
    punches = [
        _punch(1, "09:00"), _punch(2, "12:00"),
        _punch(3, "13:00"), _punch(4, "18:00", "out"),
    ]
    assert detect_lunch_pair(punches, 0) is None
    assert detect_lunch_pair(
        punches, 60, ["IN", "Lunch IN", "Lunch OUT", "Exit"]
    ) is None
    assert detect_lunch_pair(punches, 60, ["IN", "Break", "Exit"]) is None


def test_recompute_stores_detected_pair_and_deducts_once():
    _, Session = sample_db()
    db = Session()
    try:
        _set_punches(db, "SMP001", DAY, [
            ("09:01", "in"), ("13:23", "in"), ("14:04", "in"),
            ("17:59", "out"), ("18:03", "out"),
        ])
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        row = _record(db, "SMP001", DAY)
        assert row.check_in.strftime("%H:%M") == "09:01"
        assert row.check_out.strftime("%H:%M") == "18:03"
        assert row.lunch_out.strftime("%H:%M") == "13:23"
        assert row.lunch_in.strftime("%H:%M") == "14:04"
        assert row.total_hours == 8.03
    finally:
        db.close()


def test_recompute_leaves_lunch_blank_for_duplicate_only_day():
    _, Session = sample_db()
    db = Session()
    try:
        _set_punches(db, "SMP001", DAY, [
            ("08:59", "in"), ("09:03", "in"),
            ("18:01", "out"), ("19:17", "out"),
        ])
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        row = _record(db, "SMP001", DAY)
        assert row.lunch_out is None and row.lunch_in is None
        assert row.total_hours == 10.3
    finally:
        db.close()


def test_disabled_lunch_rule_leaves_columns_blank():
    _, Session = sample_db()
    db = Session()
    try:
        save_lunch_break_config(db, {"enabled": False, "duration_minutes": 60})
        _set_punches(db, "SMP001", DAY, [
            ("09:01", "in"), ("13:23", "in"), ("14:04", "in"),
            ("17:59", "out"), ("18:03", "out"),
        ])
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        row = _record(db, "SMP001", DAY)
        assert row.lunch_out is None and row.lunch_in is None
        assert row.total_hours == 9.03
    finally:
        db.close()


def test_custom_lunch_duration_is_deducted_from_detected_pair():
    _, Session = sample_db()
    db = Session()
    try:
        save_lunch_break_config(db, {"enabled": True, "duration_minutes": 45})
        _set_punches(db, "SMP001", DAY, [
            ("09:00", "in"), ("12:00", "in"),
            ("12:45", "in"), ("18:00", "out"),
        ])
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        row = _record(db, "SMP001", DAY)
        assert row.lunch_out.strftime("%H:%M") == "12:00"
        assert row.lunch_in.strftime("%H:%M") == "12:45"
        assert row.total_hours == 8.25
    finally:
        db.close()
