import json
import re
from contextlib import asynccontextmanager

import jwt
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal
from app.models import AuditLog, Device
from app.routers import (
    access, advanced_reports, attendance, audit, auth, circulars, dashboard, devices, employees,
    employee_documents, leaves, lunch_break, master, payroll, reports, shift_groups, shifts, system,
)
from app.seed import seed_database
from app.services.audit import log_system_action
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
                result = sync_device(db, device)
                if result.get("success") and (result.get("new_punches") or result.get("new_employees")):
                    log_system_action(
                        db,
                        "system.startup_sync",
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

SENSITIVE_AUDIT_KEYS = {
    "password", "old_password", "new_password", "password_hash", "token",
    "access_token", "refresh_token", "secret", "api_key", "file", "files",
    "document", "documents", "attachment", "aadhaar", "aadhaar_number", "pan", "pan_number",
}
AUDIT_SKIP_PATHS = {"/api/auth/login"}


def _redact_audit(value, depth=0):
    if depth > 5:
        return "…"
    if isinstance(value, dict):
        return {
            str(key): (
                "***" if str(key).lower() in SENSITIVE_AUDIT_KEYS
                else _redact_audit(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_audit(item, depth + 1) for item in list(value)[:50]]
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "…"
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:400]


async def _audit_request_body(request: Request):
    raw = await request.body()
    request._body = raw
    if not raw:
        return {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return _redact_audit(json.loads(raw))
        except Exception:
            return {"raw": raw[:200].decode("utf-8", "ignore")}
    if "form" in content_type:
        text = raw[:4000].decode("utf-8", "ignore")
        return {"form_fields": sorted(set(re.findall(r'(?:^|;)\s*name="([^"]+)"', text)))[:30]}
    return {"size_bytes": len(raw)}


def _audit_user_id(request: Request):
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        claims = jwt.decode(
            header.split(None, 1)[1], settings.SECRET_KEY, algorithms=["HS256"]
        )
        return int(claims.get("sub"))
    except Exception:
        return None


def _audit_entity(path: str):
    parts = [part for part in path.split("/") if part]
    if parts and parts[0] == "api":
        parts = parts[1:]
    entity = parts[0] if parts else "unknown"
    if len(parts) > 1 and parts[1] == "advanced":
        entity = "advanced_reports"
    entity_id = None
    for part in reversed(parts):
        if part.isdigit():
            entity_id = int(part)
            break
    return entity, entity_id


@app.middleware("http")
async def audit_changes(request: Request, call_next):
    path = request.url.path
    should_audit = (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and path not in AUDIT_SKIP_PATHS
    )
    details = await _audit_request_body(request) if should_audit else {}
    response = await call_next(request)

    if not should_audit or response.status_code >= 300:
        return response

    user_id = _audit_user_id(request)
    if not user_id:
        return response

    entity, entity_id = _audit_entity(path)
    try:
        db = SessionLocal()
        try:
            db.add(AuditLog(
                user_id=user_id,
                action=f"{request.method} {path}",
                entity=entity,
                entity_id=entity_id,
                details={
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "body": details,
                },
            ))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        pass
    return response

# Advanced reports live under the Attendance heading in the UI, with an alias
# under Reports for integrations that expect /api/reports/advanced/*.
attendance_advanced = APIRouter(prefix="/api/attendance/advanced")
attendance_advanced.include_router(advanced_reports.router)
reports_advanced = APIRouter(prefix="/api/reports/advanced")
reports_advanced.include_router(advanced_reports.router)

for router in (
    auth.router, dashboard.router, employees.router, employee_documents.router, circulars.router,
    master.router, shifts.router, shift_groups.router, lunch_break.router, devices.router,
    attendance.router, reports.router,
    leaves.router, payroll.router, access.router, audit.router, system.router,
    attendance_advanced, reports_advanced,
):
    app.include_router(router)


@app.get("/api/health", tags=["System"])
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
