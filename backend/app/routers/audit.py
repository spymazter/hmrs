from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogOut

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/logs", response_model=list[AuditLogOut])
def list_audit_logs(
    user_id: int | None = None,
    action: str | None = None,
    entity: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Admin-only view of recorded changes, newest first."""
    query = db.query(AuditLog).outerjoin(User, AuditLog.user_id == User.id)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if entity:
        query = query.filter(AuditLog.entity.ilike(f"%{entity}%"))
    if from_date:
        query = query.filter(AuditLog.created_at >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        query = query.filter(
            AuditLog.created_at < datetime.combine(to_date + timedelta(days=1), datetime.min.time())
        )

    rows = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return [
        AuditLogOut(
            id=row.id,
            user_id=row.user_id,
            username=row.user.username if row.user else None,
            full_name=row.user.full_name if row.user else None,
            action=row.action,
            entity=row.entity,
            entity_id=row.entity_id,
            details=row.details,
            created_at=row.created_at,
        )
        for row in rows
    ]
