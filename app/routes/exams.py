"""Exam upload, job status polling, cancellation, and source file streaming."""

from __future__ import annotations

import mimetypes
import os
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import celery, db
from app.models.medical import Exam, InferenceJob, MedicalFolder
from app.security.decorators import role_required
from app.services.access_service import (
    can_access_folder,
    can_access_inference_job,
    can_modify_folder,
)
from app.services.audit_service import log_event
from app.services.job_status_service import live_celery_state, reconcile_inference_job
from app.services.storage_service import save_upload
from app.specialty import normalize_doctor_specialty
from app.tasks.enqueue import enqueue_inference_job


exams_bp = Blueprint("exams", __name__, url_prefix="/exams")


# ---- helpers --------------------------------------------------------------

VALID_MODALITIES = {"mri", "retina_fundus"}
ALLOWED_EXTS_BY_MODALITY = {
    "mri": {".nii", ".nii.gz"},
    "retina_fundus": {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"},
}


def _ext_lower(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".nii.gz"):
        return ".nii.gz"
    return Path(name).suffix


def _validate_files(modality: str, files) -> tuple[bool, str | None]:
    if modality not in VALID_MODALITIES:
        return False, "Invalid modality."
    if modality == "mri":
        if len(files) != 4:
            return False, "Brain MRI requires exactly 4 NIfTI files (t1c, t1n, t2f, t2w)."
    else:
        if len(files) != 1:
            return False, "Retina fundus requires exactly 1 image file."
    allowed = ALLOWED_EXTS_BY_MODALITY[modality]
    for f in files:
        ext = _ext_lower(f.filename or "")
        if ext not in allowed:
            return False, f"File '{f.filename}' has unsupported extension '{ext}'."
        if not (f.filename or "").strip():
            return False, "All uploaded files must have a filename."
    return True, None


def _job_field_json(value):
    if value is None:
        return None
    return getattr(value, "value", str(value))


# ---- views ---------------------------------------------------------------


@exams_bp.route("/new/<int:folder_id>", methods=["GET"])
@login_required
def new_exam(folder_id):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        abort(403)
    prefs = current_user.preferences_json or {}
    return render_template(
        "exams/new.html",
        folder=folder,
        doctor_workflow=normalize_doctor_specialty(getattr(current_user, "specialty", None)),
        upload_default_modality=prefs.get("default_modality") or "",
    )


@exams_bp.route("/create/<int:folder_id>", methods=["POST"])
@login_required
def create_exam(folder_id):
    folder = MedicalFolder.query.get_or_404(folder_id)
    if not can_modify_folder(current_user, folder):
        abort(403)

    modality = request.form.get("modality")
    notes = (request.form.get("notes") or "").strip()
    laterality = request.form.get("laterality") or None
    files = request.files.getlist("files")
    single_file = request.files.get("file")
    if not files and single_file:
        files = [single_file]
    files = [f for f in files if f and f.filename]

    ok, err = _validate_files(modality or "", files)
    if not ok:
        flash(err or "Invalid upload.", "warning")
        return redirect(url_for("exams.new_exam", folder_id=folder.id))

    if modality == "retina_fundus" and laterality not in (None, "", "left", "right", "both"):
        laterality = None

    model_type = "brain_3d" if modality == "mri" else "diabetic_retinopathy"

    try:
        stored_paths = [save_upload(f, subfolder=f"folder_{folder.id}") for f in files]
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("exams.new_exam", folder_id=folder.id))

    stored_path = stored_paths[0]
    exam = Exam(
        folder_id=folder.id,
        modality=modality,
        laterality=laterality if laterality in ("left", "right", "both") else None,
        uploaded_file_path=stored_path,
        uploaded_files=stored_paths,
        exam_date=datetime.utcnow(),
        notes=notes or None,
    )
    db.session.add(exam)
    db.session.flush()

    job = InferenceJob(
        exam_id=exam.id,
        model_type=model_type,
        status="queued",
        progress=0,
        enqueued_by_user_id=current_user.id,
    )
    db.session.add(job)
    db.session.commit()

    enqueue_meta = enqueue_inference_job(current_app._get_current_object(), job.id)
    job.task_id = enqueue_meta.get("task_id")
    db.session.commit()

    log_event(
        "exam.upload",
        "exam",
        exam.id,
        {
            "folder_id": folder.id,
            "patient_id": folder.patient_id,
            "modality": modality,
            "model_type": model_type,
            "files": len(stored_paths),
        },
        clinic_id=folder.patient.clinic_id if folder.patient else None,
    )
    return redirect(url_for("results.view_result", job_id=job.id))


@exams_bp.route("/jobs/<int:job_id>/status", methods=["GET"])
@login_required
def get_job_status(job_id):
    job = InferenceJob.query.get_or_404(job_id)
    if not can_access_inference_job(current_user, job):
        abort(403)
    stale_minutes = int(current_app.config.get("INFERENCE_JOB_STALE_MINUTES", 45))
    reconcile_inference_job(job, stale_minutes=stale_minutes)
    db.session.refresh(job)
    result_id = job.result.id if job.result else None
    resp = jsonify(
        {
            "job_id": job.id,
            "status": _job_field_json(job.status),
            "progress": int(job.progress or 0),
            "progress_stage": job.progress_stage,
            "progress_message": job.progress_message,
            "compute_device": job.compute_device,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "result_id": result_id,
            "last_progress_at": (
                job.last_progress_at.isoformat() + "Z" if job.last_progress_at else None
            ),
            "celery_state": live_celery_state(job.task_id),
        }
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@exams_bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel_job(job_id):
    job = InferenceJob.query.get_or_404(job_id)
    if not can_access_inference_job(current_user, job):
        abort(403)
    if not (
        current_user.is_superadmin
        or current_user.is_clinic_admin
        or (job.exam and job.exam.folder and current_user.doctor_id == job.exam.folder.doctor_id)
    ):
        flash("Only the case owner or a clinic admin can cancel this analysis.", "warning")
        return redirect(url_for("results.view_result", job_id=job.id))

    st = _job_field_json(job.status)
    if st not in ("queued", "running"):
        flash("This job cannot be cancelled.", "info")
        return redirect(url_for("results.view_result", job_id=job.id))
    job.status = "cancelled"
    job.finished_at = job.finished_at or datetime.utcnow()
    job.error_message = "Cancelled by clinician."
    job.error_code = "cancelled"
    db.session.commit()
    if job.task_id:
        try:
            celery.control.revoke(job.task_id, terminate=True)
        except Exception:  # noqa: BLE001
            pass
    log_event(
        "job.cancel",
        "inference_job",
        job.id,
        clinic_id=job.exam.folder.patient.clinic_id if job.exam and job.exam.folder and job.exam.folder.patient else None,
    )
    flash("Analysis cancelled.", "success")
    return redirect(
        url_for("doctor.patient_detail", patient_id=job.exam.folder.patient_id)
        if job.exam and job.exam.folder
        else url_for("doctor.dashboard")
    )


@exams_bp.route("/exams/<int:exam_id>/source", methods=["GET"])
@login_required
def exam_source_file(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if not can_access_folder(current_user, exam.folder):
        abort(403)
    path = exam.uploaded_file_path
    if not path or not os.path.isfile(path):
        abort(404)
    root = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(root):
        abort(403)
    mtype, _ = mimetypes.guess_type(abs_path)
    return send_file(abs_path, mimetype=mtype or "application/octet-stream")
