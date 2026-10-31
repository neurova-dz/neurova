"""Shared 'new patient' form for clinician-facing routes (/patients/new and /dashboard/patients/new)."""

from __future__ import annotations

from datetime import datetime

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from app.extensions import db
from app.forms.auth import PatientForm
from app.models.medical import Patient
from app.services.audit_service import log_event


def respond_clinician_patient_new(*, cancel_url: str):
    """GET/POST: create patient in the user's clinic."""

    if current_user.is_superadmin:
        return redirect(url_for("admin.overview"))
    if current_user.is_clinic_admin:
        return redirect(url_for("clinic.patient_new"))
    if not current_user.is_doctor or current_user.clinic_id is None:
        abort(403)

    form = PatientForm()
    if form.validate_on_submit():
        bd = None
        if form.birth_date.data:
            try:
                bd = datetime.strptime(form.birth_date.data.strip(), "%Y-%m-%d").date()
            except ValueError:
                form.birth_date.errors.append("Invalid date format.")
                return render_template(
                    "clinic/patients/form.html",
                    form=form,
                    cancel_url=cancel_url,
                )
        patient = Patient(
            clinic_id=current_user.clinic_id,
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            sex=form.sex.data or None,
            birth_date=bd,
            mrn=(form.mrn.data or None),
            phone=form.phone.data or None,
            clinical_notes=form.clinical_notes.data or None,
        )
        db.session.add(patient)
        db.session.commit()
        log_event(
            "patient.create", "patient", patient.id, clinic_id=current_user.clinic_id
        )
        flash("Patient created.", "success")
        return redirect(url_for("doctor.patient_detail", patient_id=patient.id))

    return render_template(
        "clinic/patients/form.html",
        form=form,
        cancel_url=cancel_url,
    )
