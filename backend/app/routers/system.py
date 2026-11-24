from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require
from app.config import settings
from app.database import get_db
from app.models import AttendanceRecord, PunchLog

router = APIRouter(prefix="/api/system", tags=["System"])


@router.get("/log-coverage")
def log_coverage(db: Session = Depends(get_db), _=Depends(require("report.view", "attendance.view", "dashboard.view"))):
    """Report how much attendance history is stored and the retention policy."""
    punch_from, punch_to, punch_count = db.query(
        func.min(PunchLog.punch_time), func.max(PunchLog.punch_time), func.count(PunchLog.id)
    ).one()
    record_from, record_to, record_count = db.query(
        func.min(AttendanceRecord.record_date), func.max(AttendanceRecord.record_date),
        func.count(AttendanceRecord.id),
    ).one()

    return {
        "retention_days": settings.LOG_RETENTION_DAYS,
        "retention_until": (date.today() - timedelta(days=settings.LOG_RETENTION_DAYS)).isoformat(),
        "punch_from": punch_from.date().isoformat() if punch_from else None,
        "punch_to": punch_to.date().isoformat() if punch_to else None,
        "punch_count": punch_count,
        "record_from": record_from.isoformat() if record_from else None,
        "record_to": record_to.isoformat() if record_to else None,
        "record_count": record_count,
    }
