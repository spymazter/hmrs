"""Single source of truth for permission codes used by roles and role groups."""

PERMISSIONS = [
    # code, label, module
    ("dashboard.view", "View dashboard", "Dashboard"),
    ("employee.view", "View employees", "Employees"),
    ("employee.create", "Create employees", "Employees"),
    ("employee.edit", "Edit employees", "Employees"),
    ("employee.delete", "Delete employees", "Employees"),
    ("document.view", "View employee documents", "Employees"),
    ("document.manage", "Upload / remove employee documents", "Employees"),
    ("document.hr", "View confidential HR-only documents", "Employees"),
    ("shift.view", "View shifts", "Shifts"),
    ("shift.manage", "Manage shifts", "Shifts"),
    ("attendance.view", "View attendance", "Attendance"),
    ("attendance.manage", "Manage attendance / punches", "Attendance"),
    ("device.view", "View devices", "Devices"),
    ("device.manage", "Manage devices and sync", "Devices"),
    ("report.view", "View reports", "Reports"),
    ("report.export", "Export reports", "Reports"),
    ("payroll.view", "View payroll", "Payroll"),
    ("payroll.manage", "Process payroll", "Payroll"),
    ("payslip.view", "View salary slips", "Payroll"),
    ("payslip.pdf", "Download salary slips", "Payroll"),
    ("leave.view", "View leaves", "Leaves"),
    ("leave.manage", "Apply / manage leaves", "Leaves"),
    ("leave.approve", "Legacy approve leaves", "Leaves"),
    ("leave.manager_approve", "Manager-stage leave approval", "Leaves"),
    ("leave.verify", "Verify attendance and leave balances", "Leaves"),
    ("leave.final_approve", "Final leave approval", "Leaves"),
    ("leave.quota.manage", "Upload yearly leave quotas and RH list", "Leaves"),
    ("access.view", "View users and roles", "Access control"),
    ("access.manage", "Manage users, roles and groups", "Access control"),
    ("self.portal", "Employee self-service portal", "Self service"),
]

ALL_CODES = [code for code, _, _ in PERMISSIONS]

PERMISSION_MAP = {code: label for code, label, _ in PERMISSIONS}
