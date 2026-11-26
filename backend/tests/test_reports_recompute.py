from datetime import date

from conftest import sample_db
from app.models import AttendanceRecord
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
            "monthly", None, 2026, 10, None, None, db, None
        )
        payload = reports._build_payload(db, "monthly", None, 2026, 10, None, None)

        assert result["from_date"] == payload["start"] == "2026-10-01"
        assert result["to_date"] == payload["end"] == "2026-10-31"
        assert result["records"] > 0
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
