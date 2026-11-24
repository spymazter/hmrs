from datetime import date

from conftest import sample_db
from app.services.attendance_engine import (
    AttendanceEngine, EngineConfig, EngineFilters, debounce_punches, pair_punches,
)


def _lookup(calculations, code, day):
    return next(c for c in calculations if c.employee_code == code and c.date == day)


def test_strict_pairing_sums_sessions_and_deducts_break():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP001", "2026-10-06")
        assert calc.pair_count == 2
        assert calc.net_hours == 8.0
        assert calc.break_hours == 1.0
        assert calc.status_code == "P"
    finally:
        db.close()


def test_first_last_mode_uses_full_span():
    engine_db, Session = sample_db()
    db = Session()
    try:
        config = EngineConfig(pairing_mode="first_last")
        calculations = AttendanceEngine(db, config).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP001", "2026-10-06")
        assert calc.net_hours == 9.0
        assert calc.break_hours == 0.0
    finally:
        db.close()


def test_debounce_ignores_duplicate_in_punch():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP005", "2026-10-09")
        assert calc.punch_count == 2
        assert calc.all_punches == "08:30, 19:00"
    finally:
        db.close()


def test_night_shift_cross_midnight_attributed_to_start_date():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP002", "2026-10-05")
        assert calc.shift_type == "night"
        assert calc.first_in == "22:00"
        assert calc.last_out == "06:00"
        assert calc.net_hours == 8.0
        assert calc.status_code == "P"
    finally:
        db.close()


def test_flexi_shift_ignores_late_but_checks_target_hours():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP007", "2026-10-08")
        assert calc.shift_type == "flexi"
        assert calc.late_by == 0
        assert calc.net_hours == 9.25
        assert calc.status_code == "P"
    finally:
        db.close()


def test_regular_ot_threshold_and_rounding():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP005", "2026-10-09")
        assert calc.pre_shift_ot_hours == 0.5
        assert calc.post_shift_ot_hours == 1.0
        assert calc.regular_ot_hours == 1.5
    finally:
        db.close()


def test_ot_below_threshold_is_ignored():
    from datetime import datetime

    from app.services.attendance_engine import NormalizedPunch

    config = EngineConfig(ot_min_minutes=30, ot_round_minutes=15)
    punches = [
        NormalizedPunch(1, 1, datetime(2026, 10, 9, 9, 0), "in"),
        NormalizedPunch(2, 1, datetime(2026, 10, 9, 18, 20), "out"),
    ]
    sessions, net_hours, _ = pair_punches(punches, "strict")
    ot_minutes = 20
    assert config.ot_min_minutes == 30
    assert net_hours == 9.33
    assert len(sessions) == 1


def test_leave_od_and_regularization_overlay():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        leave = _lookup(calculations, "SMP004", "2026-10-06")
        od = _lookup(calculations, "SMP008", "2026-10-08")
        regularized = _lookup(calculations, "SMP003", "2026-10-08")
        assert leave.status_code == "CL" and leave.leave_paid
        assert od.status_code == "OD"
        assert regularized.status_code == "P" and regularized.source == "regularization"
    finally:
        db.close()


def test_holiday_and_weekoff_ot_with_comp_off():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        holiday = _lookup(calculations, "SMP001", "2026-10-07")
        weekoff = _lookup(calculations, "SMP005", "2026-10-11")
        assert holiday.status_code == "HL"
        assert holiday.holiday_ot_hours > 0
        assert weekoff.status_code == "WO"
        assert weekoff.weekoff_ot_hours == 4.0
        assert weekoff.comp_off_earned == 0.5
    finally:
        db.close()


def test_missed_punch_status():
    engine_db, Session = sample_db()
    db = Session()
    try:
        # Disable the approved regularization so the raw single punch is visible.
        from app.models import Regularization

        db.query(Regularization).delete()
        db.commit()
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP003", "2026-10-08")
        assert calc.status_code == "MIS"
        assert calc.pair_count == 0
    finally:
        db.close()


def test_sandwich_rule_marks_intervening_holiday_absent():
    engine_db, Session = sample_db()
    db = Session()
    try:
        config = EngineConfig(sandwich_rule=True)
        calculations = AttendanceEngine(db, config).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP006", "2026-10-07")
        assert calc.status_code == "A"
        assert calc.is_sandwich is True
    finally:
        db.close()


def test_rostered_shift_overrides_employee_default():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(date(2026, 10, 5), date(2026, 10, 11))
        calc = _lookup(calculations, "SMP009", "2026-10-08")
        assert calc.shift == "Rotation B"
        assert calc.first_in == "14:00"
        assert calc.status_code == "P"
    finally:
        db.close()


def test_filters_by_employee_code():
    engine_db, Session = sample_db()
    db = Session()
    try:
        calculations = AttendanceEngine(db).calculate_range(
            date(2026, 10, 5), date(2026, 10, 11),
            EngineFilters(employee_code="SMP001"),
        )
        assert calculations and {c.employee_code for c in calculations} == {"SMP001"}
    finally:
        db.close()
