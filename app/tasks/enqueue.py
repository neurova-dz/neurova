from __future__ import annotations

import threading
from typing import Any

from flask import Flask

from app.extensions import celery
from app.tasks.inference_tasks import process_inference_job, run_inference_job


def enqueue_inference_job(app: Flask, job_id: int) -> dict[str, Any]:
    """
    Enqueue inference through Celery when available.
    If broker/worker isn't available (common in local dev), fall back to an in-process
    background thread so the UI still receives progress updates.
    """
    # If the broker is up but no worker is running, Celery will accept the message
    # and the job will stay "queued" forever. We proactively ping workers and only
    # use Celery when at least one worker replies.
    try:
        insp = celery.control.inspect(timeout=1)
        pong = insp.ping() or {}
        if not pong:
            raise RuntimeError("No celery workers online")

        celery_task = run_inference_job.delay(job_id)
        return {"mode": "celery", "task_id": celery_task.id}
    except Exception:
        def _runner():
            with app.app_context():
                process_inference_job(job_id, task_id=None)

        t = threading.Thread(target=_runner, name=f"inference-job-{job_id}", daemon=True)
        t.start()
        return {"mode": "thread", "task_id": None}

