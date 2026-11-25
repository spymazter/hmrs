"""Permanent, application-wide identity enforcement.

Device UIDs, employee codes and the employee linked to a user are immutable
identities.  A value may never be assigned to a different record, even after
the original employee/user has been deleted or unlinked.  Reservations are kept
in a dedicated table so retired values survive row deletion, and SQLAlchemy
events enforce the rule for every write path (UI, imports, sync, CLI and seed).
"""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event, insert, select
from sqlalchemy.orm import Session

from app.models import Employee, IdentifierReservation, User

EMPLOYEE_CODE = "employee_code"
DEVICE_USER_ID = "device_user_id"
USER_EMPLOYEE = "user_employee"

_LABELS = {
    EMPLOYEE_CODE: "Employee ID",
    DEVICE_USER_ID: "Device user ID",
    USER_EMPLOYEE: "Employee account",
}


class IdentifierConflict(ValueError):
    """Raised when an identity is already reserved for another record."""


def new_identity_key() -> str:
    return uuid4().hex


def normalize(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().casefold()
    return cleaned or None


def _identity_key(record) -> str:
    """Give every record a stable key that survives row-id reuse after deletes."""
    if not getattr(record, "identity_key", None):
        record.identity_key = new_identity_key()
    return record.identity_key


def _get(executor, model, primary_key):
    if isinstance(executor, Session):
        return executor.get(model, primary_key)
    table = model.__table__
    row = executor.execute(
        select(table.c.id, table.c.identity_key, table.c.employee_code)
        .where(table.c.id == primary_key)
    ).first()
    if row is None:
        return None
    return SimpleNamespace(
        id=row.id, identity_key=row.identity_key,
        employee_code=getattr(row, "employee_code", None),
    )


def _reservation(executor, kind: str, value: str | None):
    if not value:
        return None
    table = IdentifierReservation.__table__
    row = executor.execute(
        select(table.c.owner_key).where(
            table.c.kind == kind,
            table.c.value == value,
        )
    ).first()
    if row is None:
        return None
    return SimpleNamespace(owner_key=row.owner_key)


def _reserve(executor, kind, value, owner_key, *, employee_id=None, user_id=None,
             display=None):
    value = normalize(value)
    if not value:
        return None
    existing = _reservation(executor, kind, value)
    if existing is not None:
        if existing.owner_key != owner_key:
            if kind == USER_EMPLOYEE:
                raise IdentifierConflict(
                    "This employee ID is already assigned to another user and "
                    "cannot be reused"
                )
            shown = display if display is not None else value
            raise IdentifierConflict(
                f"{_LABELS.get(kind, 'Identifier')} '{shown}' is already reserved "
                "for another record and cannot be reused"
            )
        return existing
    executor.execute(insert(IdentifierReservation).values(
        kind=kind,
        value=value,
        owner_key=owner_key,
        employee_id=employee_id,
        user_id=user_id,
        created_at=datetime.now(),
    ))
    return None


def reserve_employee(executor, employee: Employee) -> None:
    """Reserve both identifiers for an employee; existing ones stay permanent."""
    owner_key = _identity_key(employee)
    _reserve(executor, EMPLOYEE_CODE, employee.employee_code, owner_key,
             employee_id=employee.id, display=employee.employee_code)
    _reserve(executor, DEVICE_USER_ID, employee.device_user_id, owner_key,
             employee_id=employee.id, display=employee.device_user_id)


def reserve_user(executor, user: User) -> None:
    """Bind a user to an employee forever; one user per employee identity."""
    if not user.employee_id:
        return
    employee = _get(executor, Employee, user.employee_id)
    if employee is None:
        return  # Foreign key validation will report a missing employee.
    if user.id is not None:
        other = executor.execute(
            select(User.id).where(
                User.employee_id == user.employee_id,
                User.id != user.id,
            )
        ).first()
        if other is not None:
            raise IdentifierConflict(
                "This employee ID is already assigned to another user"
            )
    _reserve(executor, USER_EMPLOYEE, _identity_key(employee),
             _identity_key(user), employee_id=employee.id, user_id=user.id)


def identifiers_available(db: Session, employee_code, device_user_id,
                          owner_key: str | None = None) -> bool:
    """Check identifiers before auto-creating an employee (e.g. from a device)."""
    for kind, value in (
        (EMPLOYEE_CODE, employee_code),
        (DEVICE_USER_ID, device_user_id),
    ):
        existing = _reservation(db, kind, normalize(value))
        if existing is not None and existing.owner_key != owner_key:
            return False
    return True


def employee_is_available(db: Session, employee_id: int,
                          user_key: str | None = None) -> bool:
    """Check whether an employee identity can be linked to a user."""
    employee = db.get(Employee, employee_id)
    if employee is None:
        return False
    existing = _reservation(db, USER_EMPLOYEE, normalize(_identity_key(employee)))
    return existing is None or existing.owner_key == user_key


@event.listens_for(Employee, "before_insert")
def _employee_before_insert(_mapper, connection, target):
    reserve_employee(connection, target)


@event.listens_for(Employee, "before_update")
def _employee_before_update(_mapper, connection, target):
    reserve_employee(connection, target)


@event.listens_for(User, "before_insert")
def _user_before_insert(_mapper, connection, target):
    reserve_user(connection, target)


@event.listens_for(User, "before_update")
def _user_before_update(_mapper, connection, target):
    reserve_user(connection, target)
