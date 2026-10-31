"""
Reconcile inference_jobs with Celery task state and wall-clock staleness so the UI
does not spin forever on dead workers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from celery.result import AsyncResult

from app.extensions import celery, db
from app.models.medical import InferenceJob


def _anchor_time(job: InferenceJob) -> datetime | None:
    return job.last_progress_at or job.started_at or job.created_at


def reconcile_inference_job(job: InferenceJob, *, stale_minutes: int) -> bool:
    """
    Update job row if Celery reports a terminal state or the job is stale.
    Returns True if the row was committed with a change.
    """
    changed = False
    now = datetime.utcnow()

    if job.status in ("done", "failed", "timed_out", "cancelled"):
        return False

    if job.task_id:
        try:
            async_result = AsyncResult(job.task_id, app=celery)
            state = async_result.state
            if state == "FAILURE":
                if job.status not in ("failed", "done", "timed_out", "cancelled"):
                    job.status = "failed"
                    job.progress = 100
                    job.error_message = str(async_result.info) if async_result.info else "Celery FAILURE"
                    job.finished_at = now
                    job.last_known_async_state = state[:32] if state else None
                    changed = True
            elif state == "REVOKED":
                if job.status not in ("cancelled", "done", "failed", "timed_out"):
                    job.status = "cancelled"
                    job.progress = job.progress or 0
                    job.finished_at = now
                    job.error_message = "Job was revoked or cancelled."
                    job.last_known_async_state = state[:32] if state else None
                    changed = True
        except Exception:  # noqa: BLE001 — broker errors should not break status API
            pass

    if not changed and job.status == "running":
        anchor = _anchor_time(job)
        if anchor and (now - anchor) > timedelta(minutes=stale_minutes):
            job.status = "timed_out"
            job.progress = job.progress or 0
            job.finished_at = now
            job.error_message = (
                "No progress was reported for an extended period; the worker may have stopped."
            )
            changed = True

    if changed:
        db.session.commit()

    return changed


def live_celery_state(task_id: str | None) -> str | None:
    if not task_id:
        return None
    try:
        return AsyncResult(task_id, app=celery).state
    except Exception:  # noqa: BLE001
        return None

