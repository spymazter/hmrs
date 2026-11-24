import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP


def round2(value) -> float:
    if value is None:
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_date(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def parse_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime: {value}")


def month_bounds(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def week_bounds(year: int, week: int):
    monday = date.fromisocalendar(year, week, 1)
    return monday, monday + timedelta(days=6)


def minutes_between(start: time, end: time) -> float:
    """Duration across midnight in hours."""
    s = start.hour * 60 + start.minute + start.second / 60
    e = end.hour * 60 + end.minute + end.second / 60
    if e < s:
        e += 24 * 60
    return round((e - s) / 60, 2)


def datetime_to_hours(a: datetime, b: datetime) -> float:
    return round2((b - a).total_seconds() / 3600)


def to_csv(rows: list[dict], filename: str, fieldnames: list[str] | None = None):
    fields = fieldnames or (list(rows[0].keys()) if rows else [])
    if not fields:
        content = ""
    else:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        content = out.getvalue()
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        io.StringIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
