"""Idempotent database seeding: defaults, demo data and user accounts."""

from datetime import date, time

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.database import Base, engine, run_migrations
from app.models import (
    AppSetting, Department, Designation, Device, Employee, Holiday, LeaveQuota,
    LeaveType, PayrollPeriod, PunchLog, Role, RoleGroup, SalaryStructure, Shift,
    User,
)
from app.permissions import ALL_CODES
from app.services.attendance import recompute_records


def _role_permissions(name: str) -> list[str]:
    if name == "Admin":
        return list(ALL_CODES)
    if name == "HR Manager":
        return [
            "dashboard.view", "employee.view", "employee.create", "employee.edit",
            "document.view", "document.manage", "document.hr",
            "shift.view", "shift.manage", "attendance.view", "attendance.manage",
            "device.view", "report.view", "report.export", "leave.view",
            "leave.manage", "leave.approve", "leave.verify", "leave.quota.manage",
            "access.view", "self.portal",
        ]
    if name == "Payroll Officer":
        return [
            "dashboard.view", "employee.view", "attendance.view", "report.view",
            "report.export", "payroll.view", "payroll.manage", "payslip.view",
            "payslip.pdf", "self.portal",
        ]
    if name == "Manager":
        return [
            "dashboard.view", "employee.view", "attendance.view", "report.view",
            "leave.view", "leave.approve", "leave.manager_approve", "self.portal",
        ]
    return [
        "dashboard.view", "self.portal", "attendance.view", "payslip.view",
        "payslip.pdf", "leave.view", "leave.manage", "document.view",
    ]


ROLE_DEFINITIONS = {
    "Admin": "Full unrestricted access to every module",
    "HR Manager": "Employees, shifts, attendance, reports and leave approvals",
    "Payroll Officer": "Salary structures, payroll processing and salary slips",
    "Manager": "Team attendance, reports and leave approvals",
    "Employee": "Employee self-service portal",
}

GROUP_DEFINITIONS = {
    "HR & Payroll Admin": ["HR Manager", "Payroll Officer"],
    "Management": ["Manager", "HR Manager"],
    "Full Access": ["Admin"],
}

DEPARTMENTS = [
    ("Engineering", "ENG", "Rahul Verma"),
    ("Human Resources", "HR", "Priya Sharma"),
    ("Finance", "FIN", "Anil Mehta"),
    ("Sales", "SAL", "Neha Kapoor"),
    ("Operations", "OPS", "Vikram Rao"),
]

DESIGNATIONS = [
    ("Software Engineer", "Engineering"),
    ("Senior Engineer", "Engineering"),
    ("HR Executive", "Human Resources"),
    ("Accountant", "Finance"),
    ("Sales Executive", "Sales"),
    ("Operations Manager", "Operations"),
]

SHIFTS = [
    ("General Shift", time(9, 0), time(18, 0), 15, 8.0, [6], "#4f46e5"),
    ("Morning Shift", time(7, 0), time(16, 0), 10, 8.0, [5, 6], "#0ea5e9"),
    ("Evening Shift", time(14, 0), time(23, 0), 10, 8.0, [5, 6], "#f59e0b"),
]

EMPLOYEE_SEED = [
    ("EMP001", "Aarav", "Sharma", "1", "Engineering", "Software Engineer", "General Shift", 65000, 26000, 18000),
    ("EMP002", "Diya", "Patel", "2", "Engineering", "Senior Engineer", "General Shift", 85000, 34000, 24000),
    ("EMP003", "Rohan", "Gupta", "3", "Engineering", "Software Engineer", "Morning Shift", 60000, 24000, 15000),
    ("EMP004", "Priya", "Singh", "4", "Human Resources", "HR Executive", "General Shift", 48000, 19200, 12000),
    ("EMP005", "Ankit", "Jain", "5", "Finance", "Accountant", "General Shift", 52000, 20800, 13000),
    ("EMP006", "Neha", "Verma", "6", "Sales", "Sales Executive", "General Shift", 45000, 18000, 10000),
    ("EMP007", "Karan", "Malhotra", "7", "Sales", "Sales Executive", "Evening Shift", 45000, 18000, 10000),
    ("EMP008", "Sneha", "Iyer", "8", "Operations", "Operations Manager", "General Shift", 75000, 30000, 20000),
    ("EMP009", "Vikram", "Rao", "9", "Operations", "Operations Manager", "Morning Shift", 72000, 28800, 18000),
    ("EMP010", "Meera", "Nair", "10", "Human Resources", "HR Executive", "General Shift", 46000, 18400, 11000),
    ("EMP011", "Arjun", "Kumar", "11", "Engineering", "Software Engineer", "General Shift", 62000, 24800, 16000),
    ("EMP012", "Isha", "Bansal", "12", "Finance", "Accountant", "General Shift", 50000, 20000, 12500),
]

USERS_SEED = [
    ("admin", "admin123", "System Administrator", "Admin", ["Full Access"], None),
    ("hr", "hr123", "Priya Sharma", "HR Manager", [], None),
    ("payroll", "payroll123", "Anil Mehta", "Payroll Officer", [], None),
    ("manager", "manager123", "Sneha Iyer", "Manager", [], "EMP008"),
    ("employee", "emp123", "Aarav Sharma", "Employee", [], "EMP001"),
]


def seed_database() -> None:
    Base.metadata.create_all(bind=engine)
    run_migrations()
    db = SessionLocalWrapper()
    try:
        _seed(db)
        _recompute_history_once(db)
    finally:
        db.close()


def _recompute_history_once(db: Session) -> None:
    """Upgrade historical records to the corrected in/out pairing logic once."""
    marker_key = "attendance_engine_v4"
    if db.query(AppSetting).filter(AppSetting.key == marker_key).first():
        return

    first_punch = db.query(func.min(PunchLog.punch_time)).scalar()
    if first_punch:
        recompute_records(db, first_punch.date(), date.today())

    db.merge(AppSetting(key=marker_key, value=date.today().isoformat()))
    db.commit()


def SessionLocalWrapper():
    from app.database import SessionLocal
    return SessionLocal()


def _seed(db: Session) -> None:
    if db.query(User).count() > 0:
        return

    roles = {}
    for name, description in ROLE_DEFINITIONS.items():
        role = Role(name=name, description=description, permissions=_role_permissions(name), is_system=True)
        db.add(role)
        roles[name] = role
    db.flush()

    groups = {}
    for name, role_names in GROUP_DEFINITIONS.items():
        group = RoleGroup(name=name, description=f"Combined role group: {', '.join(role_names)}")
        group.roles = [roles[r] for r in role_names]
        db.add(group)
        groups[name] = group
    db.flush()

    departments = {}
    for name, code, head in DEPARTMENTS:
        dept = Department(name=name, code=code, head=head)
        db.add(dept)
        departments[name] = dept
    db.flush()

    designations = {}
    for name, dept_name in DESIGNATIONS:
        desig = Designation(name=name, department_id=departments[dept_name].id)
        db.add(desig)
        designations[name] = desig
    db.flush()

    shifts = {}
    for name, start, end, grace, min_hours, week_off, color in SHIFTS:
        shift = Shift(
            name=name, start_time=start, end_time=end, grace_minutes=grace,
            min_hours_for_full_day=min_hours, half_day_hours=4.0,
            week_off_days=week_off, color=color,
        )
        db.add(shift)
        shifts[name] = shift
    db.flush()

    employees = {}
    for code, first, last, device_id, dept, desig, shift, basic, hra, spl in EMPLOYEE_SEED:
        emp = Employee(
            employee_code=code, first_name=first, last_name=last,
            email=f"{first.lower()}.{last.lower()}@company.com",
            phone=f"98765{device_id.zfill(5)}",
            gender="Female" if first in ("Diya", "Priya", "Neha", "Sneha", "Meera", "Isha") else "Male",
            date_of_joining=date(date.today().year - 2, 1, 15),
            status="active", device_user_id=device_id,
            department_id=departments[dept].id,
            designation_id=designations[desig].id,
            shift_id=shifts[shift].id,
        )
        db.add(emp)
        db.flush()
        employees[code] = emp
        db.add(SalaryStructure(
            employee_id=emp.id, effective_from=date(date.today().year - 1, 1, 1),
            basic=basic, hra=hra, special_allowance=spl, conveyance=1600,
            other_earnings=[{"name": "Performance Allowance", "amount": 2500}],
            provident_fund=round(basic * 0.12, 2),
            esi=round((basic + hra + spl) * 0.0075, 2) if (basic + hra + spl) < 21000 else 0,
            professional_tax=200, income_tax=0,
            other_deductions=[{"name": "Labour Welfare Fund", "amount": 50}],
        ))

    # Demo manager (Sneha Iyer, EMP008) has direct reports so the manager
    # approval stage can be exercised immediately.
    for code in ("EMP001", "EMP002", "EMP003", "EMP004"):
        employees[code].manager_id = employees["EMP008"].id

    for username, password, full_name, role_name, group_names, emp_code in USERS_SEED:
        user = User(
            username=username,
            email=f"{username}@company.com",
            full_name=full_name,
            password_hash=hash_password(password),
            employee_id=employees[emp_code].id if emp_code else None,
            is_active=True,
            profile_completed=True,
        )
        user.roles = [roles[role_name]]
        user.groups = [groups[g] for g in group_names]
        db.add(user)

    leave_types = {}
    for name, code, quota, paid in (
        ("Casual Leave", "CL", 12, True),
        ("Earned Leave", "EL", 18, True),
        ("Restricted Holiday", "RH", 2, True),
        ("Loss of Pay", "LOP", 0, False),
    ):
        item = LeaveType(name=name, code=code, is_paid=paid, max_days_per_year=quota)
        db.add(item)
        leave_types[code] = item
    db.flush()
    for code, quota in (("CL", 12), ("EL", 18), ("RH", 2), ("LOP", 0)):
        db.add(LeaveQuota(
            scope="global", scope_value="ALL", leave_type_id=leave_types[code].id,
            year=date.today().year, days=quota,
        ))

    year = date.today().year
    for month, day, name in [
        (1, 1, "New Year's Day"), (1, 26, "Republic Day"), (5, 1, "Labour Day"),
        (8, 15, "Independence Day"), (10, 2, "Gandhi Jayanti"), (12, 25, "Christmas"),
    ]:
        db.add(Holiday(holiday_date=date(year, month, day), name=name))

    db.add(Device(
        name="Main Biometric Device",
        ip_address=settings.DEVICE_IP,
        port=settings.DEVICE_PORT,
        is_active=True,
        mode=settings.DEVICE_MODE,
    ))

    from datetime import timedelta
    from app.utils import month_bounds
    today = date.today()
    first_day = today.replace(day=1)
    prev_month_end = first_day - timedelta(days=1)
    month, year_no = (prev_month_end.month, prev_month_end.year)
    start, end = month_bounds(year_no, month)
    db.add(PayrollPeriod(
        name=start.strftime("%B %Y"), month=month, year=year_no,
        start_date=start, end_date=end, status="draft",
    ))

    db.commit()
