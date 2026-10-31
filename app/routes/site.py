"""Public site pages and legacy URL compatibility."""

from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from app.models.medical import AuditLog
from app.specialty import normalize_doctor_specialty


site_bp = Blueprint("site", __name__)


# ---- static media -----------------------------------------------------------


@site_bp.route("/logo/animation-logo.mp4")
def logo_video():
    directory = Path(current_app.root_path).parent / "templates" / "logo"
    return send_from_directory(str(directory), "animation-logo.mp4", mimetype="video/mp4")


@site_bp.route("/logo/favicon-neurova.png")
def logo_png():
    directory = Path(current_app.root_path).parent / "templates" / "logo"
    return send_from_directory(str(directory), "favicon-neurova.png", mimetype="image/png")


# ---- legacy redirects (keep old links working) -----------------------------


@site_bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_superadmin:
        return redirect(url_for("admin.overview"))
    if current_user.is_clinic_admin:
        return redirect(url_for("clinic.overview"))
    return redirect(url_for("doctor.dashboard"))


@site_bp.route("/analysis")
@login_required
def analysis_redirect():
    return redirect(url_for("site.pipeline"))


@site_bp.route("/pipeline")
@login_required
def pipeline():
    if current_user.is_superadmin:
        return redirect(url_for("admin.jobs_list"))
    if current_user.is_clinic_admin:
        return redirect(url_for("clinic.cases_board"))
    return redirect(url_for("doctor.worklist"))


@site_bp.route("/resources")
@login_required
def resources():
    wf = normalize_doctor_specialty(getattr(current_user, "specialty", None))
    return render_template("resources.html", doctor_workflow=wf)


@site_bp.route("/activity")
@login_required
def activity():
    entries = (
        AuditLog.query.filter_by(actor_user_id=current_user.id)
        .order_by(AuditLog.created_at.desc())
        .limit(80)
        .all()
    )
    return render_template("activity.html", audit_entries=entries)


@site_bp.route("/settings")
@login_required
def settings():
    if current_user.is_clinic_admin:
        return redirect(url_for("clinic.settings"))
    return redirect(url_for("doctor.settings"))


@site_bp.route("/profile")
@login_required
def profile():
    return redirect(url_for("doctor.profile"))


@site_bp.route("/landing")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("landing.html")
