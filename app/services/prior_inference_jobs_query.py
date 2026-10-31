"""Prior completed inference jobs for a patient — raw SQL only (MariaDB-safe).

ORM ``order_by`` / ``UnaryExpression`` paths have been observed to still emit
PostgreSQL-only ``NULLS LAST`` in some environments; this module uses
:class:`sqlalchemy.text` so the server only ever sees explicit MySQL/MariaDB SQL.
"""

from __future__ import annotations

from sqlalchemy import text

from app.extensions import db
from app.models.medical import InferenceJob


_PRIOR_IDS_SQL = text(
    """
    SELECT inference_jobs.id
    FROM inference_jobs
    INNER JOIN exams ON exams.id = inference_jobs.exam_id
    INNER JOIN medical_folders ON medical_folders.id = exams.folder_id
    WHERE medical_folders.patient_id = :patient_id
      AND inference_jobs.model_type = :model_type
      AND inference_jobs.id != :exclude_id
      AND inference_jobs.status = 'done'
    ORDER BY (inference_jobs.finished_at IS NULL) ASC,
             inference_jobs.finished_at DESC,
             inference_jobs.created_at DESC
    LIMIT :lim
    """
)


def prior_done_job_ids(
    *,
    patient_id: int,
    model_type: str,
    exclude_job_id: int,
    limit: int = 5,
) -> list[int]:
    rows = db.session.execute(
        _PRIOR_IDS_SQL,
        {
            "patient_id": patient_id,
            "model_type": model_type,
            "exclude_id": exclude_job_id,
            "lim": limit,
        },
    ).all()
    return [int(r[0]) for r in rows]


def prior_done_jobs(
    *,
    patient_id: int,
    model_type: str,
    exclude_job_id: int,
    limit: int = 5,
) -> list[InferenceJob]:
    ids = prior_done_job_ids(
        patient_id=patient_id,
        model_type=model_type,
        exclude_job_id=exclude_job_id,
        limit=limit,
    )
    if not ids:
        return []
    rows = InferenceJob.query.filter(InferenceJob.id.in_(ids)).all()
    by_id = {j.id: j for j in rows}
    return [by_id[i] for i in ids if i in by_id]
