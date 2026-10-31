"""In-app notification helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.extensions import db
from app.models.notification import Notification


def push(
    user_id: int,
    *,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    payload: dict | None = None,
) -> Notification:
    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
        payload_json=payload or {},
    )
    db.session.add(n)
    db.session.commit()
    return n


def push_many(user_ids: Iterable[int], **kwargs) -> list[Notification]:
    rows = []
    for uid in {uid for uid in user_ids if uid is not None}:
        rows.append(
            Notification(
                user_id=uid,
                type=kwargs.get("type"),
                title=kwargs.get("title"),
                body=kwargs.get("body"),
                link=kwargs.get("link"),
                payload_json=kwargs.get("payload") or {},
            )
        )
    if rows:
        db.session.add_all(rows)
        db.session.commit()
    return rows


def unread_notifications_count(user) -> int:
    if not user or not getattr(user, "is_authenticated", False):
        return 0
    return Notification.query.filter_by(user_id=user.id, read_at=None).count()


def recent_notifications(user, *, limit: int = 10) -> list[Notification]:
    return (
        Notification.query.filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_read(user, notif_id: int) -> bool:
    n = Notification.query.filter_by(id=notif_id, user_id=user.id).first()
    if not n:
        return False
    if n.read_at is None:
        n.read_at = datetime.utcnow()
        db.session.commit()
    return True


def mark_all_read(user) -> int:
    qs = Notification.query.filter_by(user_id=user.id, read_at=None)
    count = 0
    now = datetime.utcnow()
    for n in qs.all():
        n.read_at = now
        count += 1
    if count:
        db.session.commit()
    return count
