"""Realistic multi-employee sample data for engine tests and demos.

Creates an isolated SQLite database (in memory by default) containing normal,
night, flexi, rotational, missed-punch, leave, OD, holiday and overtime cases.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    CompOff, Department, Designation, Employee, Holiday, LeaveQuota, LeaveRequest,
    LeaveType, Location, OnDutyRequest, PunchLog, Regularization, Shift,
    ShiftRoster,
)

SAMPLE_START = date(2026, 10, 5)
SAMPLE_END = date(2026, 10, 11)


def _dt(day: date, value: str) -> datetime:
    hour, minute = (int(part) for part in value.split(":"))
    return datetime.combine(day, time(hour, minute))


def create_sample_db(url: str = "sqlite://"):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        poolclass=StaticPool if url == "sqlite://" else None,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)

    db = session()
    try:
        location = Location(name="Bengaluru", code="BLR", city="Bengaluru")
        department = Department(name="Operations", code="OPS", head="Sample Manager")
        designation = Designation(name="Executive", department=department)
        db.add_all([location, department, designation])

        general = Shift(name="General", start_time=time(9), end_time=time(18),
                        grace_minutes=15, early_out_grace_minutes=0,
                        min_hours_for_full_day=8, half_day_hours=4.5,
                        week_off_days=[6], shift_type="fixed")
        night = Shift(name="Night", start_time=time(22), end_time=time(6),
                      grace_minutes=15, min_hours_for_full_day=8,
                      half_day_hours=4.5, week_off_days=[6], shift_type="night")
        flexi = Shift(name="Flexi", start_time=time(8), end_time=time(20),
                      grace_minutes=0, min_hours_for_full_day=9,
                      half_day_hours=4.5, week_off_days=[6], shift_type="flexi",
                      target_hours=9)
        rotation_a = Shift(name="Rotation A", start_time=time(9), end_time=time(18),
                           min_hours_for_full_day=8, half_day_hours=4.5,
                           week_off_days=[6], shift_type="rotational", rotation_group="OpsRotation")
        rotation_b = Shift(name="Rotation B", start_time=time(14), end_time=time(23),
                           min_hours_for_full_day=8, half_day_hours=4.5,
                           week_off_days=[6], shift_type="rotational", rotation_group="OpsRotation")
        db.add_all([general, night, flexi, rotation_a, rotation_b])
        db.flush()

        leave_types = {}
        for name, code, quota, paid in (
            ("Casual Leave", "CL", 12, True),
            ("Sick Leave", "SL", 12, True),
            ("Earned Leave", "EL", 18, True),
            ("Restricted Holiday", "RH", 2, True),
            ("Loss of Pay", "LOP", 0, False),
        ):
            item = LeaveType(name=name, code=code, is_paid=paid, max_days_per_year=quota)
            db.add(item)
            leave_types[code] = item
        db.flush()
        for code, quota in (("CL", 12), ("SL", 12), ("EL", 18), ("RH", 2), ("LOP", 0)):
            db.add(LeaveQuota(
                scope="global", scope_value="ALL", leave_type_id=leave_types[code].id,
                year=SAMPLE_START.year, days=quota,
            ))
        casual = leave_types["CL"]

        specs = [
            ("SMP001", "Asha", general),
            ("SMP002", "Ravi", night),
            ("SMP003", "Mina", general),
            ("SMP004", "Kiran", general),
            ("SMP005", "Dev", general),
            ("SMP006", "Sandwich", general),
            ("SMP007", "Flexi", flexi),
            ("SMP008", "OnDuty", general),
            ("SMP009", "Rotate", rotation_a),
        ]
        employees = {}
        for index, (code, name, shift) in enumerate(specs, 1):
            employee = Employee(
                employee_code=code, first_name=name, last_name="Sample",
                device_user_id=str(100 + index), status="active",
                date_of_joining=SAMPLE_START - timedelta(days=30),
                department_id=department.id, designation_id=designation.id,
                location_id=location.id, shift_id=shift.id,
            )
            db.add(employee)
            db.flush()
            employees[code] = employee

        db.add(Holiday(holiday_date=date(2026, 10, 7), name="Diwali"))

        def punch(code: str, when: datetime, punch_type: str = "in", **extra):
            employee = employees[code]
            db.add(PunchLog(
                employee_id=employee.id, device_user_id=employee.device_user_id,
                punch_time=when, punch_type=punch_type, source="device",
                verify_mode=extra.get("verify_mode", "Fingerprint"),
                device_serial=extra.get("device_serial", "DEV-SAMPLE-01"),
                raw_code=0 if punch_type == "in" else 1,
            ))

        # Normal employee: two sessions on one day to verify break deduction.
        for offset in range(7):
            day = SAMPLE_START + timedelta(days=offset)
            if day.weekday() == 6:
                continue
            punch("SMP001", _dt(day, "09:00"), "in")
            if day == date(2026, 10, 6):
                punch("SMP001", _dt(day, "13:00"), "out")
                punch("SMP001", _dt(day, "14:00"), "in")
            punch("SMP001", _dt(day, "18:00"), "out")

        # Night shift: punches cross midnight and belong to the shift start date.
        for day in (date(2026, 10, 5), date(2026, 10, 6)):
            punch("SMP002", _dt(day, "22:00"), "in")
            punch("SMP002", _dt(day + timedelta(days=1), "06:00"), "out")

        # Missed/single punch.
        punch("SMP003", _dt(date(2026, 10, 8), "09:05"), "in")

        # Approved leave on 6 Oct.
        db.add(LeaveRequest(
            employee_id=employees["SMP004"].id, leave_type_id=casual.id,
            from_date=date(2026, 10, 6), to_date=date(2026, 10, 6),
            reason="Personal work", status="approved",
        ))

        # Overtime plus a duplicate punch two minutes later (debounce case).
        punch("SMP005", _dt(date(2026, 10, 9), "08:30"), "in")
        punch("SMP005", _dt(date(2026, 10, 9), "08:32"), "in")
        punch("SMP005", _dt(date(2026, 10, 9), "19:00"), "out")
        # Weekly-off work.
        punch("SMP005", _dt(date(2026, 10, 11), "10:00"), "in", verify_mode="Face", device_serial="DEV-GATE-2")
        punch("SMP005", _dt(date(2026, 10, 11), "14:00"), "out", verify_mode="Face", device_serial="DEV-GATE-2")

        # Sandwich case: absent either side of the 7 Oct holiday.
        # (No punches are added for 5 and 8 Oct.)

        # Flexi shift: starts late but meets the 9-hour target.
        punch("SMP007", _dt(date(2026, 10, 8), "11:00"), "in")
        punch("SMP007", _dt(date(2026, 10, 8), "20:15"), "out")

        # Approved on-duty, no punches.
        db.add(OnDutyRequest(
            employee_id=employees["SMP008"].id,
            from_date=date(2026, 10, 8), to_date=date(2026, 10, 8),
            reason="Client site visit", status="approved",
        ))

        # Rostered employee worked the afternoon shift on 8 Oct.
        db.add(ShiftRoster(
            employee_id=employees["SMP009"].id,
            roster_date=date(2026, 10, 8), shift_id=rotation_b.id,
        ))
        punch("SMP009", _dt(date(2026, 10, 8), "14:00"), "in")
        punch("SMP009", _dt(date(2026, 10, 8), "23:00"), "out")

        # Approved manual regularization for the missed punch.
        db.add(Regularization(
            employee_id=employees["SMP003"].id, record_date=date(2026, 10, 8),
            old_check_in="09:05", old_check_out="", old_status="missed_punch",
            new_check_in="09:05", new_check_out="18:00", new_status="present",
            reason="Biometric out punch missed", status="approved",
            decided_at=datetime(2026, 10, 9, 11, 0),
        ))

        db.add(CompOff(
            employee_id=employees["SMP005"].id, work_date=date(2026, 10, 11),
            days=0.5, reason="Weekly off project support", status="approved",
        ))

        db.commit()
    finally:
        db.close()
    return engine, session


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "sample_attendance.db"
    create_sample_db(f"sqlite:///{path}")
    print(f"Created sample database: {path}")
