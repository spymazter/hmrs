from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require
from app.database import get_db
from app.models import Employee, Shift, ShiftGroup
from app.schemas import (
    ShiftGroupCreate, ShiftGroupEmployeeMapping, ShiftGroupOut, ShiftGroupUpdate,
)

router = APIRouter(prefix="/api/shift-groups", tags=["Shift groups"])


def _resolve_rows(model, ids: list[int], label: str, db: Session) -> list:
    """Deduplicate ids and reject any that do not exist."""
    unique_ids = list(dict.fromkeys(ids or []))
    if not unique_ids:
        return []
    rows = db.query(model).filter(model.id.in_(unique_ids)).all()
    if len(rows) != len(unique_ids):
        raise HTTPException(400, f"Unknown {label} id in the selection")
    return rows


def _check_unique(group: ShiftGroup, payload, db: Session) -> None:
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Group name is required")
    query = db.query(ShiftGroup).filter(ShiftGroup.name == name)
    if group.id:
        query = query.filter(ShiftGroup.id != group.id)
    if query.first():
        raise HTTPException(400, "Shift group name already exists")

    code = (payload.code or "").strip() or None
    if code:
        query = db.query(ShiftGroup).filter(ShiftGroup.code == code)
        if group.id:
            query = query.filter(ShiftGroup.id != group.id)
        if query.first():
            raise HTTPException(400, "Shift group code already exists")


def _apply_links(group: ShiftGroup, shift_ids, employee_ids, db: Session) -> None:
    """Writing the relationship keeps both sides' foreign keys in sync."""
    if shift_ids is not None:
        group.shifts = _resolve_rows(Shift, shift_ids, "shift", db)
    if employee_ids is not None:
        group.employees = _resolve_rows(Employee, employee_ids, "employee", db)


@router.get("", response_model=list[ShiftGroupOut])
def list_groups(db: Session = Depends(get_db), _=Depends(require("shift.view", "employee.view", "self.portal"))):
    return db.query(ShiftGroup).order_by(ShiftGroup.id).all()


@router.post("", response_model=ShiftGroupOut, status_code=201)
def create_group(payload: ShiftGroupCreate, db: Session = Depends(get_db), _=Depends(require("shift.manage"))):
    group = ShiftGroup(
        name=payload.name.strip(),
        code=(payload.code or "").strip() or None,
        description=payload.description,
        is_active=payload.is_active,
    )
    _check_unique(group, payload, db)
    db.add(group)
    db.flush()
    _apply_links(group, payload.shift_ids, payload.employee_ids, db)
    db.commit()
    db.refresh(group)
    return group


@router.put("/{group_id}", response_model=ShiftGroupOut)
def update_group(group_id: int, payload: ShiftGroupUpdate, db: Session = Depends(get_db), _=Depends(require("shift.manage"))):
    group = db.get(ShiftGroup, group_id)
    if not group:
        raise HTTPException(404, "Shift group not found")
    if payload.name is not None:
        _check_unique(group, payload, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key in ("shift_ids", "employee_ids"):
            continue
        if key == "name":
            value = value.strip()
        if key == "code":
            value = value.strip() or None if value is not None else None
        setattr(group, key, value)
    _apply_links(group, payload.shift_ids, payload.employee_ids, db)
    db.commit()
    db.refresh(group)
    return group


@router.put("/{group_id}/employees", response_model=ShiftGroupOut)
def map_employees(group_id: int, payload: ShiftGroupEmployeeMapping, db: Session = Depends(get_db), _=Depends(require("shift.manage"))):
    """Replace the employees mapped to a group. An employee belongs to one group."""
    group = db.get(ShiftGroup, group_id)
    if not group:
        raise HTTPException(404, "Shift group not found")
    group.employees = _resolve_rows(Employee, payload.employee_ids, "employee", db)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: int, db: Session = Depends(get_db), _=Depends(require("shift.manage"))):
    group = db.get(ShiftGroup, group_id)
    if not group:
        raise HTTPException(404, "Shift group not found")
    # Explicitly unlink so the mapping is cleared even where SQLite FK
    # enforcement is disabled (the default for this database).
    for employee in group.employees:
        employee.shift_group_id = None
    for shift in group.shifts:
        shift.shift_group_id = None
    db.delete(group)
    db.commit()
