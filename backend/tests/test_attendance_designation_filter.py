from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook

from conftest import SAMPLE_END, SAMPLE_START, sample_db
from app.models import Designation, Employee
from app.routers import attendance
from app.services.attendance import recompute_records

USER = SimpleNamespace(employee_id=None, roles=[], groups=[])
FROM = SAMPLE_START.isoformat()
TO = SAMPLE_END.isoformat()


def _sample_with_designation():
    """Return (db, session, reassigned employee, new designation) for one test."""
    engine, Session = sample_db()
    db = Session()
    executive = db.query(Designation).filter_by(name="Executive").one()
    designation = Designation(name="Technician", department_id=executive.department_id)
    db.add(designation)
    db.flush()
    employee = db.query(Employee).filter_by(employee_code="SMP001").one()
    employee.designation_id = designation.id
    db.commit()
    recompute_records(db, SAMPLE_START, SAMPLE_END)
    return engine, db, employee, designation


def test_designation_filter_on_daily_records():
    engine, db, employee, designation = _sample_with_designation()
    try:
        all_rows = attendance.list_records(
            from_date=FROM, to_date=TO, limit=500, db=db, user=USER,
        )
        filtered = attendance.list_records(
            from_date=FROM, to_date=TO, designation_id=employee.designation_id,
            limit=500, db=db, user=USER,
        )
        assert all_rows["total"] > filtered["total"] > 0
        assert {row.employee_code for row in filtered["items"]} == {"SMP001"}
        assert all(row.designation_name == designation.name for row in filtered["items"])
    finally:
        db.close()
        engine.dispose()


def test_designation_filter_on_punch_logs():
    engine, db, employee, _designation = _sample_with_designation()
    try:
        all_rows = attendance.list_logs(
            from_date=FROM, to_date=TO, limit=500, db=db, user=USER,
        )
        filtered = attendance.list_logs(
            from_date=FROM, to_date=TO, designation_id=employee.designation_id,
            limit=500, db=db, user=USER,
        )
        assert all_rows["total"] > filtered["total"] > 0
        assert {row.employee_id for row in filtered["items"]} == {employee.id}
    finally:
        db.close()
        engine.dispose()


def test_designation_filter_on_excel_export():
    engine, db, employee, designation = _sample_with_designation()
    try:
        response = attendance.export_attendance(
            view="records", format="xlsx", from_date=FROM, to_date=TO,
            designation_id=employee.designation_id, db=db, user=USER,
        )
        workbook = load_workbook(BytesIO(response.body))
        rows = list(workbook["Report"].iter_rows(values_only=True))
        data_rows = [row for row in rows[1:] if str(row[0] or "").startswith("2026-")]
        assert data_rows
        assert all("SMP001" in (row[1] or "") for row in data_rows)
        assert all(row[2] == designation.name for row in data_rows)
        params = list(workbook["Parameters"].iter_rows(values_only=True))
        assert ("Filter 1", f"Designation: {designation.name}") in params
    finally:
        db.close()
        engine.dispose()
