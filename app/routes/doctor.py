"""Doctor (clinician) workspace routes."""

from __future__ import annotations

from datetime import datetime, timedelta

import bleach
import markdown as md
from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from app.extensions import db
from app.forms.auth import CloseFolderForm, FolderNotesForm
from app.routes.patient_creation import respond_clinician_patient_new
from app.models.doctor import Doctor
from app.models.medical import (
    AuditLog,
    Exam,
    InferenceJob,
    MedicalFolder,
    Patient,
)
from app.security.decorators import role_required
from app.services.access_service import (
    accessible_folder_query,
    can_access_folder,
    can_modify_folder,
    inference_jobs_visible_query,
    visible_patients_query,
    visible_folders_for_patient_query,
)
from app.services.audit_service import log_event


doctor_bp = Blueprint("doctor", __name__, url_prefix="/dashboard")


@doctor_bp.before_request
@role_required("doctor", "clinic_admin")
def _doctor_only():
    return None


# ---- helpers --------------------------------------------------------------

ALLOWED_NOTES_TAGS = [
    "p", "br", "ul", "ol", "li", "strong", "em", "b", "i", "u",
    "blockquote", "code", "pre", "h2", "h3", "h4", "hr", "a",
]
ALLOWED_NOTES_ATTRS = {"a": ["href", "title"]}


def _render_notes_md(text: str | None) -> str:
    if not text:
        return ""
    raw = md.markdown(text, extensions=["nl2br"])
    return bleach.clean(raw, tags=ALLOWED_NOTES_TAGS, attributes=ALLOWED_NOTES_ATTRS, strip=True)


# ---- dashboard ------------------------------------------------------------


@doctor_bp.route("/")
def dashboard():
    folder_q = accessible_folder_query(current_user)
    open_folders = (
        folder_q.filter(MedicalFolder.status.in_(("new", "in_progress", "follow_up")))
        .order_by(MedicalFolder.updated_at.desc())
        .limit(8)
        .all()
    )
    follow_ups = (
        folder_q.filter(MedicalFolder.status == "follow_up")
        .order_by(MedicalFolder.updated_at.desc())
        .limit(5)
        .all()
    )
    recent_jobs = (
        inference_jobs_visible_query(current_user)
        .order_by(InferenceJob.created_at.desc())
        .limit(8)
        .all()
    )
    pending_jobs = (
        inference_jobs_visible_query(current_user)
        .filter(InferenceJob.status.in_(("queued", "running")))
        .count()
    )
    todo_count = open_folders and len(open_folders) or 0
    return render_template(
        "doctor/dashboard.html",
        open_folders=open_folders,
        follow_ups=follow_ups,
        recent_jobs=recent_jobs,
        pending_jobs=pending_jobs,
        todo_count=todo_count,
    )


# ---- patients (doctor view) -----------------------------------------------


@doctor_bp.route("/patients")
def patients():
    q = (request.args.get("q") or "").strip()
    qs = visible_patients_query(current_user)
    if q:
        like = f"%{q}%"
        qs = qs.filter(
            or_(
                Patient.first_name.ilike(like),
                Patient.last_name.ilike(like),
                Patient.mrn.ilike(like),
            )
        )
    patients_list = qs.order_by(Patient.last_name).limit(500).all()
    return render_template("doctor/patients_list.html", patients=patients_list, q=q)


@doctor_bp.route("/patients/new", methods=["GET", "POST"])
def patient_new():
    """POST form target and ``doctor.patient_new`` endpoint."""

    return respond_clinician_patient_new(cancel_url=url_for("doctor.patients"))


@doctor_bp.route("/patients/<int:patient_id>")
def patient_detail(patient_id: int):
    patient = visible_patients_query(current_user).filter_by(id=patient_id).first_or_404()
    folders = (
        visible_folders_for_patient_query(current_user, patient.id)
        .order_by(MedicalFolder.updated_at.desc())
        .all()
    )
    # build a vertical timeline of folders/exams/jobs
    events = []
    for f in folders:
        events.append({"kind": "folder", "ts": f.created_at, "title": f"Case opened — {f.title}", "link": url_for("doctor.folder_workspace", folder_id=f.id)})
        for e in f.exams.all():
            events.append({"kind": "exam", "ts": e.created_at, "title": f"Exam · {getattr(e.modality,'value',e.modality)}",
                           "link": url_for("doctor.folder_workspace", folder_id=f.id)})
            for j in e.jobs.all():
                events.append({
                    "kind": "job",
                    "ts": j.created_at,
                    "title": f"Analysis #{j.id} — {j.status_value}",
                    "link": url_for("results.view_result", job_id=j.id),
                })
    events.sort(key=lambda x: x["ts"], reverse=True)
    return render_template(
        "doctor/patient_detail.html", patient=patient, folders=folders, events=events
    )


# ---- folder workspace -----------------------------------------------------


@doctor_bp.route("/folders/<int:folder_id>")
def folder_workspace(folder_id: int):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_access_folder(current_user, folder):
        abort(403)
    tab = request.args.get("tab", "overview")
    notes_html = _render_notes_md(folder.notes_md)
    exams = folder.exams.order_by(Exam.created_at.desc()).all()
    activity = (
        AuditLog.query.filter(
            AuditLog.resource_type.in_(("medical_folder", "inference_job", "exam")),
            (
                (AuditLog.resource_type == "medical_folder")
                & (AuditLog.resource_id == str(folder.id))
            )
            | (AuditLog.resource_type == "exam")
            | (AuditLog.resource_type == "inference_job"),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(50)
        .all()
    )
    notes_form = FolderNotesForm(notes_md=folder.notes_md or "")
    close_form = CloseFolderForm()
    can_edit = can_modify_folder(current_user, folder)
    return render_template(
        "doctor/folder_workspace.html",
        folder=folder,
        exams=exams,
        notes_html=notes_html,
        activity=activity,
        notes_form=notes_form,
        close_form=close_form,
        tab=tab,
        can_edit=can_edit,
    )


@doctor_bp.route("/folders/<int:folder_id>/notes", methods=["POST"])
def folder_notes(folder_id: int):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        abort(403)
    form = FolderNotesForm()
    if form.validate_on_submit():
        folder.notes_md = (form.notes_md.data or "")[:10000]
        db.session.commit()
        log_event("folder.notes_update", "medical_folder", folder.id, clinic_id=folder.patient.clinic_id if folder.patient else None)
        flash("Notes saved.", "success")
    return redirect(url_for("doctor.folder_workspace", folder_id=folder.id, tab="notes"))


@doctor_bp.route("/folders/<int:folder_id>/close", methods=["POST"])
def folder_close(folder_id: int):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        abort(403)
    form = CloseFolderForm()
    if not form.validate_on_submit():
        flash("Closure reason is required.", "warning")
        return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))
    folder.status = "closed"
    folder.closed_reason = form.reason.data.strip()
    folder.closed_at = datetime.utcnow()
    folder.closed_by_user_id = current_user.id
    db.session.commit()
    log_event(
        "folder.close",
        "medical_folder",
        folder.id,
        {"reason": folder.closed_reason},
        clinic_id=folder.patient.clinic_id if folder.patient else None,
    )
    flash("Case closed.", "success")
    return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))


@doctor_bp.route("/folders/<int:folder_id>/reopen", methods=["POST"])
def folder_reopen(folder_id: int):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        abort(403)
    if folder.status != "closed":
        flash("Folder is not closed.", "info")
        return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))
    folder.status = "in_progress"
    folder.closed_reason = None
    folder.closed_at = None
    folder.closed_by_user_id = None
    db.session.commit()
    log_event("folder.reopen", "medical_folder", folder.id)
    flash("Case re-opened.", "success")
    return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))


# ---- worklist -------------------------------------------------------------


@doctor_bp.route("/worklist")
def worklist():
    status = (request.args.get("status") or "").strip().lower()
    valid = ("queued", "running", "done", "failed", "timed_out", "cancelled")
    qs = inference_jobs_visible_query(current_user)
    if status in valid:
        qs = qs.filter(InferenceJob.status == status)
    jobs = qs.order_by(InferenceJob.created_at.desc()).limit(100).all()
    base_q = inference_jobs_visible_query(current_user)
    counts = {"all": base_q.count()}
    for s in valid:
        counts[s] = base_q.filter(InferenceJob.status == s).count()
    return render_template(
        "doctor/worklist.html", jobs=jobs, status=status if status in valid else "", counts=counts
    )


# ---- profile / settings (kept) --------------------------------------------


@doctor_bp.route("/profile", methods=["GET", "POST"])
def profile():
    profile_row = current_user.doctor_profile
    if not profile_row:
        # promote: clinic admins might not have a doctor profile
        from app.models.doctor import Doctor as _D

        profile_row = _D(
            user_id=current_user.id,
            clinic_id=current_user.clinic_id,
            preferences_json={"default_modality": "", "compact_results": False},
        )
        db.session.add(profile_row)
        db.session.commit()
    if request.method == "POST":
        current_user.full_name = (request.form.get("full_name") or current_user.full_name).strip()
        profile_row.title = (request.form.get("title") or "").strip() or None
        profile_row.phone = (request.form.get("phone") or "").strip() or None
        profile_row.locale = (request.form.get("locale") or "").strip() or None
        spec = (request.form.get("specialty") or "").strip()
        if spec in ("brain_tumor", "diabetic_retinopathy", ""):
            profile_row.specialty = spec or None
        db.session.commit()
        log_event("doctor.profile_update", "user", current_user.id)
        flash("Profile updated.", "success")
        return redirect(url_for("doctor.profile"))
    return render_template("doctor/profile.html", profile=profile_row)


@doctor_bp.route("/settings", methods=["GET", "POST"])
def settings():
    profile_row = current_user.doctor_profile
    if request.method == "POST" and profile_row:
        prefs = dict(profile_row.preferences_json or {})
        modality = (request.form.get("default_modality") or "").strip()
        if modality in ("", "mri", "retina_fundus"):
            if modality:
                prefs["default_modality"] = modality
            else:
                prefs.pop("default_modality", None)
        prefs["compact_results"] = request.form.get("compact_results") == "on"
        profile_row.preferences_json = prefs
        db.session.commit()
        flash("Preferences saved.", "success")
        return redirect(url_for("doctor.settings"))
    prefs = (profile_row.preferences_json if profile_row else {}) or {}
    return render_template("doctor/settings.html", prefs=prefs)
