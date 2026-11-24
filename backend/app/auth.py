from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Role, RoleGroup, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def effective_permissions(user: User) -> set[str]:
    codes: set[str] = set()
    for role in user.roles:
        codes.update(role.permissions or [])
    for group in user.groups:
        for role in group.roles:
            codes.update(role.permissions or [])
    return codes


def can(user: User, code: str) -> bool:
    return code in effective_permissions(user)


def is_admin(user: User) -> bool:
    return can(user, "access.manage") or any(r.name.lower() == "admin" for r in user.roles)


def scoped_employee_id(user: User) -> int | None:
    """Non-HR users only ever see their own employee data."""
    if user.employee_id and not can(user, "employee.view"):
        return user.employee_id
    return None


def payroll_scoped_employee_id(user: User) -> int | None:
    """Employees see only their own slips; payroll/HR/managers see all."""
    privileged = any(can(user, code) for code in ("payroll.view", "employee.view", "report.view"))
    return user.employee_id if user.employee_id and not privileged else None


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise credentials_error
    return user


def require(*codes: str):
    """Dependency factory: user must have at least one of the given permissions."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if not any(can(user, code) for code in codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user
    return checker


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "employee_id": user.employee_id,
        "must_change_password": bool(user.must_change_password),
        "profile_completed": bool(user.profile_completed),
        "roles": [{"id": r.id, "name": r.name} for r in user.roles],
        "groups": [{"id": g.id, "name": g.name} for g in user.groups],
        "permissions": sorted(effective_permissions(user)),
        "is_admin": is_admin(user),
    }
