"""HR-managed employee documents with category-based visibility."""

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import require
from app.database import get_db
from app.models import EmployeeDocument, User
from app.schemas import EmployeeDocumentOut
from app.services.employee_documents import (
    DocumentError, document_path, query_visible, remove_document, save_document,
    serialize, visible_document,
)

router = APIRouter(prefix="/api/employee-documents", tags=["Employee documents"])


@router.get("", response_model=list[EmployeeDocumentOut])
def list_documents(
    employee_id: int | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("document.view", "self.portal")),
):
    try:
        documents = query_visible(db, user, employee_id, category)
    except DocumentError as exc:
        raise HTTPException(403, str(exc)) from exc
    return [serialize(db, document) for document in documents]


@router.post("", response_model=EmployeeDocumentOut, status_code=201)
async def upload_document(
    employee_id: int = Form(...),
    category: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require("document.manage")),
):
    content = await file.read()
    try:
        document = save_document(
            db, user, employee_id, category, file.filename or "",
            file.content_type, content,
        )
    except DocumentError as exc:
        status = 403 if "Only HR" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc
    return serialize(db, document)


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("document.view", "self.portal")),
):
    document = db.get(EmployeeDocument, document_id)
    if document is None or not visible_document(document, user):
        raise HTTPException(404, "Document not found")
    path = document_path(document)
    if not os.path.exists(path):
        raise HTTPException(404, "Document file is missing")
    return FileResponse(
        path,
        media_type=document.content_type or "application/octet-stream",
        filename=document.original_filename,
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("document.manage")),
):
    try:
        remove_document(db, user, document_id)
    except DocumentError as exc:
        status = 403 if "Only HR" in str(exc) else 404
        raise HTTPException(status, str(exc)) from exc
