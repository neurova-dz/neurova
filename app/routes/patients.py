"""Patients & folders (legacy URLs kept for compatibility)."""

from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models.doctor import Doctor
from app.routes.patient_creation import respond_clinician_patient_new
from app.models.medical import (
    AuditLog,
    Exam,
    FolderShare,
    MedicalFolder,
    Patient,
)
from app.models.user import User
from app.services.access_service import (
    can_access_folder,
    can_modify_folder,
    doctor_clinic_colleagues_query,
    visible_folders_for_patient_query,
    visible_patients_query,
)
from app.services.audit_service import log_event


patients_bp = Blueprint("patients", __name__, url_prefix="/patients")


def _patient_timeline(patient_id: int):
    """Recent audit rows for this patient's folders/exams/jobs."""
    folder_ids = [f.id for f in MedicalFolder.query.filter_by(patient_id=patient_id).all()]
    if not folder_ids:
        return []
    folder_id_strs = [str(i) for i in folder_ids]
    rows = list(
        AuditLog.query.filter(
            AuditLog.resource_type == "medical_folder",
            AuditLog.resource_id.in_(folder_id_strs),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(20)
        .all()
    )
    exams = Exam.query.filter(Exam.folder_id.in_(folder_ids)).all()
    exam_id_strs = [str(e.id) for e in exams]
    if exam_id_strs:
        rows.extend(
            AuditLog.query.filter(
                AuditLog.resource_type == "exam",
                AuditLog.resource_id.in_(exam_id_strs),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(20)
            .all()
        )
    rows.sort(key=lambda x: x.created_at, reverse=True)
    return rows[:40]


@patients_bp.route("/", methods=["GET"])
@login_required
def list_patients():
    if current_user.is_superadmin:
        return redirect(url_for("admin.overview"))
    if current_user.is_clinic_admin:
        return redirect(url_for("clinic.patients_list"))
    return redirect(url_for("doctor.patients"))


@patients_bp.route("/new", methods=["GET", "POST"])
@login_required
def patient_new():
    """`/patients/new` — avoids relying on `/dashboard/` URL for bookmarks and links."""

    return respond_clinician_patient_new(cancel_url=url_for("doctor.patients"))


@patients_bp.route("/create", methods=["POST"])
@login_required
def create_patient():
    """Doctor creates a patient on the fly."""
    if current_user.is_superadmin:
        abort(403)
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    if not first_name or not last_name:
        flash("First and last name are required.", "warning")
        return redirect(request.referrer or url_for("doctor.patients"))

    bd = None
    if request.form.get("birth_date"):
        try:
            bd = datetime.strptime(request.form["birth_date"], "%Y-%m-%d").date()
        except ValueError:
            flash("Birth date must be YYYY-MM-DD.", "warning")
            return redirect(request.referrer or url_for("doctor.patients"))

    patient = Patient(
        clinic_id=current_user.clinic_id,
        first_name=first_name,
        last_name=last_name,
        birth_date=bd,
        sex=(request.form.get("sex") or "").strip() or None,
        phone=(request.form.get("phone") or "").strip() or None,
        mrn=(request.form.get("mrn") or "").strip() or None,
        clinical_notes=(request.form.get("clinical_notes") or "").strip() or None,
    )
    db.session.add(patient)
    db.session.commit()
    log_event("patient.create", "patient", patient.id, clinic_id=current_user.clinic_id)
    return redirect(url_for("doctor.patient_detail", patient_id=patient.id))


@patients_bp.route("/<int:patient_id>", methods=["GET"])
@login_required
def view_patient(patient_id):
    if current_user.is_clinic_admin:
        return redirect(url_for("clinic.patient_detail", patient_id=patient_id))
    return redirect(url_for("doctor.patient_detail", patient_id=patient_id))


@patients_bp.route("/<int:patient_id>/folders", methods=["POST"])
@login_required
def create_folder(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    if patient.clinic_id != current_user.clinic_id and not current_user.is_superadmin:
        abort(403)
    if current_user.doctor_id is None:
        abort(403)
    title = (request.form.get("title") or "").strip()
    diagnosis_context = (request.form.get("diagnosis_context") or "").strip()
    status = request.form.get("status") or "new"
    if status not in {"new", "in_progress", "follow_up", "closed"}:
        status = "new"
    if not title:
        flash("Folder title is required.", "warning")
        return redirect(request.referrer or url_for("doctor.patient_detail", patient_id=patient.id))
    folder = MedicalFolder(
        patient_id=patient.id,
        doctor_id=current_user.doctor_id,
        title=title,
        diagnosis_context=diagnosis_context,
        status=status,
    )
    db.session.add(folder)
    db.session.commit()
    log_event("folder.create", "medical_folder", folder.id, {"status": status},
              clinic_id=patient.clinic_id)
    return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))


@patients_bp.route("/folders/<int:folder_id>/status", methods=["PATCH"])
@login_required
def update_folder_status(folder_id):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        return jsonify({"error": "Forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if status not in {"new", "in_progress", "follow_up", "closed"}:
        return jsonify({"error": "Invalid status"}), 400
    folder.status = status
    db.session.commit()
    log_event("folder.status_update", "medical_folder", folder.id, {"status": status},
              clinic_id=folder.patient.clinic_id if folder.patient else None)
    return jsonify({"ok": True, "folder_id": folder.id, "status": status})


@patients_bp.route("/folders/<int:folder_id>/share", methods=["POST"])
@login_required
def share_folder(folder_id):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        flash("Only the case owner or a clinic admin can share.", "warning")
        return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))
    colleague_id = request.form.get("colleague_id", type=int)
    colleague = Doctor.query.get(colleague_id) if colleague_id else None
    if (
        not colleague
        or colleague.clinic_id != current_user.clinic_id
        or colleague.id == current_user.doctor_id
    ):
        flash("Select a valid colleague in your clinic.", "warning")
        return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))
    existing = FolderShare.query.filter_by(
        folder_id=folder.id, shared_with_doctor_id=colleague.id
    ).first()
    if existing:
        flash("That colleague already has access.", "info")
        return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))
    by_doctor_id = current_user.doctor_id or colleague.id
    db.session.add(
        FolderShare(
            folder_id=folder.id,
            shared_with_doctor_id=colleague.id,
            shared_by_doctor_id=by_doctor_id,
        )
    )
    db.session.commit()
    log_event(
        "folder.share",
        "medical_folder",
        folder.id,
        {"with_doctor_id": colleague.id},
        clinic_id=folder.patient.clinic_id if folder.patient else None,
    )

    # Notify the colleague
    if colleague.user:
        from app.services.notifications_service import push

        push(
            user_id=colleague.user.id,
            type="share_received",
            title=f"Case shared: {folder.title}",
            body=folder.patient.display_name if folder.patient else None,
            link=url_for("doctor.folder_workspace", folder_id=folder.id),
            payload={"folder_id": folder.id},
        )

    flash(f"Shared with {colleague.user.full_name if colleague.user else colleague.id}.", "success")
    return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))


@patients_bp.route("/folders/<int:folder_id>/unshare/<int:colleague_id>", methods=["POST"])
@login_required
def unshare_folder(folder_id, colleague_id):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        flash("Only the case owner or a clinic admin can remove sharing.", "warning")
        return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))
    share = FolderShare.query.filter_by(
        folder_id=folder.id, shared_with_doctor_id=colleague_id
    ).first()
    if share:
        db.session.delete(share)
        db.session.commit()
        log_event(
            "folder.unshare",
            "medical_folder",
            folder.id,
            {"with_doctor_id": colleague_id},
            clinic_id=folder.patient.clinic_id if folder.patient else None,
        )
        flash("Sharing removed.", "success")
    return redirect(url_for("doctor.folder_workspace", folder_id=folder.id))
