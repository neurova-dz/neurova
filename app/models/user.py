"""Unified login user.

The :class:`User` row owns email + password + role for every actor in the platform
(superadmin, clinic admin, doctor). Doctor-specific fields (specialty, title, etc.)
live on the :class:`Doctor` profile linked 1:1 via ``doctors.user_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask_login import UserMixin
from sqlalchemy import Enum
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager


user_role_enum = Enum(
    "superadmin",
    "clinic_admin",
    "doctor",
    name="user_role_enum",
)


class User(UserMixin, db.Model):
    """Login row. ``role`` decides which dashboard the user lands on."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(180), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(160), nullable=False)
    role = db.Column(user_role_enum, nullable=False, default="doctor", index=True)
    clinic_id = db.Column(
        db.Integer, db.ForeignKey("clinics.id"), nullable=True, index=True
    )
    is_active_account = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    clinic = db.relationship(
        "Clinic", back_populates="members", foreign_keys=[clinic_id]
    )
    doctor_profile = db.relationship(
        "Doctor", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    notifications = db.relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan", lazy="dynamic"
    )

    # ----- password helpers -----
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    # ----- role helpers -----
    @property
    def role_value(self) -> str:
        return getattr(self.role, "value", self.role)

    @property
    def is_superadmin(self) -> bool:
        return self.role_value == "superadmin"

    @property
    def is_clinic_admin(self) -> bool:
        return self.role_value == "clinic_admin"

    @property
    def is_doctor(self) -> bool:
        return self.role_value == "doctor"

    @property
    def is_active(self) -> bool:  # Flask-Login property
        return bool(self.is_active_account)

    # ----- doctor profile passthroughs (legacy templates expect these) -----
    @property
    def specialty(self) -> Optional[str]:
        return self.doctor_profile.specialty if self.doctor_profile else None

    @property
    def title(self) -> Optional[str]:
        return self.doctor_profile.title if self.doctor_profile else None

    @property
    def phone(self) -> Optional[str]:
        return self.doctor_profile.phone if self.doctor_profile else None

    @property
    def locale(self) -> Optional[str]:
        return self.doctor_profile.locale if self.doctor_profile else None

    @property
    def preferences_json(self) -> dict:
        if self.doctor_profile and isinstance(self.doctor_profile.preferences_json, dict):
            return self.doctor_profile.preferences_json
        return {}

    @preferences_json.setter
    def preferences_json(self, value: dict) -> None:
        if self.doctor_profile:
            self.doctor_profile.preferences_json = value

    @property
    def doctor_id(self) -> Optional[int]:
        return self.doctor_profile.id if self.doctor_profile else None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} role={self.role_value}>"


@login_manager.user_loader
def _load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except (TypeError, ValueError):
        return None


@login_manager.unauthorized_handler
def _on_unauthorized():
    from flask import flash, redirect, request, url_for

    if request.path.startswith("/api") or request.headers.get("HX-Request"):
        from flask import jsonify

        return jsonify({"error": "auth_required"}), 401
    flash("Please sign in to continue.", "warning")
    return redirect(url_for("auth.login", next=request.path))
