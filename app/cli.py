"""Custom Flask CLI commands.

Usage::

    flask superadmin create --email me@neurova.io --password StrongPwd1!
    flask seed-demo  # optional second demo clinic with admin + 2 doctors
"""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import AppGroup

from app.extensions import db
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.user import User


superadmin_cli = AppGroup("superadmin", help="Manage platform superadmin accounts.")


@superadmin_cli.command("create")
@click.option("--email", required=True, help="Email login for the new superadmin.")
@click.option("--password", required=True, help="Initial password (min 8 chars).")
@click.option("--full-name", default="Platform Superadmin", help="Full name.")
def superadmin_create(email: str, password: str, full_name: str) -> None:
    email = email.strip().lower()
    if len(password) < 8:
        click.secho("Password must be at least 8 chars.", fg="red")
        raise SystemExit(1)
    existing = User.query.filter_by(email=email).first()
    if existing:
        existing.role = "superadmin"
        existing.is_active_account = True
        existing.set_password(password)
        existing.full_name = full_name
        db.session.commit()
        click.secho(f"Updated existing user {email} → superadmin.", fg="yellow")
        return
    user = User(
        email=email,
        full_name=full_name,
        role="superadmin",
        clinic_id=None,
        is_active_account=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.secho(f"Created superadmin {email} (id={user.id}).", fg="green")


def _make_demo_doctor(clinic_id: int, email: str, full_name: str, specialty: str | None) -> User:
    user = User(
        email=email,
        full_name=full_name,
        role="doctor",
        clinic_id=clinic_id,
        is_active_account=True,
    )
    user.set_password("Doctor123!")
    db.session.add(user)
    db.session.flush()
    db.session.add(
        Doctor(
            user_id=user.id,
            clinic_id=clinic_id,
            specialty=specialty,
            preferences_json={"default_modality": "", "compact_results": False},
        )
    )
    return user


@click.command("seed-demo")
def seed_demo() -> None:
    """Create a demo clinic + admin + 2 doctors. Idempotent."""
    clinic = Clinic.query.filter_by(slug="demo-clinic").first()
    if not clinic:
        clinic = Clinic(
            name="Demo Imaging Center",
            slug="demo-clinic",
            email="contact@demo.local",
            country="France",
            plan="trial",
            is_active=True,
        )
        db.session.add(clinic)
        db.session.flush()

    admin = User.query.filter_by(email="admin@demo.local").first()
    if not admin:
        admin = User(
            email="admin@demo.local",
            full_name="Demo Admin",
            role="clinic_admin",
            clinic_id=clinic.id,
            is_active_account=True,
        )
        admin.set_password("Admin123!")
        db.session.add(admin)
        db.session.flush()
        db.session.add(
            Doctor(
                user_id=admin.id,
                clinic_id=clinic.id,
                specialty=None,
                preferences_json={"default_modality": "", "compact_results": False},
            )
        )
        clinic.created_by_user_id = admin.id

    if not User.query.filter_by(email="alice@demo.local").first():
        _make_demo_doctor(clinic.id, "alice@demo.local", "Dr. Alice Roy", "brain_tumor")
    if not User.query.filter_by(email="ben@demo.local").first():
        _make_demo_doctor(clinic.id, "ben@demo.local", "Dr. Ben Tahar", "diabetic_retinopathy")

    db.session.commit()
    click.secho("Demo data ready:", fg="green")
    click.echo(
        "  Default clinic seeds (migrate): superadmin / admin / doctor @neurova.dev — "
        "see migration h2a3b4c5d6e7_seed_superadmin_clinic_admin.py"
    )
    click.echo("  clinic admin:     admin@demo.local / Admin123!")
    click.echo("  doctor (brain):   alice@demo.local / Doctor123!")
    click.echo("  doctor (retina):  ben@demo.local / Doctor123!")


def register_cli(app: Flask) -> None:
    app.cli.add_command(superadmin_cli)
    app.cli.add_command(seed_demo)
