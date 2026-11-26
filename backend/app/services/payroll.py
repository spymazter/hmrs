"""Payroll processing: prorated salary components, deductions and net pay."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import (
    AttendanceRecord, Employee, Holiday, LeaveRequest, PayrollPeriod,
    Payslip, SalaryStructure,
)
from app.services.pdf import generate_payslip_pdf
from app.utils import round2


def working_days_in_period(db: Session, period: PayrollPeriod) -> int:
    holidays = {
        h.holiday_date for h in db.query(Holiday)
        .filter(Holiday.holiday_date >= period.start_date,
                Holiday.holiday_date <= period.end_date).all()
    }
    days = 0
    current = period.start_date
    while current <= period.end_date:
        if current.weekday() < 5 and current not in holidays:
            days += 1
        current += timedelta(days=1)
    return days


def structure_for(db: Session, employee: Employee, period: PayrollPeriod) -> SalaryStructure | None:
    """Find the salary structure effective for this period; never invent a zero-pay one."""
    return (
        db.query(SalaryStructure)
        .filter(
            SalaryStructure.employee_id == employee.id,
            (SalaryStructure.effective_from.is_(None))
            | (SalaryStructure.effective_from <= period.end_date),
        )
        .order_by(SalaryStructure.effective_from.desc().nullslast(), SalaryStructure.id.desc())
        .first()
    )


def process_payroll(
    db: Session,
    period: PayrollPeriod,
    scope: str = "device",
    replace_existing: bool = True,
) -> dict:
    if scope not in ("device", "all"):
        raise ValueError("Unknown payroll scope")

    working_days = working_days_in_period(db, period)
    if working_days == 0:
        raise ValueError("Payroll period has no working days")

    employee_query = db.query(Employee).filter(Employee.status == "active")
    if scope == "device":
        employee_query = employee_query.filter(Employee.employee_code.like("DEV-%"))
    employees = employee_query.order_by(Employee.employee_code).all()
    if not employees:
        raise ValueError("No active employees found for this payroll scope")

    missing = [emp for emp in employees if not structure_for(db, emp, period)]
    if missing:
        examples = ", ".join(f"{e.employee_code} ({e.full_name})" for e in missing[:5])
        raise ValueError(
            f"Salary structures are missing for {len(missing)} employees "
            f"({examples}{'…' if len(missing) > 5 else ''}). Import salary data first."
        )

    records = (
        db.query(AttendanceRecord)
        .filter(
            AttendanceRecord.record_date >= period.start_date,
            AttendanceRecord.record_date <= period.end_date,
        )
        .all()
    )
    records_by_emp: dict[int, list[AttendanceRecord]] = {}
    for record in records:
        records_by_emp.setdefault(record.employee_id, []).append(record)

    leaves = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.status == "approved",
            LeaveRequest.from_date <= period.end_date,
            LeaveRequest.to_date >= period.start_date,
        )
        .all()
    )
    paid_leave_days: dict[int, set] = {}
    lop_days: dict[int, set] = {}
    for leave in leaves:
        start = max(leave.from_date, period.start_date)
        end = min(leave.to_date, period.end_date)
        code = (leave.leave_type.code if leave.leave_type else "") or ""
        is_lop = code.upper() == "LOP" or (
            not code and leave.leave_type and not leave.leave_type.is_paid
        )
        current = start
        while current <= end:
            if current.weekday() < 5:
                if is_lop and leave.is_full_day is not False:
                    lop_days.setdefault(leave.employee_id, set()).add(current)
                elif leave.leave_type and leave.leave_type.is_paid:
                    paid_leave_days.setdefault(leave.employee_id, set()).add(current)
            current += timedelta(days=1)

    removed = 0
    if replace_existing:
        keep_ids = {emp.id for emp in employees}
        for slip in db.query(Payslip).filter(Payslip.period_id == period.id).all():
            if slip.employee_id not in keep_ids:
                db.delete(slip)
                removed += 1
        db.flush()

    existing = {
        p.employee_id: p
        for p in db.query(Payslip).filter(Payslip.period_id == period.id).all()
    }
    processed = 0

    for emp in employees:
        emp_records = records_by_emp.get(emp.id, [])
        days_present = sum(
            1.0 if r.status == "present" else 0.5 if r.status == "half_day" else 0.0
            for r in emp_records
        )
        paid_days = round2(min(working_days, days_present + len(paid_leave_days.get(emp.id, set()))))
        structure = structure_for(db, emp, period)
        if not structure:
            raise ValueError(f"Salary structure missing for {emp.employee_code}")
        factor = paid_days / working_days if working_days else 0

        # LOP is reflected through paid_days (so it is never deducted twice).
        # Store the corresponding money value as a transparent payslip line item.
        full_gross = (
            (structure.basic or 0) + (structure.hra or 0)
            + (structure.special_allowance or 0) + (structure.conveyance or 0)
            + sum((item.get("amount") or 0) for item in (structure.other_earnings or []))
        )
        emp_lop_days = len(lop_days.get(emp.id, set()))
        lop_amount = round2(full_gross * emp_lop_days / working_days)

        basic = round2((structure.basic or 0) * factor)
        hra = round2((structure.hra or 0) * factor)
        other_earnings = round2(
            (structure.special_allowance or 0) * factor
            + (structure.conveyance or 0) * factor
            + sum((item.get("amount") or 0) for item in (structure.other_earnings or [])) * factor
        )
        gross = round2(basic + hra + other_earnings)

        pf = round2((structure.provident_fund or 0) * factor)
        esi = round2((structure.esi or 0) * factor)
        other_deductions = round2(
            sum((item.get("amount") or 0) for item in (structure.other_deductions or [])) * factor
        )
        professional_tax = round2(structure.professional_tax or 0) if paid_days > 0 else 0
        income_tax = round2(structure.income_tax or 0) if paid_days > 0 else 0
        total_deductions = round2(pf + esi + professional_tax + income_tax + other_deductions)
        net = round2(gross - total_deductions)

        values = dict(
            total_days=(period.end_date - period.start_date).days + 1,
            working_days=working_days,
            days_present=round2(days_present),
            paid_days=paid_days,
            lop_days=round2(emp_lop_days),
            lop_amount=lop_amount,
            basic=basic, hra=hra, allowances=other_earnings, gross_salary=gross,
            provident_fund=pf, esi=esi, professional_tax=professional_tax,
            income_tax=income_tax, other_deductions=other_deductions,
            total_deductions=total_deductions, net_salary=net,
        )
        payslip = existing.get(emp.id)
        if payslip:
            for key, value in values.items():
                setattr(payslip, key, value)
        else:
            payslip = Payslip(
                employee_id=emp.id, period_id=period.id, status="generated", **values
            )
            db.add(payslip)
            db.flush()
            existing[emp.id] = payslip
        generate_payslip_pdf(payslip, db)
        processed += 1

    period.status = "processed"
    db.commit()
    return {
        "processed": processed,
        "working_days": working_days,
        "period": period.name,
        "scope": scope,
        "removed_existing": removed,
    }
