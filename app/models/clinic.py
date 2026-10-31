"""Clinic / Hospital tenant model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum

from app.extensions import db


clinic_plan_enum = Enum("trial", "standard", "enterprise", name="clinic_plan_enum")


class Clinic(db.Model):
    __tablename__ = "clinics"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), nullable=True, unique=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(180), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    country = db.Column(db.String(80), nullable=True)
    timezone = db.Column(db.String(64), nullable=True)
    plan = db.Column(clinic_plan_enum, nullable=False, default="trial")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    settings_json = db.Column(db.JSON, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    members = db.relationship(
        "User",
        back_populates="clinic",
        lazy="dynamic",
        foreign_keys="User.clinic_id",
    )
    doctors = db.relationship("Doctor", back_populates="clinic", lazy="dynamic")
    patients = db.relationship("Patient", back_populates="clinic", lazy="dynamic")
    invitations = db.relationship(
        "Invitation", back_populates="clinic", cascade="all, delete-orphan", lazy="dynamic"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Clinic #{self.id} {self.name}>"
