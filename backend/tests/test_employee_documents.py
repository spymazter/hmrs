import pytest
from fastapi import HTTPException

from app.auth import effective_permissions
from app.models import Employee, Role, RoleGroup, User
from app.permissions import ALL_CODES
from app.routers import employee_documents as documents_router
from app.services import employee_documents as documents
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


def _user(db, username, role, employee=None, groups=()):
    user = User(username=username, password_hash="x", employee_id=employee.id if employee else None)
    user.roles = [role]
    user.groups = list(groups)
    db.add(user)
    db.flush()
    return user


def _upload(db, user, employee, category, filename):
    return documents.save_document(
        db, user, employee.id, category, filename, "application/pdf", b"document bytes"
    )


def _ids(items):
    return {item.id for item in items}


def test_hr_uploads_all_categories_with_role_based_visibility(monkeypatch, tmp_path):
    monkeypatch.setattr(documents.settings, "DOCUMENT_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        hr_role = _role(db, "HR Manager", ["document.view", "document.manage", "document.hr"])
        emp_role = _role(db, "Employee", ["document.view", "self.portal"])
        hr = _user(db, "hr", hr_role)

        owner = _employee(db, "DOCDOC001", "8801", "Owner")
        other = _employee(db, "DOCDOC002", "8802", "Other")
        owner_user = _user(db, "owner-user", emp_role, employee=owner)
        other_user = _user(db, "other-user", emp_role, employee=other)

        appointment = _upload(db, hr, owner, "appointment_order", "appointment.pdf")
        fitness = _upload(db, hr, owner, "medical_fitness", "fitness.pdf")
        antecedent = _upload(db, hr, owner, "antecedent_verification", "antecedent.pdf")

        assert documents.is_hr(hr)
        assert _ids(documents.query_visible(db, hr)) == {appointment.id, fitness.id, antecedent.id}

        assert _ids(documents.query_visible(db, owner_user)) == {appointment.id, fitness.id}
        assert _ids(documents.query_visible(db, other_user)) == set()
        assert _ids(documents.query_visible(db, owner_user, category="antecedent_verification")) == set()

        response = documents_router.download_document(appointment.id, db, owner_user)
        assert response.filename == "appointment.pdf"
        assert documents_router.download_document(fitness.id, db, owner_user).filename == "fitness.pdf"

        for document_id in (antecedent.id, appointment.id):
            with pytest.raises(HTTPException) as denied:
                documents_router.download_document(
                    antecedent.id if document_id == antecedent.id else appointment.id,
                    db,
                    other_user if document_id == appointment.id else owner_user,
                )
            assert denied.value.status_code == 404

        with pytest.raises(documents.DocumentError, match="own documents"):
            documents.query_visible(db, owner_user, employee_id=other.id)
    finally:
        db.close()


def test_employee_and_group_inherited_hr_cannot_upload_or_view_hr_only_documents(monkeypatch, tmp_path):
    monkeypatch.setattr(documents.settings, "DOCUMENT_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        hr_role = _role(db, "HR Manager", ["document.view", "document.manage", "document.hr"])
        manager_role = _role(db, "Manager", ["dashboard.view", "self.portal"])
        management = RoleGroup(name="Management", roles=[hr_role])
        db.add(management)
        db.flush()

        hr = _user(db, "hr", hr_role)
        manager = _user(db, "manager-user", manager_role, groups=[management])
        employee = _employee(db, "DOCDOC003", "8803", "Worker")
        employee_user = _user(db, "worker-user", manager_role, employee=employee)
        antecedent = _upload(db, hr, employee, "antecedent_verification", "antecedent.pdf")

        assert "document.hr" in effective_permissions(manager)
        assert not documents.is_hr(manager)
        assert not documents.visible_document(antecedent, manager)
        assert _ids(documents.query_visible(db, manager)) == set()

        with pytest.raises(documents.DocumentError, match="Only HR"):
            documents.save_document(
                db, manager, employee.id, "appointment_order", "appointment.pdf",
                "application/pdf", b"not allowed",
            )
        with pytest.raises(documents.DocumentError, match="Only HR"):
            documents.save_document(
                db, employee_user, employee.id, "appointment_order", "appointment.pdf",
                "application/pdf", b"not allowed",
            )
    finally:
        db.close()


def test_upload_rejects_files_over_one_mb(monkeypatch, tmp_path):
    monkeypatch.setattr(documents.settings, "DOCUMENT_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        admin = _user(db, "admin-size", _role(db, "Admin", ALL_CODES))
        employee = _employee(db, "DOCDOC005", "8805", "SizeCheck")

        with pytest.raises(documents.DocumentError, match="1 MB"):
            documents.save_document(
                db, admin, employee.id, "appointment_order", "too-big.pdf",
                "application/pdf", b"x" * (documents.MAX_BYTES + 1),
            )

        accepted = documents.save_document(
            db, admin, employee.id, "appointment_order", "exact-mb.pdf",
            "application/pdf", b"x" * documents.MAX_BYTES,
        )
        assert accepted.size_bytes == documents.MAX_BYTES
    finally:
        db.close()


def test_admin_can_upload_and_delete_all_documents(monkeypatch, tmp_path):
    monkeypatch.setattr(documents.settings, "DOCUMENT_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        admin = _user(db, "admin", _role(db, "Admin", ALL_CODES))
        employee = _employee(db, "DOCDOC004", "8804", "AdminManaged")
        document = _upload(db, admin, employee, "antecedent_verification", "confidential.pdf")

        assert documents.is_hr(admin)
        documents_router.delete_document(document.id, db, admin)
        assert db.get(documents.EmployeeDocument, document.id) is None
    finally:
        db.close()
