"""Smoke tests: app boots, key public pages render, healthz returns ok."""

from __future__ import annotations


def test_index_redirects_to_landing(client):
    rv = client.get("/")
    assert rv.status_code == 302
    assert "/landing" in rv.headers.get("Location", "")


def test_login_page_renders(client):
    rv = client.get("/auth/login")
    assert rv.status_code == 200
    assert b"Sign in" in rv.data


def test_register_clinic_page_renders(client):
    rv = client.get("/auth/register-clinic")
    assert rv.status_code == 200
    assert b"Register your clinic" in rv.data


def test_healthz_ok(client):
    rv = client.get("/healthz")
    assert rv.status_code == 200
    assert rv.get_json()["status"] == "ok"
