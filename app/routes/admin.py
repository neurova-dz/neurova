"""Superadmin-only platform management routes."""

from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
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
from app.forms.auth import AdminNewClinicForm
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.invitation import Invitation
from app.models.medical import AuditLog, InferenceJob, MedicalFolder, Patient
from app.models.user import User
from app.security.decorators import role_required
from app.services.audit_service import log_event
from app.services.mailer import flash_invitation_delivery, send_email
from app.services.platform_stats_service import (
    clinic_summary_rows,
    jobs_per_day,
    modality_split,
    platform_kpis,
    top_clinics_by_jobs,
)
from app.services.worker_health import system_summary


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@role_required("superadmin")
def _superadmin_only():
    return None


# ---- overview --------------------------------------------------------------


@admin_bp.route("/")
def overview():
    kpis = platform_kpis()
    chart_jobs = jobs_per_day(14)
    chart_modality = modality_split()
    top_clinics = top_clinics_by_jobs(8)
    return render_template(
        "admin/overview.html",
        kpis=kpis,
        chart_jobs=chart_jobs,
        chart_modality=chart_modality,
        top_clinics=top_clinics,
    )


# ---- clinics ---------------------------------------------------------------


@admin_bp.route("/clinics")
def clinics_list():
    q = (request.args.get("q") or "").strip()
    rows_q = clinic_summary_rows()
    if q:
        rows_q = rows_q.filter(or_(Clinic.name.ilike(f"%{q}%"), Clinic.slug.ilike(f"%{q}%")))
    rows = rows_q.all()
    return render_template("admin/clinics/list.html", rows=rows, q=q)


@admin_bp.route("/clinics/new", methods=["GET", "POST"])
def clinic_new():
    new_clinic_form = AdminNewClinicForm()
    if new_clinic_form.validate_on_submit():
        name = new_clinic_form.clinic_name.data.strip()
        country = (new_clinic_form.country.data or "").strip() or None
        admin_email = new_clinic_form.admin_email.data.strip().lower()
        admin_full_name = new_clinic_form.admin_full_name.data.strip()

        from app.routes.auth import _ensure_unique_slug, _slugify

        clinic = Clinic(
            name=name,
            slug=_ensure_unique_slug(_slugify(name)),
            country=country,
            plan="trial",
            is_active=True,
            created_by_user_id=current_user.id,
        )
        db.session.add(clinic)
        db.session.flush()

        invitation, raw_token = Invitation.issue(
            email=admin_email,
            role="clinic_admin",
            clinic_id=clinic.id,
            invited_by_user_id=current_user.id,
            full_name=admin_full_name,
        )
        db.session.add(invitation)
        db.session.commit()

        invite_url = url_for("auth.accept_invite", token=raw_token, _external=True)
        mail_sent = send_email(
            subject=f"You're invited to manage {clinic.name} on NEUROVA",
            recipients=[admin_email],
            template="invitation",
            context={"invitation": invitation, "invite_url": invite_url},
        )

        log_event(
            "clinic.create",
            "clinic",
            clinic.id,
            {"name": clinic.name, "admin_email": admin_email},
            clinic_id=clinic.id,
        )
        if mail_sent:
            flash(
                f'Clinic "{clinic.name}" created. Invitation email sent to {admin_email}.',
                "success",
            )
        else:
            flash(f'Clinic "{clinic.name}" created.', "success")
            flash_invitation_delivery(
                email=admin_email,
                invite_url=invite_url,
                mail_sent=False,
                lead_when_no_mail=(
                    "Demo: Email off — Share this link with the clinic admin to set a password:"
                ),
            )
        return redirect(url_for("admin.clinic_detail", clinic_id=clinic.id))

    return render_template("admin/clinics/new.html", new_clinic_form=new_clinic_form)


@admin_bp.route("/clinics/<int:clinic_id>")
def clinic_detail(clinic_id: int):
    clinic = Clinic.query.get_or_404(clinic_id)
    doctors = (
        db.session.query(Doctor, User)
        .join(User, User.id == Doctor.user_id)
        .filter(Doctor.clinic_id == clinic.id)
        .order_by(User.full_name)
        .all()
    )
    patients_count = (
        Patient.query.filter_by(clinic_id=clinic.id)
        .filter(Patient.deleted_at.is_(None))
        .count()
    )
    folder_count = (
        MedicalFolder.query.join(Patient).filter(Patient.clinic_id == clinic.id).count()
    )
    job_count = (
        InferenceJob.query
        .join(MedicalFolder, MedicalFolder.id == InferenceJob.exam_id)  # placeholder join
        .filter(False)  # not used; recomputed below
        .count()
    )
    # accurate jobs count
    from app.models.medical import Exam as _Exam

    job_count = (
        InferenceJob.query.join(_Exam, _Exam.id == InferenceJob.exam_id)
        .join(MedicalFolder, MedicalFolder.id == _Exam.folder_id)
        .join(Patient, Patient.id == MedicalFolder.patient_id)
        .filter(Patient.clinic_id == clinic.id)
        .count()
    )
    audit = (
        AuditLog.query.filter_by(clinic_id=clinic.id)
        .order_by(AuditLog.created_at.desc())
        .limit(40)
        .all()
    )
    return render_template(
        "admin/clinics/detail.html",
        clinic=clinic,
        doctors=doctors,
        patients_count=patients_count,
        folder_count=folder_count,
        job_count=job_count,
        audit=audit,
    )


@admin_bp.route("/clinics/<int:clinic_id>/toggle-active", methods=["POST"])
def clinic_toggle_active(clinic_id: int):
    clinic = Clinic.query.get_or_404(clinic_id)
    clinic.is_active = not clinic.is_active
    # propagate to users in clinic
    for user in clinic.members.all():
        user.is_active_account = clinic.is_active
    db.session.commit()
    log_event(
        "clinic.suspend" if not clinic.is_active else "clinic.activate",
        "clinic",
        clinic.id,
        {"is_active": clinic.is_active},
        clinic_id=clinic.id,
    )
    flash(
        f"Clinic {'reactivated' if clinic.is_active else 'suspended'}.",
        "success" if clinic.is_active else "warning",
    )
    return redirect(url_for("admin.clinic_detail", clinic_id=clinic.id))


# ---- doctors ---------------------------------------------------------------


@admin_bp.route("/doctors")
def doctors_list():
    q = (request.args.get("q") or "").strip()
    clinic_id = request.args.get("clinic_id", type=int)
    qs = (
        db.session.query(Doctor, User, Clinic)
        .join(User, User.id == Doctor.user_id)
        .join(Clinic, Clinic.id == Doctor.clinic_id)
    )
    if q:
        qs = qs.filter(or_(User.full_name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    if clinic_id:
        qs = qs.filter(Clinic.id == clinic_id)
    rows = qs.order_by(User.full_name).limit(500).all()
    clinics = Clinic.query.order_by(Clinic.name).all()
    return render_template(
        "admin/doctors/list.html", rows=rows, q=q, clinic_id=clinic_id, clinics=clinics
    )


# ---- jobs ------------------------------------------------------------------


@admin_bp.route("/jobs")
def jobs_list():
    status = (request.args.get("status") or "").strip()
    clinic_id = request.args.get("clinic_id", type=int)
    model_type = (request.args.get("model_type") or "").strip()

    from app.models.medical import Exam as _Exam

    qs = (
        InferenceJob.query.join(_Exam, _Exam.id == InferenceJob.exam_id)
        .join(MedicalFolder, MedicalFolder.id == _Exam.folder_id)
        .join(Patient, Patient.id == MedicalFolder.patient_id)
    )
    if status in ("queued", "running", "done", "failed", "timed_out", "cancelled"):
        qs = qs.filter(InferenceJob.status == status)
    if clinic_id:
        qs = qs.filter(Patient.clinic_id == clinic_id)
    if model_type in ("brain_3d", "diabetic_retinopathy"):
        qs = qs.filter(InferenceJob.model_type == model_type)
    jobs = qs.order_by(InferenceJob.created_at.desc()).limit(200).all()
    clinics = Clinic.query.order_by(Clinic.name).all()
    return render_template(
        "admin/jobs/list.html",
        jobs=jobs,
        status=status,
        clinic_id=clinic_id,
        model_type=model_type,
        clinics=clinics,
    )


@admin_bp.route("/jobs/<int:job_id>/requeue", methods=["POST"])
def job_requeue(job_id: int):
    job = InferenceJob.query.get_or_404(job_id)
    if str(getattr(job.status, "value", job.status)) not in ("failed", "timed_out", "cancelled"):
        flash("This job cannot be re-queued.", "warning")
        return redirect(url_for("admin.jobs_list"))
    job.status = "queued"
    job.error_message = None
    job.error_code = None
    job.progress = 0
    db.session.commit()
    from flask import current_app
    from app.tasks.enqueue import enqueue_inference_job

    meta = enqueue_inference_job(current_app._get_current_object(), job.id)
    job.task_id = meta.get("task_id")
    db.session.commit()
    log_event("admin.job_requeued", "inference_job", job.id)
    flash("Job re-queued.", "success")
    return redirect(url_for("admin.jobs_list"))


# ---- audit / system --------------------------------------------------------


@admin_bp.route("/audit")
def audit():
    q = (request.args.get("q") or "").strip()
    clinic_id = request.args.get("clinic_id", type=int)
    qs = AuditLog.query
    if q:
        qs = qs.filter(AuditLog.event_type.ilike(f"%{q}%"))
    if clinic_id:
        qs = qs.filter(AuditLog.clinic_id == clinic_id)
    entries = qs.order_by(AuditLog.created_at.desc()).limit(200).all()
    clinics = Clinic.query.order_by(Clinic.name).all()
    return render_template(
        "admin/audit.html", entries=entries, q=q, clinic_id=clinic_id, clinics=clinics
    )


@admin_bp.route("/system")
def system():
    summary = system_summary()
    return render_template("admin/system.html", summary=summary)
