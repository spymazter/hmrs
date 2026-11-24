from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require
from app.database import get_db
from app.models import Shift
from app.schemas import ShiftCreate, ShiftOut, ShiftUpdate

router = APIRouter(prefix="/api/shifts", tags=["Shifts"])


@router.get("", response_model=list[ShiftOut])
def list_shifts(db: Session = Depends(get_db), _=Depends(require("shift.view", "employee.view", "self.portal"))):
    return db.query(Shift).order_by(Shift.id).all()


@router.post("", response_model=ShiftOut, status_code=201)
def create_shift(payload: ShiftCreate, db: Session = Depends(get_db), _=Depends(require("shift.manage"))):
    if db.query(Shift).filter(Shift.name == payload.name).first():
        raise HTTPException(400, "Shift name already exists")
    shift = Shift(**payload.model_dump())
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.put("/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: int, payload: ShiftUpdate, db: Session = Depends(get_db), _=Depends(require("shift.manage"))):
    shift = db.query(Shift).get(shift_id)
    if not shift:
        raise HTTPException(404, "Shift not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(shift, key, value)
    db.commit()
    db.refresh(shift)
    return shift


@router.delete("/{shift_id}", status_code=204)
def delete_shift(shift_id: int, db: Session = Depends(get_db), _=Depends(require("shift.manage"))):
    shift = db.query(Shift).get(shift_id)
    if not shift:
        raise HTTPException(404, "Shift not found")
    db.delete(shift)
    db.commit()
