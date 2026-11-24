from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require
from app.config import settings
from app.database import get_db
from app.models import Device, DeviceSyncJob
from app.schemas import DeviceOut, DeviceUpdate, SyncJobOut
from app.services.biometric import sync_device, test_connection
from app.services.sync_jobs import start_sync_job

router = APIRouter(prefix="/api/devices", tags=["Biometric devices"])


@router.get("", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db), _=Depends(require("device.view"))):
    return db.query(Device).order_by(Device.id).all()


@router.get("/settings")
def device_settings(db: Session = Depends(get_db), _=Depends(require("device.view"))):
    # The saved device row is what the next sync actually uses. Fall back to
    # .env only when no device has been configured yet.
    device = db.query(Device).order_by(Device.id).first()
    return {
        "configured_ip": device.ip_address if device else settings.DEVICE_IP,
        "configured_port": device.port if device else settings.DEVICE_PORT,
        "mode": device.mode if device else settings.DEVICE_MODE,
        "sync_interval_minutes": settings.DEVICE_SYNC_INTERVAL_MINUTES,
        "auto_create_users": settings.AUTO_CREATE_DEVICE_USERS,
    }


@router.put("/{device_id}", response_model=DeviceOut)
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db), _=Depends(require("device.manage"))):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, key, value)
    db.commit()
    db.refresh(device)
    return device


@router.post("/test")
def test_device(
    ip: str | None = None,
    port: int | None = None,
    _=Depends(require("device.manage")),
):
    return test_connection(ip or settings.DEVICE_IP, port or settings.DEVICE_PORT)


@router.post("/{device_id}/sync")
def sync(device_id: int, db: Session = Depends(get_db), _=Depends(require("device.manage"))):
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    return sync_device(db, device)


@router.post("/{device_id}/sync-job", response_model=dict, status_code=202)
def sync_job(device_id: int, db: Session = Depends(get_db), _=Depends(require("device.manage"))):
    """Start a sync in the background and return a job id for progress polling."""
    device = db.query(Device).get(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    return {"job_id": start_sync_job(device_id), "message": "Sync started"}


@router.get("/sync-jobs", response_model=list[SyncJobOut])
def list_sync_jobs(limit: int = 20, db: Session = Depends(get_db), _=Depends(require("device.view"))):
    return db.query(DeviceSyncJob).order_by(DeviceSyncJob.id.desc()).limit(min(limit, 100)).all()


@router.get("/sync-jobs/{job_id}", response_model=SyncJobOut)
def get_sync_job(job_id: int, db: Session = Depends(get_db), _=Depends(require("device.view"))):
    job = db.query(DeviceSyncJob).get(job_id)
    if not job:
        raise HTTPException(404, "Sync job not found")
    return job
