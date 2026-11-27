from datetime import date

from conftest import sample_db
from app.models import AttendanceRecord, Employee
from app.routers import reports
from app.services.attendance import recompute_records, refresh_holiday_reports

HOLIDAY = date(2026, 10, 7)
OTHER_DAY = date(2026, 10, 6)


def _record(db, code, day):
    return (
        db.query(AttendanceRecord)
        .join(Employee)
        .filter(
            Employee.employee_code == code,
            AttendanceRecord.record_date == day,
        )
        .one()
    )


def test_holiday_refresh_restores_holiday_status_and_report_counts():
    _, Session = sample_db()
    db = Session()
    try:
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        other_before = (
            _record(db, "SMP001", OTHER_DAY).status,
            _record(db, "SMP001", OTHER_DAY).total_hours,
        )
        # Simulate records created before the holiday list was uploaded.
        db.query(AttendanceRecord).filter(
            AttendanceRecord.record_date == HOLIDAY
        ).update(
            {"status": "absent", "total_hours": 0.0}, synchronize_session=False
        )
        db.commit()

        result = refresh_holiday_reports(db, 2026)

        assert result["dates"] >= 1
        assert result["applied"] > 0
        assert _record(db, "SMP001", HOLIDAY).status == "holiday"
        assert (
            _record(db, "SMP001", OTHER_DAY).status,
            _record(db, "SMP001", OTHER_DAY).total_hours,
        ) == other_before

        payload = reports.daily_report(
            date_str=HOLIDAY.isoformat(), db=db, _=None
        )
        assert payload["summary"]["holidays"] > 0
    finally:
        db.close()


def test_holiday_refresh_with_no_holidays_that_year_does_nothing():
    _, Session = sample_db()
    db = Session()
    try:
        result = refresh_holiday_reports(db, 2025)
        assert result == {"year": 2025, "dates": 0, "changed": 0, "applied": 0}
    finally:
        db.close()
