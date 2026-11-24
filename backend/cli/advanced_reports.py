"""CLI for the advanced Time & Attendance reporting engine.

Examples::

    python -m cli.advanced_reports --report daily_basic --from 2026-10-01 \
        --to 2026-10-31 --dept 25 --format xlsx --output /tmp/oct.xlsx
    python -m cli.advanced_reports --report monthly_payroll_summary \
        --format json --employee-code DEV-111
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.models import Department, Designation, Location, Shift
from app.services.advanced_reports import REPORT_MAP, build_report, report_metadata
from app.services.attendance_engine import EngineFilters
from app.services.report_formatters import (
    to_csv_bytes, to_json_bytes, to_pdf_bytes, to_xlsx_bytes,
)
from app.utils import parse_date

FORMATTERS = {
    "xlsx": to_xlsx_bytes,
    "csv": to_csv_bytes,
    "json": to_json_bytes,
    "pdf": to_pdf_bytes,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HRMS advanced attendance reports")
    parser.add_argument("--report", default="daily_basic", help="Report id (see --list-reports)")
    parser.add_argument("--from", dest="from_date", help="From date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="To date YYYY-MM-DD")
    parser.add_argument("--dept", help="Department id or name")
    parser.add_argument("--location", help="Location id or name")
    parser.add_argument("--designation", help="Designation id or name")
    parser.add_argument("--shift", help="Shift id or name")
    parser.add_argument("--employee-code", help="Employee code (partial match)")
    parser.add_argument("--format", default="table", choices=[*FORMATTERS, "table"])
    parser.add_argument("--output", help="Write bytes to this file instead of stdout")
    parser.add_argument("--list-reports", action="store_true")
    return parser


def _resolve_id(db, model, value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    row = db.query(model).filter(model.name.ilike(f"%{value}%")).first()
    return row.id if row else None


def _print_table(payload: dict) -> None:
    columns = payload["columns"]
    headers = [column["label"] for column in columns]
    rows = [[
        "" if row.get(column["key"]) is None else str(row.get(column["key"]))
        for column in columns
    ] for row in payload["rows"]]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], min(len(value), 32))
    line = " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    print(line)
    print("-+-".join("-" * width for width in widths))
    for row in rows[:200]:
        print(" | ".join(value.ljust(widths[index])[: widths[index]] for index, value in enumerate(row)))
    if len(rows) > 200:
        print(f"... {len(rows) - 200} more rows")
    summary = payload.get("summary") or {}
    print(f"\nRows: {summary.get('rows', len(rows))} · {payload['title']} · {payload['period_label']}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.list_reports:
        for item in report_metadata():
            print(f"{item['id']:26} {item['category']:22} {item['name']}")
        return 0

    if args.report not in REPORT_MAP:
        print(f"Unknown report: {args.report}", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        start = parse_date(args.from_date, date.today().replace(day=1))
        end = parse_date(args.to_date, date.today())
        if not start or not end or start > end:
            print("Invalid date range", file=sys.stderr)
            return 2
        filters = EngineFilters(
            department_id=_resolve_id(db, Department, args.dept),
            location_id=_resolve_id(db, Location, args.location),
            designation_id=_resolve_id(db, Designation, args.designation),
            shift_id=_resolve_id(db, Shift, args.shift),
            employee_code=args.employee_code,
        )
        payload = build_report(db, args.report, start, end, filters)
        if args.format == "table":
            _print_table(payload)
            return 0
        content = FORMATTERS[args.format](payload)
        if args.output:
            Path(args.output).write_bytes(content)
            print(f"Wrote {args.output} ({len(content):,} bytes)")
        else:
            sys.stdout.buffer.write(content)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
