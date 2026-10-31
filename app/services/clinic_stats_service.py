"""Aggregations scoped to a single clinic (clinic admin dashboard)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from app.extensions import db
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


def clinic_kpis(clinic_id: int) -> dict[str, Any]:
    folder_q = MedicalFolder.query.join(Patient).filter(Patient.clinic_id == clinic_id)
    job_q = (
        InferenceJob.query.join(Exam, Exam.id == InferenceJob.exam_id)
        .join(MedicalFolder, MedicalFolder.id == Exam.folder_id)
        .join(Patient, Patient.id == MedicalFolder.patient_id)
        .filter(Patient.clinic_id == clinic_id)
    )
    return {
        "doctors": Doctor.query.filter_by(clinic_id=clinic_id).count(),
        "active_doctors": (
            db.session.query(User)
            .filter(User.clinic_id == clinic_id, User.is_active_account.is_(True))
            .count()
        ),
        "patients": (
            Patient.query.filter_by(clinic_id=clinic_id)
            .filter(Patient.deleted_at.is_(None))
            .count()
        ),
        "active_folders": folder_q.filter(
            MedicalFolder.status.in_(("new", "in_progress", "follow_up"))
        ).count(),
        "treated_cases": folder_q.filter(MedicalFolder.status == "closed").count(),
        "jobs_24h": job_q.filter(InferenceJob.created_at >= _days_ago(1)).count(),
        "jobs_7d": job_q.filter(InferenceJob.created_at >= _days_ago(7)).count(),
        "jobs_30d": job_q.filter(InferenceJob.created_at >= _days_ago(30)).count(),
        "jobs_pending": job_q.filter(
            InferenceJob.status.in_(("queued", "running"))
        ).count(),
    }


def status_breakdown(clinic_id: int) -> list[dict]:
    rows = (
        db.session.query(MedicalFolder.status, func.count(MedicalFolder.id))
        .join(Patient)
        .filter(Patient.clinic_id == clinic_id)
        .group_by(MedicalFolder.status)
        .all()
    )
    return [
        {"label": str(getattr(s, "value", s)), "count": int(c)}
        for s, c in rows
    ]


def jobs_per_day(clinic_id: int, days: int = 14) -> list[dict]:
    cutoff = _days_ago(days)
    rows = (
        db.session.query(func.date(InferenceJob.created_at), func.count(InferenceJob.id))
        .join(Exam, Exam.id == InferenceJob.exam_id)
        .join(MedicalFolder, MedicalFolder.id == Exam.folder_id)
        .join(Patient, Patient.id == MedicalFolder.patient_id)
        .filter(Patient.clinic_id == clinic_id, InferenceJob.created_at >= cutoff)
        .group_by(func.date(InferenceJob.created_at))
        .order_by(func.date(InferenceJob.created_at))
        .all()
    )
    return [{"date": str(d), "count": int(c)} for d, c in rows]


def doctor_productivity(clinic_id: int, days: int = 30) -> list[dict]:
    cutoff = _days_ago(days)
    rows = (
        db.session.query(
            User.full_name,
            func.count(InferenceJob.id),
        )
        .select_from(InferenceJob)
        .join(Exam, Exam.id == InferenceJob.exam_id)
        .join(MedicalFolder, MedicalFolder.id == Exam.folder_id)
        .join(Doctor, Doctor.id == MedicalFolder.doctor_id)
        .join(User, User.id == Doctor.user_id)
        .filter(Doctor.clinic_id == clinic_id, InferenceJob.created_at >= cutoff)
        .group_by(Doctor.id, User.full_name)
        .order_by(func.count(InferenceJob.id).desc())
        .limit(10)
        .all()
    )
    return [{"doctor": name, "count": int(c)} for name, c in rows]


def doctor_summary_rows(clinic_id: int):
    """Per-doctor aggregations for the clinic doctor list."""
    cutoff = _days_ago(30)

    # active patients = patients with at least one open folder where doctor is creator/assignee
    open_statuses = ("new", "in_progress", "follow_up")

    return (
        db.session.query(
            Doctor.id,
            User.id.label("user_id"),
            User.full_name,
            User.email,
            User.is_active_account,
            Doctor.specialty,
            func.count(func.distinct(MedicalFolder.id)).label("active_folders"),
        )
        .join(User, User.id == Doctor.user_id)
        .outerjoin(
            MedicalFolder,
            (MedicalFolder.doctor_id == Doctor.id) & (MedicalFolder.status.in_(open_statuses)),
        )
        .filter(Doctor.clinic_id == clinic_id)
        .group_by(Doctor.id, User.id)
        .order_by(User.full_name)
    )
