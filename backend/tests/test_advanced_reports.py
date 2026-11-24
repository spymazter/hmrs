import json
from datetime import date

from conftest import sample_db
from openpyxl import load_workbook
from io import BytesIO

from app.services.advanced_reports import REPORT_MAP, build_report, report_metadata
from app.services.attendance_engine import EngineFilters
from app.services.report_formatters import (
    to_csv_bytes, to_json_bytes, to_pdf_bytes, to_xlsx_bytes,
)

START = date(2026, 10, 5)
END = date(2026, 10, 11)


def _payload(db, report_id):
    return build_report(db, report_id, START, END, EngineFilters())


def test_all_fourteen_reports_are_registered():
    assert len(REPORT_MAP) == 14
    assert len(report_metadata()) == 14


def test_every_report_builder_runs_on_sample_data():
    engine, Session = sample_db()
    db = Session()
    try:
        for report_id in REPORT_MAP:
            payload = _payload(db, report_id)
            assert payload["id"] == report_id
            assert isinstance(payload["rows"], list)
            assert payload["columns"]
            assert payload["summary"]["rows"] == len(payload["rows"])
    finally:
        db.close()


def test_monthly_payroll_summary_totals():
    engine, Session = sample_db()
    db = Session()
    try:
        payload = _payload(db, "monthly_payroll_summary")
        ash = next(r for r in payload["rows"] if r["employee_code"] == "SMP001")
        assert ash["present_days"] >= 5
        assert ash["holiday_ot_hours"] > 0
        assert ash["final_payable_days"] > 0
    finally:
        db.close()


def test_muster_roll_has_day_columns_and_codes():
    engine, Session = sample_db()
    db = Session()
    try:
        payload = _payload(db, "muster_roll")
        keys = [column["key"] for column in payload["columns"]]
        assert "day_05" in keys and "day_11" in keys
        ash = next(r for r in payload["rows"] if r["employee_code"] == "SMP001")
        assert ash["day_05"] == "P"
    finally:
        db.close()


def test_exception_reports_detect_cases():
    engine, Session = sample_db()
    db = Session()
    try:
        late = _payload(db, "late_early")
        assert any(r["employee_code"] == "SMP005" for r in late["rows"])

        continuous = _payload(db, "continuous_absence")
        assert any(r["employee_code"] == "SMP006" and r["consecutive_days"] >= 3 for r in continuous["rows"])

        ot = _payload(db, "ot_compoff")
        assert any(r["employee_code"] == "SMP005" and r["weekoff_ot_hours"] == 4.0 for r in ot["rows"])

        deviations = _payload(db, "shift_deviation")
        assert any(r["employee_code"] == "SMP005" for r in deviations["rows"])
    finally:
        db.close()


def test_raw_log_and_audit_reports():
    engine, Session = sample_db()
    db = Session()
    try:
        raw = _payload(db, "raw_punch_log")
        assert raw["rows"]
        assert raw["rows"][0]["punch_direction"] in ("IN", "OUT")
        assert "verification_mode" in raw["columns"][0] or any(
            c["key"] == "verification_mode" for c in raw["columns"]
        )

        audit = _payload(db, "regularization_audit")
        assert any(r["employee_code"] == "SMP003" for r in audit["rows"])
    finally:
        db.close()


def test_all_export_formats():
    engine, Session = sample_db()
    db = Session()
    try:
        payload = _payload(db, "daily_detailed")

        csv_bytes = to_csv_bytes(payload)
        assert csv_bytes.decode("utf-8-sig").startswith("Date,Emp code")

        json_bytes = to_json_bytes(payload)
        parsed = json.loads(json_bytes)
        assert parsed["id"] == "daily_detailed"

        xlsx_bytes = to_xlsx_bytes(payload)
        workbook = load_workbook(BytesIO(xlsx_bytes))
        assert "Report" in workbook.sheetnames
        assert "Summary" in workbook.sheetnames
        assert "Parameters" in workbook.sheetnames
        assert workbook["Report"].freeze_panes == "B2"

        pdf_bytes = to_pdf_bytes(payload)
        assert pdf_bytes.startswith(b"%PDF")
    finally:
        db.close()


def test_filters_apply_to_report():
    engine, Session = sample_db()
    db = Session()
    try:
        payload = build_report(
            db, "daily_basic", START, END,
            EngineFilters(employee_code="SMP001"),
        )
        assert payload["rows"]
        assert {row["employee_code"] for row in payload["rows"]} == {"SMP001"}
        assert payload["params"]
    finally:
        db.close()
