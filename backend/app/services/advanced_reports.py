"""Report registry and builders for the advanced attendance suite.

Each builder receives a ``ReportContext`` with engine results and returns
plain dictionaries, keeping calculation, data access and formatting separate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    Department, Designation, Employee, LeaveRequest, LeaveType, Location,
    PunchLog, Regularization, Shift, ShiftGroup, User,
)
from app.services.attendance_engine import (
    AttendanceEngine, EngineConfig, EngineFilters, DayCalculation,
)
from app.utils import round2


COLUMNS = list[tuple[str, str]]


@dataclass
class ReportContext:
    db: Session
    start: date
    end: date
    calculations: list[DayCalculation]
    config: EngineConfig
    engine: AttendanceEngine
    filters: dict
    by_employee: dict[int, list[DayCalculation]]
    # Report-level employee scope may be broader than calculated rows.  For
    # example, the muster roll lists every employee in scope even in months
    # before they joined, showing "—" for those days.
    employees: list[Employee] = field(default_factory=list)

    def shift(self, calc: DayCalculation) -> Shift | None:
        return self.db.get(Shift, calc.shift_id) if calc.shift_id else None


@dataclass
class ReportDefinition:
    id: str
    name: str
    category: str
    description: str
    columns: COLUMNS
    builder: Callable[[ReportContext], tuple[list[dict], dict | None]]
    notes: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _base(row: DayCalculation) -> dict:
    data = row.as_dict()
    return data


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _scoped_employees(db: Session, filters: EngineFilters) -> list[Employee]:
    """Mirror the engine's employee filters without loading attendance data.

    Used by report builders that need to list employees who had no calculations
    in the selected period (for example, colleagues who joined later).
    """
    query = db.query(Employee)
    if filters.employee_ids is not None:
        if not filters.employee_ids:
            return []
        query = query.filter(Employee.id.in_(filters.employee_ids))
    if filters.employee_code:
        query = query.filter(Employee.employee_code.ilike(f"%{filters.employee_code}%"))
    if filters.department_id:
        query = query.filter(Employee.department_id == filters.department_id)
    if filters.location_id:
        query = query.filter(Employee.location_id == filters.location_id)
    if filters.designation_id:
        query = query.filter(Employee.designation_id == filters.designation_id)
    if filters.shift_id:
        group_ids = [
            group.id for group in db.query(ShiftGroup).all()
            if any(shift.id == filters.shift_id for shift in group.shifts)
        ]
        condition = Employee.shift_id == filters.shift_id
        if group_ids:
            condition = or_(condition, Employee.shift_group_id.in_(group_ids))
        query = query.filter(condition)
    return query.order_by(Employee.employee_code).all()


def _summarize(rows: list[dict], columns: COLUMNS) -> dict:
    totals: dict[str, float] = {}
    for key, _label in columns:
        values = [row.get(key) for row in rows]
        if not values or any(isinstance(value, bool) for value in values):
            continue
        if not all(isinstance(value, (int, float)) or (isinstance(value, str) and value.replace(".", "", 1).isdigit()) for value in values):
            continue
        numeric = [_num(value) for value in values]
        if any(numeric):
            totals[key] = round2(sum(numeric))
    return {"rows": len(rows), "totals": totals}


def _charts(context: ReportContext) -> dict:
    status_counts: dict[str, int] = defaultdict(int)
    hours_by_date: dict[str, float] = defaultdict(float)
    dept_totals: dict[str, float] = defaultdict(float)
    for calc in context.calculations:
        status_counts[calc.status_code] += 1
        hours_by_date[calc.date] += calc.net_hours
        dept_totals[calc.department or "Unassigned"] += calc.net_hours
    return {
        "status_counts": dict(status_counts),
        "daily_hours": [
            {"date": day, "hours": round2(hours)}
            for day, hours in sorted(hours_by_date.items())
        ],
        "department_hours": [
            {"department": name, "hours": round2(hours)}
            for name, hours in sorted(dept_totals.items(), key=lambda item: -item[1])
        ],
    }


def _clock_datetime(value: str, day: date) -> datetime | None:
    if not value:
        return None
    try:
        hour, minute = (int(part) for part in value.split(":")[:2])
        return datetime.combine(day, _time(hour, minute))
    except (ValueError, TypeError):
        return None


from datetime import time as _time  # noqa: E402  (kept beside the helper above)


# ---------------------------------------------------------------------------
# A. Daily operational reports
# ---------------------------------------------------------------------------
def _daily_basic(ctx: ReportContext):
    columns = [
        ("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
        ("department", "Department"), ("designation", "Designation"),
        ("location", "Location"), ("shift", "Shift"), ("status_code", "Status"),
        ("first_in", "First in"), ("last_out", "Last out"),
        ("net_hours", "Net hours"), ("source", "Source"),
    ]
    return [_base(c) for c in ctx.calculations], None


def _daily_detailed(ctx: ReportContext):
    columns = [
        ("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
        ("department", "Department"), ("shift", "Shift"),
        ("shift_timings", "Shift timings"), ("all_punches", "All punches"),
        ("punch_count", "Punches"), ("pair_count", "Pairs"),
        ("gross_hours", "Gross hours"), ("net_hours", "Net hours"),
        ("break_hours", "Break hours"), ("late_by", "Late by (min)"),
        ("early_exit_by", "Early exit (min)"), ("regular_ot_hours", "Regular OT"),
        ("holiday_ot_hours", "Holiday OT"), ("weekoff_ot_hours", "WO OT"),
        ("status_code", "Status"), ("remarks", "Remarks"),
    ]
    return [_base(c) for c in ctx.calculations], None


def _punch_pairs(ctx: ReportContext):
    rows = []
    for calc in ctx.calculations:
        for session in calc.sessions:
            rows.append({
                "date": calc.date,
                "employee_code": calc.employee_code,
                "employee_name": calc.employee_name,
                "department": calc.department,
                "shift": calc.shift,
                "session": session["session"],
                "in_time": session["in_time"],
                "out_time": session["out_time"],
                "duration_hours": session["duration_hours"],
                "in_device": session["in_device"],
                "out_device": session["out_device"],
                "in_mode": session["in_mode"] or "—",
                "out_mode": session["out_mode"] or "—",
            })
    return rows, None


def _live_headcount(ctx: ReportContext):
    rows = []
    for employee_id, calcs in ctx.by_employee.items():
        calc = calcs[-1]
        if calc.status == "leave":
            state = "On leave"
        elif calc.status in ("absent", "missed_punch"):
            state = "Absent"
        elif calc.first_in and not calc.last_out:
            state = "Currently in"
        elif calc.last_out:
            state = "Punched out"
        elif calc.status in ("week_off", "holiday", "comp_off"):
            state = calc.status.replace("_", " ").title()
        else:
            state = "Yet to arrive"
        rows.append({
            "employee_code": calc.employee_code,
            "employee_name": calc.employee_name,
            "department": calc.department,
            "location": calc.location,
            "shift": calc.shift,
            "current_state": state,
            "first_in": calc.first_in,
            "last_out": calc.last_out,
            "status_code": calc.status_code,
            "as_of": calcs[-1].date,
        })
    counts = defaultdict(int)
    for row in rows:
        counts[row["current_state"]] += 1
    summary = {
        "total_strength": len(rows),
        "currently_in": counts["Currently in"],
        "punched_out": counts["Punched out"],
        "yet_to_arrive": counts["Yet to arrive"],
        "on_leave": counts["On leave"],
        "absent": counts["Absent"],
    }
    return rows, summary


# ---------------------------------------------------------------------------
# B. Monthly & payroll integration
# ---------------------------------------------------------------------------
def _monthly_summary(ctx: ReportContext):
    rows = []
    cfg = ctx.config
    for employee_id, calcs in ctx.by_employee.items():
        late_days = [c for c in calcs if c.late_by > 0]
        row = {
            "employee_code": calcs[0].employee_code,
            "employee_name": calcs[0].employee_name,
            "department": calcs[0].department,
            "designation": calcs[0].designation,
            "location": calcs[0].location,
            "calendar_days": len(calcs),
            "working_days": sum(1 for c in calcs if c.status not in ("week_off", "holiday", "comp_off")),
            "present_days": sum(1 for c in calcs if c.status == "present") + 0.5 * sum(1 for c in calcs if c.status == "half_day"),
            "half_days": sum(1 for c in calcs if c.status == "half_day"),
            "paid_leaves": sum(1 for c in calcs if c.status == "leave" and c.leave_paid),
            "unpaid_leaves": sum(1 for c in calcs if c.status == "leave" and not c.leave_paid) + sum(1 for c in calcs if c.status_code == "LWP"),
            "absent_days": sum(1 for c in calcs if c.status in ("absent", "missed_punch")),
            "week_offs": sum(1 for c in calcs if c.status == "week_off"),
            "holidays": sum(1 for c in calcs if c.status == "holiday"),
            "od_days": sum(1 for c in calcs if c.status == "od"),
            "late_count": len(late_days),
            "late_minutes": sum(c.late_by for c in calcs),
            "regular_ot_hours": round2(sum(c.regular_ot_hours for c in calcs)),
            "holiday_ot_hours": round2(sum(c.holiday_ot_hours + c.weekoff_ot_hours for c in calcs)),
            "comp_off_earned": round2(sum(c.comp_off_earned for c in calcs)),
        }
        row["total_ot_hours"] = round2(row["regular_ot_hours"] + row["holiday_ot_hours"])
        row["final_payable_days"] = round2(
            row["present_days"] + row["paid_leaves"] + row["week_offs"]
            + row["holidays"] + row["od_days"] + row["comp_off_earned"]
        )
        rows.append(row)
    return rows, None


def _muster_roll(ctx: ReportContext):
    # A muster roll lists the whole in-scope team, not only people who have
    # attendance rows in this period.  Days before an employee joined are
    # shown as "—" and are never counted as present/absent.
    span = (ctx.end - ctx.start).days + 1
    dates = [ctx.start + timedelta(days=i) for i in range(min(max(span, 0), 31))]
    columns = [
        ("employee_code", "Emp code"), ("employee_name", "Name"),
        ("department", "Department"), ("joined_on", "Joined"),
    ] + [(f"day_{day.day:02d}", f"{day.day:02d}") for day in dates] + [
        ("present", "P"), ("half_days", "HD"), ("absent", "A"),
        ("leave", "L"), ("week_offs", "WO"), ("holidays", "HL"),
    ]
    employees = ctx.employees
    if not employees and ctx.by_employee:
        ids = list(ctx.by_employee)
        employees = (
            ctx.db.query(Employee).filter(Employee.id.in_(ids))
            .order_by(Employee.employee_code).all()
        )
    rows = []
    for employee in employees:
        calcs = ctx.by_employee.get(employee.id, [])
        lookup = {date.fromisoformat(c.date): c for c in calcs}
        row = {
            "employee_code": employee.employee_code,
            "employee_name": employee.full_name,
            "department": employee.department_name or "",
            "joined_on": employee.date_of_joining.isoformat() if employee.date_of_joining else "—",
            "present": sum(1 for c in calcs if c.status == "present"),
            "half_days": sum(1 for c in calcs if c.status == "half_day"),
            "absent": sum(1 for c in calcs if c.status in ("absent", "missed_punch")),
            "leave": sum(1 for c in calcs if c.status == "leave"),
            "week_offs": sum(1 for c in calcs if c.status == "week_off"),
            "holidays": sum(1 for c in calcs if c.status == "holiday"),
        }
        for day in dates:
            key = f"day_{day.day:02d}"
            if employee.date_of_joining and day < employee.date_of_joining:
                row[key] = "—"
            else:
                row[key] = lookup[day].status_code if day in lookup else "—"
        rows.append(row)
    return rows, None, columns


def _ot_compoff(ctx: ReportContext):
    rows = []
    for calc in ctx.calculations:
        eligible = round2(
            calc.regular_ot_hours + calc.holiday_ot_hours + calc.weekoff_ot_hours
        )
        if eligible <= 0 and calc.comp_off_earned <= 0:
            continue
        row = _base(calc)
        row["eligible_ot_hours"] = eligible
        rows.append(row)
    return rows, None


# ---------------------------------------------------------------------------
# C. Exception, compliance & abnormality
# ---------------------------------------------------------------------------
def _late_early(ctx: ReportContext):
    cfg = ctx.config
    rows = []
    cumulative: dict[int, int] = defaultdict(int)
    for calc in sorted(ctx.calculations, key=lambda c: (c.employee_id, c.date)):
        if not calc.late_by and not calc.early_exit_by:
            continue
        if calc.late_by:
            cumulative[calc.employee_id] += 1
        row = _base(calc)
        row["monthly_late_count"] = cumulative[calc.employee_id]
        row["penalty_days"] = (
            cumulative[calc.employee_id] // max(1, cfg.late_penalty_instances)
        ) * cfg.late_penalty_days
        rows.append(row)
    return rows, None


def _missed_single(ctx: ReportContext):
    rows = []
    for calc in ctx.calculations:
        if calc.status == "missed_punch" or (calc.punch_count > 0 and calc.pair_count == 0):
            rows.append(_base(calc))
    return rows, None


def _continuous_absence(ctx: ReportContext):
    threshold = max(1, ctx.config.continuous_absence_days)
    rows = []
    for employee_id, calcs in ctx.by_employee.items():
        ordered = sorted(calcs, key=lambda c: c.date)
        streak: list[DayCalculation] = []
        for calc in ordered + [None]:
            is_absent = calc is not None and calc.status in ("absent", "missed_punch")
            if is_absent:
                streak.append(calc)
                continue
            if len(streak) >= threshold:
                rows.append({
                    "employee_code": streak[0].employee_code,
                    "employee_name": streak[0].employee_name,
                    "department": streak[0].department,
                    "from_date": streak[0].date,
                    "to_date": streak[-1].date,
                    "consecutive_days": len(streak),
                    "status": "ABSCONDING ALERT" if len(streak) >= threshold * 2 else "Continuous absence",
                })
            streak = []
    rows.sort(key=lambda r: (-r["consecutive_days"], r["employee_code"]))
    return rows, None


def _shift_deviation(ctx: ReportContext):
    rows = []
    authorized = set(ctx.config.authorized_devices or [])
    for calc in ctx.calculations:
        if not calc.first_in:
            continue
        shift = ctx.shift(calc)
        if not shift:
            continue
        day = date.fromisoformat(calc.date)
        start, end = ctx.engine.shift_window(day, shift)
        check_in = _clock_datetime(calc.first_in, day)
        check_out = _clock_datetime(calc.last_out, day)
        if not check_in:
            continue
        deviation = 0
        if check_in < start:
            deviation += int((start - check_in).total_seconds() / 60)
        elif check_in > end:
            deviation += int((check_in - end).total_seconds() / 60)
        device = calc.raw_punches[0].device_serial or calc.raw_punches[0].device_name if calc.raw_punches else ""
        unauthorized = bool(authorized and device and device not in authorized)
        if deviation <= (shift.grace_minutes or 0) and not unauthorized:
            continue
        rows.append({
            "date": calc.date,
            "employee_code": calc.employee_code,
            "employee_name": calc.employee_name,
            "department": calc.department,
            "assigned_shift": calc.shift,
            "shift_timings": calc.shift_timings,
            "first_in": calc.first_in,
            "last_out": calc.last_out,
            "deviation_minutes": deviation,
            "device": device or "—",
            "unauthorized_device": "Yes" if unauthorized else "No",
            "remarks": "Outside shift window" if deviation > (shift.grace_minutes or 0) else "Unauthorized device",
        })
    return rows, None


# ---------------------------------------------------------------------------
# D. Audit, leave & raw logs
# ---------------------------------------------------------------------------
def _raw_logs(ctx: ReportContext):
    query = ctx.db.query(PunchLog).outerjoin(Employee, PunchLog.employee_id == Employee.id)
    query = query.filter(
        PunchLog.punch_time >= datetime.combine(ctx.start - timedelta(days=1), _time.min),
        PunchLog.punch_time < datetime.combine(ctx.end + timedelta(days=2), _time.min),
    )
    filters = ctx.filters
    if filters.get("department_id"):
        query = query.filter(Employee.department_id == filters["department_id"])
    if filters.get("location_id"):
        query = query.filter(Employee.location_id == filters["location_id"])
    if filters.get("designation_id"):
        query = query.filter(Employee.designation_id == filters["designation_id"])
    if filters.get("shift_id"):
        query = query.filter(Employee.shift_id == filters["shift_id"])
    if filters.get("employee_code"):
        query = query.filter(Employee.employee_code.ilike(f"%{filters['employee_code']}%"))
    rows = []
    for punch in query.order_by(PunchLog.punch_time, Employee.employee_code).all():
        direction = "OUT" if (punch.punch_type or "").lower() in ("out", "checkout", "check_out", "break_out") else "IN"
        rows.append({
            "timestamp": punch.punch_time.isoformat(sep=" "),
            "employee_code": punch.employee.employee_code if punch.employee else "",
            "employee_name": punch.employee.full_name if punch.employee else "",
            "card_id": punch.device_user_id or "",
            "punch_direction": direction,
            "punch_type": punch.punch_type,
            "verification_mode": punch.verify_mode or "—",
            "device_serial": punch.device_serial or "—",
            "device_name": punch.device.name if punch.device else "—",
            "source": punch.source,
            "raw_code": punch.raw_code if punch.raw_code is not None else "—",
        })
    return rows, None


def _regularization_audit(ctx: ReportContext):
    query = ctx.db.query(Regularization).outerjoin(Employee, Regularization.employee_id == Employee.id)
    query = query.filter(
        Regularization.record_date >= ctx.start, Regularization.record_date <= ctx.end
    )
    filters = ctx.filters
    if filters.get("department_id"):
        query = query.filter(Employee.department_id == filters["department_id"])
    if filters.get("employee_code"):
        query = query.filter(Employee.employee_code.ilike(f"%{filters['employee_code']}%"))
    rows = []
    users = {u.id: u.full_name or u.username for u in ctx.db.query(User).all()}
    for item in query.order_by(Regularization.record_date, Regularization.id).all():
        old = " / ".join(filter(None, [item.old_check_in, item.old_check_out, item.old_status])) or "—"
        new = " / ".join(filter(None, [item.new_check_in, item.new_check_out, item.new_status])) or "—"
        rows.append({
            "date": item.record_date.isoformat(),
            "employee_code": item.employee.employee_code if item.employee else "",
            "employee_name": item.employee.full_name if item.employee else "",
            "old_value": old,
            "new_value": new,
            "reason": item.reason or "—",
            "modified_by": users.get(item.approved_by or item.requested_by, "—"),
            "timestamp": (item.decided_at or item.created_at).isoformat(sep=" "),
            "status": item.status,
        })
    return rows, None


def _leave_od_balance(ctx: ReportContext):
    year = ctx.start.year
    requests = (
        ctx.db.query(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(
            LeaveRequest.status == "approved",
            LeaveRequest.from_date <= ctx.end,
            LeaveRequest.to_date >= date(year, 1, 1),
        ).all()
    )
    availed: dict[tuple[int, str], float] = defaultdict(float)
    before_range: dict[tuple[int, str], float] = defaultdict(float)
    for request in requests:
        name = request.leave_type.name if request.leave_type else "Leave"
        days = ((min(request.to_date, ctx.end) - max(request.from_date, date(year, 1, 1))).days + 1)
        if days <= 0:
            continue
        key = (request.employee_id, name)
        availed[key] += days
        if request.from_date < ctx.start:
            before_range[key] += min(days, (ctx.start - request.from_date).days)

    rows = []
    employees = {
        employee.id: employee
        for employee in ctx.db.query(Employee)
        .filter(Employee.id.in_([c.employee_id for c in ctx.calculations]))
        .all()
    }
    span_days = max(1, (ctx.end - ctx.start).days + 1)
    for employee_id, calcs in ctx.by_employee.items():
        employee = employees.get(employee_id)
        if not employee:
            continue
        od_days = sum(1 for c in calcs if c.status == "od")
        od_hours = round2(sum(c.net_hours for c in calcs if c.status == "od"))
        for leave_type in ctx.db.query(LeaveType).order_by(LeaveType.name).all():
            key = (employee_id, leave_type.name)
            quota = float(leave_type.max_days_per_year or 0)
            used_in_range = availed.get(key, 0.0)
            opening = max(0.0, quota - before_range.get(key, 0.0))
            accrued = round2(quota * span_days / 365)
            closing = round2(max(0.0, opening + accrued - used_in_range))
            rows.append({
                "employee_code": employee.employee_code,
                "employee_name": employee.full_name,
                "department": employee.department_name or "",
                "leave_type": leave_type.name,
                "opening_balance": round2(opening),
                "accrued": accrued,
                "availed": round2(used_in_range),
                "closing_balance": closing,
                "od_days": od_days,
                "od_hours": od_hours,
                "status": "Paid" if leave_type.is_paid else "Unpaid",
            })
    return rows, None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
REPORTS: list[ReportDefinition] = [
    ReportDefinition(
        "daily_basic", "Daily Basic Attendance", "Daily operational",
        "First in, last out and final status per employee per day.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("department", "Department"), ("designation", "Designation"), ("location", "Location"),
         ("shift", "Shift"), ("status_code", "Status"), ("first_in", "First in"),
         ("last_out", "Last out"), ("net_hours", "Net hours"), ("source", "Source")],
        _daily_basic,
    ),
    ReportDefinition(
        "daily_detailed", "Daily Detailed Performance", "Daily operational",
        "Gross/net duration, breaks, late/early minutes and separated OT.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("department", "Department"), ("shift", "Shift"), ("shift_timings", "Shift timings"),
         ("all_punches", "All punches"), ("punch_count", "Punches"), ("pair_count", "Pairs"),
         ("gross_hours", "Gross hours"), ("net_hours", "Net hours"), ("break_hours", "Break hours"),
         ("late_by", "Late (min)"), ("early_exit_by", "Early exit (min)"),
         ("regular_ot_hours", "Regular OT"), ("holiday_ot_hours", "Holiday OT"),
         ("weekoff_ot_hours", "WO OT"), ("status_code", "Status"), ("remarks", "Remarks")],
        _daily_detailed,
    ),
    ReportDefinition(
        "punch_pairs", "In-Out Punch Pair", "Daily operational",
        "Every completed IN/OUT session with duration and terminal details.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("department", "Department"), ("shift", "Shift"), ("session", "Session"),
         ("in_time", "In"), ("out_time", "Out"), ("duration_hours", "Duration"),
         ("in_device", "In device"), ("out_device", "Out device"),
         ("in_mode", "In mode"), ("out_mode", "Out mode")],
        _punch_pairs,
    ),
    ReportDefinition(
        "live_headcount", "Live Floor / Headcount", "Daily operational",
        "Real-time strength: in, out, yet to arrive, on leave and absent.",
        [("employee_code", "Emp code"), ("employee_name", "Name"), ("department", "Department"),
         ("location", "Location"), ("shift", "Shift"), ("current_state", "State"),
         ("first_in", "First in"), ("last_out", "Last out"), ("status_code", "Status"),
         ("as_of", "As of")],
        _live_headcount,
    ),
    ReportDefinition(
        "monthly_payroll_summary", "Monthly Payroll Summary", "Monthly & payroll",
        "Payroll-ready attendance totals, OT and final payable days.",
        [("employee_code", "Emp code"), ("employee_name", "Name"), ("department", "Department"),
         ("designation", "Designation"), ("location", "Location"), ("calendar_days", "Calendar days"),
         ("working_days", "Working days"), ("present_days", "Present"), ("half_days", "Half days"),
         ("paid_leaves", "Paid leaves"), ("unpaid_leaves", "Unpaid leaves"),
         ("absent_days", "Absent"), ("week_offs", "Week offs"), ("holidays", "Holidays"),
         ("od_days", "OD days"), ("late_count", "Late count"), ("late_minutes", "Late minutes"),
         ("regular_ot_hours", "Regular OT"), ("holiday_ot_hours", "Holiday/WO OT"),
         ("total_ot_hours", "Total OT"), ("comp_off_earned", "Comp offs"),
         ("final_payable_days", "Payable days")],
        _monthly_summary,
    ),
    ReportDefinition(
        "muster_roll", "Muster Roll", "Monthly & payroll",
        "Form-compliant matrix with a daily status code per calendar day.",
        [], _muster_roll, "First 31 days of the selected range are shown in the matrix.",
    ),
    ReportDefinition(
        "ot_compoff", "OT & Comp-Off Register", "Monthly & payroll",
        "Eligible OT by day with multipliers and compensatory off earned.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("department", "Department"), ("shift", "Shift"), ("regular_ot_hours", "Regular OT"),
         ("pre_shift_ot_hours", "Pre-shift OT"), ("post_shift_ot_hours", "Post-shift OT"),
         ("holiday_ot_hours", "Holiday OT"), ("weekoff_ot_hours", "WO OT"),
         ("ot_multiplier", "Multiplier"), ("comp_off_earned", "Comp off earned"),
         ("eligible_ot_hours", "Eligible hours"), ("remarks", "Remarks")],
        _ot_compoff,
    ),
    ReportDefinition(
        "late_early", "Late Coming & Early Going", "Exception & compliance",
        "Late arrivals and early exits with cumulative count and penalty days.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("department", "Department"), ("shift", "Shift"), ("late_by", "Late (min)"),
         ("early_exit_by", "Early exit (min)"), ("first_in", "First in"),
         ("last_out", "Last out"), ("status_code", "Status"),
         ("monthly_late_count", "Cumulative lates"), ("penalty_days", "Penalty days")],
        _late_early,
    ),
    ReportDefinition(
        "missed_single", "Missed / Single Punch", "Exception & compliance",
        "Incomplete punch pairs that need HR or manager regularization.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("department", "Department"), ("shift", "Shift"), ("punch_count", "Punches"),
         ("pair_count", "Pairs"), ("first_in", "First in"), ("last_out", "Last out"),
         ("status_code", "Status"), ("remarks", "Remarks")],
        _missed_single,
    ),
    ReportDefinition(
        "continuous_absence", "Continuous Absenteeism", "Exception & compliance",
        "Absconding alerts for employees absent for consecutive working days.",
        [("employee_code", "Emp code"), ("employee_name", "Name"), ("department", "Department"),
         ("from_date", "From"), ("to_date", "To"), ("consecutive_days", "Days"), ("status", "Alert")],
        _continuous_absence,
    ),
    ReportDefinition(
        "shift_deviation", "Shift Deviation / Abnormal Punch", "Exception & compliance",
        "Punches outside assigned shift timings or at unauthorized devices.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("department", "Department"), ("assigned_shift", "Shift"),
         ("shift_timings", "Shift timings"), ("first_in", "First in"),
         ("last_out", "Last out"), ("deviation_minutes", "Deviation (min)"),
         ("device", "Device"), ("unauthorized_device", "Unauthorized"), ("remarks", "Remarks")],
        _shift_deviation,
    ),
    ReportDefinition(
        "raw_punch_log", "Raw Device Punch Log", "Audit & raw logs",
        "Unmodified biometric audit trail with direction and verification mode.",
        [("timestamp", "Timestamp"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("card_id", "Card / bio ID"), ("punch_direction", "Direction"),
         ("punch_type", "Punch type"), ("verification_mode", "Verification"),
         ("device_serial", "Device serial"), ("device_name", "Device name"),
         ("source", "Source"), ("raw_code", "Raw code")],
        _raw_logs,
    ),
    ReportDefinition(
        "regularization_audit", "Manual Regularization Audit", "Audit & raw logs",
        "Every approved manual correction with old/new values, reason and approver.",
        [("date", "Date"), ("employee_code", "Emp code"), ("employee_name", "Name"),
         ("old_value", "Old value"), ("new_value", "New value"), ("reason", "Reason"),
         ("modified_by", "Modified by"), ("timestamp", "Timestamp"), ("status", "Status")],
        _regularization_audit,
    ),
    ReportDefinition(
        "leave_od_balance", "Leave & OD Balance", "Audit & raw logs",
        "Opening, accrued, availed and closing leave balances with OD utilization.",
        [("employee_code", "Emp code"), ("employee_name", "Name"), ("department", "Department"),
         ("leave_type", "Leave type"), ("opening_balance", "Opening"),
         ("accrued", "Accrued"), ("availed", "Availed"), ("closing_balance", "Closing"),
         ("od_days", "OD days"), ("od_hours", "OD hours"), ("status", "Status")],
        _leave_od_balance,
    ),
]

REPORT_MAP = {report.id: report for report in REPORTS}


def report_metadata() -> list[dict]:
    return [
        {
            "id": report.id, "name": report.name, "category": report.category,
            "description": report.description, "notes": report.notes,
            "columns": [{"key": key, "label": label} for key, label in report.columns],
        }
        for report in REPORTS
    ]


def build_report(
    db: Session,
    report_id: str,
    start: date,
    end: date,
    filters: EngineFilters | None = None,
    config: EngineConfig | None = None,
    calculations: list[DayCalculation] | None = None,
) -> dict:
    definition = REPORT_MAP.get(report_id)
    if not definition:
        raise ValueError(f"Unknown report: {report_id}")

    filters = filters or EngineFilters()
    engine = AttendanceEngine(db, config)
    if calculations is None:
        calculations = engine.calculate_range(start, end, filters)

    by_employee: dict[int, list[DayCalculation]] = defaultdict(list)
    for calc in calculations:
        by_employee[calc.employee_id].append(calc)

    filter_values = {
        "department_id": filters.department_id,
        "location_id": filters.location_id,
        "designation_id": filters.designation_id,
        "shift_id": filters.shift_id,
        "employee_code": filters.employee_code,
    }
    ctx = ReportContext(
        db=db, start=start, end=end, calculations=calculations,
        config=engine.config, engine=engine, filters=filter_values,
        by_employee=dict(by_employee),
        employees=_scoped_employees(db, filters),
    )
    result = definition.builder(ctx)
    if len(result) == 3:
        rows, custom_summary, custom_columns = result
    else:
        rows, custom_summary = result
        custom_columns = None
    columns = custom_columns or definition.columns
    if custom_summary is None and not columns:
        columns = [(key, key.replace("_", " ").title()) for key in rows[0]] if rows else []

    summary = _summarize(rows, columns)
    if custom_summary:
        summary.update(custom_summary)

    params = []
    for key, label in (
        ("department_id", "Department"), ("location_id", "Location"),
        ("designation_id", "Designation"), ("shift_id", "Shift"),
        ("employee_code", "Employee code"),
    ):
        if filter_values.get(key):
            params.append(f"{label}: {filter_values[key]}")

    return {
        "id": report_id,
        "title": definition.name,
        "category": definition.category,
        "description": definition.description,
        "notes": definition.notes,
        "period_label": f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "params": params,
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": rows,
        "summary": summary,
        "charts": _charts(ctx),
        "filename": f"advanced_{report_id}_{start.isoformat()}_{end.isoformat()}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": engine.config.as_dict(),
    }
