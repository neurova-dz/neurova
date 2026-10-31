"""Patient/folder/exam/job/result/audit models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum, UniqueConstraint

from app.extensions import db


folder_status_enum = Enum(
    "new", "in_progress", "follow_up", "closed", name="folder_status_enum"
)
modality_enum = Enum("mri", "ultrasound", "retina_fundus", name="modality_enum")
model_type_enum = Enum("brain_3d", "diabetic_retinopathy", name="model_type_enum")
job_status_enum = Enum(
    "queued",
    "running",
    "done",
    "failed",
    "timed_out",
    "cancelled",
    name="job_status_enum",
)
laterality_enum = Enum("left", "right", "both", name="laterality_enum")


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False, index=True)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    birth_date = db.Column(db.Date, nullable=True)
    sex = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    mrn = db.Column(db.String(80), nullable=True, index=True)
    clinical_notes = db.Column(db.Text, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("clinic_id", "mrn", name="uq_patients_clinic_mrn"),
    )

    clinic = db.relationship("Clinic", back_populates="patients")
    folders = db.relationship("MedicalFolder", back_populates="patient", lazy="dynamic")

    @property
    def display_name(self) -> str:
        return f"{self.last_name.upper()}, {self.first_name}"

    @property
    def age_years(self) -> int | None:
        if not self.birth_date:
            return None
        today = datetime.utcnow().date()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


class MedicalFolder(db.Model):
    __tablename__ = "medical_folders"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    assigned_doctor_id = db.Column(
        db.Integer, db.ForeignKey("doctors.id"), nullable=True, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    diagnosis_context = db.Column(db.Text, nullable=True)
    notes_md = db.Column(db.Text, nullable=True)
    status = db.Column(folder_status_enum, nullable=False, default="new")
    closed_reason = db.Column(db.String(500), nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    closed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    patient = db.relationship("Patient", back_populates="folders")
    doctor = db.relationship(
        "Doctor", back_populates="folders", foreign_keys=[doctor_id]
    )
    assigned_doctor = db.relationship(
        "Doctor", back_populates="assigned_folders", foreign_keys=[assigned_doctor_id]
    )
    closed_by = db.relationship("User", foreign_keys=[closed_by_user_id])
    exams = db.relationship("Exam", back_populates="folder", lazy="dynamic")
    shares = db.relationship(
        "FolderShare", back_populates="folder", cascade="all, delete-orphan", lazy="dynamic"
    )


class FolderShare(db.Model):
    """Grants a colleague in the same clinic access to a medical folder."""

    __tablename__ = "folder_shares"
    __table_args__ = (
        UniqueConstraint(
            "folder_id", "shared_with_doctor_id", name="uq_folder_share_recipient"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("medical_folders.id"), nullable=False, index=True)
    shared_with_doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    shared_by_doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    folder = db.relationship("MedicalFolder", back_populates="shares")
    shared_with = db.relationship(
        "Doctor", foreign_keys=[shared_with_doctor_id], back_populates="shares_received"
    )
    shared_by = db.relationship(
        "Doctor", foreign_keys=[shared_by_doctor_id], back_populates="shares_granted"
    )


class Exam(db.Model):
    __tablename__ = "exams"

    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("medical_folders.id"), nullable=False, index=True)
    modality = db.Column(modality_enum, nullable=False)
    laterality = db.Column(laterality_enum, nullable=True)
    uploaded_file_path = db.Column(db.String(500), nullable=False)
    uploaded_files = db.Column(db.JSON, nullable=True)
    exam_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    folder = db.relationship("MedicalFolder", back_populates="exams")
    jobs = db.relationship("InferenceJob", back_populates="exam", lazy="dynamic")


class InferenceJob(db.Model):
    __tablename__ = "inference_jobs"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False, index=True)
    model_type = db.Column(model_type_enum, nullable=False)
    approach = db.Column(db.String(120), nullable=True)
    task_id = db.Column(db.String(120), nullable=True, index=True)
    status = db.Column(job_status_enum, nullable=False, default="queued")
    progress = db.Column(db.Integer, nullable=False, default=0)
    progress_stage = db.Column(db.String(64), nullable=True)
    progress_message = db.Column(db.String(255), nullable=True)
    compute_device = db.Column(db.String(16), nullable=True)
    error_code = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    last_progress_at = db.Column(db.DateTime, nullable=True)
    last_known_async_state = db.Column(db.String(32), nullable=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    priority = db.Column(db.SmallInteger, nullable=False, default=0)
    enqueued_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    exam = db.relationship("Exam", back_populates="jobs")
    result = db.relationship("InferenceResult", back_populates="job", uselist=False)
    enqueued_by = db.relationship("User", foreign_keys=[enqueued_by_user_id])

    @property
    def status_value(self) -> str:
        return getattr(self.status, "value", self.status)

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None


class InferenceResult(db.Model):
    __tablename__ = "inference_results"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("inference_jobs.id"), nullable=False, unique=True)
    report_json = db.Column(db.JSON, nullable=True)
    report_path = db.Column(db.String(500), nullable=True)
    mask_path = db.Column(db.String(500), nullable=True)
    axial_overlay_path = db.Column(db.String(500), nullable=True)
    coronal_overlay_path = db.Column(db.String(500), nullable=True)
    sagittal_overlay_path = db.Column(db.String(500), nullable=True)
    html_3d_path = db.Column(db.String(500), nullable=True)
    thumbnail_path = db.Column(db.String(500), nullable=True)
    probability_chart_path = db.Column(db.String(500), nullable=True)
    diagnosis_label = db.Column(db.String(200), nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    job = db.relationship("InferenceJob", back_populates="result")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=True, index=True)
    resource_type = db.Column(db.String(100), nullable=True)
    resource_id = db.Column(db.String(120), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor = db.relationship("User", foreign_keys=[actor_user_id])
    clinic = db.relationship("Clinic", foreign_keys=[clinic_id])


def unique_output_dir_name() -> str:
    return str(uuid.uuid4())
