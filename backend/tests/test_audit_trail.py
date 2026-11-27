from datetime import date, datetime, timedelta

from app.models import AuditLog, Employee, PayrollPeriod, Payslip, Role, User
from app.routers import audit
from app.schemas import PayslipOut
from app.services.audit import log_system_action
from conftest import sample_db


def _admin(db):
    role = Role(name="AuditAdmin", permissions=["access.manage"])
    db.add(role)
    db.flush()
    user = User(username="audit-admin", password_hash="x", full_name="Audit Admin")
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def test_audit_logs_are_newest_first_and_filterable():
    _, Session = sample_db()
    db = Session()
    try:
        admin = _admin(db)
        other = User(username="hr-user", password_hash="x", full_name="HR User")
        db.add(other)
        db.flush()

        db.add_all([
            AuditLog(
                user_id=admin.id,
                action="POST /api/employees",
                entity="employees",
                entity_id=7,
                details={"body": {"first_name": "Asha"}},
                created_at=datetime.now() - timedelta(days=2),
            ),
            AuditLog(
                user_id=other.id,
                action="leave.final_approved",
                entity="leave_request",
                entity_id=12,
                details={"status": "approved"},
                created_at=datetime.now() - timedelta(days=1),
            ),
        ])
        db.commit()

        rows = audit.list_audit_logs(db=db, _=admin)
        assert [row.action for row in rows] == ["leave.final_approved", "POST /api/employees"]
        assert rows[0].username == "hr-user"
        assert rows[1].full_name == "Audit Admin"

        filtered = audit.list_audit_logs(db=db, _=admin, entity="employees")
        assert len(filtered) == 1
        assert filtered[0].entity_id == 7

        by_user = audit.list_audit_logs(db=db, _=admin, user_id=other.id)
        assert len(by_user) == 1
        assert by_user[0].action == "leave.final_approved"
    finally:
        db.close()


def test_payslip_exposes_period_month_and_year():
    _, Session = sample_db()
    db = Session()
    try:
        period = PayrollPeriod(
            name="October 2026", month=10, year=2026,
            start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
        )
        db.add(period)
        db.flush()
        employee = db.query(Employee).first()
        slip = Payslip(employee_id=employee.id, period_id=period.id)
        db.add(slip)
        db.commit()

        payload = PayslipOut.model_validate(slip)
        assert payload.period_month == 10
        assert payload.period_year == 2026
        assert payload.period_name == "October 2026"
    finally:
        db.close()


def test_system_actions_are_logged_without_a_user():
    _, Session = sample_db()
    db = Session()
    try:
        admin = _admin(db)
        log_system_action(
            db,
            "system.device_sync",
            "punch_log",
            details={"new_punches": 3, "device_id": 1},
        )
        db.commit()

        rows = audit.list_audit_logs(db=db, _=admin)
        assert len(rows) == 1
        assert rows[0].username is None
        assert rows[0].action == "system.device_sync"
        assert rows[0].details["new_punches"] == 3
    finally:
        db.close()
