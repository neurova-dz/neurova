"""Surface advisory information for clinicians on top of raw inference output.

This service is **strictly advisory**. The clinical_summary disclaimer remains
authoritative. We expose follow-up suggestions and longitudinal trend hints so
the doctor can act faster — never as a clinical decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.medical import InferenceJob, InferenceResult, MedicalFolder
from app.services.prior_inference_jobs_query import prior_done_jobs


# Tunable thresholds; any clinic can override via settings_json["helper_thresholds"].
DEFAULT_THRESHOLDS = {
    "brain": {
        "lesion_volume_cc_minor": 1.0,
        "lesion_volume_cc_significant": 5.0,
        "follow_up_days_minor": 90,
        "follow_up_days_significant": 30,
    },
    "retina": {
        "follow_up_days_grade_0": 365,
        "follow_up_days_grade_1": 180,
        "follow_up_days_grade_2": 90,
        "follow_up_days_grade_3": 30,
        "follow_up_days_grade_4": 14,
    },
}


def _previous_jobs_for_patient(job: InferenceJob, *, model_type: str) -> list[InferenceJob]:
    folder = job.exam.folder
    if folder is None or folder.patient is None:
        return []
    return prior_done_jobs(
        patient_id=folder.patient_id,
        model_type=model_type,
        exclude_job_id=job.id,
        limit=5,
    )


def _safe_get(d: dict | None, *keys, default=None):
    cur = d or {}
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def helper_for_brain(job: InferenceJob, thresholds: dict | None = None) -> dict[str, Any]:
    th = (thresholds or {}).get("brain", DEFAULT_THRESHOLDS["brain"])
    result: InferenceResult | None = job.result
    raw = (result.report_json or {}) if result else {}
    metrics = _safe_get(raw, "metrics") or {}
    raw_inner = _safe_get(raw, "raw") or {}

    volume_cc = (
        metrics.get("lesion_volume_cc")
        or raw_inner.get("lesion_volume_cc")
        or raw_inner.get("tumor_volume_cm3")
    )
    tumor_present = metrics.get("tumor_present") if metrics.get("tumor_present") is not None else raw_inner.get("tumor_present")

    suggestions: list[str] = []
    if tumor_present is False:
        suggestions.append(
            "No convincing lesion burden — consider routine annual follow-up unless clinical indication."
        )
    elif tumor_present is True:
        if volume_cc is not None and float(volume_cc) >= th["lesion_volume_cc_significant"]:
            suggestions.append(
                f"Significant lesion volume ({volume_cc:.2f} cc). Recommend short-interval follow-up "
                f"(~{th['follow_up_days_significant']} days) and multidisciplinary review."
            )
        else:
            suggestions.append(
                f"Lesion detected. Recommend follow-up in ~{th['follow_up_days_minor']} days "
                "with comparison to prior structural series."
            )

    # longitudinal compare to most recent prior brain job
    delta_msg = None
    prior = _previous_jobs_for_patient(job, model_type="brain_3d")
    if prior:
        prior_job = prior[0]
        prior_metrics = _safe_get((prior_job.result.report_json if prior_job.result else None), "metrics") or {}
        prior_volume = prior_metrics.get("lesion_volume_cc") or _safe_get(prior_job.result.report_json if prior_job.result else None, "raw", "lesion_volume_cc")
        if volume_cc is not None and prior_volume:
            try:
                delta = float(volume_cc) - float(prior_volume)
                if abs(delta) >= 0.5:
                    direction = "increase" if delta > 0 else "decrease"
                    delta_msg = (
                        f"Versus previous study ({prior_job.created_at:%Y-%m-%d}): lesion volume {direction} "
                        f"of {abs(delta):.2f} cc."
                    )
            except (TypeError, ValueError):
                pass

    return {
        "suggestions": suggestions,
        "delta": delta_msg,
        "prior_count": len(prior),
    }


def helper_for_retina(job: InferenceJob, thresholds: dict | None = None) -> dict[str, Any]:
    th = (thresholds or {}).get("retina", DEFAULT_THRESHOLDS["retina"])
    result = job.result
    raw = (result.report_json or {}) if result else {}
    raw_inner = _safe_get(raw, "raw") or {}
    metrics = _safe_get(raw, "metrics") or {}
    class_id = metrics.get("class_id") if metrics.get("class_id") is not None else raw_inner.get("class_id")

    follow_days = None
    if class_id is not None:
        try:
            follow_days = th.get(f"follow_up_days_grade_{int(class_id)}")
        except (TypeError, ValueError):
            follow_days = None

    suggestions = []
    if follow_days is not None:
        suggestions.append(f"Suggested ophthalmology follow-up: ~{follow_days} days.")
    else:
        suggestions.append("Schedule follow-up at the discretion of the clinician.")

    history = []
    prior = _previous_jobs_for_patient(job, model_type="diabetic_retinopathy")
    for p in prior:
        pmetrics = _safe_get((p.result.report_json if p.result else None), "metrics") or {}
        history.append(
            {
                "date": (p.finished_at or p.created_at).isoformat(),
                "class_id": pmetrics.get("class_id"),
                "diagnosis_label": (p.result.diagnosis_label if p.result else None),
            }
        )
    return {
        "suggestions": suggestions,
        "history": history,
    }


def helper_for_job(job: InferenceJob, *, clinic_settings: dict | None = None) -> dict[str, Any]:
    """Return advisory info specific to the model type. Always JSON-friendly."""
    if not job:
        return {}
    thresholds = (clinic_settings or {}).get("helper_thresholds") or {}
    mt = getattr(job.model_type, "value", job.model_type)
    if str(mt) == "brain_3d":
        return helper_for_brain(job, thresholds)
    return helper_for_retina(job, thresholds)
