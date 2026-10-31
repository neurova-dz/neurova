"""Invitations for clinic admins (issued by superadmin) and doctors (issued by clinic admin)."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets

from sqlalchemy import Enum

from app.extensions import db


invitation_role_enum = Enum("clinic_admin", "doctor", name="invitation_role_enum")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Invitation(db.Model):
    __tablename__ = "invitations"

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=True, index=True)
    email = db.Column(db.String(180), nullable=False, index=True)
    role = db.Column(invitation_role_enum, nullable=False)
    full_name = db.Column(db.String(160), nullable=True)
    specialty = db.Column(db.String(120), nullable=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    invited_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    clinic = db.relationship("Clinic", back_populates="invitations")
    invited_by = db.relationship("User", foreign_keys=[invited_by_user_id])

    @staticmethod
    def issue(*, email: str, role: str, clinic_id: int | None,
              invited_by_user_id: int | None, full_name: str | None = None,
              specialty: str | None = None, ttl_hours: int = 72) -> tuple["Invitation", str]:
        """Create an invitation row and return ``(invitation, raw_token)``.

        The raw token is shown to the inviter once and never persisted.
        """
        raw_token = secrets.token_urlsafe(32)
        inv = Invitation(
            email=email.lower().strip(),
            role=role,
            clinic_id=clinic_id,
            invited_by_user_id=invited_by_user_id,
            full_name=full_name,
            specialty=specialty,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
        )
        return inv, raw_token

    @classmethod
    def find_active_by_token(cls, raw_token: str) -> "Invitation | None":
        if not raw_token:
            return None
        token_hash = _hash_token(raw_token)
        inv = cls.query.filter_by(token_hash=token_hash).first()
        if not inv:
            return None
        if inv.accepted_at is not None:
            return None
        if inv.expires_at < datetime.utcnow():
            return None
        return inv


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")

    @staticmethod
    def issue(user_id: int, *, ttl_minutes: int = 30) -> tuple["PasswordResetToken", str]:
        raw = secrets.token_urlsafe(32)
        row = PasswordResetToken(
            user_id=user_id,
            token_hash=_hash_token(raw),
            expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
        )
        return row, raw

    @classmethod
    def find_active_by_token(cls, raw_token: str) -> "PasswordResetToken | None":
        if not raw_token:
            return None
        token_hash = _hash_token(raw_token)
        row = cls.query.filter_by(token_hash=token_hash).first()
        if not row:
            return None
        if row.used_at is not None:
            return None
        if row.expires_at < datetime.utcnow():
            return None
        return row
