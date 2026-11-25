from datetime import date, datetime, time
from uuid import uuid4

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
    JSON, String, Table, Text, Time, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from app.database import Base

# ---------------------------------------------------------------------------
# Association tables (users <-> roles <-> groups)
# ---------------------------------------------------------------------------
user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

group_roles = Table(
    "group_roles", Base.metadata,
    Column("group_id", Integer, ForeignKey("role_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

user_groups = Table(
    "user_groups", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Integer, ForeignKey("role_groups.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(String(255))
    permissions = Column(JSON, default=list)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    users = relationship("User", secondary=user_roles, back_populates="roles")
    groups = relationship("RoleGroup", secondary=group_roles, back_populates="roles")


class RoleGroup(Base):
    __tablename__ = "role_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)

    roles = relationship("Role", secondary=group_roles, back_populates="groups")
    users = relationship("User", secondary=user_groups, back_populates="groups")

    @property
    def role_ids(self):
        return [r.id for r in self.roles]


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(150), unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(150))
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    profile_completed = Column(Boolean, default=False, nullable=False, server_default=text("0"))
    identity_key = Column(String(64), unique=True, index=True, nullable=False,
                          default=lambda: uuid4().hex)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"),
                         unique=True, index=True)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    roles = relationship("Role", secondary=user_roles, back_populates="users")
    groups = relationship("RoleGroup", secondary=user_groups, back_populates="users")
    employee = relationship("Employee", foreign_keys=[employee_id])


# ---------------------------------------------------------------------------
# Organisation
# ---------------------------------------------------------------------------
class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    code = Column(String(30), unique=True)
    head = Column(String(120))


class Location(Base):
    """Physical workplace/branch used by advanced attendance reports."""
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    code = Column(String(30), unique=True)
    city = Column(String(120))

    @property
    def label(self):
        return " — ".join(filter(None, [self.name, self.city]))


class Designation(Base):
    __tablename__ = "designations"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"))
    department = relationship("Department")

    @property
    def department_name(self):
        return self.department.name if self.department else None


class ShiftGroup(Base):
    """A named roster group: a set of shifts shared by a set of employees.

    Employees mapped to a group rotate through that group's shifts when no
    explicit daily roster row exists.  Membership is stored on the employee
    (one group per employee) and on each shift (one group per shift).
    """
    __tablename__ = "shift_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    code = Column(String(30), unique=True)
    description = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    shifts = relationship("Shift", back_populates="shift_group")
    employees = relationship("Employee", back_populates="shift_group")

    @property
    def shift_ids(self):
        return [s.id for s in self.shifts]

    @property
    def employee_ids(self):
        return [e.id for e in self.employees]


class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    start_time = Column(Time, default=time(9, 0))
    end_time = Column(Time, default=time(18, 0))
    grace_minutes = Column(Integer, default=15)
    early_out_grace_minutes = Column(Integer, default=0)
    min_hours_for_full_day = Column(Float, default=8.0)
    half_day_hours = Column(Float, default=4.0)
    week_off_days = Column(JSON, default=list)  # 0=Mon ... 6=Sun
    is_active = Column(Boolean, default=True)
    color = Column(String(20), default="#4f46e5")
    # Advanced engine metadata.  Night shifts are also detected when
    # start_time > end_time, so older shifts keep working unchanged.
    shift_type = Column(String(20), default="fixed")  # fixed / rotational / flexi / night
    target_hours = Column(Float)  # flexi shift target; defaults to scheduled span
    break_minutes = Column(Integer, default=0)
    rotation_group = Column(String(50))  # legacy: shifts with this name rotate by roster/date
    shift_group_id = Column(Integer, ForeignKey("shift_groups.id", ondelete="SET NULL"))
    shift_group = relationship("ShiftGroup", back_populates="shifts")

    @property
    def shift_group_name(self):
        return self.shift_group.name if self.shift_group else None


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    identity_key = Column(String(64), unique=True, index=True, nullable=False,
                          default=lambda: uuid4().hex)
    employee_code = Column(String(50), unique=True, nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), default="")
    email = Column(String(150))
    phone = Column(String(30))
    alternate_phone = Column(String(30))
    date_of_birth = Column(Date)
    gender = Column(String(20))
    emergency_contact_name = Column(String(100))
    emergency_contact_phone = Column(String(30))
    emergency_contact_relationship = Column(String(50))
    address = Column(Text)
    date_of_joining = Column(Date)
    status = Column(String(30), default="active")  # active / inactive / left
    device_user_id = Column(String(50), unique=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"))
    designation_id = Column(Integer, ForeignKey("designations.id"))
    shift_id = Column(Integer, ForeignKey("shifts.id"))
    shift_group_id = Column(Integer, ForeignKey("shift_groups.id", ondelete="SET NULL"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    manager_id = Column(Integer, ForeignKey("employees.id"))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    department = relationship("Department")
    designation = relationship("Designation")
    shift = relationship("Shift")
    shift_group = relationship("ShiftGroup", back_populates="employees")
    location = relationship("Location")
    manager = relationship("Employee", remote_side=[id])

    @property
    def full_name(self):
        return " ".join(filter(None, [self.first_name, self.last_name]))

    @property
    def department_name(self):
        return self.department.name if self.department else None

    @property
    def designation_name(self):
        return self.designation.name if self.designation else None

    @property
    def shift_name(self):
        return self.shift.name if self.shift else None

    @property
    def shift_group_name(self):
        return self.shift_group.name if self.shift_group else None

    @property
    def location_name(self):
        return self.location.name if self.location else None


class EmployeeDocument(Base):
    """An HR-uploaded document belonging to an employee."""
    __tablename__ = "employee_documents"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False, unique=True)
    content_type = Column(String(100))
    size_bytes = Column(Integer, default=0)
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at = Column(DateTime, default=datetime.now)

    employee = relationship("Employee")


class IdentifierReservation(Base):
    """Permanent ownership record for employee codes, device UIDs and user links.

    Rows are never deleted, so a retired identifier cannot be recycled after an
    Employee or User has been removed from the database.
    """
    __tablename__ = "identifier_reservations"
    id = Column(Integer, primary_key=True)
    kind = Column(String(40), nullable=False)
    value = Column(String(100), nullable=False)
    owner_key = Column(String(64), nullable=False, index=True)
    employee_id = Column(Integer)
    user_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    __table_args__ = (
        UniqueConstraint("kind", "value", name="uq_identifier_reservation"),
    )


# ---------------------------------------------------------------------------
# Biometric / attendance
# ---------------------------------------------------------------------------
class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    ip_address = Column(String(100), nullable=False)
    port = Column(Integer, default=4370)
    is_active = Column(Boolean, default=True)
    mode = Column(String(20), default="simulate")  # simulate / live
    serial_number = Column(String(100))
    location_id = Column(Integer, ForeignKey("locations.id"))
    last_sync_at = Column(DateTime)
    last_error = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    location = relationship("Location")


class DeviceSyncState(Base):
    """Read-only sync high-water mark so repeat syncs skip old punches."""
    __tablename__ = "device_sync_state"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, unique=True)
    last_punch_time = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DeviceSyncJob(Base):
    """Background punch-sync job with a live, pollable progress log."""
    __tablename__ = "device_sync_jobs"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default="running", nullable=False)  # running/success/failed
    phase = Column(String(120), default="queued")
    total = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    new_punches = Column(Integer, default=0)
    new_employees = Column(Integer, default=0)
    full_history = Column(Boolean, default=False)
    message = Column(Text)
    logs = Column(JSON, default=list)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime)


class PunchLog(Base):
    __tablename__ = "punch_logs"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"))
    device_user_id = Column(String(50), index=True)
    punch_time = Column(DateTime, nullable=False, index=True)
    punch_type = Column(String(20), default="in")  # in / out / break_in / break_out
    raw_code = Column(Integer)
    source = Column(String(20), default="device")  # device / manual / simulation
    verify_mode = Column(String(30))  # Face / Fingerprint / Card / Password
    device_serial = Column(String(100))
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.now)

    employee = relationship("Employee")
    device = relationship("Device")

    @property
    def employee_name(self):
        return self.employee.full_name if self.employee else None

    __table_args__ = (
        UniqueConstraint("device_user_id", "punch_time", "punch_type", name="uq_punch"),
        Index("ix_punch_employee_time", "employee_id", "punch_time"),
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    record_date = Column(Date, nullable=False, index=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"))
    check_in = Column(DateTime)
    check_out = Column(DateTime)
    total_hours = Column(Float, default=0)
    overtime_hours = Column(Float, default=0)
    late_minutes = Column(Integer, default=0)
    early_departure_minutes = Column(Integer, default=0)
    status = Column(String(30), default="absent")  # present / absent / half_day / week_off / holiday / leave
    remarks = Column(Text)
    source = Column(String(20), default="auto")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    employee = relationship("Employee")
    shift = relationship("Shift")

    @property
    def employee_name(self):
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self):
        return self.employee.employee_code if self.employee else None

    @property
    def shift_name(self):
        return self.shift.name if self.shift else None

    __table_args__ = (
        UniqueConstraint("employee_id", "record_date", name="uq_attendance_record"),
    )


class LeaveType(Base):
    __tablename__ = "leave_types"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    is_paid = Column(Boolean, default=True)
    max_days_per_year = Column(Integer, default=12)
    color = Column(String(20), default="#0ea5e9")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    leave_type_id = Column(Integer, ForeignKey("leave_types.id"))
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    reason = Column(Text)
    status = Column(String(20), default="pending")  # pending / approved / rejected
    approved_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.now)

    employee = relationship("Employee")
    leave_type = relationship("LeaveType")

    @property
    def employee_name(self):
        return self.employee.full_name if self.employee else None

    @property
    def leave_type_name(self):
        return self.leave_type.name if self.leave_type else None


class Holiday(Base):
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True)
    holiday_date = Column(Date, unique=True, nullable=False)
    name = Column(String(150), nullable=False)


class ShiftRoster(Base):
    """Rotational/rostered shift assignment for an employee on a given date."""
    __tablename__ = "shift_rosters"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    roster_date = Column(Date, nullable=False, index=True)
    shift_id = Column(Integer, ForeignKey("shifts.id", ondelete="SET NULL"))
    employee = relationship("Employee")
    shift = relationship("Shift")
    __table_args__ = (
        UniqueConstraint("employee_id", "roster_date", name="uq_shift_roster"),
    )


class OnDutyRequest(Base):
    """Approved on-duty travel/field-work that overrides absent punches."""
    __tablename__ = "on_duty_requests"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    reason = Column(Text)
    status = Column(String(20), default="approved")  # pending / approved / rejected
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.now)
    employee = relationship("Employee")


class CompOff(Base):
    """Compensatory off earned on weekly-off/holiday work and later consumed."""
    __tablename__ = "comp_offs"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False)
    expiry_date = Column(Date)
    days = Column(Float, default=1.0)
    reason = Column(Text)
    status = Column(String(20), default="approved")  # pending / approved / used / expired
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.now)
    employee = relationship("Employee")
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_comp_off_work_date"),
    )


class Regularization(Base):
    """Approved manual punch/status correction with a full audit trail."""
    __tablename__ = "regularizations"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    record_date = Column(Date, nullable=False, index=True)
    old_check_in = Column(String(20))
    old_check_out = Column(String(20))
    old_status = Column(String(30))
    new_check_in = Column(String(20))
    new_check_out = Column(String(20))
    new_status = Column(String(30))
    reason = Column(Text)
    status = Column(String(20), default="approved")  # pending / approved / rejected
    requested_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    decided_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    employee = relationship("Employee")


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------
class PayrollPeriod(Base):
    __tablename__ = "payroll_periods"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), default="draft")  # draft / processed / paid
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (UniqueConstraint("month", "year", name="uq_payroll_period"),)


class SalaryStructure(Base):
    __tablename__ = "salary_structures"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    effective_from = Column(Date)
    basic = Column(Float, default=0)
    hra = Column(Float, default=0)
    special_allowance = Column(Float, default=0)
    conveyance = Column(Float, default=0)
    other_earnings = Column(JSON, default=list)   # [{name, amount}]
    provident_fund = Column(Float, default=0)
    esi = Column(Float, default=0)
    professional_tax = Column(Float, default=0)
    income_tax = Column(Float, default=0)
    other_deductions = Column(JSON, default=list)  # [{name, amount}]
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    employee = relationship("Employee")

    @property
    def employee_name(self):
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self):
        return self.employee.employee_code if self.employee else None

    __table_args__ = (UniqueConstraint("employee_id", "effective_from", name="uq_salary_structure"),)


class Payslip(Base):
    __tablename__ = "payslips"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    period_id = Column(Integer, ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    total_days = Column(Integer, default=0)
    working_days = Column(Integer, default=0)
    days_present = Column(Float, default=0)
    paid_days = Column(Float, default=0)
    basic = Column(Float, default=0)
    hra = Column(Float, default=0)
    allowances = Column(Float, default=0)
    gross_salary = Column(Float, default=0)
    provident_fund = Column(Float, default=0)
    esi = Column(Float, default=0)
    professional_tax = Column(Float, default=0)
    income_tax = Column(Float, default=0)
    other_deductions = Column(Float, default=0)
    total_deductions = Column(Float, default=0)
    net_salary = Column(Float, default=0)
    status = Column(String(20), default="generated")  # generated / paid
    pdf_filename = Column(String(255))
    generated_at = Column(DateTime, default=datetime.now)

    employee = relationship("Employee")
    period = relationship("PayrollPeriod")

    @property
    def employee_name(self):
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self):
        return self.employee.employee_code if self.employee else None

    @property
    def period_name(self):
        return self.period.name if self.period else None

    __table_args__ = (UniqueConstraint("employee_id", "period_id", name="uq_payslip"),)


class AppSetting(Base):
    """Small key/value store for one-off, idempotent data upgrades."""
    __tablename__ = "app_settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)
    entity = Column(String(100))
    entity_id = Column(Integer)
    details = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)


# Register global identity guards.  Importing models always installs them, so
# every write path (routers, sync, imports, seed and CLI) is covered.
from app.services import identity as _identity  # noqa: E402,F401
