"""Per-patient RGPD export (folders, exams, jobs, results) as a ZIP archive."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

from app.models.medical import Patient


def _serialize_patient(patient: Patient) -> dict:
    folders = []
    for f in patient.folders.all():
        folder_blob = {
            "id": f.id,
            "title": f.title,
            "status": getattr(f.status, "value", f.status),
            "diagnosis_context": f.diagnosis_context,
            "notes_md": f.notes_md,
            "closed_at": f.closed_at.isoformat() if f.closed_at else None,
            "closed_reason": f.closed_reason,
            "created_at": f.created_at.isoformat(),
            "exams": [],
        }
        for e in f.exams.all():
            exam_blob = {
                "id": e.id,
                "modality": getattr(e.modality, "value", e.modality),
                "laterality": getattr(e.laterality, "value", e.laterality) if e.laterality else None,
                "exam_date": e.exam_date.isoformat() if e.exam_date else None,
                "notes": e.notes,
                "uploaded_files": e.uploaded_files,
                "jobs": [],
            }
            for j in e.jobs.all():
                exam_blob["jobs"].append(
                    {
                        "id": j.id,
                        "model_type": getattr(j.model_type, "value", j.model_type),
                        "status": getattr(j.status, "value", j.status),
                        "error_code": j.error_code,
                        "error_message": j.error_message,
                        "started_at": j.started_at.isoformat() if j.started_at else None,
                        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                        "result": j.result.report_json if j.result else None,
                    }
                )
            folder_blob["exams"].append(exam_blob)
        folders.append(folder_blob)
    return {
        "patient": {
            "id": patient.id,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "sex": patient.sex,
            "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
            "mrn": patient.mrn,
            "phone": patient.phone,
            "clinical_notes": patient.clinical_notes,
            "created_at": patient.created_at.isoformat(),
        },
        "folders": folders,
        "exported_at": datetime.utcnow().isoformat() + "Z",
    }


def patient_export_zip(patient: Patient) -> bytes:
    payload = _serialize_patient(patient)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"patient_{patient.id}/record.json",
            json.dumps(payload, indent=2, default=str),
        )
        # text README
        zf.writestr(
            f"patient_{patient.id}/README.txt",
            "NEUROVA RGPD export — clinical record snapshot.\n"
            "All times are UTC. Source files (uploaded imaging) are referenced by path,\n"
            "not embedded, to keep the archive small. Request a full media export\n"
            "from your clinic admin if you need the original NIfTI/JPG files.\n",
        )
    return buf.getvalue()
