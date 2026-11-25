from datetime import date, datetime

from conftest import sample_db
from scripts.generate_sample_data import SAMPLE_END, SAMPLE_START

from app.services import biometric
from app.models import Department, Device, DeviceSyncState, Employee, PunchLog
from app.services.advanced_reports import build_report
from app.services.biometric import sync_device
from app.services.attendance_engine import EngineFilters


def _live_device_db(Session):
    db = Session()
    device = Device(
        name="Test device", ip_address="192.0.2.10", port=4370,
        mode="live", is_active=True, serial_number="TEST-SERIAL",
    )
    db.add(device)
    db.flush()
    employee = Employee(
        employee_code="DEV-TEST", first_name="Test", device_user_id="TEST",
        status="active", date_of_joining=date(2026, 1, 1),
    )
    db.add(employee)
    db.flush()
    db.add(DeviceSyncState(device_id=device.id, last_punch_time=datetime(2026, 6, 1)))
    db.commit()
    return db, device, employee


def _punch(day):
    return {
        "user_id": "TEST", "timestamp": datetime(day.year, day.month, day.day, 9, 0),
        "punch_type": "in", "raw_code": 0, "uid": 1, "verify_mode": "Fingerprint",
    }


def test_full_history_download_imports_punches_before_high_water_mark(monkeypatch):
    _, Session = sample_db()
    db, device, employee = _live_device_db(Session)
    old, recent = _punch(date(2026, 1, 5)), _punch(date(2026, 7, 5))
    monkeypatch.setattr(
        biometric, "_fetch_live",
        lambda ip, port, timeout: ([{"user_id": "TEST", "name": "Test", "uid": 1}], [old, recent]),
    )
    try:
        incremental = sync_device(db, device)
        assert incremental["success"]
        assert incremental["new_punches"] == 1
        assert db.query(PunchLog).filter(PunchLog.device_user_id == "TEST").count() == 1

        full = sync_device(db, device, full_history=True)
        assert full["success"]
        assert full["full_history"] is True
        assert full["new_punches"] == 1  # only the earlier punch was missing
        assert db.query(PunchLog).filter(PunchLog.device_user_id == "TEST").count() == 2

        repeat = sync_device(db, device, full_history=True)
        assert repeat["new_punches"] == 0  # no duplicates on a repeat download
        assert db.query(PunchLog).filter(PunchLog.device_user_id == "TEST").count() == 2
    finally:
        db.close()


def test_multiple_departments_can_be_selected_for_a_report():
    _, Session = sample_db()
    db = Session()
    try:
        departments = db.query(Department).order_by(Department.id).limit(2).all()
        if len(departments) < 2:
            extra = Department(name="Extra department")
            db.add(extra)
            db.flush()
            departments.append(extra)
        employees = db.query(Employee).order_by(Employee.id).limit(2).all()
        for employee, department in zip(employees, departments):
            employee.department_id = department.id
        db.commit()

        selected = [d.id for d in departments]
        payload = build_report(
            db, "muster_roll", SAMPLE_START, SAMPLE_END,
            EngineFilters(department_ids=selected),
        )
        codes = {row["employee_code"] for row in payload["rows"]}
        assert {employees[0].employee_code, employees[1].employee_code} <= codes

        single = build_report(
            db, "muster_roll", SAMPLE_START, SAMPLE_END,
            EngineFilters(department_id=selected[0]),
        )
        assert employees[0].employee_code in {row["employee_code"] for row in single["rows"]}
        assert employees[1].employee_code not in {row["employee_code"] for row in single["rows"]}
    finally:
        db.close()
