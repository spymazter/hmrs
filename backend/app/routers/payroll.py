import csv
import io
import os
import re
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from app.auth import payroll_scoped_employee_id, require
from app.config import settings
from app.database import get_db
from app.models import Employee, PayrollPeriod, Payslip, SalaryStructure
from app.schemas import (
    PayrollPeriodCreate, PayrollPeriodOut, PayrollPeriodUpdate, PayslipDownloadRequest,
    PayslipOut, ProcessPayrollRequest, SalaryStructureCreate, SalaryStructureOut,
    SalaryStructureUpdate,
)
from app.services.payroll import process_payroll
from app.utils import month_bounds, parse_date, round2, to_csv

router = APIRouter(prefix="/api/payroll", tags=["Payroll"])


# Salary structure import/export ---------------------------------------------
SALARY_HEADERS = [
    "Employee Code", "Employee Name", "Employee ID", "Effective From",
    "Basic", "HRA", "Special Allowance", "Conveyance",
    "Provident Fund", "ESI", "Professional Tax", "Income Tax",
    "Other Earnings", "Other Deductions",
]

COLUMN_ALIASES = {
    "employeecode": "employee_code", "empcode": "employee_code", "code": "employee_code",
    "deviceuserid": "employee_code", "deviceid": "employee_code", "biometricid": "employee_code",
    "enrollmentno": "employee_code", "uid": "employee_code",
    "employeeid": "employee_id", "empid": "employee_id",
    "employeename": "employee_name", "name": "employee_name",
    "effectivefrom": "effective_from", "effectivedate": "effective_from",
    "fromdate": "effective_from", "date": "effective_from",
    "basic": "basic", "basicsalary": "basic", "basicpay": "basic",
    "hra": "hra", "houserentallowance": "hra", "houserent": "hra",
    "specialallowance": "special_allowance", "splallowance": "special_allowance",
    "special": "special_allowance",
    "conveyance": "conveyance", "conveyanceallowance": "conveyance",
    "transportallowance": "conveyance",
    "providentfund": "provident_fund", "pf": "provident_fund", "provident": "provident_fund",
    "esi": "esi", "employerstateinsurance": "esi",
    "professionaltax": "professional_tax", "pt": "professional_tax",
    "incometax": "income_tax", "tds": "income_tax", "tax": "income_tax",
    "otherearnings": "other_earnings", "allowances": "other_earnings",
    "otherdeductions": "other_deductions", "deductions": "other_deductions",
}

NUMERIC_FIELDS = (
    "basic", "hra", "special_allowance", "conveyance",
    "provident_fund", "esi", "professional_tax", "income_tax",
)


def _norm(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _number(value) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return round2(value)
    text = str(value).strip().replace(",", "").replace("₹", "").replace("Rs.", "").strip()
    if not text:
        return 0.0
    return round2(float(text))


def _effective_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return parse_date(value)
    except (ValueError, TypeError):
        text = str(value).strip()
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y"):
            try:
                return datetime.strptime(text[:20], fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Invalid effective date: {value}")


def _parse_items(value) -> list[dict]:
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    items = []
    for part in str(value).replace("|", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, amount = part.split(":", 1)
        elif "=" in part:
            name, amount = part.split("=", 1)
        else:
            continue
        items.append({"name": name.strip(), "amount": _number(amount)})
    return items


def _serialize_items(value) -> str:
    if not isinstance(value, list):
        return ""
    return "; ".join(
        f"{item.get('name', '')}: {item.get('amount', 0)}"
        for item in value if isinstance(item, dict)
    )


def _structure_rows(db: Session, include_demo: bool = False) -> list[dict]:
    query = db.query(SalaryStructure).join(Employee)
    if not include_demo:
        query = query.filter(Employee.employee_code.like("DEV-%"))
    rows = []
    for item in query.order_by(Employee.employee_code).all():
        rows.append({
            "Employee Code": item.employee_code or "",
            "Employee Name": item.employee_name or "",
            "Employee ID": item.employee_id,
            "Effective From": item.effective_from.isoformat() if item.effective_from else "",
            "Basic": item.basic or 0,
            "HRA": item.hra or 0,
            "Special Allowance": item.special_allowance or 0,
            "Conveyance": item.conveyance or 0,
            "Provident Fund": item.provident_fund or 0,
            "ESI": item.esi or 0,
            "Professional Tax": item.professional_tax or 0,
            "Income Tax": item.income_tax or 0,
            "Other Earnings": _serialize_items(item.other_earnings),
            "Other Deductions": _serialize_items(item.other_deductions),
        })
    return rows


def _download_rows(rows: list[dict], filename: str, file_format: str = "csv"):
    if file_format == "xlsx":
        book = Workbook()
        sheet = book.active
        sheet.title = "Salary structures"
        sheet.append(SALARY_HEADERS)
        for row in rows:
            sheet.append([row.get(header, "") for header in SALARY_HEADERS])
        output = io.BytesIO()
        book.save(output)
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
        )
    return to_csv(rows, f"{filename}.csv")


async def _read_upload(file: UploadFile) -> list[dict]:
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = book.active
        values = list(sheet.iter_rows(values_only=True))
        if not values:
            return []
        headers = [str(v).strip() if v is not None else "" for v in values[0]]
        return [
            dict(zip(headers, row))
            for row in values[1:]
            if any(v not in (None, "") for v in row)
        ]
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [
            row for row in csv.DictReader(io.StringIO(text))
            if any(v not in (None, "") for v in row.values())
        ]
    raise HTTPException(400, "Unsupported file type — upload a .csv or .xlsx file")


def _normalize_row(row: dict) -> dict:
    result = {}
    for key, value in row.items():
        canonical = COLUMN_ALIASES.get(_norm(key))
        if canonical and value is not None:
            result[canonical] = value
    return result


def _find_employee(db: Session, row: dict):
    code = str(row.get("employee_code") or "").strip()
    emp_id = str(row.get("employee_id") or "").strip()
    if code:
        employee = db.query(Employee).filter(Employee.employee_code.ilike(code)).first()
        if employee:
            return employee
        if code.isdigit():
            uid = str(int(code))
            employee = db.query(Employee).filter(Employee.device_user_id == uid).first()
            if employee:
                return employee
            employee = db.query(Employee).filter(Employee.employee_code == f"DEV-{uid}").first()
            if employee:
                return employee
    if emp_id.isdigit():
        return db.query(Employee).filter(Employee.id == int(emp_id)).first()
    return None


# Periods -------------------------------------------------------------------
@router.get("/periods", response_model=list[PayrollPeriodOut])
def list_periods(db: Session = Depends(get_db), _=Depends(require("payroll.view", "payslip.view"))):
    return db.query(PayrollPeriod).order_by(PayrollPeriod.year.desc(), PayrollPeriod.month.desc()).all()


@router.post("/periods", response_model=PayrollPeriodOut, status_code=201)
def create_period(payload: PayrollPeriodCreate, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    if db.query(PayrollPeriod).filter(PayrollPeriod.month == payload.month, PayrollPeriod.year == payload.year).first():
        raise HTTPException(400, "A payroll period already exists for this month")
    period = PayrollPeriod(**payload.model_dump())
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


@router.post("/periods/from-month")
def create_period_from_month(month: int, year: int, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    if db.query(PayrollPeriod).filter(PayrollPeriod.month == month, PayrollPeriod.year == year).first():
        raise HTTPException(400, "A payroll period already exists for this month")
    start, end = month_bounds(year, month)
    period = PayrollPeriod(name=start.strftime("%B %Y"), month=month, year=year, start_date=start, end_date=end)
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


@router.put("/periods/{period_id}", response_model=PayrollPeriodOut)
def update_period(period_id: int, payload: PayrollPeriodUpdate, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    period = db.query(PayrollPeriod).get(period_id)
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if payload.status not in ("draft", "processed", "paid"):
        raise HTTPException(400, "Invalid status")
    period.status = payload.status
    db.commit()
    db.refresh(period)
    return period


# Salary structures ---------------------------------------------------------
@router.get("/structures", response_model=list[SalaryStructureOut])
def list_structures(
    employee_id: int | None = None,
    include_demo: bool = False,
    db: Session = Depends(get_db),
    _=Depends(require("payroll.view")),
):
    query = db.query(SalaryStructure).join(Employee)
    if employee_id:
        query = query.filter(SalaryStructure.employee_id == employee_id)
    if not include_demo:
        query = query.filter(Employee.employee_code.like("DEV-%"))
    return query.all()


@router.post("/structures", response_model=SalaryStructureOut, status_code=201)
def create_structure(payload: SalaryStructureCreate, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    existing = db.query(SalaryStructure).filter(
        SalaryStructure.employee_id == payload.employee_id,
        SalaryStructure.effective_from == payload.effective_from,
    ).first()
    if existing:
        raise HTTPException(400, "A salary structure already exists with this effective date")
    structure = SalaryStructure(**payload.model_dump())
    db.add(structure)
    db.commit()
    db.refresh(structure)
    return structure


@router.get("/structures/template")
def download_structure_template(
    format: str = "csv",
    _=Depends(require("payroll.view", "payroll.manage")),
):
    """Download an empty salary structure template."""
    rows = [{header: "" for header in SALARY_HEADERS}]
    return _download_rows(rows, "salary_structures_template", format)


@router.get("/structures/export")
def export_structures(
    format: str = "csv",
    include_demo: bool = False,
    db: Session = Depends(get_db),
    _=Depends(require("payroll.view", "payroll.manage")),
):
    """Export current salary structures (live DEV-* records by default)."""
    return _download_rows(_structure_rows(db, include_demo), "salary_structures", format)


@router.post("/structures/import")
async def import_structures(
    file: UploadFile = File(...),
    replace_existing: bool = Form(False),
    db: Session = Depends(get_db),
    _=Depends(require("payroll.manage")),
):
    """Upsert salary structures from CSV/XLSX. Rows are matched by employee code or device ID."""
    raw_rows = await _read_upload(file)
    removed = 0
    if replace_existing:
        live_ids = [
            emp.id for emp in db.query(Employee)
            .filter(Employee.employee_code.like("DEV-%")).all()
        ]
        if live_ids:
            removed = db.query(SalaryStructure).filter(
                SalaryStructure.employee_id.in_(live_ids)
            ).delete(synchronize_session=False)
        db.flush()

    created = 0
    updated = 0
    errors: list[str] = []

    for index, raw in enumerate(raw_rows, start=2):
        row = _normalize_row(raw)
        try:
            employee = _find_employee(db, row)
            if not employee:
                raise ValueError(f"Employee not found for code '{row.get('employee_code') or row.get('employee_id') or ''}'")
            values = {field: _number(row.get(field)) for field in NUMERIC_FIELDS}
            values["other_earnings"] = _parse_items(row.get("other_earnings"))
            values["other_deductions"] = _parse_items(row.get("other_deductions"))
            effective_from = _effective_date(row.get("effective_from"))

            existing = db.query(SalaryStructure).filter(
                SalaryStructure.employee_id == employee.id,
                SalaryStructure.effective_from == effective_from,
            ).first()
            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
                updated += 1
            else:
                db.add(SalaryStructure(
                    employee_id=employee.id,
                    effective_from=effective_from,
                    **values,
                ))
                created += 1
        except (ValueError, TypeError) as exc:
            errors.append(f"Row {index}: {exc}")

    db.commit()
    return {
        "rows": len(raw_rows),
        "created": created,
        "updated": updated,
        "removed": removed,
        "errors": errors,
    }


@router.put("/structures/{structure_id}", response_model=SalaryStructureOut)
def update_structure(structure_id: int, payload: SalaryStructureUpdate, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    structure = db.query(SalaryStructure).get(structure_id)
    if not structure:
        raise HTTPException(404, "Salary structure not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(structure, key, value)
    db.commit()
    db.refresh(structure)
    return structure


@router.delete("/structures/{structure_id}", status_code=204)
def delete_structure(structure_id: int, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    structure = db.query(SalaryStructure).get(structure_id)
    if not structure:
        raise HTTPException(404, "Salary structure not found")
    db.delete(structure)
    db.commit()


# Processing & slips --------------------------------------------------------
@router.post("/process")
def process(payload: ProcessPayrollRequest, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    period = db.query(PayrollPeriod).get(payload.period_id)
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status == "paid":
        raise HTTPException(400, "This period has already been marked as paid")
    try:
        return process_payroll(
            db, period,
            scope=payload.scope,
            replace_existing=payload.replace_existing,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/payslips", response_model=list[PayslipOut])
def list_payslips(
    period_id: int | None = None,
    employee_id: int | None = None,
    include_demo: bool = False,
    db: Session = Depends(get_db),
    user=Depends(require("payslip.view", "payroll.view")),
):
    query = db.query(Payslip).join(Employee)
    scoped = payroll_scoped_employee_id(user)
    if scoped:
        # Self-service users must still see their own slip, even if demo.
        query = query.filter(Payslip.employee_id == scoped)
    else:
        if not include_demo:
            query = query.filter(Employee.employee_code.like("DEV-%"))
        if employee_id:
            query = query.filter(Payslip.employee_id == employee_id)
    if period_id:
        query = query.filter(Payslip.period_id == period_id)
    return query.order_by(Payslip.generated_at.desc()).all()


@router.post("/payslips/download-zip")
def download_payslips_zip(
    payload: PayslipDownloadRequest,
    db: Session = Depends(get_db),
    user=Depends(require("payslip.view", "payroll.view")),
):
    """Download selected months' salary slips as one ZIP.

    Employee-linked accounts are always limited to their own slips, regardless
    of the periods or include_demo values supplied by the caller.
    """
    query = db.query(Payslip).join(Employee)
    scoped = payroll_scoped_employee_id(user)
    if scoped:
        query = query.filter(Payslip.employee_id == scoped)
    elif not payload.include_demo:
        query = query.filter(Employee.employee_code.like("DEV-%"))

    if payload.period_ids:
        query = query.filter(Payslip.period_id.in_(payload.period_ids))

    slips = query.order_by(Payslip.period_id, Employee.employee_code).all()
    if not slips:
        raise HTTPException(404, "No salary slips found for the selected periods")

    def safe(value) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._") or "unknown"

    buffer = io.BytesIO()
    added = 0
    skipped: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for slip in slips:
            if not slip.pdf_filename:
                skipped.append(f"slip {slip.id}: no PDF")
                continue
            path = os.path.join(settings.PDF_DIR, slip.pdf_filename)
            if not os.path.isfile(path):
                skipped.append(f"slip {slip.id}: PDF missing")
                continue
            folder = safe(slip.period_name or f"period_{slip.period_id}")
            code = safe(slip.employee_code or f"emp_{slip.employee_id}")
            filename = f"{code}_{slip.id}.pdf"
            archive.write(path, arcname=f"{folder}/{filename}")
            added += 1

    if not added:
        detail = "No salary slip PDFs are available for download"
        if skipped:
            detail += f" ({', '.join(skipped[:5])})"
        raise HTTPException(404, detail)

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="salary_slips.zip"',
            "X-Skipped-Slips": str(len(skipped)),
        },
    )


@router.get("/payslips/{payslip_id}/pdf")
def download_payslip(
    payslip_id: int,
    db: Session = Depends(get_db),
    user=Depends(require("payslip.pdf", "payroll.view")),
):
    payslip = db.query(Payslip).get(payslip_id)
    if not payslip:
        raise HTTPException(404, "Salary slip not found")
    scoped = payroll_scoped_employee_id(user)
    if scoped and payslip.employee_id != scoped:
        raise HTTPException(403, "Not allowed")
    if not payslip.pdf_filename or not os.path.exists(os.path.join(settings.PDF_DIR, payslip.pdf_filename)):
        raise HTTPException(404, "PDF is not available for this slip")
    return FileResponse(
        os.path.join(settings.PDF_DIR, payslip.pdf_filename),
        media_type="application/pdf",
        filename=payslip.pdf_filename,
    )


@router.post("/payslips/{payslip_id}/mark-paid", response_model=PayslipOut)
def mark_paid(payslip_id: int, db: Session = Depends(get_db), _=Depends(require("payroll.manage"))):
    payslip = db.query(Payslip).get(payslip_id)
    if not payslip:
        raise HTTPException(404, "Salary slip not found")
    payslip.status = "paid"
    db.commit()
    db.refresh(payslip)
    return payslip
