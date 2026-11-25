from datetime import date

import pytest

from app.models import Employee, Role, User
from app.routers import employees as employees_router
from app.routers import employee_documents as documents_router
from app.schemas import EmployeeSelfUpdate
from app.services import employee_documents as documents
from conftest import sample_db


def _role(db, name, permissions):
    role = Role(name=name, permissions=list(permissions))
    db.add(role)
    db.flush()
    return role


def _employee(db, code, uid, first_name):
    employee = Employee(
        employee_code=code, first_name=first_name, last_name="Self",
        device_user_id=uid, status="active",
    )
    db.add(employee)
    db.flush()
    return employee


def _user(db, username, role, employee=None, full_name=None):
    user = User(
        username=username, password_hash="x", full_name=full_name or username,
        employee_id=employee.id if employee else None,
    )
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def _upload(db, user, employee, category, filename):
    return documents.save_document(
        db, user, employee.id, category, filename, "application/pdf", b"kyc bytes"
    )


def test_employee_can_update_dob_and_nominee_details():
    _, Session = sample_db()
    db = Session()
    try:
        role = _role(db, "Employee", ["self.portal", "document.view"])
        employee = _employee(db, "SELF001", "9001", "Self")
        user = _user(db, "self-update-user", role, employee)

        updated = employees_router.update_my_profile(
            EmployeeSelfUpdate(
                date_of_birth=date(1992, 4, 18),
                nominee_name="Family Member",
                nominee_relationship="Spouse",
            ),
            db,
            user,
        )

        assert updated.date_of_birth == date(1992, 4, 18)
        assert updated.nominee_name == "Family Member"
        assert updated.nominee_relationship == "Spouse"
        assert db.get(Employee, employee.id).nominee_name == "Family Member"
    finally:
        db.close()


def test_employee_uploads_own_kyc_and_hr_can_view(monkeypatch, tmp_path):
    monkeypatch.setattr(documents.settings, "DOCUMENT_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        employee_role = _role(db, "Employee", ["self.portal", "document.view"])
        hr_role = _role(db, "HR Manager", ["document.view", "document.manage", "document.hr"])

        owner = _employee(db, "SELF002", "9002", "Owner")
        other = _employee(db, "SELF003", "9003", "Other")
        owner_user = _user(db, "self-owner", employee_role, owner)
        other_user = _user(db, "self-other", employee_role, other)
        hr = _user(db, "self-hr", hr_role)

        uploads = [
            _upload(db, owner_user, owner, category, f"{category}.pdf")
            for category in documents.EMPLOYEE_KYC_CATEGORIES
        ]

        assert {document.category for document in uploads} == set(
            documents.EMPLOYEE_KYC_CATEGORIES
        )
        assert {document.id for document in documents.query_visible(db, owner_user)} == {
            document.id for document in uploads
        }
        assert documents.query_visible(db, other_user).count() == 0
        assert {document.id for document in documents.query_visible(db, hr)} >= {
            document.id for document in uploads
        }
        for document in uploads:
            response = documents_router.download_document(document.id, db, hr)
            assert response.filename == f"{document.category}.pdf"

        with pytest.raises(documents.DocumentError, match="own documents"):
            _upload(db, owner_user, other, "employee_pan", "other.pdf")
        with pytest.raises(documents.DocumentError, match="Only HR"):
            _upload(db, owner_user, owner, "appointment_order", "appointment.pdf")
    finally:
        db.close()


def test_employee_can_remove_only_own_uploaded_kyc(monkeypatch, tmp_path):
    monkeypatch.setattr(documents.settings, "DOCUMENT_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        employee_role = _role(db, "Employee", ["self.portal", "document.view"])
        hr_role = _role(db, "HR Manager", ["document.view", "document.manage", "document.hr"])
        employee = _employee(db, "SELF004", "9004", "Removable")
        user = _user(db, "self-delete-user", employee_role, employee)
        hr = _user(db, "self-delete-hr", hr_role)

        own = _upload(db, user, employee, "nominee_aadhaar", "own.pdf")
        hr_uploaded = _upload(db, hr, employee, "employee_pan", "hr.pdf")

        documents_router.delete_document(own.id, db, user)
        assert db.get(documents.EmployeeDocument, own.id) is None

        with pytest.raises(documents.DocumentError, match="own KYC documents"):
            documents.remove_document(db, user, hr_uploaded.id)
        assert db.get(documents.EmployeeDocument, hr_uploaded.id) is not None
    finally:
        db.close()
