"""Clinic admin routes: overview, doctors, patients, cases, settings."""

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

from app.data.timezones import DEFAULT_CLINIC_TIMEZONE, is_valid_timezone, timezone_choices
from app.extensions import db
from app.forms.auth import DoctorInviteForm, PatientForm
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.invitation import Invitation
from app.models.medical import (
    AuditLog,
    Exam,
    InferenceJob,
    MedicalFolder,
    Patient,
)
from app.models.user import User
from app.security.decorators import role_required
from app.services.audit_service import log_event
from app.services.clinic_stats_service import (
    clinic_kpis,
    doctor_productivity,
    doctor_summary_rows,
    jobs_per_day,
    status_breakdown,
)
from app.services.mailer import flash_invitation_delivery, send_email


clinic_bp = Blueprint("clinic", __name__, url_prefix="/clinic")


@clinic_bp.before_request
@role_required("clinic_admin")
def _clinic_admin_only():
    if current_user.clinic_id is None:
        abort(403)
    return None


def _scoped_clinic() -> Clinic:
    return Clinic.query.get_or_404(current_user.clinic_id)


# ---- overview --------------------------------------------------------------


@clinic_bp.route("/")
def overview():
    clinic = _scoped_clinic()
    kpis = clinic_kpis(clinic.id)
    breakdown = status_breakdown(clinic.id)
    chart_jobs = jobs_per_day(clinic.id, 14)
    productivity = doctor_productivity(clinic.id, 30)
    recent_jobs = (
        InferenceJob.query.join(Exam, Exam.id == InferenceJob.exam_id)
        .join(MedicalFolder, MedicalFolder.id == Exam.folder_id)
        .join(Patient, Patient.id == MedicalFolder.patient_id)
        .filter(Patient.clinic_id == clinic.id)
        .order_by(InferenceJob.created_at.desc())
        .limit(8)
        .all()
    )
    return render_template(
        "clinic/overview.html",
        clinic=clinic,
        kpis=kpis,
        breakdown=breakdown,
        chart_jobs=chart_jobs,
        productivity=productivity,
        recent_jobs=recent_jobs,
    )


# ---- doctors ---------------------------------------------------------------


@clinic_bp.route("/doctors")
def doctors_list():
    clinic = _scoped_clinic()
    q = (request.args.get("q") or "").strip()
    rows_q = doctor_summary_rows(clinic.id)
    if q:
        like = f"%{q}%"
        rows_q = rows_q.filter(or_(User.full_name.ilike(like), User.email.ilike(like)))
    rows = rows_q.all()
    return render_template("clinic/doctors/list.html", rows=rows, clinic=clinic, q=q)


@clinic_bp.route("/doctors/new", methods=["GET", "POST"])
def doctor_new():
    clinic = _scoped_clinic()
    form = DoctorInviteForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("A user already exists with that email.", "warning")
            return render_template("clinic/doctors/form.html", form=form, clinic=clinic)
        invitation, raw_token = Invitation.issue(
            email=email,
            role="doctor",
            clinic_id=clinic.id,
            invited_by_user_id=current_user.id,
            full_name=form.full_name.data.strip(),
            specialty=form.specialty.data or None,
        )
        db.session.add(invitation)
        db.session.commit()

        invite_url = url_for("auth.accept_invite", token=raw_token, _external=True)
        mail_sent = send_email(
            subject=f"You're invited to {clinic.name} on NEUROVA",
            recipients=[email],
            template="invitation",
            context={"invitation": invitation, "invite_url": invite_url},
        )

        log_event(
            "doctor.invite",
            "invitation",
            invitation.id,
            {"email": email, "specialty": invitation.specialty},
            clinic_id=clinic.id,
        )
        flash_invitation_delivery(
            email=email,
            invite_url=invite_url,
            mail_sent=mail_sent,
        )
        return redirect(url_for("clinic.doctors_list"))
    return render_template("clinic/doctors/form.html", form=form, clinic=clinic)


@clinic_bp.route("/doctors/<int:doctor_id>")
def doctor_detail(doctor_id: int):
    clinic = _scoped_clinic()
    doctor = Doctor.query.filter_by(id=doctor_id, clinic_id=clinic.id).first_or_404()
    open_folders = (
        MedicalFolder.query.filter(
            or_(
                MedicalFolder.doctor_id == doctor.id,
                MedicalFolder.assigned_doctor_id == doctor.id,
            ),
            MedicalFolder.status.in_(("new", "in_progress", "follow_up")),
        )
        .order_by(MedicalFolder.updated_at.desc())
        .all()
    )
    return render_template(
        "clinic/doctors/detail.html",
        clinic=clinic,
        doctor=doctor,
        open_folders=open_folders,
    )


@clinic_bp.route("/doctors/<int:doctor_id>/toggle-active", methods=["POST"])
def doctor_toggle_active(doctor_id: int):
    clinic = _scoped_clinic()
    doctor = Doctor.query.filter_by(id=doctor_id, clinic_id=clinic.id).first_or_404()
    user = doctor.user
    if not user:
        abort(404)
    user.is_active_account = not user.is_active_account
    db.session.commit()
    log_event(
        "doctor.activate" if user.is_active_account else "doctor.deactivate",
        "user",
        user.id,
        clinic_id=clinic.id,
    )
    flash(
        f"{user.full_name} is now {'active' if user.is_active_account else 'disabled'}.",
        "success" if user.is_active_account else "warning",
    )
    return redirect(url_for("clinic.doctor_detail", doctor_id=doctor.id))


# ---- patients --------------------------------------------------------------


@clinic_bp.route("/patients")
def patients_list():
    clinic = _scoped_clinic()
    q = (request.args.get("q") or "").strip()
    qs = Patient.query.filter_by(clinic_id=clinic.id).filter(Patient.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        qs = qs.filter(
            or_(
                Patient.first_name.ilike(like),
                Patient.last_name.ilike(like),
                Patient.mrn.ilike(like),
            )
        )
    patients = qs.order_by(Patient.last_name).limit(500).all()
    return render_template("clinic/patients/list.html", patients=patients, q=q, clinic=clinic)


@clinic_bp.route("/patients/new", methods=["GET", "POST"])
def patient_new():
    clinic = _scoped_clinic()
    form = PatientForm()
    if form.validate_on_submit():
        from datetime import date

        bd = None
        if form.birth_date.data:
            try:
                bd = datetime.strptime(form.birth_date.data, "%Y-%m-%d").date()
            except ValueError:
                form.birth_date.errors.append("Invalid date format.")
                return render_template("clinic/patients/form.html", form=form, clinic=clinic)
        patient = Patient(
            clinic_id=clinic.id,
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            sex=form.sex.data or None,
            birth_date=bd,
            mrn=(form.mrn.data or None),
            phone=form.phone.data or None,
            clinical_notes=form.clinical_notes.data or None,
        )
        db.session.add(patient)
        db.session.commit()
        log_event("patient.create", "patient", patient.id, clinic_id=clinic.id)
        flash("Patient created.", "success")
        return redirect(url_for("clinic.patient_detail", patient_id=patient.id))
    return render_template("clinic/patients/form.html", form=form, clinic=clinic)


@clinic_bp.route("/patients/<int:patient_id>")
def patient_detail(patient_id: int):
    clinic = _scoped_clinic()
    patient = (
        Patient.query.filter_by(id=patient_id, clinic_id=clinic.id)
        .filter(Patient.deleted_at.is_(None))
        .first_or_404()
    )
    folders = (
        MedicalFolder.query.filter_by(patient_id=patient.id)
        .order_by(MedicalFolder.updated_at.desc())
        .all()
    )
    return render_template(
        "clinic/patients/detail.html", patient=patient, folders=folders, clinic=clinic
    )


# ---- cases board -----------------------------------------------------------


@clinic_bp.route("/cases")
def cases_board():
    clinic = _scoped_clinic()
    doctor_filter = request.args.get("doctor_id", type=int)
    qs = (
        MedicalFolder.query.join(Patient, Patient.id == MedicalFolder.patient_id)
        .filter(Patient.clinic_id == clinic.id)
    )
    if doctor_filter:
        qs = qs.filter(
            or_(
                MedicalFolder.doctor_id == doctor_filter,
                MedicalFolder.assigned_doctor_id == doctor_filter,
            )
        )
    folders = qs.order_by(MedicalFolder.updated_at.desc()).limit(500).all()

    cols: dict[str, list] = {"new": [], "in_progress": [], "follow_up": [], "closed": []}
    for f in folders:
        s = getattr(f.status, "value", f.status)
        cols.setdefault(s, []).append(f)

    doctors = (
        db.session.query(Doctor, User)
        .join(User, User.id == Doctor.user_id)
        .filter(Doctor.clinic_id == clinic.id)
        .order_by(User.full_name)
        .all()
    )
    return render_template(
        "clinic/cases/board.html",
        cols=cols,
        clinic=clinic,
        doctors=doctors,
        doctor_filter=doctor_filter,
    )


@clinic_bp.route("/cases/<int:folder_id>/assign", methods=["POST"])
def case_assign(folder_id: int):
    clinic = _scoped_clinic()
    folder = (
        MedicalFolder.query.join(Patient)
        .filter(MedicalFolder.id == folder_id, Patient.clinic_id == clinic.id)
        .first_or_404()
    )
    doctor_id = request.form.get("doctor_id", type=int)
    if doctor_id:
        doctor = Doctor.query.filter_by(id=doctor_id, clinic_id=clinic.id).first_or_404()
        folder.assigned_doctor_id = doctor.id
    else:
        folder.assigned_doctor_id = None
    db.session.commit()
    log_event(
        "folder.assign",
        "medical_folder",
        folder.id,
        {"assigned_doctor_id": folder.assigned_doctor_id},
        clinic_id=clinic.id,
    )

    # Notify the assigned doctor.
    if folder.assigned_doctor_id and folder.assigned_doctor and folder.assigned_doctor.user:
        from app.services.notifications_service import push

        push(
            user_id=folder.assigned_doctor.user.id,
            type="case_assigned",
            title=f"New case assigned: {folder.title}",
            body=folder.patient.display_name if folder.patient else None,
            link=url_for("doctor.folder_workspace", folder_id=folder.id),
            payload={"folder_id": folder.id},
        )

    flash("Assignment updated.", "success")
    return redirect(request.referrer or url_for("clinic.cases_board"))


# ---- patient export / settings ---------------------------------------------


@clinic_bp.route("/patients/<int:patient_id>/export", methods=["GET"])
def patient_export(patient_id: int):
    from flask import Response, current_app
    from app.services.export_service import patient_export_zip

    if not current_app.config.get("FEATURE_RGPD_EXPORT", True):
        abort(404)
    clinic = _scoped_clinic()
    patient = (
        Patient.query.filter_by(id=patient_id, clinic_id=clinic.id)
        .filter(Patient.deleted_at.is_(None))
        .first_or_404()
    )
    blob = patient_export_zip(patient)
    log_event("patient.export", "patient", patient.id, clinic_id=clinic.id)
    resp = Response(blob, mimetype="application/zip")
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="neurova-patient-{patient.id}-export.zip"'
    )
    return resp


@clinic_bp.route("/patients/<int:patient_id>/delete", methods=["POST"])
def patient_soft_delete(patient_id: int):
    clinic = _scoped_clinic()
    patient = Patient.query.filter_by(id=patient_id, clinic_id=clinic.id).first_or_404()
    patient.deleted_at = datetime.utcnow()
    db.session.commit()
    log_event("patient.delete", "patient", patient.id, clinic_id=clinic.id)
    flash("Patient soft-deleted (30-day purge window).", "warning")
    return redirect(url_for("clinic.patients_list"))


@clinic_bp.route("/settings", methods=["GET", "POST"])
def settings():
    clinic = _scoped_clinic()
    if request.method == "POST":
        clinic.name = (request.form.get("name") or clinic.name).strip()[:200]
        clinic.email = (request.form.get("email") or clinic.email or "").strip().lower() or None
        clinic.phone = (request.form.get("phone") or "").strip() or None
        clinic.address = (request.form.get("address") or "").strip() or None
        clinic.country = (request.form.get("country") or "").strip() or None
        raw_tz = (request.form.get("timezone") or "").strip()
        if not raw_tz:
            clinic.timezone = None
        elif is_valid_timezone(raw_tz):
            clinic.timezone = raw_tz
        else:
            flash("Invalid time zone. Choose a value from the list.", "warning")
        # default modality stored in settings_json
        settings_json = dict(clinic.settings_json or {})
        modality = (request.form.get("default_modality") or "").strip()
        if modality in ("", "mri", "retina_fundus", "ultrasound"):
            if modality:
                settings_json["default_modality"] = modality
            else:
                settings_json.pop("default_modality", None)
        clinic.settings_json = settings_json
        db.session.commit()
        log_event("clinic.settings_update", "clinic", clinic.id, clinic_id=clinic.id)
        flash("Clinic settings saved.", "success")
        return redirect(url_for("clinic.settings"))
    return render_template(
        "clinic/settings.html",
        clinic=clinic,
        timezone_choices=timezone_choices(current=clinic.timezone),
        default_clinic_timezone=DEFAULT_CLINIC_TIMEZONE,
    )
