from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require
from app.database import get_db
from app.models import Shift
from app.schemas import LunchBreakConfigIn, LunchBreakConfigOut
from app.services.attendance_engine import get_lunch_break_config, save_lunch_break_config

router = APIRouter(prefix="/api/lunch-break", tags=["Lunch break"])


def _config_out(db: Session, config) -> dict:
    shifts = db.query(Shift).order_by(Shift.id).all()
    return {
        **config.as_dict(),
        "shifts": [
            {
                "id": shift.id,
                "name": shift.name,
                "start_time": shift.start_time.strftime("%H:%M") if shift.start_time else None,
                "end_time": shift.end_time.strftime("%H:%M") if shift.end_time else None,
                "break_minutes": shift.break_minutes or 0,
                "effective_minutes": config.effective_minutes(shift),
                "is_active": bool(shift.is_active),
            }
            for shift in shifts
        ],
    }


@router.get("", response_model=LunchBreakConfigOut)
def get_config(db: Session = Depends(get_db), _=Depends(require("shift.view", "employee.view", "self.portal"))):
    return _config_out(db, get_lunch_break_config(db))


@router.put("", response_model=LunchBreakConfigOut)
def update_config(
    payload: LunchBreakConfigIn,
    db: Session = Depends(get_db),
    _=Depends(require("shift.manage")),
):
    current = get_lunch_break_config(db).as_dict()
    current.update(payload.model_dump(exclude_unset=True, exclude_none=True))
    config = save_lunch_break_config(db, current)
    return _config_out(db, config)
