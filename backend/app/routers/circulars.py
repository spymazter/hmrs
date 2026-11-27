"""HR notice board: circular uploads, employee dashboards and read receipts."""

import os
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import require
from app.database import get_db
from app.models import CircularNotice, User
from app.schemas import CircularNoticeOut
from app.services.circulars import (
    CircularError, mark_viewed, notice_path, query_all, query_for_user,
    remove_notice, save_notice, serialize, visible_notice,
)

router = APIRouter(prefix="/api/circulars", tags=["Circular notices"])


def _fail(exc: CircularError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


@router.get("", response_model=list[CircularNoticeOut])
def list_circulars(
    db: Session = Depends(get_db),
    user: User = Depends(require("circular.manage")),
):
    return [serialize(db, notice, user) for notice in query_all(db)]


@router.post("", response_model=CircularNoticeOut, status_code=201)
async def upload_circular(
    title: str = Form(...),
    audience: str = Form("all"),
    employee_id: int | None = Form(None),
    issued_date: date | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require("circular.manage")),
):
    content = await file.read()
    try:
        notice = save_notice(
            db, user, title, audience, employee_id, issued_date,
            file.filename or "", file.content_type, content,
        )
    except CircularError as exc:
        raise _fail(exc) from exc
    return serialize(db, notice, user)


@router.get("/inbox", response_model=list[CircularNoticeOut])
def circular_inbox(
    db: Session = Depends(get_db),
    user: User = Depends(require("dashboard.view", "self.portal", "circular.manage")),
):
    """Employee notice board: notices for all staff plus personal notices."""
    return [serialize(db, notice, user) for notice in query_for_user(db, user)]


@router.get("/{circular_id}/download")
def download_circular(
    circular_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("dashboard.view", "self.portal", "circular.manage")),
):
    notice = db.get(CircularNotice, circular_id)
    if not visible_notice(notice, user):
        raise HTTPException(404, "Circular not found")
    path = notice_path(notice)
    if not os.path.exists(path):
        raise HTTPException(404, "Circular file is missing")
    return FileResponse(
        path,
        media_type=notice.content_type or "application/octet-stream",
        filename=notice.original_filename,
    )


@router.post("/{circular_id}/view", response_model=CircularNoticeOut)
def view_circular(
    circular_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("dashboard.view", "self.portal", "circular.manage")),
):
    try:
        notice = mark_viewed(db, user, circular_id)
    except CircularError as exc:
        raise _fail(exc) from exc
    return serialize(db, notice, user)


@router.delete("/{circular_id}", status_code=204)
def delete_circular(
    circular_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("circular.manage")),
):
    try:
        remove_notice(db, user, circular_id)
    except CircularError as exc:
        raise _fail(exc) from exc
