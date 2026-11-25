from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import hash_password, require, user_to_dict
from app.database import get_db
from app.models import Role, RoleGroup, User
from app.permissions import PERMISSIONS
from app.schemas import (
    GroupCreate, GroupOut, GroupUpdate, RoleCreate, RoleOut, RoleUpdate,
    UserAssign, UserCreate, UserOut, UserUpdate,
)
from app.services.identity import IdentifierConflict

router = APIRouter(prefix="/api/access", tags=["Access control"])


@router.get("/permissions")
def list_permissions(_=Depends(require("access.view", "access.manage"))):
    return [{"code": code, "label": label, "module": module} for code, label, module in PERMISSIONS]


# Roles ---------------------------------------------------------------------
@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _=Depends(require("access.view", "access.manage"))):
    return db.query(Role).order_by(Role.id).all()


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(payload: RoleCreate, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    if db.query(Role).filter(Role.name == payload.name).first():
        raise HTTPException(400, "Role name already exists")
    role = Role(**payload.model_dump())
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    role = db.query(Role).get(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(role, key, value)
    db.commit()
    db.refresh(role)
    return role


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    role = db.query(Role).get(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    db.delete(role)
    db.commit()


# Role groups ---------------------------------------------------------------
@router.get("/groups", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db), _=Depends(require("access.view", "access.manage"))):
    return db.query(RoleGroup).order_by(RoleGroup.id).all()


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(payload: GroupCreate, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    if db.query(RoleGroup).filter(RoleGroup.name == payload.name).first():
        raise HTTPException(400, "Group name already exists")
    group = RoleGroup(name=payload.name, description=payload.description)
    group.roles = db.query(Role).filter(Role.id.in_(payload.role_ids)).all()
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.put("/groups/{group_id}", response_model=GroupOut)
def update_group(group_id: int, payload: GroupUpdate, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    group = db.query(RoleGroup).get(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if payload.name is not None:
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    if payload.role_ids is not None:
        group.roles = db.query(Role).filter(Role.id.in_(payload.role_ids)).all()
    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: int, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    group = db.query(RoleGroup).get(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    db.delete(group)
    db.commit()


# Users ---------------------------------------------------------------------
@router.get("/users", response_model=list[dict])
def list_users(db: Session = Depends(get_db), _=Depends(require("access.view", "access.manage"))):
    return [user_to_dict(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users", response_model=dict, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "Username already exists")
    user = User(
        username=payload.username, email=payload.email,
        full_name=payload.full_name, is_active=payload.is_active,
        employee_id=payload.employee_id,
        password_hash=hash_password(payload.password),
        must_change_password=bool(payload.employee_id),
        profile_completed=not bool(payload.employee_id),
    )
    user.roles = db.query(Role).filter(Role.id.in_(payload.role_ids)).all()
    user.groups = db.query(RoleGroup).filter(RoleGroup.id.in_(payload.group_ids)).all()
    db.add(user)
    try:
        db.commit()
    except IdentifierConflict as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.refresh(user)
    return user_to_dict(user)


@router.put("/users/{user_id}", response_model=dict)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for key, value in data.items():
        setattr(user, key, value)

    if "employee_id" in data:
        if data["employee_id"]:
            user.profile_completed = False
            user.must_change_password = True
        else:
            user.profile_completed = True
            user.must_change_password = False
    if password:
        user.password_hash = hash_password(password)
        if user.employee_id:
            user.must_change_password = True
    try:
        db.commit()
    except IdentifierConflict as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.refresh(user)
    return user_to_dict(user)


@router.post("/users/{user_id}/assign", response_model=dict)
def assign_roles(user_id: int, payload: UserAssign, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.roles = db.query(Role).filter(Role.id.in_(payload.role_ids)).all()
    user.groups = db.query(RoleGroup).filter(RoleGroup.id.in_(payload.group_ids)).all()
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), _=Depends(require("access.manage"))):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
