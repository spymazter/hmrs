"""Biometric device integration.

Supports the ZKTeco / eSSL TCP protocol (port 4370) through the ``pyzk``
library, plus a simulation mode so the whole application can be evaluated
before the physical device is reachable.
"""

import hashlib
import logging
import random
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Device, DeviceSyncState, Employee, PunchLog, Shift
from app.services.attendance import recompute_records
from app.services.identity import identifiers_available, new_identity_key

logger = logging.getLogger(__name__)

PUNCH_MAP = {
    0: ("in", "Check In"),
    1: ("out", "Check Out"),
    2: ("break_out", "Break Out"),
    3: ("break_in", "Break In"),
    4: ("in", "Overtime In"),
    5: ("out", "Overtime Out"),
}


def _zk_connection(ip: str, port: int, timeout: int):
    try:
        from zk import ZK
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "pyzk is not installed. Add it to requirements and rebuild the image."
        ) from exc
    # pyzk performs an ICMP ping before connecting by default. Minimal Docker
    # images usually do not ship the `ping` binary, and some networks block
    # ICMP entirely, so skip it and rely on the TCP connection test instead.
    return ZK(ip, port=port, timeout=timeout, ommit_ping=True)


def test_connection(ip: str, port: int, timeout: Optional[int] = None) -> dict:
    conn = None
    try:
        zk = _zk_connection(ip, port, timeout or settings.DEVICE_TIMEOUT)
        conn = zk.connect()
        info = {}
        try:
            device_info = conn.get_device_info()
            if device_info is not None:
                info = {
                    k: str(v)
                    for k, v in vars(device_info).items()
                    if not k.startswith("_")
                }
        except Exception:
            pass
        user_count = len(conn.get_users())
        log_count = len(conn.get_attendance())
        return {
            "success": True,
            "message": "Connected successfully",
            "device_info": info,
            "users": user_count,
            "attendance_records": log_count,
        }
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def _fetch_live(ip: str, port: int, timeout: int):
    conn = None
    users, punches = [], []
    try:
        zk = _zk_connection(ip, port, timeout)
        conn = zk.connect()
        for user in conn.get_users():
            users.append({
                "user_id": str(getattr(user, "user_id", "") or "").strip(),
                "name": getattr(user, "name", "") or "",
                "uid": getattr(user, "uid", None),
            })
        for log in conn.get_attendance():
            code = getattr(log, "punch", None)
            if code is None:
                status = getattr(log, "status", 0)
                code = status
            try:
                code = int(code)
            except (TypeError, ValueError):
                code = 0
            punch_type, punch_label = PUNCH_MAP.get(code, ("in", "Unknown"))
            verify_mode = getattr(log, "verify_mode", None)
            if verify_mode is None:
                verify_mode = getattr(log, "verification_mode", None)
            verification = {
                0: "Fingerprint", 1: "Card", 2: "Password", 3: "Face",
            }.get(verify_mode if isinstance(verify_mode, int) else None, verify_mode or punch_label)
            users_set = {u["user_id"] for u in users}
            user_id = str(getattr(log, "user_id", "") or "").strip()
            if user_id and user_id not in users_set:
                users.append({"user_id": user_id, "name": "", "uid": None})
            punches.append({
                "user_id": user_id,
                "timestamp": getattr(log, "timestamp", None),
                "punch_type": punch_type,
                "raw_code": code,
                "uid": getattr(log, "uid", None),
                "verify_mode": str(verification),
            })
        return users, punches
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def _default_shift(db: Session) -> Optional[Shift]:
    shift = db.query(Shift).filter(Shift.name == settings.DEFAULT_SHIFT_NAME).first()
    return shift or db.query(Shift).order_by(Shift.id).first()


def _simulate(db: Session, device: Device) -> tuple[int, int]:
    """Generate realistic punches for the last two weeks (demo mode)."""
    today = date.today()
    # ~45 days of history covers the previous calendar month for payroll demos.
    start = today - timedelta(days=44)
    now = datetime.now()
    employees = (
        db.query(Employee)
        .filter(Employee.status == "active", Employee.device_user_id.isnot(None))
        .all()
    )
    existing = {
        (p.device_user_id, p.punch_time.replace(microsecond=0), p.punch_type)
        for p in db.query(PunchLog)
        .filter(PunchLog.punch_time >= datetime.combine(start, time.min))
        .all()
    }
    added = 0
    for emp in employees:
        seed = int(hashlib.md5(f"emp-{emp.id}".encode()).hexdigest()[:8], 16)
        rnd = random.Random(seed)
        shift = emp.shift or _default_shift(db)
        st = shift.start_time if shift else time(9, 0)
        et = shift.end_time if shift else time(18, 0)
        for offset in range(45):
            day = start + timedelta(days=offset)
            if day.weekday() >= 5 or day > today:
                continue
            if emp.date_of_joining and day < emp.date_of_joining:
                continue
            if rnd.random() < 0.07:  # occasional absence
                continue
            in_minutes = st.hour * 60 + st.minute + rnd.randint(-10, 28)
            out_minutes = et.hour * 60 + et.minute + rnd.randint(-10, 80)
            base = datetime.combine(day, time.min)
            check_in = base + timedelta(minutes=in_minutes)
            check_out = base + timedelta(minutes=out_minutes)
            if check_in > now:
                continue
            candidates = [("in", check_in)]
            if check_out <= now:
                candidates.append(("out", check_out))
            for punch_type, punch_time in candidates:
                punch_time = punch_time.replace(second=0, microsecond=0)
                key = (emp.device_user_id, punch_time, punch_type)
                if key in existing:
                    continue
                db.add(PunchLog(
                    employee_id=emp.id,
                    device_user_id=emp.device_user_id,
                    punch_time=punch_time,
                    punch_type=punch_type,
                    source="simulation",
                    device_id=device.id,
                ))
                existing.add(key)
                added += 1
    return added, 0


def sync_device(
    db: Session,
    device: Device,
    progress: Optional[Callable[[str, str, dict], None]] = None,
    full_history: bool = False,
) -> dict:
    """Pull users and punches from the configured device and persist them.

    With ``full_history=True`` the sync high-water mark is ignored and every
    punch held by the device is scanned. Records already stored locally are
    still skipped by the dedupe key, and the device itself is never modified.
    """

    def report(phase: str, message: str, **extra):
        payload = {
            "phase": phase,
            "message": message,
            "time": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
        logger.info("[sync device=%s] %s: %s", device.id, phase, message)
        if progress:
            progress(payload)

    mode = (device.mode or settings.DEVICE_MODE or "simulate").lower()
    if mode == "simulate":
        report("start", "Starting simulated punch generation")
        added, new_users = _simulate(db, device)
        device.last_error = None
        device.last_sync_at = datetime.now()
        db.commit()
        if added:
            report("attendance", "Recomputing attendance records")
            affected_start = date.today() - timedelta(days=45)
            recompute_records(db, affected_start, date.today())
        message = f"Generated {added} demo punches"
        report("done", message, new_punches=added, new_employees=new_users)
        return {
            "success": True,
            "mode": "simulate",
            "new_punches": added,
            "new_employees": new_users,
            "message": message,
        }

    # Device access is strictly read-only: _fetch_live() only calls
    # get_users() and get_attendance(). We never clear logs, delete users or
    # change device settings/time, so nothing is removed from the biometric unit.
    report("connecting", f"Connecting to {device.ip_address}:{device.port}")
    try:
        users, punches = _fetch_live(
            device.ip_address, device.port, settings.DEVICE_TIMEOUT
        )
    except Exception as exc:
        device.last_error = str(exc)
        db.commit()
        report("failed", f"Connection failed: {exc}")
        return {"success": False, "mode": "live", "message": str(exc)}
    report(
        "fetched",
        f"Fetched {len(users)} users and {len(punches)} punch records from device"
        + (" — scanning the full history" if full_history else ""),
        total=len(punches),
        users=len(users),
    )

    # Earliest punch date per device user is used as the joining date for
    # auto-created employees so historical attendance is not skipped.
    first_punch_date: dict[str, date] = {}
    for punch in punches:
        ts = punch["timestamp"]
        uid = punch["user_id"]
        if isinstance(ts, datetime) and uid:
            day = ts.date()
            if uid not in first_punch_date or day < first_punch_date[uid]:
                first_punch_date[uid] = day

    try:
        employees = {
            e.device_user_id: e
            for e in db.query(Employee).filter(Employee.device_user_id.isnot(None)).all()
        }
        new_users = 0
        skipped_users = 0
        if settings.AUTO_CREATE_DEVICE_USERS:
            default_shift = _default_shift(db)
            for user in users:
                uid = user["user_id"]
                if not uid or uid in employees:
                    continue
                code = f"DEV-{uid}"
                owner_key = new_identity_key()
                # A retired code/UID is never recycled: skip the device user
                # instead of creating a second employee with a reserved ID.
                if not identifiers_available(db, code, uid, owner_key):
                    skipped_users += 1
                    continue
                emp = Employee(
                    identity_key=owner_key,
                    employee_code=code,
                    first_name=user["name"] or f"User {uid}",
                    device_user_id=uid,
                    status="active",
                    shift_id=default_shift.id if default_shift else None,
                    date_of_joining=first_punch_date.get(uid, date.today()),
                )
                db.add(emp)
                db.flush()
                employees[uid] = emp
                new_users += 1
        message = f"Mapped device users; created {new_users} new employees"
        if skipped_users:
            message += f"; skipped {skipped_users} reserved IDs"
        report("employees", message, new_employees=new_users,
               skipped_users=skipped_users)

        # Correct auto-created employees from earlier imports that were given
        # today's joining date before historical punches were considered.
        for uid, emp in employees.items():
            day = first_punch_date.get(uid)
            if day and emp.employee_code.startswith("DEV-") and (not emp.date_of_joining or day < emp.date_of_joining):
                emp.date_of_joining = day

        existing = {
            (p.device_user_id, p.punch_time.replace(microsecond=0), p.punch_type)
            for p in db.query(PunchLog).all()
        }
        state = db.query(DeviceSyncState).filter_by(device_id=device.id).first()
        if state is None:
            state = DeviceSyncState(device_id=device.id)
            db.add(state)
        # A normal sync starts at the high-water mark. A full-history download
        # deliberately ignores it so every log on the device is scanned; the
        # dedupe key below still prevents importing the same punch twice.
        since = None if full_history else state.last_punch_time

        # pyzk reads the full attendance log from the device, but a high-water
        # mark keeps repeat syncs from reprocessing every old punch.
        latest_punch: datetime | None = None
        for punch in punches:
            ts = punch["timestamp"]
            if not isinstance(ts, datetime):
                continue
            if latest_punch is None or ts > latest_punch:
                latest_punch = ts

        added = 0
        affected_dates: set[date] = set()
        if full_history:
            scan_label = "all punches from the beginning of the device log"
        elif since:
            scan_label = f"punches after {since.isoformat(timespec='seconds')}"
        else:
            scan_label = "punches from the beginning"
        report(
            "punches",
            f"Scanning {scan_label}",
            processed=0,
            total=len(punches),
            new_punches=0,
        )
        for index, punch in enumerate(punches, 1):
            ts = punch["timestamp"]
            if not isinstance(ts, datetime):
                continue
            if since is not None and ts < since:
                continue
            uid = punch["user_id"]
            if not uid:
                continue
            punch_time = ts.replace(second=0, microsecond=0)
            punch_type = punch["punch_type"]
            key = (uid, punch_time, punch_type)
            if key in existing:
                continue
            emp = employees.get(uid)
            db.add(PunchLog(
                employee_id=emp.id if emp else None,
                device_user_id=uid,
                punch_time=punch_time,
                punch_type=punch_type,
                raw_code=punch["raw_code"],
                source="device",
                verify_mode=punch.get("verify_mode"),
                device_serial=device.serial_number or f"{device.name or 'device'}#{device.id}",
                device_id=device.id,
            ))
            existing.add(key)
            added += 1
            affected_dates.add(punch_time.date())
            if index % 2000 == 0:
                report(
                    "punches",
                    f"Processed {index}/{len(punches)} punch records — {added} new",
                    processed=index,
                    total=len(punches),
                    new_punches=added,
                )
        report(
            "punches",
            f"Finished scanning {len(punches)} punch records — {added} new",
            processed=len(punches),
            total=len(punches),
            new_punches=added,
        )

        if latest_punch and (state.last_punch_time is None or latest_punch > state.last_punch_time):
            state.last_punch_time = latest_punch
        device.last_error = None
        device.last_sync_at = datetime.now()
        db.commit()
    except Exception as exc:
        db.rollback()
        device.last_error = str(exc)
        db.commit()
        report("failed", f"Sync failed: {exc}")
        return {"success": False, "mode": "live", "message": str(exc)}

    if affected_dates:
        report(
            "attendance",
            f"Recomputing attendance for {len(affected_dates)} days ({min(affected_dates)} → {max(affected_dates)})",
        )
        count = recompute_records(db, min(affected_dates), max(affected_dates))
        report("attendance", f"Recomputed {count} daily attendance records")
    message = (
        f"Full history: imported {added} missing punches, {new_users} new employees"
        if full_history
        else f"Synced {added} punches, {new_users} new employees"
    )
    report(
        "done",
        message,
        processed=len(punches),
        total=len(punches),
        new_punches=added,
        new_employees=new_users,
    )
    return {
        "success": True,
        "mode": "live",
        "full_history": full_history,
        "new_punches": added,
        "new_employees": new_users,
        "last_punch_at": latest_punch.isoformat() if latest_punch else None,
        "message": message,
    }
