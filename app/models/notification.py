"""User-targeted in-app notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum, Index

from app.extensions import db


notification_type_enum = Enum(
    "job_done",
    "job_failed",
    "share_received",
    "case_assigned",
    "system",
    name="notification_type_enum",
)


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = db.Column(notification_type_enum, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(500), nullable=True)
    link = db.Column(db.String(500), nullable=True)
    payload_json = db.Column(db.JSON, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="notifications")

    @property
    def is_unread(self) -> bool:
        return self.read_at is None
