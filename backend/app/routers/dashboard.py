from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user, require, scoped_employee_id
from app.database import get_db
from app.models import AttendanceRecord, Employee, PayrollPeriod, Payslip, User

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require("dashboard.view", "self.portal"))):
    today = date.today()
    scoped = scoped_employee_id(user)

    emp_query = db.query(Employee).filter(Employee.status == "active")
    if scoped:
        emp_query = emp_query.filter(Employee.id == scoped)

    today_query = db.query(AttendanceRecord).filter(AttendanceRecord.record_date == today)
    if scoped:
        today_query = today_query.filter(AttendanceRecord.employee_id == scoped)
    today_records = today_query.all()

    start = today - timedelta(days=6)
    trend_query = db.query(AttendanceRecord).filter(
        AttendanceRecord.record_date >= start, AttendanceRecord.record_date <= today
    )
    if scoped:
        trend_query = trend_query.filter(AttendanceRecord.employee_id == scoped)
    trend_records = trend_query.all()
    trend = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        day_records = [r for r in trend_records if r.record_date == day]
        trend.append({
            "date": day.isoformat(),
            "label": day.strftime("%a"),
            "present": sum(1 for r in day_records if r.status in ("present", "half_day")),
            "absent": sum(1 for r in day_records if r.status == "absent"),
        })

    pending = db.query(Payslip).filter(Payslip.status == "generated").count()
    if scoped:
        pending = db.query(Payslip).filter(Payslip.status == "generated", Payslip.employee_id == scoped).count()

    return {
        "total_employees": emp_query.count(),
        "present_today": sum(1 for r in today_records if r.status in ("present", "half_day")),
        "absent_today": sum(1 for r in today_records if r.status == "absent"),
        "late_today": sum(1 for r in today_records if r.late_minutes > 0),
        "on_leave_today": sum(1 for r in today_records if r.status == "leave"),
        "avg_hours_week": round(
            sum(r.total_hours or 0 for r in trend_records) / max(1, len([r for r in trend_records if r.total_hours])), 2
        ),
        "pending_payslips": pending,
        "open_payroll_periods": db.query(PayrollPeriod).filter(PayrollPeriod.status != "paid").count(),
        "trend": trend,
    }
