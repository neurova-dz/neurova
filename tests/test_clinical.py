"""Cross-tenant isolation and core clinical model invariants."""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.medical import MedicalFolder, Patient
from app.models.user import User
from tests.conftest import login_as


def _seed_clinic_b(app):
    c = Clinic(name="Clinic B", slug="clinic-b", plan="trial", is_active=True)
    db.session.add(c)
    db.session.flush()
    u = User(email="doc-b@example.com", full_name="Doctor B",
            role="doctor", clinic_id=c.id, is_active_account=True)
    u.set_password("Pwd12345!")
    db.session.add(u)
    db.session.flush()
    db.session.add(Doctor(user_id=u.id, clinic_id=c.id, specialty="brain_tumor"))
    p = Patient(clinic_id=c.id, mrn="B-001", first_name="Jane", last_name="Doe")
    db.session.add(p)
    db.session.commit()
    return c, u, p


def test_patient_mrn_unique_per_clinic(app, clinic_a):
    p1 = Patient(clinic_id=clinic_a.id, mrn="X-1", first_name="A", last_name="B")
    p2 = Patient(clinic_id=clinic_a.id, mrn="X-1", first_name="C", last_name="D")
    db.session.add_all([p1, p2])
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_same_mrn_allowed_in_different_clinics(app, clinic_a):
    other, _, _ = _seed_clinic_b(app)
    p = Patient(clinic_id=clinic_a.id, mrn="B-001", first_name="J", last_name="D")
    db.session.add(p)
    db.session.commit()


def test_doctor_cannot_view_other_clinic_patient(app, client, doctor_a):
    _, _, patient_b = _seed_clinic_b(app)
    assert login_as(client, "doc-a@example.com")
    rv = client.get(f"/patients/{patient_b.id}", follow_redirects=False)
    assert rv.status_code in (302, 403, 404)


def test_folder_lifecycle_close_reopen(app, clinic_a, doctor_a):
    p = Patient(clinic_id=clinic_a.id, mrn="L-1", first_name="L", last_name="C")
    db.session.add(p)
    db.session.flush()
    doctor_profile = doctor_a.doctor_profile
    f = MedicalFolder(
        patient_id=p.id, doctor_id=doctor_profile.id,
        title="Case 1", status="new",
    )
    db.session.add(f)
    db.session.commit()

    f.status = "closed"
    db.session.commit()
    assert f.status == "closed"

    f.status = "in_progress"
    db.session.commit()
    assert f.status == "in_progress"
