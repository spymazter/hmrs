from datetime import date

from conftest import sample_db
from app.models import AttendanceRecord, Designation, Employee
from app.routers import advanced_reports, reports
from app.services.attendance import recompute_records
from app.services.attendance_engine import EngineFilters


def test_recompute_records_can_be_scoped_by_engine_filters():
    _, Session = sample_db()
    db = Session()
    try:
        db.query(AttendanceRecord).delete()
        db.commit()

        count = recompute_records(
            db, date(2026, 10, 5), date(2026, 10, 11),
            filters=EngineFilters(employee_code="SMP001"),
        )

        rows = db.query(AttendanceRecord).all()
        assert count == 7
        assert rows
        assert {row.employee.employee_code for row in rows} == {"SMP001"}
        assert all(date(2026, 10, 5) <= row.record_date <= date(2026, 10, 11) for row in rows)
    finally:
        db.close()


def test_reports_recompute_uses_the_exact_report_period():
    _, Session = sample_db()
    db = Session()
    try:
        result = reports.recompute_report(
            "monthly", None, 2026, 10, None, None, None, db, None
        )
        payload = reports._build_payload(db, "monthly", None, 2026, 10, None, None, None)

        assert result["from_date"] == payload["start"] == "2026-10-01"
        assert result["to_date"] == payload["end"] == "2026-10-31"
        assert result["records"] > 0
    finally:
        db.close()


def test_reports_recompute_can_be_scoped_by_designation():
    _, Session = sample_db()
    db = Session()
    try:
        designation = db.query(Designation).first()
        result = reports.recompute_report(
            "daily", "2026-10-06", None, None, None, None, designation.id, db, None
        )
        rows = db.query(AttendanceRecord).filter(
            AttendanceRecord.record_date == date(2026, 10, 6)
        ).all()
        payload = reports.daily_report("2026-10-06", None, designation.id, db, None)

        assert result["records"] > 0
        assert rows
        assert all(db.get(Employee, row.employee_id).designation_id == designation.id for row in rows)
        expected_codes = {
            emp.employee_code for emp in db.query(Employee)
            .filter(Employee.designation_id == designation.id).all()
        }
        assert payload["designation_label"] == designation.name
        assert payload["rows"]
        assert {row["employee_code"] for row in payload["rows"]} <= expected_codes
    finally:
        db.close()


def test_advanced_recompute_honors_active_filters():
    _, Session = sample_db()
    db = Session()
    try:
        db.query(AttendanceRecord).delete()
        db.commit()

        result = advanced_reports.advanced_recompute(
            "2026-10-05", "2026-10-11", "SMP001", None, None, None, None, db, None
        )
        rows = db.query(AttendanceRecord).all()

        assert result["from_date"] == "2026-10-05"
        assert result["to_date"] == "2026-10-11"
        assert {row.employee.employee_code for row in rows} == {"SMP001"}
    finally:
        db.close()
