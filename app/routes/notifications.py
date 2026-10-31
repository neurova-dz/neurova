"""In-app notifications: bell, drawer, inbox, mark-as-read."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, redirect, url_for
from flask_login import current_user, login_required

from app.services.notifications_service import (
    mark_all_read,
    mark_read,
    recent_notifications,
    unread_notifications_count,
)


notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications_bp.route("/unread-count", methods=["GET"])
@login_required
def unread_count():
    return str(unread_notifications_count(current_user))


@notifications_bp.route("/recent", methods=["GET"])
@login_required
def recent():
    notifs = recent_notifications(current_user, limit=10)
    return render_template("notifications/_drawer.html", notifs=notifs)


@notifications_bp.route("/", methods=["GET"])
@login_required
def inbox():
    notifs = recent_notifications(current_user, limit=200)
    return render_template("notifications/inbox.html", notifs=notifs)


@notifications_bp.route("/<int:notif_id>/read", methods=["POST"])
@login_required
def read(notif_id: int):
    if not mark_read(current_user, notif_id):
        abort(404)
    return jsonify({"ok": True})


@notifications_bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    n = mark_all_read(current_user)
    return jsonify({"ok": True, "count": n})
