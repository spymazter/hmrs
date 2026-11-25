from datetime import date, datetime, time
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Auth ----------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


# Access control ------------------------------------------------------------
class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: list[str] = []


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[list[str]] = None


class RoleOut(ORMBase, RoleBase):
    id: int
    is_system: bool = False


class GroupBase(BaseModel):
    name: str
    description: Optional[str] = None
    role_ids: list[int] = []


class GroupCreate(GroupBase):
    pass


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    role_ids: Optional[list[int]] = None


class GroupOut(ORMBase):
    id: int
    name: str
    description: Optional[str] = None
    role_ids: list[int] = []
    roles: list[RoleOut] = []


class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool = True
    employee_id: Optional[int] = None


class UserCreate(UserBase):
    password: str
    role_ids: list[int] = []
    group_ids: list[int] = []


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    employee_id: Optional[int] = None
    password: Optional[str] = None


class UserAssign(BaseModel):
    role_ids: list[int] = []
    group_ids: list[int] = []


class UserOut(ORMBase):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool
    employee_id: Optional[int] = None
    last_login: Optional[datetime] = None
    roles: list[RoleOut] = []
    groups: list[GroupOut] = []
    permissions: list[str] = []
    is_admin: bool = False


# Organisation --------------------------------------------------------------
class DepartmentBase(BaseModel):
    name: str
    code: Optional[str] = None
    head: Optional[str] = None


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentOut(ORMBase, DepartmentBase):
    id: int


class LocationBase(BaseModel):
    name: str
    code: Optional[str] = None
    city: Optional[str] = None


class LocationCreate(LocationBase):
    pass


class LocationOut(ORMBase, LocationBase):
    id: int
    label: Optional[str] = None


class DesignationBase(BaseModel):
    name: str
    department_id: Optional[int] = None


class DesignationCreate(DesignationBase):
    pass


class DesignationOut(ORMBase, DesignationBase):
    id: int
    department_name: Optional[str] = None


class ShiftGroupBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class ShiftGroupMemberOut(ORMBase):
    id: int
    employee_code: str
    full_name: str
    shift_name: Optional[str] = None


class ShiftGroupShiftOut(ORMBase):
    id: int
    name: str


class ShiftGroupCreate(ShiftGroupBase):
    shift_ids: list[int] = []
    employee_ids: list[int] = []


class ShiftGroupUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    shift_ids: Optional[list[int]] = None
    employee_ids: Optional[list[int]] = None


class ShiftGroupOut(ORMBase, ShiftGroupBase):
    id: int
    shift_ids: list[int] = []
    employee_ids: list[int] = []
    shifts: list[ShiftGroupShiftOut] = []
    employees: list[ShiftGroupMemberOut] = []


class ShiftGroupEmployeeMapping(BaseModel):
    employee_ids: list[int]


class ShiftBase(BaseModel):
    name: str
    start_time: time = time(9, 0)
    end_time: time = time(18, 0)
    grace_minutes: int = 15
    early_out_grace_minutes: int = 0
    min_hours_for_full_day: float = 8.0
    half_day_hours: float = 4.0
    week_off_days: list[int] = [5]
    is_active: bool = True
    color: str = "#4f46e5"
    shift_type: str = "fixed"
    target_hours: Optional[float] = None
    break_minutes: int = 0
    rotation_group: Optional[str] = None
    shift_group_id: Optional[int] = None


class ShiftCreate(ShiftBase):
    pass


class ShiftUpdate(BaseModel):
    name: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    grace_minutes: Optional[int] = None
    early_out_grace_minutes: Optional[int] = None
    min_hours_for_full_day: Optional[float] = None
    half_day_hours: Optional[float] = None
    week_off_days: Optional[list[int]] = None
    is_active: Optional[bool] = None
    color: Optional[str] = None
    shift_type: Optional[str] = None
    target_hours: Optional[float] = None
    break_minutes: Optional[int] = None
    rotation_group: Optional[str] = None
    shift_group_id: Optional[int] = None


class ShiftOut(ORMBase, ShiftBase):
    id: int
    shift_group_name: Optional[str] = None


class EmployeeBase(BaseModel):
    employee_code: str
    first_name: str
    last_name: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    address: Optional[str] = None
    date_of_joining: Optional[date] = None
    status: str = "active"
    device_user_id: Optional[str] = None
    department_id: Optional[int] = None
    designation_id: Optional[int] = None
    shift_id: Optional[int] = None
    shift_group_id: Optional[int] = None
    location_id: Optional[int] = None
    manager_id: Optional[int] = None


class EmployeeCreate(EmployeeBase):
    create_login: bool = False
    login_password: Optional[str] = None


class EmployeeUpdate(BaseModel):
    employee_code: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    address: Optional[str] = None
    date_of_joining: Optional[date] = None
    status: Optional[str] = None
    device_user_id: Optional[str] = None
    department_id: Optional[int] = None
    designation_id: Optional[int] = None
    shift_id: Optional[int] = None
    shift_group_id: Optional[int] = None
    location_id: Optional[int] = None
    manager_id: Optional[int] = None


class EmployeeSelfUpdate(BaseModel):
    """Fields an employee is allowed to change from the self-service portal.

    Deliberately excludes employee_code, username, status, device UID,
    department, designation, shift and manager.
    """
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    address: Optional[str] = None


class OnboardingRequest(ChangePasswordRequest):
    first_name: str
    last_name: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    address: Optional[str] = None


class EmployeeOut(ORMBase, EmployeeBase):
    id: int
    full_name: str
    department_name: Optional[str] = None
    designation_name: Optional[str] = None
    shift_name: Optional[str] = None
    shift_group_name: Optional[str] = None
    created_at: Optional[datetime] = None


class EmployeeListOut(BaseModel):
    items: list[EmployeeOut]
    total: int


# Devices / punches ---------------------------------------------------------
class DeviceOut(ORMBase):
    id: int
    name: str
    ip_address: str
    port: int
    is_active: bool
    mode: str
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    is_active: Optional[bool] = None
    mode: Optional[str] = None


class SyncJobOut(ORMBase):
    id: int
    device_id: int
    status: str
    phase: str
    total: int = 0
    processed: int = 0
    new_punches: int = 0
    new_employees: int = 0
    message: Optional[str] = None
    logs: list[dict] = []
    started_at: datetime
    finished_at: Optional[datetime] = None


class PunchOut(ORMBase):
    id: int
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    device_user_id: Optional[str] = None
    punch_time: datetime
    punch_type: str
    raw_code: Optional[int] = None
    source: str


class PunchCreate(BaseModel):
    employee_id: int
    punch_time: datetime
    punch_type: str = "in"
    source: str = "manual"


class PunchListOut(BaseModel):
    items: list[PunchOut]
    total: int


class AttendanceOut(ORMBase):
    id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    record_date: date
    shift_name: Optional[str] = None
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    total_hours: float
    overtime_hours: float
    late_minutes: int
    early_departure_minutes: int
    status: str
    remarks: Optional[str] = None
    source: str


class AttendanceListOut(BaseModel):
    items: list[AttendanceOut]
    total: int


# Leaves --------------------------------------------------------------------
class LeaveTypeBase(BaseModel):
    name: str
    is_paid: bool = True
    max_days_per_year: int = 12
    color: str = "#0ea5e9"


class LeaveTypeCreate(LeaveTypeBase):
    pass


class LeaveTypeOut(ORMBase, LeaveTypeBase):
    id: int


class LeaveRequestBase(BaseModel):
    employee_id: int
    leave_type_id: int
    from_date: date
    to_date: date
    reason: Optional[str] = None


class LeaveRequestCreate(LeaveRequestBase):
    pass


class LeaveRequestOut(ORMBase, LeaveRequestBase):
    id: int
    status: str
    created_at: Optional[datetime] = None
    employee_name: Optional[str] = None
    leave_type_name: Optional[str] = None


class LeaveAction(BaseModel):
    status: str  # approved / rejected


class HolidayCreate(BaseModel):
    holiday_date: date
    name: str


class HolidayOut(ORMBase):
    id: int
    holiday_date: date
    name: str


# Payroll -------------------------------------------------------------------
class PayrollPeriodBase(BaseModel):
    name: str
    month: int
    year: int
    start_date: date
    end_date: date


class PayrollPeriodCreate(PayrollPeriodBase):
    pass


class PayrollPeriodUpdate(BaseModel):
    status: str


class PayrollPeriodOut(ORMBase, PayrollPeriodBase):
    id: int
    status: str


class SalaryStructureBase(BaseModel):
    employee_id: int
    effective_from: Optional[date] = None
    basic: float = 0
    hra: float = 0
    special_allowance: float = 0
    conveyance: float = 0
    other_earnings: list[dict] = []
    provident_fund: float = 0
    esi: float = 0
    professional_tax: float = 0
    income_tax: float = 0
    other_deductions: list[dict] = []


class SalaryStructureCreate(SalaryStructureBase):
    pass


class SalaryStructureUpdate(BaseModel):
    effective_from: Optional[date] = None
    basic: Optional[float] = None
    hra: Optional[float] = None
    special_allowance: Optional[float] = None
    conveyance: Optional[float] = None
    other_earnings: Optional[list[dict]] = None
    provident_fund: Optional[float] = None
    esi: Optional[float] = None
    professional_tax: Optional[float] = None
    income_tax: Optional[float] = None
    other_deductions: Optional[list[dict]] = None


class SalaryStructureOut(ORMBase, SalaryStructureBase):
    id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None


class ProcessPayrollRequest(BaseModel):
    period_id: int
    include_unapproved_leave: bool = False
    # device = live employees imported from the biometric device (DEV-*)
    # all    = every active employee (including seeded demo records)
    scope: str = "device"
    replace_existing: bool = True


class PayslipDownloadRequest(BaseModel):
    # Empty means "all periods available to this user".
    period_ids: list[int] = []
    include_demo: bool = False


class PayslipOut(ORMBase):
    id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    period_id: int
    period_name: Optional[str] = None
    total_days: int
    working_days: int
    days_present: float
    paid_days: float
    basic: float
    hra: float
    allowances: float
    gross_salary: float
    provident_fund: float
    esi: float
    professional_tax: float
    income_tax: float
    other_deductions: float
    total_deductions: float
    net_salary: float
    status: str
    generated_at: Optional[datetime] = None
