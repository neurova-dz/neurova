"""Results display, JSON payload, file streaming and PDF export."""

from __future__ import annotations

import os

from flask import Blueprint, abort, current_app, jsonify, render_template, send_file
from flask_login import current_user, login_required
from app.extensions import db
from app.models.medical import Exam, InferenceJob, MedicalFolder
from app.services.access_service import can_access_inference_job
from app.services.audit_service import log_event
from app.services.clinical_report_service import extract_display_summary
from app.services.diagnostic_helper_service import helper_for_job
from app.services.prior_inference_jobs_query import prior_done_jobs
from app.services.job_status_service import reconcile_inference_job
from app.services.pdf_report_service import render_job_pdf
from app.services.storage_service import to_public_path


results_bp = Blueprint("results", __name__, url_prefix="/results")


def _brain_multiclass_asset_urls(result) -> dict[str, str]:
    """Public URLs for slice PNGs with BraTS colormap (paths live in report ``artifacts``)."""
    if not result or not result.report_json or not isinstance(result.report_json, dict):
        return {}
    rj = result.report_json
    inner = rj.get("raw") if isinstance(rj.get("raw"), dict) else rj
    arts = inner.get("artifacts") if isinstance(inner, dict) else None
    if not isinstance(arts, dict):
        return {}
    root = os.path.abspath(current_app.config["RESULTS_FOLDER"])
    out: dict[str, str] = {}
    for plane in ("axial", "coronal", "sagittal"):
        key = f"{plane}_multiclass"
        path = arts.get(key)
        if not path or not isinstance(path, str):
            continue
        try:
            abs_p = os.path.abspath(path)
        except Exception:  # noqa: BLE001
            continue
        if not abs_p.startswith(root) or not os.path.isfile(abs_p):
            continue
        try:
            out[f"{plane}_multiclass_path"] = to_public_path(abs_p)
        except Exception:  # noqa: BLE001
            continue
    return out


def _candidate_compare_jobs(job: InferenceJob):
    """List previous completed jobs of the same modality for the same patient."""
    if not job.exam or not job.exam.folder or not job.exam.folder.patient:
        return []
    mt = str(getattr(job.model_type, "value", job.model_type))
    return prior_done_jobs(
        patient_id=job.exam.folder.patient_id,
        model_type=mt,
        exclude_job_id=job.id,
        limit=10,
    )


@results_bp.route("/jobs/<int:job_id>", methods=["GET"])
@login_required
def view_result(job_id):
    job = InferenceJob.query.get_or_404(job_id)
    if not can_access_inference_job(current_user, job):
        abort(403)

    stale_minutes = int(current_app.config.get("INFERENCE_JOB_STALE_MINUTES", 45))
    reconcile_inference_job(job, stale_minutes=stale_minutes)
    db.session.refresh(job)

    if job.status_value != "done":
        can_cancel = (
            current_user.is_superadmin
            or current_user.is_clinic_admin
            or (job.exam and job.exam.folder and current_user.doctor_id == job.exam.folder.doctor_id)
        ) and job.status_value in ("queued", "running")
        return render_template(
            "results/pending.html",
            job=job,
            can_cancel=can_cancel,
        )

    result = job.result
    assets = {}
    for key in (
        "axial_overlay_path",
        "coronal_overlay_path",
        "sagittal_overlay_path",
        "html_3d_path",
        "thumbnail_path",
        "probability_chart_path",
    ):
        file_path = getattr(result, key, None) if result else None
        if file_path:
            try:
                assets[key] = to_public_path(file_path)
            except Exception:  # noqa: BLE001
                pass
    assets.update(_brain_multiclass_asset_urls(result))

    clinical_summary = extract_display_summary(result.report_json if result else None)
    clinic_settings = (
        job.exam.folder.patient.clinic.settings_json
        if job.exam and job.exam.folder and job.exam.folder.patient and job.exam.folder.patient.clinic
        else {}
    )
    helper_block = helper_for_job(job, clinic_settings=clinic_settings)
    compare_jobs = _candidate_compare_jobs(job)

    log_event(
        "result.view",
        "inference_job",
        job.id,
        {"exam_id": job.exam_id},
        clinic_id=(job.exam.folder.patient.clinic_id if job.exam and job.exam.folder and job.exam.folder.patient else None),
    )
    return render_template(
        "results/view.html",
        job=job,
        result=result,
        assets=assets,
        clinical_summary=clinical_summary,
        helper_block=helper_block,
        compare_jobs=compare_jobs,
    )


@results_bp.route("/api/jobs/<int:job_id>", methods=["GET"])
@login_required
def job_result_payload(job_id):
    job = InferenceJob.query.get_or_404(job_id)
    if not can_access_inference_job(current_user, job):
        abort(403)
    result = job.result
    if not result:
        return jsonify({"error": "No result yet"}), 404
    clinical = extract_display_summary(result.report_json)
    mc_urls = _brain_multiclass_asset_urls(result)
    api_assets: dict[str, str | None] = {
        "axial": to_public_path(result.axial_overlay_path) if result.axial_overlay_path else None,
        "coronal": to_public_path(result.coronal_overlay_path) if result.coronal_overlay_path else None,
        "sagittal": to_public_path(result.sagittal_overlay_path) if result.sagittal_overlay_path else None,
        "axial_multiclass": mc_urls.get("axial_multiclass_path"),
        "coronal_multiclass": mc_urls.get("coronal_multiclass_path"),
        "sagittal_multiclass": mc_urls.get("sagittal_multiclass_path"),
        "view3d": to_public_path(result.html_3d_path) if result.html_3d_path else None,
        "thumbnail": to_public_path(result.thumbnail_path) if result.thumbnail_path else None,
        "probabilities": to_public_path(result.probability_chart_path) if result.probability_chart_path else None,
    }
    return jsonify(
        {
            "job_id": job.id,
            "status": job.status_value,
            "clinical_summary": clinical,
            "report": result.report_json,
            "diagnosis_label": result.diagnosis_label,
            "confidence": result.confidence,
            "assets": api_assets,
        }
    )


@results_bp.route("/jobs/<int:job_id>/compare/<int:other_id>", methods=["GET"])
@login_required
def compare(job_id: int, other_id: int):
    job = InferenceJob.query.get_or_404(job_id)
    other = InferenceJob.query.get_or_404(other_id)
    if not can_access_inference_job(current_user, job) or not can_access_inference_job(
        current_user, other
    ):
        abort(403)
    a = extract_display_summary(job.result.report_json if job.result else None)
    b = extract_display_summary(other.result.report_json if other.result else None)
    return jsonify(
        {
            "a": {"job_id": job.id, "summary": a, "created_at": job.created_at.isoformat()},
            "b": {"job_id": other.id, "summary": b, "created_at": other.created_at.isoformat()},
        }
    )


@results_bp.route("/jobs/<int:job_id>/pdf", methods=["GET"])
@login_required
def job_pdf(job_id: int):
    job = InferenceJob.query.get_or_404(job_id)
    if not can_access_inference_job(current_user, job):
        abort(403)
    if job.status_value != "done":
        abort(404)
    clinical = extract_display_summary(job.result.report_json if job.result else None)
    clinic_settings = (
        job.exam.folder.patient.clinic.settings_json
        if job.exam and job.exam.folder and job.exam.folder.patient and job.exam.folder.patient.clinic
        else {}
    )
    helper_block = helper_for_job(job, clinic_settings=clinic_settings)
    log_event("result.download_pdf", "inference_job", job.id)
    return render_job_pdf(job, job.result, clinical, helper_block)


@results_bp.route("/files/<path:relative_path>", methods=["GET"])
@login_required
def serve_result_file(relative_path):
    root = os.path.abspath(current_app.config["RESULTS_FOLDER"])
    abs_path = os.path.abspath(os.path.join(root, relative_path))
    if not abs_path.startswith(root):
        abort(403)
    if not os.path.exists(abs_path):
        abort(404)
    return send_file(abs_path)
