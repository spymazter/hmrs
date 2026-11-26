import csv
import io

from openpyxl import load_workbook

from app.models import Employee, Role, User
from app.routers import employees as employees_router
from conftest import sample_db


def _admin(db):
    admin = User(
        username="export-admin", password_hash="x",
        roles=[Role(name="Admin", permissions=["employee.view"])],
    )
    db.add(admin)
    db.commit()
    return admin


def test_excel_export_includes_every_employee():
    _, Session = sample_db()
    db = Session()
    try:
        admin = _admin(db)
        total = db.query(Employee).count()

        response = employees_router.export_employees("", None, None, "xlsx", db, admin)

        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == str(total)
        assert "employees_" in response.headers["Content-Disposition"]
        sheet = load_workbook(io.BytesIO(response.body), read_only=True, data_only=True).active
        rows = list(sheet.values)
        headers = employees_router.EMPLOYEE_EXPORT_HEADERS
        assert rows[0] == tuple(headers)
        assert len(rows) - 1 == total
        code_col = headers.index("Employee Code")
        dept_col = headers.index("Department")
        codes = {row[code_col] for row in rows[1:]}
        assert {"SMP001", "SMP009"}.issubset(codes)
        assert any(row[dept_col] == "Operations" for row in rows[1:])
    finally:
        db.close()


def test_csv_export_honours_the_current_filters():
    _, Session = sample_db()
    db = Session()
    try:
        admin = _admin(db)

        response = employees_router.export_employees("SMP001", None, None, "csv", db, admin)

        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "1"
        assert response.headers["Content-Disposition"].endswith('.csv"')
        rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8-sig"))))
        assert len(rows) == 1
        assert rows[0]["Employee Code"] == "SMP001"
        assert rows[0]["Full Name"] == "Asha Sample"
    finally:
        db.close()
