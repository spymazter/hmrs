import asyncio
import io
from datetime import date, datetime, time, timedelta

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AttendanceRecord, CompOff, Employee, LeaveRequest, LeaveType, PayrollPeriod,
    PunchLog, Role, SalaryStructure, Shift, User,
)
from app.routers import leaves as leaves_router
from app.schemas import (
    LeaveQuotaIn, LeaveRequestCreate, LeaveVerifyIn, RestrictedHolidayIn,
)
from app.services.comp_off import accrue_comp_offs
from app.services.payroll import process_payroll
from conftest import sample_db

ALL_LEAVE_CODES = [
    "leave.view", "leave.manage", "leave.approve", "leave.manager_approve",
    "leave.verify", "leave.final_approve", "leave.quota.manage", "access.manage",
]


def _role(db, name, permissions):
    role = Role(name=name, permissions=list(permissions))
    db.add(role)
    db.flush()
    return role


def _employee(db, code, uid, shift=None, manager=None):
    employee = Employee(
        employee_code=code, first_name=code, last_name="Test",
        device_user_id=uid, status="active", shift_id=shift.id if shift else None,
        manager_id=manager.id if manager else None,
        date_of_joining=date(2026, 1, 1),
    )
    db.add(employee)
    db.flush()
    return employee


def _user(db, username, role, employee=None):
    user = User(
        username=username, password_hash="x", full_name=username,
        employee_id=employee.id if employee else None,
    )
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def _leave_type(db, code):
    return db.query(LeaveType).filter(LeaveType.code == code).first()


def _apply(db, user, employee, leave_type, start, end, rh_id=None):
    return leaves_router.apply_leave(
        LeaveRequestCreate(
            employee_id=employee.id, leave_type_id=leave_type.id,
            from_date=start, to_date=end, reason="Test leave",
            restricted_holiday_id=rh_id,
        ),
        db, user,
    )


def test_employee_manager_hr_admin_workflow():
    _, Session = sample_db()
    db = Session()
    try:
        manager_role = _role(db, "Manager", [
            "dashboard.view", "employee.view", "leave.view", "leave.manager_approve",
        ])
        hr_role = _role(db, "HR", ["employee.view", "leave.view", "leave.verify"])
        admin_role = _role(db, "Admin", ALL_LEAVE_CODES)
        general = db.query(Shift).filter(Shift.name == "General").first()
        manager_emp = _employee(db, "MGR001", "9001", general)
        report = _employee(db, "REP001", "9002", general, manager_emp)
        outsider = _employee(db, "OUT001", "9003", general)
        manager = _user(db, "mgr", manager_role, manager_emp)
        hr = _user(db, "hr", hr_role)
        admin = _user(db, "admin", admin_role)
        employee_role = _role(db, "Employee", ["self.portal", "leave.view", "leave.manage"])
        report_user = _user(db, "rep", employee_role, report)
        casual = _leave_type(db, "CL")

        leave = _apply(db, report_user, report, casual, date(2026, 11, 2), date(2026, 11, 3))
        assert leave.status == "pending"

        approved = leaves_router.manager_approve_leave(leave.id, db, manager)
        assert approved.status == "manager_approved"
        assert approved.manager_approved_by == manager.id

        verified = leaves_router.verify_leave_request(
            leave.id, LeaveVerifyIn(notes="Checked punches"), db, hr
        )
        assert verified.status == "verified"
        assert verified.hr_verified_at is not None
        assert "Checked punches" in verified.verification_notes

        final = leaves_router.final_approve_leave(leave.id, db, admin)
        assert final.status == "approved"
        assert final.final_approved_by == admin.id
        assert final.approved_by == admin.id
    finally:
        db.close()


def test_stages_enforce_scope_and_hr_verification():
    _, Session = sample_db()
    db = Session()
    try:
        manager_role = _role(db, "Manager", ["employee.view", "leave.view", "leave.manager_approve"])
        admin_role = _role(db, "Admin", ALL_LEAVE_CODES)
        general = db.query(Shift).filter(Shift.name == "General").first()
        manager_emp = _employee(db, "MGR002", "9011", general)
        report = _employee(db, "REP002", "9012", general, manager_emp)
        outsider = _employee(db, "OUT002", "9013", general)
        manager = _user(db, "mgr2", manager_role, manager_emp)
        admin = _user(db, "admin2", admin_role)
        casual = _leave_type(db, "CL")

        other_leave = _apply(db, admin, outsider, casual, date(2026, 11, 4), date(2026, 11, 4))
        with pytest.raises(HTTPException) as exc:
            leaves_router.manager_approve_leave(other_leave.id, db, manager)
        assert exc.value.status_code == 403

        own_leave = _apply(db, admin, report, casual, date(2026, 11, 5), date(2026, 11, 5))
        leaves_router.manager_approve_leave(own_leave.id, db, manager)
        with pytest.raises(HTTPException, match="HR must verify"):
            leaves_router.final_approve_leave(own_leave.id, db, admin)
    finally:
        db.close()


def test_hr_yearly_quota_upload_and_balances():
    _, Session = sample_db()
    db = Session()
    try:
        hr_role = _role(db, "HR", ["employee.view", "leave.view", "leave.quota.manage"])
        hr = _user(db, "hr-quota", hr_role)
        employee = _employee(db, "Q001", "9021")
        earned = _leave_type(db, "EL")
        casual = _leave_type(db, "CL")

        leaves_router.upsert_quota(
            LeaveQuotaIn(employee_id=employee.id, leave_type_id=earned.id, year=2026, days=20),
            db, hr,
        )
        balances = leaves_router.list_balances(2026, employee.id, db, hr)
        earned_balance = next(row for row in balances if row["leave_type_code"] == "EL")
        casual_balance = next(row for row in balances if row["leave_type_code"] == "CL")
        assert earned_balance["quota"] == 20
        assert earned_balance["source"] == "employee"
        assert casual_balance["quota"] == 12

        content = (
            "Employee Code,Leave Code,Year,Days\n"
            "Q001,CL,2026,15\n"
            f"{employee.employee_code},EL,2026,21\n"
        ).encode()
        file = UploadFile(filename="quotas.csv", file=io.BytesIO(content))
        result = asyncio.run(leaves_router.upload_quotas(file, db, hr))
        assert result["skipped"] == []
        balances = leaves_router.list_balances(2026, employee.id, db, hr)
        assert next(row for row in balances if row["leave_type_code"] == "CL")["quota"] == 15
        assert next(row for row in balances if row["leave_type_code"] == "EL")["quota"] == 21
    finally:
        db.close()


def test_rh_list_limits_two_days_per_year():
    _, Session = sample_db()
    db = Session()
    try:
        hr_role = _role(db, "HR", ["employee.view", "leave.view", "leave.quota.manage"])
        admin_role = _role(db, "Admin", ALL_LEAVE_CODES)
        hr = _user(db, "hr-rh", hr_role)
        admin = _user(db, "admin-rh", admin_role)
        employee = _employee(db, "RH001", "9031")
        rh_type = _leave_type(db, "RH")

        first = leaves_router.create_restricted_holiday(
            RestrictedHolidayIn(year=2026, holiday_date=date(2026, 11, 12), name="Diwali RH"),
            db, hr,
        )
        second = leaves_router.create_restricted_holiday(
            RestrictedHolidayIn(year=2026, holiday_date=date(2026, 12, 24), name="Christmas RH"),
            db, hr,
        )
        _apply(db, admin, employee, rh_type, first.holiday_date, first.holiday_date, rh_id=first.id)
        _apply(db, admin, employee, rh_type, second.holiday_date, second.holiday_date, rh_id=second.id)
        with pytest.raises(HTTPException, match="Only 2 restricted holidays"):
            _apply(db, admin, employee, rh_type, date(2026, 11, 13), date(2026, 11, 13), rh_id=first.id)
    finally:
        db.close()


def test_comp_off_accrues_one_day_per_nine_extra_hours_idempotently():
    _, Session = sample_db()
    db = Session()
    try:
        general = db.query(Shift).filter(Shift.name == "General").first()
        employee = _employee(db, "CO001", "9041", general)
        work_date = date(2026, 10, 9)
        db.add_all([
            PunchLog(
                employee_id=employee.id, device_user_id=employee.device_user_id,
                punch_time=datetime.combine(work_date, time(0)), punch_type="in",
                source="device",
            ),
            PunchLog(
                employee_id=employee.id, device_user_id=employee.device_user_id,
                punch_time=datetime.combine(work_date, time(18)), punch_type="out",
                source="device",
            ),
        ])
        db.commit()

        result = accrue_comp_offs(db, work_date, work_date, force=True)
        assert result["earned_days"] >= 1
        rows = db.query(CompOff).filter(
            CompOff.employee_id == employee.id, CompOff.source == "auto_9h"
        ).all()
        assert len(rows) == 1
        assert rows[0].days == 1

        again = accrue_comp_offs(db, work_date, work_date)
        assert again["earned_days"] == 0
        assert db.query(CompOff).filter(
            CompOff.employee_id == employee.id, CompOff.source == "auto_9h"
        ).count() == 1
    finally:
        db.close()


def test_full_day_lop_reduces_payroll_and_appears_on_payslip(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "PDF_DIR", str(tmp_path))
    _, Session = sample_db()
    db = Session()
    try:
        period = PayrollPeriod(
            name="October 2026", month=10, year=2026,
            start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
        )
        db.add(period)
        db.flush()
        for employee in db.query(Employee).all():
            db.add(SalaryStructure(
                employee_id=employee.id, effective_from=date(2026, 1, 1),
                basic=50000, hra=20000, special_allowance=10000, conveyance=1600,
                provident_fund=6000, professional_tax=200,
            ))
        db.commit()

        baseline = process_payroll(db, period, scope="all", replace_existing=True)
        assert baseline["processed"] >= 1

        employee = db.query(Employee).filter(Employee.employee_code == "SMP001").first()
        lop_type = _leave_type(db, "LOP")
        leave = LeaveRequest(
            employee_id=employee.id, leave_type_id=lop_type.id,
            from_date=date(2026, 10, 9), to_date=date(2026, 10, 9),
            status="approved", is_full_day=True, reason="Personal work",
        )
        db.add(leave)
        db.commit()

        from app.models import Payslip
        from app.services.attendance import recompute_records

        recompute_records(db, date(2026, 10, 1), date(2026, 10, 31))
        result = process_payroll(db, period, scope="all", replace_existing=True)
        assert result["processed"] >= 1
        payslip = db.query(Payslip).filter(
            Payslip.employee_id == employee.id, Payslip.period_id == period.id
        ).first()
        assert payslip.lop_days == 1
        assert payslip.lop_amount > 0
        assert payslip.gross_salary < 81000
    finally:
        db.close()
