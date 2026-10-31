"""Aggregations for the superadmin overview."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.medical import (
    Exam,
    InferenceJob,
    MedicalFolder,
    Patient,
)
from app.models.user import User


def _days_ago(n: int) -> datetime:
    return datetime.utcnow() - timedelta(days=n)


def platform_kpis() -> dict[str, Any]:
    now = datetime.utcnow()
    return {
        "clinics_total": Clinic.query.count(),
        "clinics_active": Clinic.query.filter_by(is_active=True).count(),
        "users_total": User.query.count(),
        "doctors_total": Doctor.query.count(),
        "patients_total": Patient.query.filter(Patient.deleted_at.is_(None)).count(),
        "exams_total": Exam.query.count(),
        "active_folders": MedicalFolder.query.filter(
            MedicalFolder.status.in_(("new", "in_progress", "follow_up"))
        ).count(),
        "jobs_24h": InferenceJob.query.filter(InferenceJob.created_at >= _days_ago(1)).count(),
        "jobs_7d": InferenceJob.query.filter(InferenceJob.created_at >= _days_ago(7)).count(),
        "jobs_30d": InferenceJob.query.filter(InferenceJob.created_at >= _days_ago(30)).count(),
        "jobs_running": InferenceJob.query.filter(InferenceJob.status == "running").count(),
        "jobs_queued": InferenceJob.query.filter(InferenceJob.status == "queued").count(),
        "jobs_failed_30d": InferenceJob.query.filter(
            InferenceJob.status == "failed", InferenceJob.created_at >= _days_ago(30)
        ).count(),
        "now": now,
    }


def jobs_per_day(days: int = 14) -> list[dict]:
    """Return a list of {date, count} entries for the last ``days`` days."""
    cutoff = _days_ago(days)
    rows = (
        db.session.query(
            func.date(InferenceJob.created_at).label("d"),
            func.count(InferenceJob.id),
        )
        .filter(InferenceJob.created_at >= cutoff)
        .group_by(func.date(InferenceJob.created_at))
        .order_by(func.date(InferenceJob.created_at))
        .all()
    )
    return [{"date": str(d), "count": int(c)} for d, c in rows]


def modality_split() -> list[dict]:
    rows = (
        db.session.query(InferenceJob.model_type, func.count(InferenceJob.id))
        .group_by(InferenceJob.model_type)
        .all()
    )
    return [{"label": str(getattr(m, "value", m)), "count": int(c)} for m, c in rows]


def top_clinics_by_jobs(limit: int = 8) -> list[dict]:
    rows = (
        db.session.query(Clinic.name, func.count(InferenceJob.id))
        .join(Patient, Patient.clinic_id == Clinic.id)
        .join(MedicalFolder, MedicalFolder.patient_id == Patient.id)
        .join(Exam, Exam.folder_id == MedicalFolder.id)
        .join(InferenceJob, InferenceJob.exam_id == Exam.id)
        .group_by(Clinic.id)
        .order_by(func.count(InferenceJob.id).desc())
        .limit(limit)
        .all()
    )
    return [{"clinic": name, "count": int(c)} for name, c in rows]


def clinic_summary_rows():
    """Per-clinic aggregations for the clinics list page."""
    return (
        db.session.query(
            Clinic.id,
            Clinic.name,
            Clinic.slug,
            Clinic.is_active,
            Clinic.plan,
            Clinic.created_at,
            func.count(func.distinct(Doctor.id)).label("doctors_count"),
            func.count(func.distinct(Patient.id)).label("patients_count"),
        )
        .outerjoin(Doctor, Doctor.clinic_id == Clinic.id)
        .outerjoin(
            Patient,
            (Patient.clinic_id == Clinic.id) & (Patient.deleted_at.is_(None)),
        )
        .group_by(Clinic.id)
        .order_by(Clinic.name)
    )
