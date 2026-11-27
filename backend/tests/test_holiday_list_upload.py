import asyncio
import io
from datetime import date

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook, load_workbook

from app.models import Holiday, RestrictedHoliday, Role, User
from app.routers import leaves as leaves_router
from conftest import sample_db


ALL_LEAVE_CODES = [
    "leave.view", "leave.manage", "leave.approve", "leave.manager_approve",
    "leave.verify", "leave.final_approve", "leave.quota.manage", "access.manage",
]


async def _body(response):
    if hasattr(response, "body"):
        return response.body
    iterator = response.body_iterator
    if hasattr(iterator, "__aiter__"):
        chunks = [chunk async for chunk in iterator]
    else:
        chunks = list(iterator)
    return b"".join(
        chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in chunks
    )


def _hr(db):
    role = Role(name="HR", permissions=ALL_LEAVE_CODES)
    db.add(role)
    db.flush()
    user = User(username="hr-holidays", password_hash="x", full_name="HR")
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def _upload(filename, content):
    return UploadFile(filename=filename, file=io.BytesIO(content))


def test_yearly_holiday_template_has_type_column_and_values():
    _, Session = sample_db()
    db = Session()
    try:
        hr = _hr(db)
        csv_response = leaves_router.holiday_list_template("csv", 2026, hr)
        csv_text = asyncio.run(_body(csv_response)).decode()
        assert csv_text.splitlines()[0] == "Date,Name,Type,Year,Reason"
        assert "RH or GH" in csv_text
        assert "gazetted holiday" in csv_text

        xlsx_response = leaves_router.holiday_list_template("xlsx", 2026, hr)
        book = load_workbook(
            io.BytesIO(asyncio.run(_body(xlsx_response))), read_only=True, data_only=True
        )
        assert next(book.active.iter_rows(values_only=True)) == tuple(
            leaves_router.HOLIDAY_LIST_HEADERS
        )
    finally:
        db.close()


def test_upload_routes_rh_and_compulsory_holidays_without_deleting_rows():
    _, Session = sample_db()
    db = Session()
    try:
        hr = _hr(db)
        content = (
            "Date,Name,Type,Year,Reason\n"
            "02.01.2026,Republic Day,Holiday,2026,Compulsory\n"
            "07.01.2026,Shakambahri Vrutha,RH,2026,Optional\n"
            "10.01.2026,Thyagaraja Aradhane,Compulsory Holiday,2026,\n"
            "20..04.2026,Basava Jayanthi,RH,2026,\n"
            "27.11.2025,Wrong year,RH,2025,Skip me\n"
        ).encode()
        result = asyncio.run(leaves_router.upload_holiday_list(
            2026, _upload("holidays.csv", content), db, hr
        ))
        assert result["year"] == 2026
        assert result["rh_created"] == 2
        assert result["holiday_created"] == 2
        assert result["created"] == 4
        assert result["updated"] == 0
        assert len(result["skipped"]) == 1
        assert "date must be in 2026" in result["skipped"][0]

        rh_names = {row.name for row in db.query(RestrictedHoliday).filter_by(year=2026).all()}
        assert {"Shakambahri Vrutha", "Basava Jayanthi"}.issubset(rh_names)
        holiday_names = {row.name for row in db.query(Holiday).all()}
        assert {"Republic Day", "Thyagaraja Aradhane"}.issubset(holiday_names)

        update = (
            "Date,Name,Type,Year,Reason\n"
            "07.01.2026,Shakambahri Vrutha Updated,RH,2026,Optional\n"
        ).encode()
        again = asyncio.run(leaves_router.upload_holiday_list(
            2026, _upload("update.csv", update), db, hr
        ))
        assert again["rh_created"] == 0
        assert again["rh_updated"] == 1
        assert again["created"] == 0

        remaining = {row.name for row in db.query(Holiday).all()}
        assert {"Republic Day", "Thyagaraja Aradhane"}.issubset(remaining)
        assert db.query(RestrictedHoliday).filter_by(year=2026).count() == 2
    finally:
        db.close()


def test_xlsx_upload_and_legacy_rh_only_file():
    _, Session = sample_db()
    db = Session()
    try:
        hr = _hr(db)
        book = Workbook()
        sheet = book.active
        sheet.append(leaves_router.HOLIDAY_LIST_HEADERS)
        sheet.append([date(2026, 3, 21), "Holi RH", "RH", 2026, "Optional"])
        output = io.BytesIO()
        book.save(output)
        result = asyncio.run(leaves_router.upload_holiday_list(
            2026, _upload("holidays.xlsx", output.getvalue()), db, hr
        ))
        assert result["rh_created"] == 1
        assert result["skipped"] == []

        legacy = "Date,Name,Year,Reason\n15.08.2026,Independence Day RH,2026,\n".encode()
        legacy_result = asyncio.run(leaves_router.upload_holiday_list(
            2026, _upload("old_rh.csv", legacy), db, hr
        ))
        assert legacy_result["rh_created"] == 1
        assert legacy_result["skipped"] == []

        with pytest.raises(HTTPException, match="Invalid year"):
            asyncio.run(leaves_router.upload_holiday_list(
                1999, _upload("bad.csv", legacy), db, hr
            ))
    finally:
        db.close()


def test_dedicated_rh_and_gh_templates():
    _, Session = sample_db()
    db = Session()
    try:
        hr = _hr(db)
        rh_text = asyncio.run(_body(
            leaves_router.holiday_list_template("csv", 2026, hr, "RH")
        )).decode()
        assert rh_text.splitlines()[0] == "Date,Name,Year,Reason"
        assert "restricted holiday" in rh_text

        gh_text = asyncio.run(_body(
            leaves_router.holiday_list_template("csv", 2026, hr, "GH")
        )).decode()
        assert gh_text.splitlines()[0] == "Date,Name,Year,Reason"
        assert "gazetted holiday" in gh_text

        combined = asyncio.run(_body(
            leaves_router.holiday_list_template("csv", 2026, hr)
        )).decode()
        assert "Type" in combined.splitlines()[0]
        assert "RH or GH" in combined
        assert "GH = gazetted holiday" in combined
    finally:
        db.close()


def test_dedicated_rh_and_gh_uploads_and_gh_type_code():
    _, Session = sample_db()
    db = Session()
    try:
        hr = _hr(db)
        rh = asyncio.run(leaves_router.upload_holiday_list(
            2026,
            _upload("rh.csv", b"Date,Name,Year,Reason\n05.01.2026,Diwali RH,2026,Optional\n"),
            db, hr, "RH",
        ))
        assert rh["rh_created"] == 1
        assert rh["holiday_created"] == 0
        assert rh["skipped"] == []

        gh = asyncio.run(leaves_router.upload_holiday_list(
            2026,
            _upload("gh.csv", b"Date,Name\n15.01.2026,Republic Day\n"),
            db, hr, "GH",
        ))
        assert gh["holiday_created"] == 1
        assert gh["rh_created"] == 0
        assert gh["skipped"] == []

        combined = asyncio.run(leaves_router.upload_holiday_list(
            2026,
            _upload("combined.csv", b"Date,Name,Type,Year\n15.01.2026,Republic Day,GH,2026\n"),
            db, hr,
        ))
        assert combined["holiday_updated"] == 1
        assert combined["rh_created"] == 0
        assert db.query(Holiday).filter_by(holiday_date=date(2026, 1, 15)).count() == 1
    finally:
        db.close()
