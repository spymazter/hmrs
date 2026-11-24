from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require, scoped_employee_id
from app.database import get_db
from app.models import LeaveRequest, User
from app.schemas import LeaveAction, LeaveRequestCreate, LeaveRequestOut
from app.services.attendance import recompute_records

router = APIRouter(prefix="/api/leaves", tags=["Leaves"])


@router.get("/requests", response_model=list[LeaveRequestOut])
def list_requests(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.view", "self.portal")),
):
    query = db.query(LeaveRequest)
    scoped = scoped_employee_id(user)
    if scoped:
        query = query.filter(LeaveRequest.employee_id == scoped)
    if status:
        query = query.filter(LeaveRequest.status == status)
    return query.order_by(LeaveRequest.from_date.desc()).all()


@router.post("/requests", response_model=LeaveRequestOut, status_code=201)
def apply_leave(
    payload: LeaveRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.manage", "self.portal")),
):
    employee_id = payload.employee_id
    scoped = scoped_employee_id(user)
    if scoped:
        employee_id = scoped
    if payload.to_date < payload.from_date:
        raise HTTPException(400, "to_date must be on or after from_date")
    leave = LeaveRequest(**payload.model_dump(exclude={"employee_id"}), employee_id=employee_id)
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


@router.post("/requests/{leave_id}/action", response_model=LeaveRequestOut)
def action_leave(
    leave_id: int,
    payload: LeaveAction,
    db: Session = Depends(get_db),
    user: User = Depends(require("leave.approve")),
):
    leave = db.query(LeaveRequest).get(leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be approved or rejected")
    leave.status = payload.status
    leave.approved_by = user.id
    db.commit()
    db.refresh(leave)
    recompute_records(db, leave.from_date, leave.to_date, employee_id=leave.employee_id)
    return leave


@router.delete("/requests/{leave_id}", status_code=204)
def delete_leave(leave_id: int, db: Session = Depends(get_db), user: User = Depends(require("leave.manage", "self.portal"))):
    leave = db.query(LeaveRequest).get(leave_id)
    if not leave:
        raise HTTPException(404, "Leave request not found")
    scoped = scoped_employee_id(user)
    if scoped and leave.employee_id != scoped:
        raise HTTPException(403, "Not allowed")
    db.delete(leave)
    db.commit()
