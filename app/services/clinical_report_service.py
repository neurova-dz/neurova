"""
Canonical clinical summary shape for API and HTML (v1), built from model-specific raw JSON.
"""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = 1


def _brain_pipeline_payload(blob: dict[str, Any]) -> dict[str, Any]:
    """Worker JSON is flat; v1 clinical envelopes nest stats under ``raw``."""
    if not isinstance(blob, dict):
        return {}
    inner = blob.get("raw")
    if isinstance(inner, dict) and (
        blob.get("schema_version") is not None
        or "findings" in blob
        or "impression" in blob
    ):
        metrics = blob.get("metrics") if isinstance(blob.get("metrics"), dict) else {}
        return {**inner, **metrics}
    return dict(blob)


def _brain_lesion_volumes_mm3_cc(raw: dict[str, Any]) -> tuple[Any, Any]:
    """Resolve display lesion volumes from BraTS-style or legacy field names."""
    d = _brain_pipeline_payload(raw)
    mm3 = d.get("lesion_volume_mm3")
    if mm3 is None:
        mm3 = d.get("tumor_volume_mm3")
    if mm3 is None and isinstance(d.get("classes"), dict):
        total = 0.0
        for c in d["classes"].values():
            if isinstance(c, dict) and c.get("volume_mm3") is not None:
                total += float(c["volume_mm3"])
        mm3 = total or None
    cc = d.get("lesion_volume_cc")
    if cc is None:
        cc = d.get("tumor_volume_cm3")
    if cc is None and isinstance(d.get("classes"), dict):
        total = 0.0
        for c in d["classes"].values():
            if isinstance(c, dict) and c.get("volume_cm3") is not None:
                total += float(c["volume_cm3"])
        cc = total or None
    return mm3, cc


def build_clinical_summary(
    model_type: str,
    raw_report: dict[str, Any] | None,
    *,
    diagnosis_label: str | None,
    confidence: float | None,
) -> dict[str, Any]:
    """Merge raw inference output into a small, stable report_json envelope."""
    raw = raw_report if isinstance(raw_report, dict) else {}
    if model_type == "brain_3d":
        pipe = _brain_pipeline_payload(raw)
        impression = diagnosis_label or (
            "Tumor suspected" if pipe.get("tumor_present") else "No tumor detected"
        )
        vol_mm3, vol_cc = _brain_lesion_volumes_mm3_cc(raw)
        if vol_mm3 is not None:
            try:
                vol_mm3 = float(vol_mm3)
            except (TypeError, ValueError):
                pass
        if vol_cc is not None:
            try:
                vol_cc = float(vol_cc)
            except (TypeError, ValueError):
                pass
        metrics = {
            "tumor_present": pipe.get("tumor_present"),
            "lesion_volume_mm3": vol_mm3,
            "lesion_volume_cc": vol_cc,
        }
        findings_parts = []
        if pipe.get("tumor_present") is not None:
            findings_parts.append(
                "Lesion signal on structural MRI suggests tumor burden."
                if pipe.get("tumor_present")
                else "No convincing lesion burden on the provided structural series."
            )
        findings = " ".join(findings_parts) if findings_parts else "See structured metrics and overlays."
    else:
        impression = diagnosis_label or raw.get("diagnosis") or "See probabilities."
        probs = raw.get("probabilities") or {}
        metrics = {"class_id": raw.get("class_id"), "probabilities": probs, "continuous_score": raw.get("continuous_score")}
        if probs:
            top = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:3]
            findings = "Class probabilities (top): " + ", ".join(f"{k} {v:.3f}" for k, v in top)
        else:
            findings = "Fundus grading output attached; see impression."

    return {
        "schema_version": SCHEMA_VERSION,
        "model_type": model_type,
        "findings": findings,
        "impression": impression,
        "metrics": metrics,
        "disclaimer": "Assistive software only; not a substitute for clinical judgment.",
        "raw": raw,
        "diagnosis_label": diagnosis_label,
        "confidence": confidence,
    }


def _patch_brain_metrics_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Backfill lesion volumes on stored v1 summaries when raw used tumor_volume_* keys."""
    if str(envelope.get("model_type")) != "brain_3d":
        return envelope
    metrics = envelope.get("metrics")
    if not isinstance(metrics, dict):
        return envelope
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else {}
    mm3, cc = _brain_lesion_volumes_mm3_cc({**raw, **metrics})
    new_metrics = dict(metrics)
    changed = False
    if metrics.get("lesion_volume_mm3") is None and mm3 is not None:
        try:
            new_metrics["lesion_volume_mm3"] = float(mm3)
        except (TypeError, ValueError):
            new_metrics["lesion_volume_mm3"] = mm3
        changed = True
    if metrics.get("lesion_volume_cc") is None and cc is not None:
        try:
            new_metrics["lesion_volume_cc"] = float(cc)
        except (TypeError, ValueError):
            new_metrics["lesion_volume_cc"] = cc
        changed = True
    if not changed:
        return envelope
    return {**envelope, "metrics": new_metrics}


def extract_display_summary(report_json: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize legacy rows (raw only) vs v1 envelope for templates/API."""
    if not report_json or not isinstance(report_json, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "findings": "",
            "impression": "",
            "metrics": {},
            "disclaimer": "",
        }
    try:
        schema_ok = int(report_json.get("schema_version")) == SCHEMA_VERSION
    except (TypeError, ValueError):
        schema_ok = False
    if schema_ok and "findings" in report_json:
        return _patch_brain_metrics_envelope(report_json)
    # Legacy: treat whole blob as raw brain/retina output
    mt = report_json.get("model_type")
    if not mt:
        if report_json.get("tumor_present") is not None or report_json.get("tumor_volume_mm3") is not None:
            mt = "brain_3d"
        else:
            mt = "diabetic_retinopathy"
    return build_clinical_summary(
        str(mt),
        report_json,
        diagnosis_label=report_json.get("diagnosis") or report_json.get("diagnosis_label"),
        confidence=report_json.get("confidence"),
    )
