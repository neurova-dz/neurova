"""Login / role redirect / role gating."""

from __future__ import annotations

from tests.conftest import login_as


def test_doctor_login_redirects_to_doctor_dashboard(client, doctor_a):
    assert login_as(client, "doc-a@example.com")
    rv = client.get("/", follow_redirects=False)
    assert rv.status_code == 302
    assert "/dashboard" in (rv.headers.get("Location") or "")


def test_clinic_admin_login_redirects_to_clinic_overview(client, clinic_admin_a):
    assert login_as(client, "admin-a@example.com")
    rv = client.get("/", follow_redirects=False)
    assert "/clinic" in (rv.headers.get("Location") or "")


def test_superadmin_login_redirects_to_admin(client, superadmin):
    assert login_as(client, "superadmin@example.com")
    rv = client.get("/", follow_redirects=False)
    assert "/admin" in (rv.headers.get("Location") or "")


def test_superadmin_new_clinic_page_renders(client, superadmin):
    assert login_as(client, "superadmin@example.com")
    rv = client.get("/admin/clinics/new")
    assert rv.status_code == 200
    assert b"clinic_name" in rv.data
    assert b"country" in rv.data


def test_doctor_blocked_from_admin(client, doctor_a):
    assert login_as(client, "doc-a@example.com")
    rv = client.get("/admin/", follow_redirects=False)
    assert rv.status_code == 403


def test_doctor_blocked_from_clinic_pages(client, doctor_a):
    assert login_as(client, "doc-a@example.com")
    rv = client.get("/clinic/doctors", follow_redirects=False)
    assert rv.status_code == 403


def test_clinic_admin_blocked_from_admin(client, clinic_admin_a):
    assert login_as(client, "admin-a@example.com")
    rv = client.get("/admin/", follow_redirects=False)
    assert rv.status_code == 403
