from datetime import date
from types import SimpleNamespace

from conftest import sample_db
from app.models import AttendanceRecord, Employee
from app.routers import attendance
from app.services.attendance import recompute_records


def test_recompute_records_stores_lunch_punches():
    _, Session = sample_db()
    db = Session()
    try:
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        row = (
            db.query(AttendanceRecord)
            .join(Employee)
            .filter(
                AttendanceRecord.record_date == date(2026, 10, 6),
                Employee.employee_code == "SMP001",
            )
            .first()
        )
        assert row is not None
        assert row.lunch_out.strftime("%H:%M") == "13:00"
        assert row.lunch_in.strftime("%H:%M") == "14:00"
    finally:
        db.close()


def test_two_punch_day_has_no_lunch_columns():
    _, Session = sample_db()
    db = Session()
    try:
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        row = (
            db.query(AttendanceRecord)
            .join(Employee)
            .filter(
                AttendanceRecord.record_date == date(2026, 10, 9),
                Employee.employee_code == "SMP005",
            )
            .first()
        )
        assert row is not None
        assert row.lunch_out is None and row.lunch_in is None
    finally:
        db.close()


def test_records_api_exposes_lunch_columns():
    _, Session = sample_db()
    db = Session()
    try:
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        result = attendance.list_records(
            from_date="2026-10-06", to_date="2026-10-06", limit=500, db=db,
            user=SimpleNamespace(employee_id=None, roles=[], groups=[]),
        )
        row = next(r for r in result["items"] if r.employee_code == "SMP001")
        assert row.lunch_out.strftime("%H:%M") == "13:00"
        assert row.lunch_in.strftime("%H:%M") == "14:00"
    finally:
        db.close()
