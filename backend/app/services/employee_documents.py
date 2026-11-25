"""Storage and visibility rules for HR-uploaded employee documents."""

import os
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Employee, EmployeeDocument, User

CATEGORIES = {
    "appointment_order": "Appointment order",
    "medical_fitness": "Medical fitness certificate",
    "antecedent_verification": "Antecedent verification form",
}
CONFIDENTIAL = {"antecedent_verification"}
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png",
}
MAX_BYTES = 20 * 1024 * 1024


class DocumentError(ValueError):
    """Raised for invalid uploads or unauthorised document access."""


def _direct_permissions(user: User) -> set[str]:
    codes: set[str] = set()
    for role in user.roles or []:
        codes.update(role.permissions or [])
    return codes


def is_hr(user: User) -> bool:
    """HR/admin must be a direct role, not inherited through a role group.

    The demo Management group includes the HR Manager role; inheriting it must
    not expose HR-only documents to managers or payroll officers.
    """
    names = {role.name.strip().casefold() for role in (user.roles or [])}
    return (
        bool(names & {"hr manager", "admin"})
        or "document.hr" in _direct_permissions(user)
        or (getattr(user, "username", "") or "").casefold() == "admin"
    )


def visible_document(document: EmployeeDocument, user: User) -> bool:
    if document.category in CONFIDENTIAL:
        return is_hr(user)
    if is_hr(user):
        return True
    return user.employee_id == document.employee_id


def query_visible(db: Session, user: User, employee_id: int | None = None,
                  category: str | None = None):
    query = db.query(EmployeeDocument)
    if category:
        query = query.filter(EmployeeDocument.category == category)
    if is_hr(user):
        if employee_id:
            query = query.filter(EmployeeDocument.employee_id == employee_id)
    else:
        own_id = user.employee_id or -1
        query = query.filter(
            EmployeeDocument.employee_id == own_id,
            ~EmployeeDocument.category.in_(CONFIDENTIAL),
        )
        if employee_id and employee_id != user.employee_id:
            raise DocumentError("You can only view your own documents")
    return query.order_by(EmployeeDocument.uploaded_at.desc())


def serialize(db: Session, document: EmployeeDocument) -> dict:
    employee = db.get(Employee, document.employee_id)
    uploader = db.get(User, document.uploaded_by) if document.uploaded_by else None
    return {
        "id": document.id,
        "employee_id": document.employee_id,
        "employee_code": employee.employee_code if employee else None,
        "employee_name": employee.full_name if employee else None,
        "category": document.category,
        "category_label": CATEGORIES.get(document.category, document.category),
        "original_filename": document.original_filename,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes or 0,
        "uploaded_by": document.uploaded_by,
        "uploaded_by_name": uploader.full_name if uploader else None,
        "uploaded_at": document.uploaded_at,
    }


def save_document(db: Session, user: User, employee_id: int, category: str,
                  filename: str, content_type: str | None, content: bytes) -> EmployeeDocument:
    if not is_hr(user):
        raise DocumentError("Only HR can upload employee documents")
    if category not in CATEGORIES:
        raise DocumentError("Unknown document type")
    if not filename or not content:
        raise DocumentError("An empty file cannot be uploaded")
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentError(
            "Only PDF, Word and image files are allowed"
        )
    if len(content) > MAX_BYTES:
        raise DocumentError("File is larger than the 20 MB limit")
    if db.get(Employee, employee_id) is None:
        raise DocumentError("Employee not found")

    directory = settings.DOCUMENT_DIR
    os.makedirs(directory, exist_ok=True)
    stored = f"{employee_id}_{category}_{uuid4().hex}{extension}"
    with open(os.path.join(directory, stored), "wb") as handle:
        handle.write(content)

    document = EmployeeDocument(
        employee_id=employee_id,
        category=category,
        original_filename=os.path.basename(filename),
        stored_filename=stored,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(content),
        uploaded_by=user.id,
        uploaded_at=datetime.now(),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def document_path(document: EmployeeDocument) -> str:
    return os.path.join(settings.DOCUMENT_DIR, document.stored_filename)


def remove_document(db: Session, user: User, document_id: int) -> None:
    if not is_hr(user):
        raise DocumentError("Only HR can remove employee documents")
    document = db.get(EmployeeDocument, document_id)
    if document is None:
        raise DocumentError("Document not found")
    path = document_path(document)
    if os.path.exists(path):
        os.remove(path)
    db.delete(document)
    db.commit()
