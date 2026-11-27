import calendar
from datetime import date, timedelta

from app.models import Employee, Role, User
from app.routers import employees as employees_router
from conftest import sample_db


def _hr(db):
    role = Role(name="HR", permissions=["employee.view", "employee.edit"])
    db.add(role)
    db.flush()
    user = User(username="birthday-hr", password_hash="x", full_name="HR")
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def test_birthday_portal_lists_today_week_and_month_from_dob():
    _, Session = sample_db()
    db = Session()
    try:
        hr = _hr(db)
        today = date.today()
        sunday = today + timedelta(days=6 - today.weekday())
        month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

        employees = (
            db.query(Employee).filter(Employee.status == "active")
            .order_by(Employee.id).limit(3).all()
        )
        employees[0].date_of_birth = date(1990, today.month, today.day)
        employees[1].date_of_birth = date(1991, sunday.month, sunday.day)
        employees[2].date_of_birth = date(1992, month_end.month, month_end.day)
        db.commit()

        result = employees_router.birthday_portal(db, hr)

        assert result["date"] == today.isoformat()
        assert any(row["employee_id"] == employees[0].id for row in result["today"])
        assert any(row["employee_id"] == employees[1].id for row in result["week"]["items"])
        assert any(row["employee_id"] == employees[2].id for row in result["month"]["items"])
        assert all(row["days_away"] >= 0 for row in result["month"]["items"])
        assert result["today"][0]["employee_code"] == employees[0].employee_code
    finally:
        db.close()


def test_birthday_portal_ignores_missing_dob_and_inactive_staff():
    _, Session = sample_db()
    db = Session()
    try:
        hr = _hr(db)
        employee = db.query(Employee).filter(Employee.status == "active").first()
        employee.date_of_birth = None
        inactive = db.query(Employee).filter(Employee.status != "active").first()
        if inactive:
            inactive.date_of_birth = date(1990, date.today().month, date.today().day)
        db.commit()

        result = employees_router.birthday_portal(db, hr)

        assert result["today"] == []
        assert result["week"]["items"] == []
        assert result["month"]["items"] == []
    finally:
        db.close()
