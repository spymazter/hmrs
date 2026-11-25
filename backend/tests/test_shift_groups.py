from datetime import date

from conftest import sample_db
from app.models import Employee, Shift, ShiftGroup
from app.routers.shift_groups import create_group, delete_group, map_employees, update_group
from app.schemas import ShiftGroupCreate, ShiftGroupEmployeeMapping, ShiftGroupUpdate
from app.services.attendance_engine import AttendanceData, AttendanceEngine, EngineFilters


def test_group_crud_maps_employees_and_shifts():
    _, Session = sample_db()
    db = Session()
    try:
        shift_ids = [s.id for s in db.query(Shift).order_by(Shift.id).limit(2).all()]
        employee_ids = [e.id for e in db.query(Employee).order_by(Employee.id).limit(3).all()]

        created = create_group(
            ShiftGroupCreate(name="Ops rotation", code="OPS", shift_ids=shift_ids,
                             employee_ids=employee_ids[:1]), db, None,
        )
        assert created.shift_ids == shift_ids
        assert created.employee_ids == employee_ids[:1]
        assert db.get(Employee, employee_ids[0]).shift_group_id == created.id

        mapped = map_employees(
            created.id, ShiftGroupEmployeeMapping(employee_ids=employee_ids), db, None,
        )
        assert mapped.employee_ids == employee_ids
        assert all(db.get(Employee, i).shift_group_id == created.id for i in employee_ids)

        updated = update_group(
            created.id, ShiftGroupUpdate(name="Ops rotation 2", shift_ids=[shift_ids[0]]), db, None,
        )
        assert updated.name == "Ops rotation 2"
        assert updated.shift_ids == [shift_ids[0]]

        delete_group(created.id, db, None)
        assert db.query(ShiftGroup).count() == 0
        assert all(db.get(Employee, i).shift_group_id is None for i in employee_ids)
    finally:
        db.close()


def test_mapped_group_controls_rotation_and_shift_filter():
    _, Session = sample_db()
    db = Session()
    try:
        employee = db.query(Employee).filter(Employee.employee_code == "SMP009").one()
        general = db.query(Shift).filter(Shift.name == "General").one()
        group = ShiftGroup(name="Day group")
        db.add(group)
        db.flush()
        group.shifts = [general]
        group.employees = [employee]
        db.commit()

        # No roster on this day: the mapped group wins over legacy rotation_group.
        data = AttendanceData(db, date(2026, 10, 5), date(2026, 10, 11))
        resolved = AttendanceEngine(db)._resolve_shift(employee, date(2026, 10, 6), data)
        assert resolved.name == "General"

        # A shift filter also includes employees mapped through the group.
        rows = AttendanceEngine(db).calculate_range(
            date(2026, 10, 5), date(2026, 10, 11), EngineFilters(shift_id=general.id),
        )
        assert "SMP009" in {row.employee_code for row in rows}
    finally:
        db.close()
