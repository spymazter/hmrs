from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings

_scheduler: BackgroundScheduler | None = None


def scheduled_sync():
    from app.database import SessionLocal
    from app.models import Device
    from app.services.biometric import sync_device

    db = SessionLocal()
    try:
        for device in db.query(Device).filter(Device.is_active.is_(True)).all():
            try:
                sync_device(db, device)
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
