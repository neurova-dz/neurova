"""Single data seed after ``users`` + clinic metadata exist.

Runs in order:

1. Superadmin (no clinic FK).
2. Default clinic shell (already inserted in ``f8a1c2b3d4e5`` unless empty —
   full row with slug/metadata is completed here).
3. Clinic admin + ``doctors`` profile; ``clinics.created_by_user_id``.
4. Active doctor + ``doctors`` profile under the same clinic.

Development defaults — change passwords in production.

Addresses use ``@neurova.dev`` so they pass WTForms/email-validator login checks
(``.local`` is rejected as a reserved/special-use domain).

- superadmin: ``superadmin@neurova.dev`` / ``Superadmin123!``
- clinic admin: ``admin@neurova.dev`` / ``Admin123!``
- doctor: ``doctor@neurova.dev`` / ``Doctor123!``

Idempotent on re-run.

Revision ID: h2a3b4c5d6e7
Revises: g1a2b3c4d5e6

"""

from __future__ import annotations

import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from werkzeug.security import generate_password_hash


revision = "h2a3b4c5d6e7"
down_revision = "g1a2b3c4d5e6"
branch_labels = None
depends_on = None


SUPER_EMAIL = "superadmin@neurova.dev"
SUPER_PW = "Superadmin123!"
SUPER_NAME = "Platform Superadmin"

ADMIN_EMAIL = "admin@neurova.dev"
ADMIN_PW = "Admin123!"
ADMIN_NAME = "Clinic Administrator"

DOC_EMAIL = "doctor@neurova.dev"
DOC_PW = "Doctor123!"
DOC_NAME = "Dr. Demo Physician"
DOC_SPECIALTY = "brain_tumor"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _has_user_email(bind, email: str) -> bool:
    n = bind.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE email = :e"), {"e": email}
    ).scalar()
    return int(n or 0) > 0


def _ensure_superadmin(bind) -> None:
    if _has_user_email(bind, SUPER_EMAIL):
        return
    ts = _utcnow()
    bind.execute(
        sa.text(
            """
            INSERT INTO users (
              email, password_hash, full_name, role,
              clinic_id, is_active_account, created_at, updated_at
            ) VALUES (
              :email, :password_hash, :full_name, 'superadmin',
              NULL, 1, :created_at, :updated_at
            )
            """
        ),
        {
            "email": SUPER_EMAIL,
            "password_hash": generate_password_hash(SUPER_PW),
            "full_name": SUPER_NAME,
            "created_at": ts,
            "updated_at": ts,
        },
    )


def _resolve_default_clinic_id(bind):
    cid = bind.execute(
        sa.text(
            """
            SELECT id FROM clinics WHERE name = :n ORDER BY id ASC LIMIT 1
            """
        ),
        {"n": "Default Clinic"},
    ).scalar()
    if cid is None:
        cid = bind.execute(
            sa.text("SELECT id FROM clinics ORDER BY id ASC LIMIT 1")
        ).scalar()
    return cid


def _ensure_default_clinic_row(bind) -> int:
    """Only when ``clinics`` is empty (normally f8 inserts ``Default Clinic`` first)."""
    ts = _utcnow()
    if bind.dialect.name == "mysql":
        bind.execute(
            sa.text(
                """
                INSERT INTO clinics (
                  name, address, timezone, settings_json,
                  slug, email, phone, country, plan, is_active,
                  created_by_user_id, created_at, updated_at
                )
                VALUES (
                  'Default Clinic', NULL, NULL, NULL,
                  'default-clinic', NULL, NULL, NULL,
                  'trial', 1, NULL, NOW(), NOW()
                )
                """
            )
        )
        cid = bind.execute(sa.text("SELECT id FROM clinics ORDER BY id DESC LIMIT 1")).scalar()
        return int(cid)
    bind.execute(
        sa.text(
            """
            INSERT INTO clinics (
              name, address, timezone, settings_json,
              slug, email, phone, country, plan, is_active,
              created_by_user_id, created_at, updated_at
            )
            VALUES (
              'Default Clinic', NULL, NULL, NULL,
              'default-clinic', NULL, NULL, NULL,
              'trial', 1, NULL, :created_at, :updated_at
            )
            """
        ),
        {"created_at": ts, "updated_at": ts},
    )
    cid = bind.execute(sa.text("SELECT last_insert_rowid()")).scalar()
    return int(cid)


def _set_clinic_slug_if_free(bind, clinic_id: int) -> None:
    taken = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM clinics WHERE slug = 'default-clinic' AND id <> :id"
        ),
        {"id": clinic_id},
    ).scalar()
    if int(taken or 0) > 0:
        return
    bind.execute(
        sa.text(
            """
            UPDATE clinics SET slug = 'default-clinic'
            WHERE id = :id AND (slug IS NULL OR slug = '')
            """
        ),
        {"id": clinic_id},
    )


def _count_clinic_admins(bind, clinic_id: int) -> int:
    n = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM users
            WHERE clinic_id = :cid AND role = 'clinic_admin'
            """
        ),
        {"cid": clinic_id},
    ).scalar()
    return int(n or 0)


def _insert_user_and_uid(
    bind, *, email: str, password: str, full_name: str, role: str, clinic_id: int | None, utc
) -> int:
    bind.execute(
        sa.text(
            """
            INSERT INTO users (
              email, password_hash, full_name, role,
              clinic_id, is_active_account, created_at, updated_at
            ) VALUES (
              :email, :password_hash, :full_name, :role,
              :clinic_id, 1, :created_at, :updated_at
            )
            """
        ),
        {
            "email": email,
            "password_hash": generate_password_hash(password),
            "full_name": full_name,
            "role": role,
            "clinic_id": clinic_id,
            "created_at": utc,
            "updated_at": utc,
        },
    )
    uid = bind.execute(
        sa.text("SELECT id FROM users WHERE email = :e ORDER BY id DESC LIMIT 1"),
        {"e": email},
    ).scalar()
    return int(uid)


def _insert_doctor_profile(bind, *, uid: int, clinic_id: int, utc, specialty: str | None):
    prefs = json.dumps({"default_modality": "", "compact_results": False})
    bind.execute(
        sa.text(
            """
            INSERT INTO doctors (
              user_id, clinic_id, specialty,
              title, phone, locale, preferences_json,
              created_at
            )
            VALUES (
              :uid, :cid, :specialty,
              NULL, NULL, NULL, :prefs,
              :created_at
            )
            """
        ),
        {
            "uid": uid,
            "cid": clinic_id,
            "specialty": specialty,
            "prefs": prefs,
            "created_at": utc,
        },
    )


def _ensure_clinic_admin(bind, clinic_id: int, utc: datetime) -> None:
    if _count_clinic_admins(bind, clinic_id) > 0:
        return
    conflict = bind.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE email = :e"), {"e": ADMIN_EMAIL}
    ).scalar()
    if int(conflict or 0) > 0:
        return
    uid = _insert_user_and_uid(
        bind,
        email=ADMIN_EMAIL,
        password=ADMIN_PW,
        full_name=ADMIN_NAME,
        role="clinic_admin",
        clinic_id=clinic_id,
        utc=utc,
    )
    _insert_doctor_profile(bind, uid=uid, clinic_id=clinic_id, utc=utc, specialty=None)
    bind.execute(
        sa.text(
            """
            UPDATE clinics SET created_by_user_id = :uid
            WHERE id = :cid AND created_by_user_id IS NULL
            """
        ),
        {"uid": uid, "cid": clinic_id},
    )


def _ensure_seed_doctor(bind, clinic_id: int, utc: datetime) -> None:
    if _has_user_email(bind, DOC_EMAIL):
        return
    uid = _insert_user_and_uid(
        bind,
        email=DOC_EMAIL,
        password=DOC_PW,
        full_name=DOC_NAME,
        role="doctor",
        clinic_id=clinic_id,
        utc=utc,
    )
    _insert_doctor_profile(
        bind, uid=uid, clinic_id=clinic_id, utc=utc, specialty=DOC_SPECIALTY
    )


def upgrade() -> None:
    bind = op.get_bind()
    utc = _utcnow()

    _ensure_superadmin(bind)

    clinic_id = _resolve_default_clinic_id(bind)
    if clinic_id is None:
        clinic_id = _ensure_default_clinic_row(bind)
    clinic_id = int(clinic_id)
    _set_clinic_slug_if_free(bind, clinic_id)

    _ensure_clinic_admin(bind, clinic_id, utc)
    _ensure_seed_doctor(bind, clinic_id, utc)


def downgrade() -> None:
    bind = op.get_bind()
    for email in (ADMIN_EMAIL, DOC_EMAIL, SUPER_EMAIL):
        uid = bind.execute(
            sa.text("SELECT id FROM users WHERE email = :e ORDER BY id ASC LIMIT 1"),
            {"e": email},
        ).scalar()
        if uid is None:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE clinics SET created_by_user_id = NULL
                WHERE created_by_user_id = :uid
                """
            ),
            {"uid": int(uid)},
        )
        bind.execute(sa.text("DELETE FROM users WHERE id = :uid"), {"uid": int(uid)})
