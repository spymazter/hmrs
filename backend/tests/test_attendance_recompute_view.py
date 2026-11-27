from datetime import date, time
from types import SimpleNamespace

from conftest import SAMPLE_END, SAMPLE_START, sample_db
from app.models import AttendanceRecord, Employee, Shift
from app.routers import attendance
from app.routers.shift_groups import create_group
from app.schemas import ShiftGroupCreate
from app.services.attendance import recompute_records

USER = SimpleNamespace(employee_id=None, roles=[], groups=[])
FROM = SAMPLE_START.isoformat()
TO = SAMPLE_END.isoformat()
DAY = date(2026, 10, 6)


def _employee(db, code):
    return db.query(Employee).filter_by(employee_code=code).one()


def _record(db, employee_id, day):
    return db.query(AttendanceRecord).filter_by(
        employee_id=employee_id, record_date=day
    ).one()


def _fresh_records(db):
    db.query(AttendanceRecord).delete()
    recompute_records(db, SAMPLE_START, SAMPLE_END)
    db.commit()


def test_preview_detects_new_group_and_apply_updates_only_changed_rows():
    _, Session = sample_db()
    db = Session()
    try:
        _fresh_records(db)
        employee = _employee(db, "SMP001")
        other = _employee(db, "SMP002")
        old_shift_id = _record(db, employee.id, DAY).shift_id
        other_before = [
            (r.record_date, r.shift_id, r.status, r.total_hours, r.late_minutes)
            for r in db.query(AttendanceRecord).filter_by(employee_id=other.id).all()
        ]

        shift = Shift(
            name="Evening rotation", start_time=time(13, 0), end_time=time(22, 0),
            grace_minutes=15, min_hours_for_full_day=8, half_day_hours=4,
        )
        db.add(shift)
        db.commit()
        create_group(
            ShiftGroupCreate(
                name="Nursing Staff Group", shift_ids=[shift.id],
                employee_ids=[employee.id],
            ),
            db, None,
        )

        preview = attendance.recompute_view(
            from_date=FROM, to_date=TO, db=db, user=USER
        )
        assert preview["applied"] == 0
        assert preview["changed"] > 0
        assert any(
            change["employee_code"] == "SMP001"
            and any(field[0] == "Shift" for field in change["fields"])
            for change in preview["changes"]
        )
        # Preview must not write anything.
        assert _record(db, employee.id, DAY).shift_id == old_shift_id

        applied = attendance.recompute_view(
            from_date=FROM, to_date=TO, apply=True, db=db, user=USER
        )
        assert applied["applied"] == preview["changed"]
        assert _record(db, employee.id, DAY).shift_id == shift.id
        other_after = [
            (r.record_date, r.shift_id, r.status, r.total_hours, r.late_minutes)
            for r in db.query(AttendanceRecord).filter_by(employee_id=other.id).all()
        ]
        assert other_after == other_before
    finally:
        db.close()


def test_status_filter_only_previews_matching_rows():
    _, Session = sample_db()
    db = Session()
    try:
        _fresh_records(db)
        employee = _employee(db, "SMP001")
        shift = Shift(
            name="Late rotation", start_time=time(12, 0), end_time=time(21, 0),
            grace_minutes=5, min_hours_for_full_day=8, half_day_hours=4,
        )
        db.add(shift)
        db.commit()
        create_group(
            ShiftGroupCreate(name="Late group", shift_ids=[shift.id], employee_ids=[employee.id]),
            db, None,
        )

        all_rows = attendance.recompute_view(
            from_date=FROM, to_date=TO, employee_id=employee.id, db=db, user=USER
        )
        present_only = attendance.recompute_view(
            from_date=FROM, to_date=TO, employee_id=employee.id,
            status="present", db=db, user=USER,
        )
        assert present_only["checked"] < all_rows["checked"]
        assert all(
            change["date"] in {
                r.record_date.isoformat() for r in db.query(AttendanceRecord).filter_by(
                    employee_id=employee.id, status="present"
                ).all()
            }
            for change in present_only["changes"]
        )
    finally:
        db.close()


def test_recompute_does_not_touch_night_shift_before_the_range():
    _, Session = sample_db()
    db = Session()
    try:
        _fresh_records(db)
        employee = _employee(db, "SMP002")
        night_day = date(2026, 10, 6)
        original = _record(db, employee.id, night_day)
        snapshot = (
            original.shift_id, original.status, original.check_in,
            original.check_out, original.total_hours,
        )

        result = attendance.recompute_view(
            from_date="2026-10-07", to_date="2026-10-08",
            employee_id=employee.id, apply=True, db=db, user=USER,
        )
        assert all(change["date"] != night_day.isoformat() for change in result["changes"])
        current = _record(db, employee.id, night_day)
        assert (
            current.shift_id, current.status, current.check_in,
            current.check_out, current.total_hours,
        ) == snapshot
    finally:
        db.close()
