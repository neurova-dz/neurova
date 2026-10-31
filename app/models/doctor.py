"""Doctor profile linked 1:1 to a :class:`User` row.

Login lives on :class:`User`; Doctor only carries clinical metadata.
"""

from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Doctor(db.Model):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    clinic_id = db.Column(
        db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True
    )
    specialty = db.Column(db.String(120), nullable=True)
    title = db.Column(db.String(80), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    locale = db.Column(db.String(32), nullable=True)
    preferences_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="doctor_profile")
    clinic = db.relationship("Clinic", back_populates="doctors")

    folders = db.relationship(
        "MedicalFolder",
        back_populates="doctor",
        foreign_keys="MedicalFolder.doctor_id",
        lazy="dynamic",
    )
    assigned_folders = db.relationship(
        "MedicalFolder",
        back_populates="assigned_doctor",
        foreign_keys="MedicalFolder.assigned_doctor_id",
        lazy="dynamic",
    )
    shares_received = db.relationship(
        "FolderShare",
        foreign_keys="FolderShare.shared_with_doctor_id",
        back_populates="shared_with",
        lazy="dynamic",
    )
    shares_granted = db.relationship(
        "FolderShare",
        foreign_keys="FolderShare.shared_by_doctor_id",
        back_populates="shared_by",
        lazy="dynamic",
    )

    # ----- convenience proxies to user -----
    @property
    def email(self) -> str | None:
        return self.user.email if self.user else None

    @property
    def full_name(self) -> str | None:
        return self.user.full_name if self.user else None

    @property
    def is_active_account(self) -> bool:
        return bool(self.user and self.user.is_active_account)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Doctor #{self.id} clinic={self.clinic_id}>"
