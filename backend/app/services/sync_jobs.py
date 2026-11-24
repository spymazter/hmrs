"""Background biometric sync jobs with a pollable, human-readable progress log."""

import threading
from datetime import datetime

from app.database import SessionLocal
from app.models import Device, DeviceSyncJob
from app.services.biometric import sync_device

MAX_LOG_LINES = 300


def _write_job(job_id: int, payload: dict | None = None, status: str | None = None, finished: bool = False, append_log: bool = True):
    db = SessionLocal()
    try:
        job = db.query(DeviceSyncJob).filter(DeviceSyncJob.id == job_id).first()
        if not job:
            return
        if payload:
            for field in ("phase", "message", "total", "processed", "new_punches", "new_employees"):
                if field in payload:
                    setattr(job, field, payload[field])
            logs = list(job.logs or [])
            duplicate = bool(logs and logs[-1].get('phase') == payload.get('phase')
                             and logs[-1].get('message') == payload.get('message'))
            if not duplicate and append_log:
                logs.append(payload)
            job.logs = logs[-MAX_LOG_LINES:]
        if status:
            job.status = status
        if finished:
            job.finished_at = datetime.now()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _run_job(job_id: int, device_id: int):
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            _write_job(job_id, {"phase": "failed", "message": "Device not found", "time": datetime.now().isoformat(timespec="seconds")}, status="failed", finished=True)
            return

        def progress(payload: dict):
            _write_job(job_id, payload)

        result = sync_device(db, device, progress=progress)
        success = bool(result.get("success"))
        # On failure sync_device() already logged the detailed error; only add
        # a final line for successful runs so the log stays readable.
        _write_job(
            job_id,
            {
                "phase": "done" if success else "failed",
                "message": result.get("message", ""),
                "time": datetime.now().isoformat(timespec="seconds"),
                "processed": result.get("total") or result.get("processed") or 0,
                "total": result.get("total") or 0,
                "new_punches": result.get("new_punches", 0),
                "new_employees": result.get("new_employees", 0),
            },
            status="success" if success else "failed",
            finished=True,
            append_log=success,
        )
    except Exception as exc:
        _write_job(
            job_id,
            {"phase": "failed", "message": f"Unexpected error: {exc}", "time": datetime.now().isoformat(timespec="seconds")},
            status="failed",
            finished=True,
        )
    finally:
        db.close()


def start_sync_job(device_id: int) -> int:
    db = SessionLocal()
    try:
        job = DeviceSyncJob(
            device_id=device_id,
            status="running",
            phase="queued",
            total=0,
            processed=0,
            new_punches=0,
            new_employees=0,
            logs=[{
                "phase": "queued",
                "message": "Sync job queued",
                "time": datetime.now().isoformat(timespec="seconds"),
            }],
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    finally:
        db.close()
    threading.Thread(target=_run_job, args=(job_id, device_id), daemon=True).start()
    return job_id
