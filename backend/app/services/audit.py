"""Helpers for recording changes that were not made through a user request."""

from app.models import AuditLog


def log_system_action(db, action: str, entity: str, entity_id: int | None = None, details: dict | None = None):
    """Record a system-originated change with no human actor."""
    db.add(AuditLog(
        user_id=None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details or {},
    ))
