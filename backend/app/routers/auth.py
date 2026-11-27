from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token, get_current_user, hash_password, user_to_dict, verify_password,
)
from app.database import get_db
from app.models import Employee, User
from app.schemas import ChangePasswordRequest, LoginRequest, OnboardingRequest

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been disabled")
    user.last_login = datetime.now()
    db.commit()
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_to_dict(user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return {"message": "Password changed successfully"}


@router.post("/onboarding")
def complete_onboarding(
    payload: OnboardingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Finish first-login setup: verify password, save personal details, set new password."""
    if not user.employee_id:
        raise HTTPException(400, "This account is not linked to an employee profile")
    employee = db.query(Employee).get(user.employee_id)
    if not employee:
        raise HTTPException(404, "Linked employee profile not found")

    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if len(payload.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")

    data = payload.model_dump(
        exclude={"old_password", "new_password"}, exclude_unset=True
    )
    cleaned = {}
    for key, value in data.items():
        cleaned[key] = value.strip() if isinstance(value, str) else value

    if not cleaned.get("first_name"):
        raise HTTPException(400, "First name is required")
    if not cleaned.get("date_of_birth"):
        raise HTTPException(400, "Date of birth is required")

    for key, value in cleaned.items():
        setattr(employee, key, value)

    user.full_name = f"{employee.first_name} {employee.last_name}".strip()
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.profile_completed = True
    db.commit()
    return {"message": "Profile completed", "user": user_to_dict(user)}
