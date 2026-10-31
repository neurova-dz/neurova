"""Centralised audit log writer keyed on the unified User model."""

from __future__ import annotations

from typing import Any

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models.medical import AuditLog


def log_event(
    event_type: str,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    details: dict[str, Any] | None = None,
    *,
    actor_user_id: int | None = None,
    clinic_id: int | None = None,
) -> AuditLog:
    """Write an audit row.

    Captures actor and clinic from ``current_user`` when not provided explicitly.
    """

    if actor_user_id is None and getattr(current_user, "is_authenticated", False):
        actor_user_id = current_user.id
    if clinic_id is None and getattr(current_user, "is_authenticated", False):
        clinic_id = getattr(current_user, "clinic_id", None)

    ip_address = None
    if has_request_context():
        try:
            ip_address = (request.access_route[0] if request.access_route else request.remote_addr)
        except Exception:  # noqa: BLE001
            ip_address = request.remote_addr

    entry = AuditLog(
        event_type=event_type,
        actor_user_id=actor_user_id,
        clinic_id=clinic_id,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=details or {},
        ip_address=ip_address,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
