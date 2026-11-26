from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require
from app.database import get_db
from app.models import Department, Designation, Employee, Holiday, LeaveType, Location
from app.schemas import (
    DepartmentCreate, DepartmentOut, DesignationCreate, DesignationOut,
    HolidayCreate, HolidayOut, LeaveTypeCreate, LeaveTypeOut,
    LocationCreate, LocationOut,
)

router = APIRouter(prefix="/api", tags=["Master data"])


# Departments ---------------------------------------------------------------
@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db), _=Depends(require("employee.view", "self.portal"))):
    return db.query(Department).order_by(Department.name).all()


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), _=Depends(require("employee.create"))):
    department = Department(**payload.model_dump())
    db.add(department)
    db.commit()
    db.refresh(department)
    return department


@router.put("/departments/{item_id}", response_model=DepartmentOut)
def update_department(item_id: int, payload: DepartmentCreate, db: Session = Depends(get_db), _=Depends(require("employee.edit"))):
    department = db.query(Department).get(item_id)
    if not department:
        raise HTTPException(404, "Department not found")
    for key, value in payload.model_dump().items():
        setattr(department, key, value)
    db.commit()
    db.refresh(department)
    return department


@router.delete("/departments/{item_id}", status_code=204)
def delete_department(item_id: int, db: Session = Depends(get_db), _=Depends(require("employee.delete"))):
    department = db.query(Department).get(item_id)
    if not department:
        raise HTTPException(404, "Department not found")
    db.delete(department)
    db.commit()


# Locations -----------------------------------------------------------------
@router.get("/locations", response_model=list[LocationOut])
def list_locations(db: Session = Depends(get_db), _=Depends(require("employee.view", "self.portal", "report.view"))):
    return db.query(Location).order_by(Location.name).all()


@router.post("/locations", response_model=LocationOut, status_code=201)
def create_location(payload: LocationCreate, db: Session = Depends(get_db), _=Depends(require("employee.create"))):
    location = Location(**payload.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


@router.put("/locations/{item_id}", response_model=LocationOut)
def update_location(item_id: int, payload: LocationCreate, db: Session = Depends(get_db), _=Depends(require("employee.edit"))):
    location = db.query(Location).get(item_id)
    if not location:
        raise HTTPException(404, "Location not found")
    for key, value in payload.model_dump().items():
        setattr(location, key, value)
    db.commit()
    db.refresh(location)
    return location


@router.delete("/locations/{item_id}", status_code=204)
def delete_location(item_id: int, db: Session = Depends(get_db), _=Depends(require("employee.delete"))):
    location = db.query(Location).get(item_id)
    if not location:
        raise HTTPException(404, "Location not found")
    if db.query(Employee).filter_by(location_id=item_id).count():
        raise HTTPException(400, "Location is assigned to employees and cannot be deleted")
    db.delete(location)
    db.commit()


# Designations --------------------------------------------------------------
@router.get("/designations", response_model=list[DesignationOut])
def list_designations(db: Session = Depends(get_db), _=Depends(require("employee.view", "self.portal"))):
    return db.query(Designation).order_by(Designation.name).all()


@router.post("/designations", response_model=DesignationOut, status_code=201)
def create_designation(payload: DesignationCreate, db: Session = Depends(get_db), _=Depends(require("employee.create"))):
    designation = Designation(**payload.model_dump())
    db.add(designation)
    db.commit()
    db.refresh(designation)
    return designation


@router.put("/designations/{item_id}", response_model=DesignationOut)
def update_designation(item_id: int, payload: DesignationCreate, db: Session = Depends(get_db), _=Depends(require("employee.edit"))):
    designation = db.query(Designation).get(item_id)
    if not designation:
        raise HTTPException(404, "Designation not found")
    for key, value in payload.model_dump().items():
        setattr(designation, key, value)
    db.commit()
    db.refresh(designation)
    return designation


@router.delete("/designations/{item_id}", status_code=204)
def delete_designation(item_id: int, db: Session = Depends(get_db), _=Depends(require("employee.delete"))):
    designation = db.query(Designation).get(item_id)
    if not designation:
        raise HTTPException(404, "Designation not found")
    db.delete(designation)
    db.commit()


# Leave types ---------------------------------------------------------------
@router.get("/leave-types", response_model=list[LeaveTypeOut])
def list_leave_types(db: Session = Depends(get_db), _=Depends(require("leave.view", "self.portal"))):
    return db.query(LeaveType).filter(LeaveType.is_active.is_(True)).order_by(LeaveType.name).all()


@router.post("/leave-types", response_model=LeaveTypeOut, status_code=201)
def create_leave_type(payload: LeaveTypeCreate, db: Session = Depends(get_db), _=Depends(require("leave.manage"))):
    item = LeaveType(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# Holidays ------------------------------------------------------------------
@router.get("/holidays", response_model=list[HolidayOut])
def list_holidays(db: Session = Depends(get_db), _=Depends(require("attendance.view", "self.portal"))):
    return db.query(Holiday).order_by(Holiday.holiday_date).all()


@router.post("/holidays", response_model=HolidayOut, status_code=201)
def create_holiday(payload: HolidayCreate, db: Session = Depends(get_db), _=Depends(require("attendance.manage"))):
    if db.query(Holiday).filter(Holiday.holiday_date == payload.holiday_date).first():
        raise HTTPException(400, "A holiday already exists on that date")
    item = Holiday(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/holidays/{item_id}", status_code=204)
def delete_holiday(item_id: int, db: Session = Depends(get_db), _=Depends(require("attendance.manage"))):
    item = db.query(Holiday).get(item_id)
    if not item:
        raise HTTPException(404, "Holiday not found")
    db.delete(item)
    db.commit()
