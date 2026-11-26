from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal
from app.models import Device
from app.routers import (
    access, advanced_reports, attendance, auth, dashboard, devices, employees,
    employee_documents, leaves, lunch_break, master, payroll, reports, shift_groups, shifts, system,
)
from app.seed import seed_database
from app.services.biometric import sync_device
from app.services.scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_database()
    start_scheduler()

    # First pull so dashboards are populated immediately after boot.
    db = SessionLocal()
    try:
        for device in db.query(Device).filter(Device.is_active.is_(True)).all():
            try:
                sync_device(db, device)
            except Exception:
                db.rollback()
    finally:
        db.close()

    yield
    shutdown_scheduler()


app = FastAPI(
    title="HRMS API",
    description="HRMS with biometric attendance, reports, payroll and role-group access control",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Advanced reports live under the Attendance heading in the UI, with an alias
# under Reports for integrations that expect /api/reports/advanced/*.
attendance_advanced = APIRouter(prefix="/api/attendance/advanced")
attendance_advanced.include_router(advanced_reports.router)
reports_advanced = APIRouter(prefix="/api/reports/advanced")
reports_advanced.include_router(advanced_reports.router)

for router in (
    auth.router, dashboard.router, employees.router, employee_documents.router,
    master.router, shifts.router, shift_groups.router, lunch_break.router, devices.router,
    attendance.router, reports.router,
    leaves.router, payroll.router, access.router, system.router,
    attendance_advanced, reports_advanced,
):
    app.include_router(router)


@app.get("/api/health", tags=["System"])
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
