"""Centralized Time & Attendance calculation engine.

This module is deliberately independent of report formatters.  It converts raw
biometric punches plus leave/OD/comp-off/regularization data into clean daily
results used by both the standard attendance records and the advanced report
suite.

Supported rules:
  * First-In/Last-Out or strict alternating in/out pairs
  * configurable duplicate-punch debounce
  * fixed, rotational/rostered, flexi and cross-midnight night shifts
  * shift groups assigned directly or by employee designation
  * late-in / early-out grace, half-day and full-day thresholds
  * pre/post shift, weekly-off and holiday OT with threshold + rounding
  * leave, on-duty, comp-off and approved manual regularization overlay
  * optional sandwich rule for WO/HL between two absent working days
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AppSetting, CompOff, Employee, Holiday, LeaveRequest, OnDutyRequest,
    PunchLog, Regularization, Shift, ShiftGroup, ShiftRoster,
)
from app.utils import round2

CONFIG_KEY = "advanced_engine_config"

OUT_TYPES = {"out", "checkout", "check_out", "break_out", "clock_out"}
IN_TYPES = {"in", "checkin", "check_in", "break_in", "clock_in"}


def _default_config() -> dict:
    return {
        "pairing_mode": settings.PAIRING_MODE,
        "punch_debounce_minutes": settings.PUNCH_DEBOUNCE_MINUTES,
        "half_day_hours": settings.HALF_DAY_HOURS,
        "full_day_hours": settings.FULL_DAY_HOURS,
        "ot_min_minutes": settings.OT_MIN_MINUTES,
        "ot_round_minutes": settings.OT_ROUND_MINUTES,
        "ot_multiplier": settings.OT_MULTIPLIER,
        "holiday_ot_multiplier": settings.HOLIDAY_OT_MULTIPLIER,
        "weekoff_ot_multiplier": settings.WEEKOFF_OT_MULTIPLIER,
        "comp_off_hours_per_day": settings.COMP_OFF_HOURS_PER_DAY,
        "sandwich_rule": settings.SANDWICH_RULE,
        "continuous_absence_days": settings.CONTINUOUS_ABSENCE_DAYS,
        "late_penalty_instances": settings.LATE_PENALTY_INSTANCES,
        "late_penalty_days": settings.LATE_PENALTY_DAYS,
        "authorized_devices": [],
    }


@dataclass
class EngineConfig:
    pairing_mode: str = "strict"
    punch_debounce_minutes: int = 2
    half_day_hours: float = 4.5
    full_day_hours: float = 8.0
    ot_min_minutes: int = 30
    ot_round_minutes: int = 15
    ot_multiplier: float = 1.5
    holiday_ot_multiplier: float = 2.0
    weekoff_ot_multiplier: float = 2.0
    comp_off_hours_per_day: float = 8.0
    sandwich_rule: bool = False
    continuous_absence_days: int = 3
    late_penalty_instances: int = 3
    late_penalty_days: float = 0.5
    authorized_devices: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, values: dict | None) -> "EngineConfig":
        merged = _default_config()
        merged.update(values or {})
        allowed = {key: merged[key] for key in cls.__dataclass_fields__ if key in merged}
        return cls(**allowed)

    def as_dict(self) -> dict:
        return asdict(self)


def get_engine_config(db: Session) -> EngineConfig:
    row = db.query(AppSetting).filter(AppSetting.key == CONFIG_KEY).first()
    values = {}
    if row and row.value:
        try:
            values = json.loads(row.value)
        except (TypeError, ValueError):
            values = {}
    return EngineConfig.from_dict(values)


def save_engine_config(db: Session, values: dict) -> EngineConfig:
    config = EngineConfig.from_dict(values)
    row = db.query(AppSetting).filter(AppSetting.key == CONFIG_KEY).first()
    if row is None:
        row = AppSetting(key=CONFIG_KEY)
        db.add(row)
    row.value = json.dumps(config.as_dict())
    db.commit()
    return config


@dataclass
class NormalizedPunch:
    id: int
    employee_id: int | None
    punch_time: datetime
    punch_type: str
    verify_mode: str | None = None
    device_serial: str | None = None
    device_name: str | None = None
    source: str | None = None

    @property
    def direction(self) -> str:
        return "OUT" if (self.punch_type or "").lower() in OUT_TYPES else "IN"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "time": self.punch_time.strftime("%H:%M:%S"),
            "timestamp": self.punch_time.isoformat(sep=" "),
            "type": self.punch_type,
            "direction": self.direction,
            "verify_mode": self.verify_mode,
            "device": self.device_serial or self.device_name or "—",
            "source": self.source,
        }


@dataclass
class DayCalculation:
    employee_id: int
    employee_code: str
    employee_name: str
    department: str
    designation: str
    location: str
    shift: str
    shift_id: int | None
    shift_type: str
    shift_timings: str
    date: str
    first_in: str = ""
    last_out: str = ""
    all_punches: str = ""
    punch_count: int = 0
    pair_count: int = 0
    gross_hours: float = 0.0
    net_hours: float = 0.0
    break_hours: float = 0.0
    late_by: int = 0
    early_exit_by: int = 0
    regular_ot_hours: float = 0.0
    pre_shift_ot_hours: float = 0.0
    post_shift_ot_hours: float = 0.0
    holiday_ot_hours: float = 0.0
    weekoff_ot_hours: float = 0.0
    ot_multiplier: float = 1.0
    comp_off_earned: float = 0.0
    status: str = "absent"
    status_code: str = "A"
    leave_type: str = ""
    leave_paid: bool = False
    od_reason: str = ""
    source: str = "auto"
    remarks: str = ""
    is_sandwich: bool = False
    # Non-exported helper fields used by report builders.
    raw_punches: list[NormalizedPunch] = field(default_factory=list, repr=False)
    sessions: list[dict] = field(default_factory=list, repr=False)

    def as_dict(self, include_raw: bool = False) -> dict:
        data = asdict(self)
        data.pop("raw_punches", None)
        data.pop("sessions", None)
        if include_raw:
            data["punches"] = [p.as_dict() for p in self.raw_punches]
            data["punch_sessions"] = self.sessions
        return data


@dataclass
class EngineFilters:
    employee_ids: list[int] | None = None
    employee_code: str | None = None
    department_id: int | None = None
    location_id: int | None = None
    designation_id: int | None = None
    shift_id: int | None = None
    # Repeated query parameters from the advanced reports UI. Blank means
    # "all", so only non-empty lists narrow the employee set.
    department_ids: list[int] | None = None
    location_ids: list[int] | None = None
    designation_ids: list[int] | None = None
    shift_ids: list[int] | None = None


class AttendanceData:
    """Data access layer: one query per entity, then in-memory lookups."""

    def __init__(self, db: Session, start: date, end: date, filters: EngineFilters | None = None):
        self.db = db
        self.filters = filters or EngineFilters()
        # Explicit shift groups take priority over the legacy rotation_group
        # text field when resolving a shift for a day.  Designation groups are
        # resolved dynamically so new employees inherit the mapping.
        groups = db.query(ShiftGroup).order_by(ShiftGroup.id).all()
        self.group_shifts = {
            group.id: sorted(group.shifts, key=lambda s: s.id)
            for group in groups
        }
        self.group_designations: dict[int, int] = {}
        for group in groups:
            for designation_id in group.designation_ids or []:
                self.group_designations.setdefault(designation_id, group.id)
        self.employees = self._load_employees()
        ids = [e.id for e in self.employees]
        self.punches = self._load_punches(start - timedelta(days=1), end + timedelta(days=1), ids)
        self.holidays = {
            h.holiday_date: h.name
            for h in db.query(Holiday)
            .filter(Holiday.holiday_date >= start, Holiday.holiday_date <= end).all()
        }
        self.leaves = self._load_leaves(start, end, ids)
        self.ods = self._load_approved(OnDutyRequest, start, end, ids)
        self.comp_offs = self._load_compoffs(start, end, ids)
        self.regularizations = self._load_regularizations(start, end, ids)
        self.rosters = self._load_rosters(start, end, ids)
        self.rotation_shifts = {
            (s.rotation_group or s.name): []
            for s in db.query(Shift).all() if s.rotation_group
        }
        if self.rotation_shifts:
            for shift in db.query(Shift).order_by(Shift.id).all():
                if shift.rotation_group:
                    self.rotation_shifts.setdefault(shift.rotation_group, []).append(shift)

    def _load_employees(self) -> list[Employee]:
        query = self.db.query(Employee)
        filters = self.filters
        if filters.employee_ids is not None:
            if not filters.employee_ids:
                return []
            query = query.filter(Employee.id.in_(filters.employee_ids))
        if filters.employee_code:
            query = query.filter(Employee.employee_code.ilike(f"%{filters.employee_code}%"))

        def selected(ids: list[int] | None, single: int | None) -> list[int]:
            # Lists come from multi-select dropdowns; the scalar form is kept
            # for older API clients and internal callers.
            return list(ids) if ids else ([single] if single else [])

        for column, values in (
            (Employee.department_id, selected(filters.department_ids, filters.department_id)),
            (Employee.location_id, selected(filters.location_ids, filters.location_id)),
            (Employee.designation_id, selected(filters.designation_ids, filters.designation_id)),
        ):
            if values:
                query = query.filter(column.in_(values))
        shift_values = selected(filters.shift_ids, filters.shift_id)
        if shift_values:
            group_ids = [
                group_id for group_id, shifts in self.group_shifts.items()
                if any(shift.id in shift_values for shift in shifts)
            ]
            condition = Employee.shift_id.in_(shift_values)
            if group_ids:
                grouped_conditions = [Employee.shift_group_id.in_(group_ids)]
                designation_ids = [
                    designation_id
                    for designation_id, group_id in self.group_designations.items()
                    if group_id in group_ids
                ]
                if designation_ids:
                    grouped_conditions.append(Employee.designation_id.in_(designation_ids))
                condition = or_(condition, *grouped_conditions)
            query = query.filter(condition)
        return query.order_by(Employee.employee_code).all()

    def _load_punches(self, start: date, end: date, employee_ids: list[int]) -> dict[int, list[NormalizedPunch]]:
        result: dict[int, list[NormalizedPunch]] = {}
        if not employee_ids:
            return result
        rows = (
            self.db.query(PunchLog)
            .filter(
                PunchLog.employee_id.in_(employee_ids),
                PunchLog.punch_time >= datetime.combine(start, time.min),
                PunchLog.punch_time < datetime.combine(end, time.min),
            )
            .order_by(PunchLog.employee_id, PunchLog.punch_time, PunchLog.id).all()
        )
        for row in rows:
            result.setdefault(row.employee_id, []).append(NormalizedPunch(
                id=row.id,
                employee_id=row.employee_id,
                punch_time=row.punch_time,
                punch_type=row.punch_type or "in",
                verify_mode=row.verify_mode,
                device_serial=row.device_serial,
                device_name=row.device.name if row.device else None,
                source=row.source,
            ))
        return result

    def _load_leaves(self, start: date, end: date, employee_ids: list[int]) -> dict[tuple[int, date], dict]:
        result: dict[tuple[int, date], dict] = {}
        if not employee_ids:
            return result
        rows = (
            self.db.query(LeaveRequest)
            .filter(
                LeaveRequest.status == "approved",
                LeaveRequest.employee_id.in_(employee_ids),
                LeaveRequest.from_date <= end,
                LeaveRequest.to_date >= start,
            ).all()
        )
        for leave in rows:
            day = leave.from_date
            while day <= leave.to_date:
                result[(leave.employee_id, day)] = {
                    "name": leave.leave_type.name if leave.leave_type else "Leave",
                    "code": _leave_code(leave.leave_type.name if leave.leave_type else "Leave"),
                    "paid": bool(leave.leave_type and leave.leave_type.is_paid),
                    "reason": leave.reason,
                }
                day += timedelta(days=1)
        return result

    def _load_approved(self, model, start: date, end: date, employee_ids: list[int]) -> dict[tuple[int, date], object]:
        result: dict[tuple[int, date], object] = {}
        if not employee_ids:
            return result
        rows = (
            self.db.query(model)
            .filter(
                model.status == "approved",
                model.employee_id.in_(employee_ids),
                model.from_date <= end,
                model.to_date >= start,
            ).all()
        )
        for row in rows:
            day = row.from_date
            while day <= row.to_date:
                result[(row.employee_id, day)] = row
                day += timedelta(days=1)
        return result

    def _load_compoffs(self, start: date, end: date, employee_ids: list[int]) -> dict[tuple[int, date], CompOff]:
        result: dict[tuple[int, date], CompOff] = {}
        if not employee_ids:
            return result
        rows = (
            self.db.query(CompOff)
            .filter(
                CompOff.status == "approved",
                CompOff.employee_id.in_(employee_ids),
                CompOff.work_date >= start,
                CompOff.work_date <= end,
                (CompOff.days or 0) > 0,
            )
            .order_by(CompOff.days.desc())
            .all()
        )
        for row in rows:
            # Manual and automatic rows may share a work date; keep the largest
            # balance for status calculation. Zero-day ledger rows are ignored.
            result.setdefault((row.employee_id, row.work_date), row)
        return result

    def _load_regularizations(self, start: date, end: date, employee_ids: list[int]) -> dict[tuple[int, date], Regularization]:
        result: dict[tuple[int, date], Regularization] = {}
        if not employee_ids:
            return result
        rows = (
            self.db.query(Regularization)
            .filter(
                Regularization.status == "approved",
                Regularization.employee_id.in_(employee_ids),
                Regularization.record_date >= start,
                Regularization.record_date <= end,
            )
            .order_by(Regularization.decided_at, Regularization.id).all()
        )
        for row in rows:
            result[(row.employee_id, row.record_date)] = row
        return result

    def _load_rosters(self, start: date, end: date, employee_ids: list[int]) -> dict[tuple[int, date], int | None]:
        result: dict[tuple[int, date], int | None] = {}
        if not employee_ids:
            return result
        rows = (
            self.db.query(ShiftRoster)
            .filter(
                ShiftRoster.employee_id.in_(employee_ids),
                ShiftRoster.roster_date >= start,
                ShiftRoster.roster_date <= end,
            ).all()
        )
        for row in rows:
            result[(row.employee_id, row.roster_date)] = row.shift_id
        return result


def _leave_code(name: str) -> str:
    text = (name or "").lower()
    if "casual" in text:
        return "CL"
    if "sick" in text:
        return "SL"
    if "earned" in text or "annual" in text:
        return "EL"
    if "unpaid" in text or "without pay" in text or "lwp" in text:
        return "LWP"
    return "L"


def _is_out(punch: NormalizedPunch) -> bool:
    return punch.direction == "OUT"


def debounce_punches(punches: Iterable[NormalizedPunch], minutes: int) -> list[NormalizedPunch]:
    """Drop repeated same-direction punches inside the debounce window."""
    ordered = sorted(punches, key=lambda p: (p.punch_time, p.id))
    if minutes <= 0:
        return ordered
    kept: list[NormalizedPunch] = []
    window = timedelta(minutes=minutes)
    for punch in ordered:
        if kept:
            previous = kept[-1]
            if (
                previous.direction == punch.direction
                and timedelta(0) <= punch.punch_time - previous.punch_time <= window
            ):
                continue
        kept.append(punch)
    return kept


def pair_punches(punches: list[NormalizedPunch], mode: str = "strict") -> tuple[list[dict], float, float]:
    """Return work sessions, net hours and break hours.

    ``strict`` creates every completed IN/OUT session and deducts the gaps
    between them.  Repeated IN punches before the first OUT are treated as
    device duplicates, so the day is one session from the first IN to the last
    OUT.  ``first_last`` always uses the full span of the day.
    """
    if not punches:
        return [], 0.0, 0.0

    if mode == "first_last":
        start, end = punches[0].punch_time, punches[-1].punch_time
        seconds = max(0.0, (end - start).total_seconds())
        sessions = [{
            "in": punches[0].as_dict(), "out": punches[-1].as_dict(),
            "start": start, "end": end, "minutes": seconds / 60,
        }] if len(punches) >= 2 else []
        return sessions, round2(seconds / 3600), 0.0

    # Device double-punches can arrive as IN, IN, ..., OUT, OUT.  When more
    # than one IN appears before the first OUT, keep the first IN and the last
    # OUT so the full work span is preserved.
    first_out_index = next(
        (index for index, punch in enumerate(punches) if _is_out(punch)), None
    )
    leading_ins = [
        punch for punch in punches[:first_out_index] if not _is_out(punch)
    ] if first_out_index is not None else []
    out_punches = [punch for punch in punches if _is_out(punch)]
    if len(leading_ins) > 1 and out_punches:
        start, end = leading_ins[0].punch_time, out_punches[-1].punch_time
        seconds = max(0.0, (end - start).total_seconds())
        sessions = [{
            "in": leading_ins[0].as_dict(), "out": out_punches[-1].as_dict(),
            "start": start, "end": end, "minutes": seconds / 60,
        }]
        return sessions, round2(seconds / 3600), 0.0

    sessions: list[dict] = []
    open_in: NormalizedPunch | None = None
    for punch in punches:
        if _is_out(punch):
            if open_in is not None:
                seconds = max(0.0, (punch.punch_time - open_in.punch_time).total_seconds())
                sessions.append({
                    "in": open_in.as_dict(), "out": punch.as_dict(),
                    "start": open_in.punch_time, "end": punch.punch_time,
                    "minutes": seconds / 60,
                })
                open_in = None
        elif open_in is None:
            open_in = punch
        elif any(_is_out(item) for item in punches):
            # A later IN after a completed session starts a new session.
            open_in = punch

    net_seconds = sum(float(s["minutes"]) * 60 for s in sessions)
    break_seconds = 0.0
    for previous, following in zip(sessions, sessions[1:]):
        gap = (following["start"] - previous["end"]).total_seconds()
        if gap > 0:
            break_seconds += gap
    return sessions, round2(net_seconds / 3600), round2(break_seconds / 3600)


def _overlap_minutes(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> float:
    left = max(start, window_start)
    right = min(end, window_end)
    return max(0.0, (right - left).total_seconds() / 60) if right > left else 0.0


def _round_minutes(minutes: float, step: int) -> float:
    if step <= 0:
        return float(minutes)
    return float((int(minutes) // step) * step)


def _parse_clock(value, day: date) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if " " in text or "T" in text:
        try:
            return datetime.fromisoformat(text.replace("T", " "))
        except ValueError:
            return None
    try:
        parts = [int(part) for part in text.split(":")[:2]]
        return datetime.combine(day, time(parts[0], parts[1]))
    except (ValueError, IndexError):
        return None


class AttendanceEngine:
    def __init__(self, db: Session, config: EngineConfig | None = None):
        self.db = db
        self.config = config or get_engine_config(db)

    # -- shift resolution ---------------------------------------------------
    def _resolve_shift(self, employee: Employee, day: date, data: AttendanceData) -> Shift | None:
        roster_shift_id = data.rosters.get((employee.id, day))
        if roster_shift_id:
            shift = self.db.get(Shift, roster_shift_id)
            if shift:
                return shift
        # Grouped employees rotate weekly from a fixed anchor when no roster
        # row exists.  A direct employee group wins over a designation group;
        # legacy shift.rotation_group remains the final fallback.
        shifts = []
        group_id = employee.shift_group_id or data.group_designations.get(employee.designation_id)
        if group_id:
            shifts = data.group_shifts.get(group_id) or []
        if not shifts:
            group = employee.shift.rotation_group if employee.shift else None
            shifts = data.rotation_shifts.get(group, []) if group else []
        if shifts:
            anchor = date(2026, 1, 5)  # a Monday
            return shifts[((day - anchor).days // 7) % len(shifts)]
        if employee.shift:
            return employee.shift
        return None

    @staticmethod
    def is_night(shift: Shift | None) -> bool:
        if not shift:
            return False
        return (shift.shift_type or "").lower() == "night" or shift.start_time > shift.end_time

    @staticmethod
    def shift_window(day: date, shift: Shift | None) -> tuple[datetime, datetime]:
        if not shift:
            start = datetime.combine(day, time(9, 0))
            return start, start + timedelta(hours=9)
        start = datetime.combine(day, shift.start_time)
        end_day = day + timedelta(days=1) if (AttendanceEngine.is_night(shift) or shift.end_time <= shift.start_time) else day
        end = datetime.combine(end_day, shift.end_time)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    @staticmethod
    def punch_window(day: date, shift: Shift | None) -> tuple[datetime, datetime]:
        """Window used to collect punches attributed to a shift day."""
        if AttendanceEngine.is_night(shift) and shift:
            start = datetime.combine(day, shift.start_time) - timedelta(hours=2)
            end = datetime.combine(day + timedelta(days=1), shift.end_time) + timedelta(hours=2)
            return start, end
        return datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min)

    # -- main calculation ---------------------------------------------------
    def calculate_range(
        self,
        start: date,
        end: date,
        filters: EngineFilters | None = None,
        include_future: bool = False,
    ) -> list[DayCalculation]:
        if not filters:
            filters = EngineFilters()
        if filters.employee_ids is None and filters.employee_code is None:
            # Default engine scope is all employees; callers can narrow it.
            filters.employee_ids = None
        data = AttendanceData(self.db, start, end, filters)
        today = date.today()
        results: list[DayCalculation] = []

        for employee in data.employees:
            if employee.date_of_joining and start < employee.date_of_joining:
                # Still calculate from the joining date inside this range.
                employee_start = max(start, employee.date_of_joining)
            else:
                employee_start = start
            all_punches = data.punches.get(employee.id, [])
            consumed: set[int] = set()

            day = employee_start
            while day <= end:
                if not include_future and day > today:
                    break
                shift = self._resolve_shift(employee, day, data)
                window_start, window_end = self.punch_window(day, shift)
                candidates = [
                    p for p in all_punches
                    if p.id not in consumed and window_start <= p.punch_time < window_end
                ]
                consumed.update(p.id for p in candidates)
                results.append(self._calculate_day(employee, day, shift, candidates, data))
                day += timedelta(days=1)

        if self.config.sandwich_rule:
            self._apply_sandwich_rule(results)
        return results

    def _calculate_day(
        self,
        employee: Employee,
        day: date,
        shift: Shift | None,
        punches: list[NormalizedPunch],
        data: AttendanceData,
    ) -> DayCalculation:
        cfg = self.config
        normalized = debounce_punches(punches, cfg.punch_debounce_minutes)
        sessions, net_hours, break_hours = pair_punches(normalized, cfg.pairing_mode)
        first_in = normalized[0].punch_time if normalized else None
        last_out = normalized[-1].punch_time if normalized else None
        gross_hours = round2((last_out - first_in).total_seconds() / 3600) if first_in and last_out and len(normalized) > 1 else 0.0

        planned_start, planned_end = self.shift_window(day, shift)
        shift_type = (shift.shift_type if shift and shift.shift_type else "fixed").lower()
        if self.is_night(shift):
            shift_type = "night"
        target_hours = (
            shift.target_hours if shift and shift.target_hours
            else ((planned_end - planned_start).total_seconds() / 3600 if shift else 8.0)
        )
        full_hours = shift.min_hours_for_full_day if shift and shift.min_hours_for_full_day else cfg.full_day_hours
        half_hours = shift.half_day_hours if shift and shift.half_day_hours else cfg.half_day_hours

        late_by = 0
        early_by = 0
        if shift and shift_type != "flexi" and first_in:
            grace = shift.grace_minutes if shift.grace_minutes is not None else 0
            late_by = max(0, int((first_in - planned_start).total_seconds() / 60 - grace))
        if shift and shift_type != "flexi" and last_out and len(normalized) > 1:
            grace = shift.early_out_grace_minutes if shift.early_out_grace_minutes is not None else 0
            early_by = max(0, int((planned_end - last_out).total_seconds() / 60 - grace))

        # Regular OT: work outside the assigned shift window, pre/post split.
        pre_minutes = 0.0
        post_minutes = 0.0
        if shift and shift_type not in ("flexi",):
            for session in sessions:
                pre_minutes += _overlap_minutes(session["start"], session["end"], datetime.min, planned_start)
                post_minutes += _overlap_minutes(session["start"], session["end"], planned_end, datetime.max)

        leave = data.leaves.get((employee.id, day))
        od = data.ods.get((employee.id, day))
        comp_off = data.comp_offs.get((employee.id, day))
        regularization = data.regularizations.get((employee.id, day))
        holiday = data.holidays.get(day)
        week_offs = set(shift.week_off_days or []) if shift else {5}
        is_week_off = day.weekday() in week_offs
        is_holiday = holiday is not None

        status = "absent"
        status_code = "A"
        leave_type = ""
        leave_paid = False
        od_reason = ""
        source = "auto"
        remarks = ""
        ot_multiplier = cfg.ot_multiplier
        regular_ot = 0.0
        pre_shift_ot = 0.0
        post_shift_ot = 0.0
        holiday_ot = 0.0
        weekoff_ot = 0.0
        comp_off_earned = 0.0

        if regularization:
            manual_in = _parse_clock(regularization.new_check_in, day)
            manual_out = _parse_clock(regularization.new_check_out, day)
            if manual_in:
                first_in = manual_in
            if manual_out:
                last_out = manual_out
            if regularization.new_status:
                status = regularization.new_status.lower().replace(" ", "_")
            source = "regularization"
            remarks = regularization.reason or "Manual regularization"

        if od:
            status, status_code = "od", "OD"
            od_reason = od.reason or "On duty"
            source = "on_duty"
            remarks = remarks or od_reason
        elif leave:
            status, status_code = "leave", leave["code"]
            leave_type = leave["name"]
            leave_paid = leave["paid"]
            remarks = remarks or leave_type
        elif is_holiday:
            status, status_code = "holiday", "HL"
            remarks = "Holiday: " + holiday
        elif is_week_off:
            # A comp-off *earned* on a weekly off does not replace the WO status.
            status, status_code = "week_off", "WO"
            remarks = "Weekly off worked" if normalized else "Weekly off"
        elif comp_off:
            status, status_code = "comp_off", "CO"
            remarks = remarks or "Compensatory off"
        elif not normalized:
            status, status_code = "absent", "A"
        elif net_hours >= full_hours or net_hours >= target_hours:
            status, status_code = "present", "P"
        elif net_hours >= half_hours:
            status, status_code = "half_day", "HD"
        elif len(normalized) == 1 or not sessions:
            status, status_code = "missed_punch", "MIS"
            remarks = "Single/incomplete punch pair"
        else:
            status, status_code = "half_day", "HD"

        if regularization and regularization.new_status and status not in ("od", "leave", "comp_off"):
            status = regularization.new_status.lower().replace(" ", "_")
            status_code = {
                "present": "P", "half_day": "HD", "absent": "A", "missed_punch": "MIS",
                "week_off": "WO", "holiday": "HL", "comp_off": "CO",
            }.get(status, status_code)

        # Overtime is only earned when punches exist and the day is not leave/OD.
        if normalized and status not in ("leave", "od"):
            if is_holiday:
                ot_minutes = self._ot_minutes(net_hours * 60)
                holiday_ot = round2(ot_minutes / 60)
                ot_multiplier = cfg.holiday_ot_multiplier
            elif is_week_off:
                ot_minutes = self._ot_minutes(net_hours * 60)
                weekoff_ot = round2(ot_minutes / 60)
                ot_multiplier = cfg.weekoff_ot_multiplier
            else:
                pre = self._ot_minutes(pre_minutes)
                post = self._ot_minutes(post_minutes)
                pre_hours, post_hours = round2(pre / 60), round2(post / 60)
                pre_shift_ot = pre_hours
                post_shift_ot = post_hours
                regular_ot = round2(pre_hours + post_hours)
            if is_week_off or is_holiday:
                earned_hours = holiday_ot if is_holiday else weekoff_ot
                comp_off_earned = round(min(1.0, earned_hours / cfg.comp_off_hours_per_day), 2) if cfg.comp_off_hours_per_day else 0.0

        if late_by and status in ("present", "half_day"):
            remarks = (remarks + "; " if remarks else "") + f"Late by {late_by} min"
        if early_by and status in ("present", "half_day"):
            remarks = (remarks + "; " if remarks else "") + f"Early exit by {early_by} min"

        punches_with_sessions = []
        for index, session in enumerate(sessions, 1):
            punches_with_sessions.append({
                "session": index,
                "in_time": session["in"]["time"],
                "out_time": session["out"]["time"],
                "duration_hours": round2(session["minutes"] / 60),
                "in_device": session["in"]["device"],
                "out_device": session["out"]["device"],
                "in_mode": session["in"]["verify_mode"],
                "out_mode": session["out"]["verify_mode"],
            })

        timings = (
            f"{shift.start_time.strftime('%H:%M')}–{shift.end_time.strftime('%H:%M')}"
            if shift else "—"
        )
        return DayCalculation(
            employee_id=employee.id,
            employee_code=employee.employee_code,
            employee_name=employee.full_name,
            department=employee.department_name or "",
            designation=employee.designation_name or "",
            location=employee.location_name or "",
            shift=shift.name if shift else "",
            shift_id=shift.id if shift else None,
            shift_type=shift_type,
            shift_timings=timings,
            date=day.isoformat(),
            first_in=first_in.strftime("%H:%M") if first_in else "",
            last_out=last_out.strftime("%H:%M") if last_out else "",
            all_punches=", ".join(p.punch_time.strftime("%H:%M") for p in normalized),
            punch_count=len(normalized),
            pair_count=len(sessions),
            gross_hours=gross_hours,
            net_hours=net_hours,
            break_hours=break_hours,
            late_by=late_by,
            early_exit_by=early_by,
            regular_ot_hours=regular_ot,
            pre_shift_ot_hours=pre_shift_ot,
            post_shift_ot_hours=post_shift_ot,
            holiday_ot_hours=holiday_ot,
            weekoff_ot_hours=weekoff_ot,
            ot_multiplier=ot_multiplier,
            comp_off_earned=comp_off_earned,
            status=status,
            status_code=status_code,
            leave_type=leave_type,
            leave_paid=leave_paid,
            od_reason=od_reason,
            source=source,
            remarks=remarks,
            raw_punches=normalized,
            sessions=punches_with_sessions,
        )

    def _ot_minutes(self, minutes: float) -> float:
        cfg = self.config
        if minutes <= 0 or minutes < cfg.ot_min_minutes:
            return 0.0
        return _round_minutes(minutes, cfg.ot_round_minutes)

    def _apply_sandwich_rule(self, calculations: list[DayCalculation]) -> None:
        by_employee: dict[int, list[DayCalculation]] = {}
        for calc in calculations:
            by_employee.setdefault(calc.employee_id, []).append(calc)
        absent_states = {"absent", "missed_punch", "LWP"}
        intervening = {"week_off", "holiday", "comp_off"}
        for items in by_employee.values():
            items.sort(key=lambda c: c.date)
            for index, calc in enumerate(items):
                if calc.status not in intervening or index == 0 or index >= len(items) - 1:
                    continue
                previous = items[index - 1]
                following = items[index + 1]
                if (
                    (datetime.fromisoformat(calc.date).date() - datetime.fromisoformat(previous.date).date()).days == 1
                    and (datetime.fromisoformat(following.date).date() - datetime.fromisoformat(calc.date).date()).days == 1
                    and previous.status in absent_states
                    and following.status in absent_states
                ):
                    calc.status = "absent"
                    calc.status_code = "A"
                    calc.is_sandwich = True
                    calc.remarks = (calc.remarks + "; " if calc.remarks else "") + "Sandwich rule"
