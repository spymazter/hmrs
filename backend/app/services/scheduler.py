from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings

_scheduler: BackgroundScheduler | None = None


def scheduled_sync():
    from app.database import SessionLocal
    from app.models import Device
    from app.services.audit import log_system_action
    from app.services.biometric import sync_device

    db = SessionLocal()
    try:
        for device in db.query(Device).filter(Device.is_active.is_(True)).all():
            try:
                result = sync_device(db, device)
                if result.get("success") and (result.get("new_punches") or result.get("new_employees")):
                    log_system_action(
                        db,
                        "system.scheduled_sync",
                        "punch_log",
                        details={
                            "device_id": device.id,
                            "new_punches": result.get("new_punches", 0),
                            "new_employees": result.get("new_employees", 0),
                            "message": result.get("message", ""),
                        },
                    )
                    db.commit()
            except Exception:
                db.rollback()
    except Exception:
        pass
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        scheduled_sync,
        trigger="interval",
        minutes=max(1, settings.DEVICE_SYNC_INTERVAL_MINUTES),
        id="biometric-sync",
        replace_existing=True,
        next_run_time=datetime.now() + timedelta(seconds=20),
    )
    _scheduler.start()


def shutdown_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
