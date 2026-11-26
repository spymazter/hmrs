from datetime import date
from types import SimpleNamespace

from conftest import sample_db
from app.routers import attendance
from app.services.attendance import recompute_records


def test_daily_records_are_sorted_by_employee_name():
    _, Session = sample_db()
    db = Session()
    try:
        recompute_records(db, date(2026, 10, 5), date(2026, 10, 11))
        result = attendance.list_records(
            from_date="2026-10-06", to_date="2026-10-06",
            limit=500, db=db,
            user=SimpleNamespace(employee_id=None, roles=[], groups=[]),
        )
        names = [item.employee_name for item in result["items"]]
        assert names
        assert names == sorted(names, key=str.casefold)
        assert names[0] == "Asha Sample"
    finally:
        db.close()
