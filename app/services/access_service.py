"""Authorization helpers built on top of the unified :class:`User` model.

Tenant boundary: ``user.clinic_id`` (None for superadmin → full access).
Folder boundary: creator (``MedicalFolder.doctor_id``), assignee
(``MedicalFolder.assigned_doctor_id``), or explicit :class:`FolderShare`.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import exists, or_, select

from app.extensions import db
from app.models.doctor import Doctor
from app.models.medical import (
    Exam,
    FolderShare,
    InferenceJob,
    MedicalFolder,
    Patient,
)
from app.models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_super(user) -> bool:
    return bool(getattr(user, "is_superadmin", False))


def _is_clinic_admin(user) -> bool:
    return bool(getattr(user, "is_clinic_admin", False))


def _is_doctor(user) -> bool:
    return bool(getattr(user, "is_doctor", False))


def current_clinic_id(user) -> int | None:
    """Return the user's clinic scope. ``None`` means full platform access."""
    if user is None or not getattr(user, "is_authenticated", True):
        return None
    if _is_super(user):
        return None
    return getattr(user, "clinic_id", None)


def doctor_profile_id(user) -> int | None:
    return getattr(user, "doctor_id", None)


# ---------------------------------------------------------------------------
# Folder-level checks
# ---------------------------------------------------------------------------

def can_access_folder(user, folder: MedicalFolder) -> bool:
    if folder is None:
        return False
    if _is_super(user):
        return True

    user_clinic_id = getattr(user, "clinic_id", None)
    if user_clinic_id is None or folder.patient is None:
        return False
    if folder.patient.clinic_id != user_clinic_id:
        return False

    if _is_clinic_admin(user):
        return True

    # doctor: needs to be creator, assignee, or share recipient
    profile_id = doctor_profile_id(user)
    if profile_id is None:
        return False
    if folder.doctor_id == profile_id:
        return True
    if folder.assigned_doctor_id == profile_id:
        return True
    return (
        FolderShare.query.filter_by(
            folder_id=folder.id, shared_with_doctor_id=profile_id
        ).first()
        is not None
    )


def can_access_inference_job(user, job: InferenceJob) -> bool:
    if job is None or job.exam is None:
        return False
    return can_access_folder(user, job.exam.folder)


def can_modify_folder(user, folder: MedicalFolder) -> bool:
    """Decide if the user may close, share, or upload exams to this folder."""
    if _is_super(user) or _is_clinic_admin(user):
        return can_access_folder(user, folder)
    profile_id = doctor_profile_id(user)
    if profile_id is None:
        return False
    return folder.doctor_id == profile_id or folder.assigned_doctor_id == profile_id


# ---------------------------------------------------------------------------
# Query helpers (for list pages)
# ---------------------------------------------------------------------------

def visible_folders_for_patient_query(user, patient_id: int):
    """Folders for a given patient that the user may open."""
    q = MedicalFolder.query.join(Patient).filter(MedicalFolder.patient_id == patient_id)

    if _is_super(user):
        return q

    clinic_id = getattr(user, "clinic_id", None)
    if clinic_id is None:
        return q.filter(False)
    q = q.filter(Patient.clinic_id == clinic_id)

    if _is_clinic_admin(user):
        return q

    profile_id = doctor_profile_id(user)
    if profile_id is None:
        return q.filter(False)
    sh = exists(
        select(1).select_from(FolderShare).where(
            FolderShare.folder_id == MedicalFolder.id,
            FolderShare.shared_with_doctor_id == profile_id,
        )
    )
    return q.filter(
        or_(
            MedicalFolder.doctor_id == profile_id,
            MedicalFolder.assigned_doctor_id == profile_id,
            sh,
        )
    )


def visible_patients_query(user):
    """Patients the user may see in their clinic.

    Doctors see patients with at least one accessible folder, or no folder yet
    (intake stage). Clinic admins see all patients in their clinic. Superadmins
    see everything.
    """
    base = Patient.query.filter(Patient.deleted_at.is_(None))
    if _is_super(user):
        return base

    clinic_id = getattr(user, "clinic_id", None)
    if clinic_id is None:
        return base.filter(False)

    base = base.filter(Patient.clinic_id == clinic_id)
    if _is_clinic_admin(user):
        return base

    profile_id = doctor_profile_id(user)
    if profile_id is None:
        return base.filter(False)
    sh = exists(
        select(1).select_from(FolderShare).where(
            FolderShare.folder_id == MedicalFolder.id,
            FolderShare.shared_with_doctor_id == profile_id,
        )
    )
    accessible = exists(
        select(1).select_from(MedicalFolder).where(
            MedicalFolder.patient_id == Patient.id,
            or_(
                MedicalFolder.doctor_id == profile_id,
                MedicalFolder.assigned_doctor_id == profile_id,
                sh,
            ),
        )
    )
    no_folders = ~exists(
        select(1).select_from(MedicalFolder).where(MedicalFolder.patient_id == Patient.id)
    )
    return base.filter(or_(accessible, no_folders))


def accessible_folder_query(user):
    """All folders the user may access (own + assigned + shared, scoped to clinic)."""
    q = MedicalFolder.query.join(Patient)
    if _is_super(user):
        return q
    clinic_id = getattr(user, "clinic_id", None)
    if clinic_id is None:
        return q.filter(False)
    q = q.filter(Patient.clinic_id == clinic_id)
    if _is_clinic_admin(user):
        return q
    profile_id = doctor_profile_id(user)
    if profile_id is None:
        return q.filter(False)
    sh = exists(
        select(1).select_from(FolderShare).where(
            FolderShare.folder_id == MedicalFolder.id,
            FolderShare.shared_with_doctor_id == profile_id,
        )
    )
    return q.filter(
        or_(
            MedicalFolder.doctor_id == profile_id,
            MedicalFolder.assigned_doctor_id == profile_id,
            sh,
        )
    )


def inference_jobs_visible_query(user):
    q = (
        InferenceJob.query.join(Exam, InferenceJob.exam_id == Exam.id)
        .join(MedicalFolder, Exam.folder_id == MedicalFolder.id)
        .join(Patient, MedicalFolder.patient_id == Patient.id)
    )
    if _is_super(user):
        return q
    clinic_id = getattr(user, "clinic_id", None)
    if clinic_id is None:
        return q.filter(False)
    q = q.filter(Patient.clinic_id == clinic_id)
    if _is_clinic_admin(user):
        return q
    profile_id = doctor_profile_id(user)
    if profile_id is None:
        return q.filter(False)
    sh = exists(
        select(1).select_from(FolderShare).where(
            FolderShare.folder_id == MedicalFolder.id,
            FolderShare.shared_with_doctor_id == profile_id,
        )
    )
    return q.filter(
        or_(
            MedicalFolder.doctor_id == profile_id,
            MedicalFolder.assigned_doctor_id == profile_id,
            sh,
        )
    )


# ---------------------------------------------------------------------------
# Mutating helpers (audit hooks)
# ---------------------------------------------------------------------------

def assign_folder(folder: MedicalFolder, doctor: Doctor, *, by_user: User) -> None:
    """Assign a clinic doctor to a folder. Does not commit."""
    folder.assigned_doctor_id = doctor.id if doctor else None


def share_folder(
    folder: MedicalFolder, target_doctor: Doctor, *, by_user: User
) -> FolderShare | None:
    """Create a :class:`FolderShare` row if not already present."""
    if folder is None or target_doctor is None:
        return None
    existing = FolderShare.query.filter_by(
        folder_id=folder.id, shared_with_doctor_id=target_doctor.id
    ).first()
    if existing:
        return existing
    by_doctor_id = doctor_profile_id(by_user)
    if by_doctor_id is None:
        # Clinic admins might not have a doctor profile. Use any doctor in the clinic
        # as "by" — fall back to target as a self-link to satisfy NOT NULL.
        by_doctor_id = target_doctor.id
    share = FolderShare(
        folder_id=folder.id,
        shared_with_doctor_id=target_doctor.id,
        shared_by_doctor_id=by_doctor_id,
    )
    db.session.add(share)
    return share


def doctor_clinic_colleagues_query(user, *, exclude_self: bool = True):
    """Doctors visible for sharing/assignment within the user's clinic."""
    q = Doctor.query.filter(Doctor.clinic_id == getattr(user, "clinic_id", None))
    if exclude_self:
        own_id = doctor_profile_id(user)
        if own_id:
            q = q.filter(Doctor.id != own_id)
    return q.order_by(Doctor.id)
