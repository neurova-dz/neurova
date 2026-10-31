"""Decorators that gate routes by role and tenant."""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import abort, jsonify, redirect, request, url_for
from flask_login import current_user


def _is_api_call() -> bool:
    return request.path.startswith("/api") or request.headers.get("HX-Request") == "true"


def role_required(*roles: str):
    """Allow only authenticated users whose role is in ``roles``.

    Usage::

        @role_required("clinic_admin", "superadmin")
        def some_route(): ...
    """

    accepted = {r.strip() for r in roles if r}

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not getattr(current_user, "is_authenticated", False):
                if _is_api_call():
                    return jsonify({"error": "auth_required"}), 401
                return redirect(url_for("auth.login", next=request.path))
            if not getattr(current_user, "is_active", True):
                abort(403)
            user_role = getattr(current_user, "role_value", None)
            if accepted and user_role not in accepted:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def same_clinic_required(get_resource_clinic_id):
    """Wrap a view that takes a resource id; reject if it lives in another clinic.

    ``get_resource_clinic_id`` is a callable receiving the same kwargs as the view
    and returning the resource's ``clinic_id`` (or ``None`` if not found).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            clinic_id = get_resource_clinic_id(*args, **kwargs)
            if clinic_id is None:
                abort(404)
            if getattr(current_user, "is_superadmin", False):
                return view(*args, **kwargs)
            if getattr(current_user, "clinic_id", None) != clinic_id:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def any_role(*roles: Iterable[str]):
    """Alias for :func:`role_required` for readability when listing many roles."""
    return role_required(*roles)
