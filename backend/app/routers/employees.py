import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.auth import can, get_current_user, hash_password, require
from app.database import get_db
from app.models import Employee, Role, User
from app.schemas import (
    EmployeeCreate, EmployeeListOut, EmployeeOut, EmployeeSelfUpdate, EmployeeUpdate,
)
from app.services.identity import IdentifierConflict

router = APIRouter(prefix="/api/employees", tags=["Employees"])

EMPLOYEE_EXPORT_HEADERS = [
    "ID", "Employee Code", "Device UID", "First Name", "Last Name", "Full Name",
    "Email", "Phone", "Alternate Phone", "Date of Birth", "Gender", "Blood Group",
    "Emergency Contact Name", "Emergency Contact Phone", "Emergency Contact Relationship",
    "Address", "Date of Joining", "Status", "Department", "Designation", "Shift",
    "Shift Group", "Location", "Reporting Manager", "Created At",
    "Nominee Name", "Nominee Relationship",
]


def _export_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _employee_export_row(employee: Employee) -> dict:
    values = [
        employee.id, employee.employee_code, employee.device_user_id,
        employee.first_name, employee.last_name, employee.full_name,
        employee.email, employee.phone, employee.alternate_phone,
        employee.date_of_birth, employee.gender, employee.blood_group,
        employee.emergency_contact_name, employee.emergency_contact_phone,
        employee.emergency_contact_relationship, employee.address,
        employee.date_of_joining, employee.status,
        employee.department.name if employee.department else None,
        employee.designation.name if employee.designation else None,
        employee.shift.name if employee.shift else None,
        employee.shift_group.name if employee.shift_group else None,
        employee.location.label if employee.location else None,
        employee.manager.full_name if employee.manager else None,
        employee.created_at,
        employee.nominee_name,
        employee.nominee_relationship,
    ]
    return {
        header: _export_value(value)
        for header, value in zip(EMPLOYEE_EXPORT_HEADERS, values)
    }


def _filtered_employees(db: Session, search: str = "", department_id: int | None = None,
                        status: str | None = None):
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
    return query


def _employee_export_response(rows: list[dict], file_format: str):
    filename = f"employees_{date.today().isoformat()}"
    if file_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=EMPLOYEE_EXPORT_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            content=output.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}.csv"',
                "X-Total-Count": str(len(rows)),
            },
        )

    book = Workbook()
    sheet = book.active
    sheet.title = "Employees"
    sheet.append(EMPLOYEE_EXPORT_HEADERS)
    for row in rows:
        sheet.append([row[header] for header in EMPLOYEE_EXPORT_HEADERS])
    output = io.BytesIO()
    book.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.xlsx"',
            "X-Total-Count": str(len(rows)),
        },
    )


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
    query = _filtered_employees(db, search, department_id, status)
    total = query.count()
    items = query.order_by(Employee.employee_code).offset(skip).limit(min(limit, 500)).all()
    return {"items": items, "total": total}


@router.get("/export")
def export_employees(
    search: str = "",
    department_id: int | None = None,
    status: str | None = None,
    file_format: str = Query("xlsx", alias="format", pattern="^(xlsx|csv)$"),
    db: Session = Depends(get_db),
    _user: User = Depends(require("employee.view")),
):
    """Download every employee matching the current Employee-page filters."""
    employees = _filtered_employees(db, search, department_id, status).order_by(Employee.employee_code).all()
    rows = [_employee_export_row(employee) for employee in employees]
    return _employee_export_response(rows, file_format)


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
