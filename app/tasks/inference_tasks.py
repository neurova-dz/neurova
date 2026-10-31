"""Celery (and threaded) inference task with the unified progress contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.extensions import celery, db
from app.models.medical import InferenceJob, InferenceResult
from app.services.clinical_report_service import build_clinical_summary
from app.services.inference.compute_env import resolve_compute_device_label
from app.services.inference.contract import (
    InferenceError,
    ModelLoadError,
    TransientStorageError,
    classify_exception,
)
from app.services.storage_service import create_result_dir


def _coerce_progress(value: Any) -> tuple[int, str | None, str | None]:
    """Accept either a percent int or a ``Progress``-like object."""
    if value is None:
        return 0, None, None
    if isinstance(value, (int, float)):
        return int(value), None, None
    percent = getattr(value, "percent", None)
    stage = getattr(value, "stage", None)
    message = getattr(value, "message", None)
    if percent is None:
        return 0, stage, message
    return int(percent), stage, message


def process_inference_job(job_id: int, *, task_id: str | None = None) -> dict[str, Any]:
    """Run a single inference job. Used by Celery and the in-process fallback."""

    def _update(p, *, status: str | None = None) -> None:
        nonlocal job
        percent, stage, message = _coerce_progress(p)
        if status is not None:
            job.status = status
        job.progress = max(0, min(100, percent))
        if stage is not None:
            job.progress_stage = stage[:64]
        if message is not None:
            job.progress_message = message[:255]
        job.last_progress_at = datetime.utcnow()
        db.session.commit()

    job = InferenceJob.query.get(job_id)
    if not job:
        raise ValueError(f"Inference job {job_id} not found")

    status_val = getattr(job.status, "value", job.status)
    if str(status_val) == "done" and job.result is not None:
        return {"job_id": job.id, "status": str(status_val)}
    if str(status_val) == "cancelled":
        return {"job_id": job.id, "status": "cancelled"}

    job.attempt_count = int(job.attempt_count or 0) + 1
    job.error_code = None
    job.error_message = None
    db.session.commit()

    if task_id is not None:
        job.task_id = task_id
    if job.started_at is None:
        job.started_at = datetime.utcnow()

    label = resolve_compute_device_label(job.model_type)
    job.compute_device = label
    db.session.commit()

    _update(5, status="running")

    exam = job.exam
    result_payload: dict[str, Any] = {}
    try:
        if not exam:
            raise InferenceError("Exam record is missing.", code="invalid_input")

        mt = getattr(job.model_type, "value", job.model_type)
        if str(mt) == "brain_3d":
            from app.services.inference.brain_tumor_service import run_brain_inference

            result_dir = create_result_dir(job.id)
            _update(15)
            result_payload = run_brain_inference(
                input_paths=exam.uploaded_files or [exam.uploaded_file_path],
                model_path=celery.conf.get("BRAIN_MODEL_PATH", ""),
                output_dir=result_dir,
                progress_callback=lambda p: _update(p),
            )
        else:
            from app.services.inference.retina_dr_service import run_retina_inference

            result_dir = create_result_dir(job.id)
            _update(25)
            retina_output = run_retina_inference(
                image_path=exam.uploaded_file_path,
                model_path=celery.conf.get("RETINA_MODEL_PATH", ""),
                thresholds_path=celery.conf.get("RETINA_THRESHOLDS_PATH", ""),
                progress_callback=lambda p: _update(p),
            )
            artifacts = _persist_retina_artifacts(
                job_id=job.id,
                result_dir=result_dir,
                source_path=exam.uploaded_file_path,
                payload=retina_output,
            )
            result_payload = {
                "report_json": retina_output,
                "report_path": artifacts.get("report_path"),
                "thumbnail_path": artifacts.get("thumbnail_path"),
                "probability_chart_path": artifacts.get("chart_path"),
                "diagnosis_label": retina_output.get("diagnosis"),
                "confidence": retina_output.get("confidence"),
            }

    except Exception as exc:
        db.session.rollback()
        failed = InferenceJob.query.get(job_id)
        if failed:
            failed.status = "failed"
            failed.progress = 100
            failed.error_message = str(exc)[:5000]
            failed.error_code = classify_exception(exc)
            failed.finished_at = datetime.utcnow()
            failed.last_progress_at = datetime.utcnow()
            db.session.commit()
            _notify_outcome(failed, success=False)
        raise

    _update(95, status="running")
    if job.result:
        result = job.result
    else:
        result = InferenceResult(job_id=job.id)
        db.session.add(result)

    raw = result_payload.get("report_json")
    mt = getattr(job.model_type, "value", job.model_type)
    if isinstance(raw, dict):
        result_payload["report_json"] = build_clinical_summary(
            str(mt),
            raw,
            diagnosis_label=result_payload.get("diagnosis_label"),
            confidence=result_payload.get("confidence"),
        )

    for key, value in result_payload.items():
        if hasattr(result, key):
            setattr(result, key, value)

    job.status = "done"
    job.progress = 100
    job.finished_at = datetime.utcnow()
    job.last_progress_at = datetime.utcnow()
    job.error_code = None
    job.error_message = None
    db.session.commit()

    _notify_outcome(job, success=True)
    return {"job_id": job.id, "status": job.status}


def _persist_retina_artifacts(*, job_id: int, result_dir: str, source_path: str, payload: dict) -> dict:
    """Write retina thumbnail + probability chart + report JSON to disk."""
    import json
    from pathlib import Path

    out: dict[str, str | None] = {}
    base = Path(result_dir)
    base.mkdir(parents=True, exist_ok=True)

    # report.json
    try:
        report_path = base / "report.json"
        report_path.write_text(json.dumps(payload, default=str, indent=2))
        out["report_path"] = str(report_path)
    except Exception:  # noqa: BLE001
        out["report_path"] = None

    # thumbnail (resized copy of source)
    try:
        from PIL import Image

        if source_path:
            with Image.open(source_path) as im:
                im.thumbnail((512, 512))
                thumb = base / "thumbnail.jpg"
                im.convert("RGB").save(thumb, "JPEG", quality=85)
                out["thumbnail_path"] = str(thumb)
        else:
            out["thumbnail_path"] = None
    except Exception:  # noqa: BLE001 — Pillow optional
        out["thumbnail_path"] = None

    # probability bar chart
    try:
        probs = (payload.get("probabilities") or {})
        if probs:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            labels = list(probs.keys())
            values = [float(probs[k]) for k in labels]
            fig, ax = plt.subplots(figsize=(5, 3), dpi=120)
            ax.barh(labels, values, color="#0d9488")
            ax.set_xlim(0, 1)
            ax.set_xlabel("Probability")
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            fig.tight_layout()
            chart_path = base / "probabilities.png"
            fig.savefig(chart_path)
            plt.close(fig)
            out["chart_path"] = str(chart_path)
        else:
            out["chart_path"] = None
    except Exception:  # noqa: BLE001
        out["chart_path"] = None
    return out


def _notify_outcome(job: InferenceJob, *, success: bool) -> None:
    """Push notifications to creator and assignee when a job finishes."""
    try:
        from flask import url_for

        from app.services.notifications_service import push_many

        folder = job.exam.folder if job.exam else None
        if not folder:
            return
        recipient_user_ids: set[int] = set()
        if folder.doctor and folder.doctor.user:
            recipient_user_ids.add(folder.doctor.user.id)
        if folder.assigned_doctor and folder.assigned_doctor.user:
            recipient_user_ids.add(folder.assigned_doctor.user.id)
        if job.enqueued_by_user_id:
            recipient_user_ids.add(job.enqueued_by_user_id)

        if not recipient_user_ids:
            return

        title = f"Analysis #{job.id} — {'completed' if success else 'failed'}"
        body = folder.title
        link = url_for("results.view_result", job_id=job.id)
        push_many(
            list(recipient_user_ids),
            type="job_done" if success else "job_failed",
            title=title,
            body=body,
            link=link,
            payload={"job_id": job.id, "model_type": getattr(job.model_type, "value", job.model_type)},
        )
    except Exception:  # noqa: BLE001 — never let notifications break a successful job
        pass


@celery.task(
    bind=True,
    name="run_inference_job",
    autoretry_for=(ModelLoadError, TransientStorageError),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=2,
    acks_late=True,
)
def run_inference_job(self, job_id: int):
    return process_inference_job(job_id, task_id=getattr(self.request, "id", None))
