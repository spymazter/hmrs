from app.auth import hash_password, verify_password
from app.models import Role, User
from app.routers import access
from app.schemas import UserUpdate
from conftest import sample_db


def _admin(db):
    role = Role(name="AccessAdmin", permissions=["access.manage"])
    db.add(role)
    db.flush()
    user = User(username="access-admin", password_hash=hash_password("admin-pass"), full_name="Admin")
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def test_admin_password_reset_updates_hash_for_employee_user():
    _, Session = sample_db()
    db = Session()
    try:
        admin = _admin(db)
        target = User(
            username="prabhushankar-test", password_hash=hash_password("old-password"),
            full_name="Prabhu", employee_id=78, must_change_password=True,
            profile_completed=False,
        )
        db.add(target)
        db.commit()

        access.update_user(target.id, UserUpdate(password=""), db, admin)
        db.refresh(target)
        assert verify_password("old-password", target.password_hash)

        access.update_user(target.id, UserUpdate(password="new-secret-123"), db, admin)
        db.refresh(target)
        assert verify_password("new-secret-123", target.password_hash)
        assert not verify_password("old-password", target.password_hash)
        assert target.must_change_password is True
    finally:
        db.close()


def test_password_is_not_needed_when_editing_other_fields():
    _, Session = sample_db()
    db = Session()
    try:
        admin = _admin(db)
        target = User(username="no-password-change", password_hash=hash_password("keep-me"), full_name="Old")
        db.add(target)
        db.commit()

        access.update_user(target.id, UserUpdate(full_name="Updated"), db, admin)
        db.refresh(target)
        assert target.full_name == "Updated"
        assert verify_password("keep-me", target.password_hash)
    finally:
        db.close()
