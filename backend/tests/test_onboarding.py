from fastapi import HTTPException

from app.auth import hash_password, verify_password
from app.models import Employee, Role, User
from app.routers import auth as auth_router
from app.schemas import OnboardingRequest
from conftest import sample_db


def _employee_user(db):
    role = Role(name="OnboardingEmployee", permissions=["self.portal"])
    db.add(role)
    db.flush()
    employee = db.query(Employee).first()
    employee.date_of_birth = None
    user = User(
        username="onboarding-test", password_hash=hash_password("current-pass"),
        employee_id=employee.id, full_name="Test User",
        must_change_password=True, profile_completed=False,
    )
    user.roles = [role]
    db.add(user)
    db.flush()
    return user, employee


def test_blank_dob_is_treated_as_missing():
    payload = OnboardingRequest(
        old_password="current-pass", new_password="new-secret-1",
        first_name="Test", date_of_birth="",
    )
    assert payload.date_of_birth is None


def test_onboarding_blank_dob_gives_friendly_error_not_validation_crash():
    _, Session = sample_db()
    db = Session()
    try:
        user, employee = _employee_user(db)
        payload = OnboardingRequest(
            old_password="current-pass", new_password="new-secret-1",
            first_name="Test", date_of_birth="",
        )
        try:
            auth_router.complete_onboarding(payload, user, db)
            assert False, "blank DOB should be rejected"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "date of birth" in str(exc.detail).lower()
        db.refresh(user)
        assert verify_password("current-pass", user.password_hash)
        assert user.must_change_password is True
    finally:
        db.close()


def test_onboarding_completes_with_real_dob():
    _, Session = sample_db()
    db = Session()
    try:
        user, employee = _employee_user(db)
        payload = OnboardingRequest(
            old_password="current-pass", new_password="new-secret-1",
            first_name="Test", last_name="User", date_of_birth="1990-05-06",
        )
        result = auth_router.complete_onboarding(payload, user, db)
        db.refresh(user)
        assert result["user"]["profile_completed"] is True
        assert result["user"]["must_change_password"] is False
        assert verify_password("new-secret-1", user.password_hash)
        assert str(employee.date_of_birth) == "1990-05-06"
    finally:
        db.close()
