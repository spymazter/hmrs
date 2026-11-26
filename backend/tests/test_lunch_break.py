from datetime import datetime
from types import SimpleNamespace

from conftest import sample_db
from app.routers import lunch_break
from app.schemas import LunchBreakConfigIn
from app.services.attendance_engine import (
    LunchBreakConfig, get_lunch_break_config, pair_punches,
)


def _four_punches():
    return [
        # Device labels the middle punches as IN/OUT, but their positions are
        # IN, Lunch OUT, Lunch IN, Exit.
        (1, 1, datetime(2026, 11, 25, 9, 0), "in"),
        (2, 1, datetime(2026, 11, 25, 13, 56), "in"),
        (3, 1, datetime(2026, 11, 25, 15, 6), "out"),
        (4, 1, datetime(2026, 11, 25, 18, 4), "out"),
    ]


def _punches():
    from app.services.attendance_engine import NormalizedPunch
    return [NormalizedPunch(*row) for row in _four_punches()]


def test_four_punch_sequence_deducts_configured_lunch():
    sessions, net_hours, break_hours = pair_punches(
        _punches(), "strict", lunch_minutes=60
    )
    assert net_hours == 8.07
    assert break_hours == 1.0
    assert len(sessions) == 2
    assert [s["in"]["time"] for s in sessions] == ["09:00:00", "15:06:00"]
    assert [s["out"]["time"] for s in sessions] == ["13:56:00", "18:04:00"]


def test_lunch_disabled_preserves_legacy_pairing():
    sessions, net_hours, break_hours = pair_punches(_punches(), "strict", lunch_minutes=0)
    assert net_hours == 9.07
    assert break_hours == 0.0
    assert len(sessions) == 1


def test_custom_lunch_duration_is_used():
    _, net_hours, break_hours = pair_punches(
        _punches(), "strict", lunch_minutes=90
    )
    assert net_hours == 7.57
    assert break_hours == 1.5


def test_invalid_lunch_order_falls_back_to_standard_pairing():
    from app.services.attendance_engine import NormalizedPunch

    punches = [
        NormalizedPunch(1, 1, datetime(2026, 11, 25, 9, 0), "in"),
        NormalizedPunch(2, 1, datetime(2026, 11, 25, 18, 0), "in"),
        NormalizedPunch(3, 1, datetime(2026, 11, 25, 10, 0), "out"),
        NormalizedPunch(4, 1, datetime(2026, 11, 25, 19, 0), "out"),
    ]
    _, net_hours, break_hours = pair_punches(punches, "strict", lunch_minutes=60)
    assert break_hours == 0.0
    assert net_hours > 0


def test_config_defaults_and_shift_override():
    config = LunchBreakConfig.from_dict(None)
    assert config.enabled is True
    assert config.duration_minutes == 60
    assert config.sequence == ["IN", "Lunch OUT", "Lunch IN", "Exit"]
    assert config.effective_minutes(None) == 60
    assert config.effective_minutes(SimpleNamespace(break_minutes=90)) == 90
    assert LunchBreakConfig.from_dict({"enabled": False}).effective_minutes(None) == 0


def test_config_api_roundtrip_and_effective_shift_minutes():
    _, Session = sample_db()
    db = Session()
    try:
        initial = lunch_break.get_config(db)
        assert initial["duration_minutes"] == 60
        assert initial["sequence"] == ["IN", "Lunch OUT", "Lunch IN", "Exit"]

        updated = lunch_break.update_config(
            LunchBreakConfigIn(enabled=True, duration_minutes=45), db=db
        )
        assert updated["duration_minutes"] == 45
        assert get_lunch_break_config(db).duration_minutes == 45
        assert all(row["effective_minutes"] == 45 for row in updated["shifts"])
    finally:
        db.close()
