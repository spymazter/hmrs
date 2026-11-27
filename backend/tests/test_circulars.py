from datetime import date

import pytest

from app.models import Employee, Role, User
from app.services import circulars
from conftest import sample_db


def _role(db, name, permissions):
    role = Role(name=name, permissions=list(permissions))
    db.add(role)
    db.flush()
    return role


def _employee(db, code, uid, first_name):
    employee = Employee(
        employee_code=code, first_name=first_name, last_name="Sample",
        device_user_id=uid, status="active",
    )
    db.add(employee)
    db.flush()
    return employee


def _user(db, username, role, employee=None):
    user = User(username=username, password_hash="x", employee_id=employee.id if employee else None)
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def _upload(db, user, title, audience="all", employee=None):
    return circulars.save_notice(
        db, user, title, audience, employee.id if employee else None,
        date(2026, 11, 27), "circular.pdf", "application/pdf", b"circular bytes",
    )


def _ids(items):
    return {item.id for item in items}


def test_hr_notices_reach_all_employees_and_selected_employee(monkeypatch, tmp_path):
    monkeypatch.setattr(circulars.settings, "CIRCULAR_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        hr = _user(db, "hr", _role(db, "HR Manager", ["circular.manage"]))
        employee_role = _role(db, "Employee", ["dashboard.view", "self.portal"])
        owner = _employee(db, "CIRC001", "9001", "Owner")
        other = _employee(db, "CIRC002", "9002", "Other")
        owner_user = _user(db, "owner", employee_role, employee=owner)
        other_user = _user(db, "other", employee_role, employee=other)

        notice_all = _upload(db, hr, "Office closure")
        notice_own = _upload(db, hr, "Your appraisal", "employee", owner)

        assert _ids(circulars.query_for_user(db, owner_user)) == {notice_all.id, notice_own.id}
        assert _ids(circulars.query_for_user(db, other_user)) == {notice_all.id}

        with pytest.raises(circulars.CircularError, match="Only HR"):
            _upload(db, owner_user, "Not allowed")

        with pytest.raises(circulars.CircularError, match="not found"):
            circulars.mark_viewed(db, other_user, notice_own.id)
    finally:
        db.close()


def test_view_receipts_and_size_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(circulars.settings, "CIRCULAR_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        hr = _user(db, "hr", _role(db, "HR Manager", ["circular.manage"]))
        employee_role = _role(db, "Employee", ["dashboard.view", "self.portal"])
        employee = _employee(db, "CIRC003", "9003", "Viewer")
        employee_user = _user(db, "viewer", employee_role, employee=employee)
        notice = _upload(db, hr, "Policy update")

        row = circulars.serialize(db, notice, employee_user)
        assert row["viewed_by_me"] is False
        assert row["viewed_count"] == 0
        assert row["target_count"] >= 1

        circulars.mark_viewed(db, employee_user, notice.id)
        circulars.mark_viewed(db, employee_user, notice.id)  # idempotent
        row = circulars.serialize(db, notice, employee_user)
        assert row["viewed_by_me"] is True
        assert row["viewed_count"] == 1
        assert row["viewed_at"] is not None

        with pytest.raises(circulars.CircularError, match="1 MB"):
            circulars.save_notice(
                db, hr, "Too big", "all", None, date.today(), "big.pdf",
                "application/pdf", b"x" * (circulars.MAX_BYTES + 1),
            )

        circulars.remove_notice(db, hr, notice.id)
        assert db.get(type(notice), notice.id) is None
    finally:
        db.close()
