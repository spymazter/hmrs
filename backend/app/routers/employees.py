from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import can, get_current_user, hash_password, require
from app.database import get_db
from app.models import Employee, Role, User
from app.schemas import (
    EmployeeCreate, EmployeeListOut, EmployeeOut, EmployeeSelfUpdate, EmployeeUpdate,
)
from app.services.identity import IdentifierConflict

router = APIRouter(prefix="/api/employees", tags=["Employees"])


@router.get("/me", response_model=EmployeeOut)
def my_profile(user: User = Depends(require("self.portal", "employee.view"))):
    if not user.employee_id:
        raise HTTPException(404, "No employee profile is linked to this account")
    return user.employee


@router.put("/me", response_model=EmployeeOut)
def update_my_profile(
    payload: EmployeeSelfUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("self.portal", "employee.view")),
):
    """Update only personal details for the logged-in employee.

    Username, employee code, status, device UID, department, designation,
    shift and manager are intentionally not accepted here.
    """
    if not user.employee_id:
        raise HTTPException(404, "No employee profile is linked to this account")
    employee = db.query(Employee).get(user.employee_id)
    if not employee:
        raise HTTPException(404, "Employee profile not found")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(employee, key, value.strip() if isinstance(value, str) else value)

    if "first_name" in data or "last_name" in data:
        user.full_name = f"{employee.first_name} {employee.last_name}".strip()

    db.commit()
    db.refresh(employee)
    return employee


@router.get("", response_model=EmployeeListOut)
def list_employees(
    search: str = "",
    department_id: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require("employee.view")),
):
    query = db.query(Employee)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Employee.first_name.ilike(like))
            | (Employee.last_name.ilike(like))
            | (Employee.employee_code.ilike(like))
            | (Employee.email.ilike(like))
        )
    if department_id:
        query = query.filter(Employee.department_id == department_id)
    if status:
        query = query.filter(Employee.status == status)
    total = query.count()
    items = query.order_by(Employee.employee_code).offset(skip).limit(min(limit, 500)).all()
    return {"items": items, "total": total}


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db), _=Depends(require("employee.create"))):
    data = payload.model_dump(exclude={"create_login", "login_password"})
    if db.query(Employee).filter(Employee.employee_code == data["employee_code"]).first():
        raise HTTPException(400, "Employee code already exists")
    if data.get("device_user_id") and db.query(Employee).filter(Employee.device_user_id == data["device_user_id"]).first():
        raise HTTPException(400, "Device user ID is already assigned")
    employee = Employee(**data)
    try:
        db.add(employee)
        db.flush()

        if payload.create_login:
            if db.query(User).filter(User.username == data["employee_code"]).first():
                raise HTTPException(400, "A login with this username already exists")
            employee_role = db.query(Role).filter(Role.name == "Employee").first()
            login = User(
                username=data["employee_code"],
                email=data.get("email"),
                full_name=employee.full_name,
                password_hash=hash_password(payload.login_password or "emp123"),
                employee_id=employee.id,
                roles=[employee_role] if employee_role else [],
                must_change_password=True,
                profile_completed=False,
            )
            db.add(login)
        db.commit()
    except IdentifierConflict as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.refresh(employee)
    return employee


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, db: Session = Depends(get_db), user: User = Depends(require("employee.view", "self.portal"))):
    employee = db.query(Employee).get(employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")
    if not can(user, "employee.view") and user.employee_id != employee_id:
        raise HTTPException(403, "You can only view your own profile")
    return employee


@router.put("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: int, payload: EmployeeUpdate, db: Session = Depends(get_db),
    _=Depends(require("employee.edit")),
):
    employee = db.query(Employee).get(employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(employee, key, value)
    try:
        db.commit()
    except IdentifierConflict as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.refresh(employee)
    return employee


@router.delete("/{employee_id}", status_code=204)
def delete_employee(employee_id: int, db: Session = Depends(get_db), _=Depends(require("employee.delete"))):
    employee = db.query(Employee).get(employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")
    db.delete(employee)
    db.commit()
