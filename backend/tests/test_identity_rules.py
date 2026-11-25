from conftest import sample_db

from app.models import Device, Employee, User
from app.services import biometric
from app.services.biometric import sync_device
from app.services.identity import IdentifierConflict


def _employee(db, code, device_uid):
    employee = Employee(
        employee_code=code, first_name="Test", device_user_id=device_uid,
        status="active",
    )
    db.add(employee)
    db.commit()
    return employee


def _expect_conflict(db):
    try:
        db.commit()
    except IdentifierConflict:
        db.rollback()
        return
    raise AssertionError("Expected an identifier conflict")


def test_employee_ids_and_device_uids_are_permanent():
    _, Session = sample_db()
    db = Session()
    try:
        original = _employee(db, "NEW100", "9001")

        db.add(Employee(employee_code="NEW100", first_name="Other", device_user_id="9002"))
        _expect_conflict(db)

        db.add(Employee(employee_code="NEW101", first_name="Other", device_user_id="9001"))
        _expect_conflict(db)

        db.delete(original)
        db.commit()

        db.add(Employee(employee_code="NEW100", first_name="Reused", device_user_id="9003"))
        _expect_conflict(db)
        db.add(Employee(employee_code="NEW102", first_name="Reused", device_user_id="9001"))
        _expect_conflict(db)

        survivor = _employee(db, "NEW102", "9004")
        survivor.employee_code = "NEW100"
        _expect_conflict(db)
    finally:
        db.close()


def test_only_one_user_can_ever_be_linked_to_an_employee():
    _, Session = sample_db()
    db = Session()
    try:
        employee = _employee(db, "LINK100", "9100")
        first = User(username="link-user-1", password_hash="x", employee_id=employee.id)
        db.add(first)
        db.commit()

        second = User(username="link-user-2", password_hash="x", employee_id=employee.id)
        db.add(second)
        _expect_conflict(db)

        first.employee_id = None
        db.commit()
        db.add(second)
        _expect_conflict(db)
    finally:
        db.close()


def test_live_sync_does_not_recreate_a_retired_device_user(monkeypatch):
    _, Session = sample_db()
    db = Session()
    try:
        device = Device(
            name="Live", ip_address="192.0.2.10", port=4370,
            mode="live", is_active=True,
        )
        db.add(device)
        db.flush()
        retired = _employee(db, "DEV-RES1", "RES1")
        db.delete(retired)
        db.commit()

        monkeypatch.setattr(biometric.settings, "AUTO_CREATE_DEVICE_USERS", True)
        monkeypatch.setattr(
            biometric, "_fetch_live",
            lambda ip, port, timeout: ([{"user_id": "RES1", "name": "New", "uid": 1}], []),
        )
        result = sync_device(db, device)
        assert result["success"] is True
        assert db.query(Employee).filter(Employee.device_user_id == "RES1").count() == 0
    finally:
        db.close()
