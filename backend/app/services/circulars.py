"""Storage and visibility rules for the HR circular notice board."""

import os
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import can
from app.config import settings
from app.models import CircularNotice, CircularView, Employee, User
from app.services.employee_documents import ALLOWED_EXTENSIONS, MAX_BYTES


class CircularError(ValueError):
    """Raised for invalid circular uploads or unauthorised access."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def is_manager(user: User) -> bool:
    return can(user, "circular.manage")


def visible_notice(notice: CircularNotice, user: User) -> bool:
    if not notice or not notice.is_active:
        return False
    if is_manager(user):
        return True
    if notice.audience == "all":
        return True
    return bool(user.employee_id) and notice.employee_id == user.employee_id


def query_for_user(db: Session, user: User) -> list[CircularNotice]:
    """Notices for a dashboard: all-employee notices plus personal ones."""
    query = db.query(CircularNotice).filter(CircularNotice.is_active.is_(True))
    if is_manager(user):
        return query.order_by(CircularNotice.issued_date.desc(), CircularNotice.id.desc()).all()
    if not user.employee_id:
        return []
    query = query.filter(or_(
        CircularNotice.audience == "all",
        CircularNotice.employee_id == user.employee_id,
    ))
    return query.order_by(CircularNotice.issued_date.desc(), CircularNotice.id.desc()).all()


def query_all(db: Session) -> list[CircularNotice]:
    return db.query(CircularNotice).order_by(
        CircularNotice.issued_date.desc(), CircularNotice.id.desc()
    ).all()


def serialize(db: Session, notice: CircularNotice, user: User | None = None) -> dict:
    employee = db.get(Employee, notice.employee_id) if notice.employee_id else None
    uploader = db.get(User, notice.uploaded_by) if notice.uploaded_by else None
    view_query = db.query(CircularView).filter(CircularView.circular_id == notice.id)
    viewed_count = view_query.count()
    if notice.audience == "all":
        target_count = db.query(func.count(Employee.id)).filter(Employee.status == "active").scalar() or 0
    else:
        target_count = 1 if notice.employee_id else 0

    my_view = None
    if user:
        my_view = view_query.filter(CircularView.user_id == user.id).first()

    return {
        "id": notice.id,
        "title": notice.title,
        "audience": notice.audience,
        "audience_label": "All employees" if notice.audience == "all" else "Specific employee",
        "employee_id": notice.employee_id,
        "employee_code": employee.employee_code if employee else None,
        "employee_name": employee.full_name if employee else None,
        "original_filename": notice.original_filename,
        "content_type": notice.content_type,
        "size_bytes": notice.size_bytes or 0,
        "issued_date": notice.issued_date,
        "is_active": bool(notice.is_active),
        "uploaded_by": notice.uploaded_by,
        "uploaded_by_name": uploader.full_name if uploader else None,
        "created_at": notice.created_at,
        "viewed_count": viewed_count,
        "target_count": target_count,
        "viewed_by_me": my_view is not None,
        "viewed_at": my_view.viewed_at if my_view else None,
        "download_url": f"/api/circulars/{notice.id}/download",
    }


def save_notice(
    db: Session, user: User, title: str, audience: str, employee_id: int | None,
    issued: date | None, filename: str, content_type: str | None, content: bytes,
) -> CircularNotice:
    if not is_manager(user):
        raise CircularError("Only HR can upload circular notices", 403)
    title = (title or "").strip()
    if not title:
        raise CircularError("Enter a title for the circular")
    if audience not in ("all", "employee"):
        raise CircularError("Unknown audience")
    if audience == "employee" and not employee_id:
        raise CircularError("Select the employee this circular is issued to")
    if audience == "employee" and db.get(Employee, employee_id) is None:
        raise CircularError("Employee not found", 404)
    if not filename or not content:
        raise CircularError("An empty file cannot be uploaded")
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise CircularError("Only PDF, Word and image files are allowed")
    if len(content) > MAX_BYTES:
        raise CircularError("File is larger than the 1 MB limit")

    directory = settings.CIRCULAR_DIR
    os.makedirs(directory, exist_ok=True)
    stored = f"circular_{uuid4().hex}{extension}"
    with open(os.path.join(directory, stored), "wb") as handle:
        handle.write(content)

    notice = CircularNotice(
        title=title,
        audience=audience,
        employee_id=employee_id if audience == "employee" else None,
        original_filename=os.path.basename(filename),
        stored_filename=stored,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(content),
        issued_date=issued or date.today(),
        is_active=True,
        uploaded_by=user.id,
        created_at=datetime.now(),
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


def notice_path(notice: CircularNotice) -> str:
    return os.path.join(settings.CIRCULAR_DIR, notice.stored_filename)


def mark_viewed(db: Session, user: User, circular_id: int) -> CircularNotice:
    notice = db.get(CircularNotice, circular_id)
    if not visible_notice(notice, user):
        raise CircularError("Circular not found", 404)
    existing = db.query(CircularView).filter(
        CircularView.circular_id == circular_id,
        CircularView.user_id == user.id,
    ).first()
    if not existing:
        db.add(CircularView(
            circular_id=circular_id,
            user_id=user.id,
            employee_id=user.employee_id,
            viewed_at=datetime.now(),
        ))
        db.commit()
    return notice


def remove_notice(db: Session, user: User, circular_id: int) -> None:
    if not is_manager(user):
        raise CircularError("Only HR can remove circular notices", 403)
    notice = db.get(CircularNotice, circular_id)
    if notice is None:
        raise CircularError("Circular not found", 404)
    path = notice_path(notice)
    if os.path.exists(path):
        os.remove(path)
    db.delete(notice)
    db.commit()
