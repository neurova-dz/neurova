"""Shared pytest fixtures: Flask app + per-role users."""

from __future__ import annotations

import pytest

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.user import User


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _make_user(email: str, password: str, *, role: str, clinic_id: int | None = None,
               full_name: str = "Test User") -> User:
    u = User(
        email=email, full_name=full_name, role=role,
        clinic_id=clinic_id, is_active_account=True,
    )
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    return u


def _make_clinic(name: str = "Test Clinic") -> Clinic:
    c = Clinic(name=name, slug=name.lower().replace(" ", "-"), plan="trial", is_active=True)
    db.session.add(c)
    db.session.flush()
    return c


@pytest.fixture
def clinic_a(app):
    c = _make_clinic("Clinic A")
    db.session.commit()
    return c


@pytest.fixture
def superadmin(app):
    u = _make_user("superadmin@example.com", "Pwd12345!", role="superadmin", full_name="Super Admin")
    db.session.commit()
    return u


@pytest.fixture
def clinic_admin_a(app, clinic_a):
    u = _make_user("admin-a@example.com", "Pwd12345!", role="clinic_admin",
                   clinic_id=clinic_a.id, full_name="Admin A")
    db.session.add(Doctor(user_id=u.id, clinic_id=clinic_a.id))
    db.session.commit()
    return u


@pytest.fixture
def doctor_a(app, clinic_a):
    u = _make_user("doc-a@example.com", "Pwd12345!", role="doctor",
                   clinic_id=clinic_a.id, full_name="Doctor A")
    db.session.add(Doctor(user_id=u.id, clinic_id=clinic_a.id, specialty="brain_tumor"))
    db.session.commit()
    return u


def login_as(client, email: str, password: str = "Pwd12345!") -> bool:
    rv = client.post("/auth/login",
                     data={"email": email, "password": password},
                     follow_redirects=False)
    return rv.status_code in (302, 303)
