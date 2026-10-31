"""roles, invitations, notifications and case lifecycle

Revision ID: g1a2b3c4d5e6
Revises: f8a1c2b3d4e5
Create Date: 2026-05-02

This migration introduces the unified ``users`` table with a role enum,
splits the legacy ``doctors`` table into a profile (no email/password) linked
1:1 to a ``users`` row, and adds ``invitations``, ``password_reset_tokens``,
``notifications``. It also adds clinic metadata, folder lifecycle columns,
the inference progress contract and audit clinic scoping.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "g1a2b3c4d5e6"
down_revision = "f8a1c2b3d4e5"
branch_labels = None
depends_on = None


def _dialect() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
    bind = op.get_bind()

    # ---- 1. clinics: extra metadata ----
    with op.batch_alter_table("clinics", schema=None) as batch_op:
        batch_op.add_column(sa.Column("slug", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=180), nullable=True))
        batch_op.add_column(sa.Column("phone", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("country", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "plan",
                sa.Enum("trial", "standard", "enterprise", name="clinic_plan_enum"),
                nullable=False,
                server_default="trial",
            )
        )
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )
        batch_op.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.create_index("ix_clinics_slug", ["slug"], unique=True)

    # ---- 2. users (login table) ----
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=180), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column(
            "role",
            sa.Enum("superadmin", "clinic_admin", "doctor", name="user_role_enum"),
            nullable=False,
            server_default="doctor",
        ),
        sa.Column("clinic_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_active_account",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], name="fk_users_clinic_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_index("ix_users_clinic_id", "users", ["clinic_id"], unique=False)

    # backfill: each doctor row -> users row
    bind.execute(
        sa.text(
            """
            INSERT INTO users (email, password_hash, full_name, role, clinic_id,
                               is_active_account, created_at, updated_at)
            SELECT d.email, d.password_hash, d.full_name, 'clinic_admin', d.clinic_id,
                   d.is_active_account, d.created_at, d.created_at
            FROM doctors d
            """
        )
    )

    # ---- 3. doctors -> profile only ----
    with op.batch_alter_table("doctors", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))

    # link doctors.user_id by matching email
    bind.execute(
        sa.text(
            """
            UPDATE doctors
            SET user_id = (
                SELECT u.id FROM users u WHERE u.email = doctors.email LIMIT 1
            )
            """
        )
        if _dialect() != "mysql"
        else sa.text(
            """
            UPDATE doctors d
            INNER JOIN users u ON u.email = d.email
            SET d.user_id = u.id
            """
        )
    )

    # drop legacy auth columns from doctors
    with op.batch_alter_table("doctors", schema=None) as batch_op:
        # remove old unique email index
        try:
            batch_op.drop_index("ix_doctors_email")
        except Exception:  # noqa: BLE001 — index name may differ
            pass
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint("uq_doctors_user_id", ["user_id"])
        batch_op.create_foreign_key(
            "fk_doctors_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_column("email")
        batch_op.drop_column("password_hash")
        batch_op.drop_column("is_active_account")
        batch_op.drop_column("full_name")

    # ---- 4. invitations & password resets ----
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clinic_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=False),
        sa.Column(
            "role",
            sa.Enum("clinic_admin", "doctor", name="invitation_role_enum"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(length=160), nullable=True),
        sa.Column("specialty", sa.String(length=120), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], name="fk_invitations_clinic"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], name="fk_invitations_user"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invitations_email", "invitations", ["email"], unique=False)
    op.create_index("ix_invitations_clinic_id", "invitations", ["clinic_id"], unique=False)
    op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"], unique=True)

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_prt_user"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"], unique=False
    )

    # ---- 5. notifications ----
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "job_done",
                "job_failed",
                "share_received",
                "case_assigned",
                "system",
                name="notification_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notifications_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"], unique=False)
    op.create_index(
        "ix_notifications_user_unread", "notifications", ["user_id", "read_at"], unique=False
    )

    # ---- 6. patients lifecycle ----
    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.create_index("ix_patients_mrn", ["mrn"], unique=False)
        batch_op.create_index("ix_patients_deleted_at", ["deleted_at"], unique=False)
        batch_op.create_unique_constraint("uq_patients_clinic_mrn", ["clinic_id", "mrn"])

    # ---- 7. medical_folders lifecycle ----
    with op.batch_alter_table("medical_folders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assigned_doctor_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("notes_md", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("closed_reason", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("closed_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_medical_folders_assigned_doctor",
            "doctors",
            ["assigned_doctor_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_medical_folders_closed_by_user",
            "users",
            ["closed_by_user_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_medical_folders_assigned_doctor_id",
            ["assigned_doctor_id"],
            unique=False,
        )

    # ---- 8. exams: laterality ----
    with op.batch_alter_table("exams", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "laterality",
                sa.Enum("left", "right", "both", name="laterality_enum"),
                nullable=True,
            )
        )

    # ---- 9. inference_jobs progress contract ----
    with op.batch_alter_table("inference_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("progress_stage", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("progress_message", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("error_code", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "priority", sa.SmallInteger(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(sa.Column("enqueued_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_inference_jobs_enqueued_by",
            "users",
            ["enqueued_by_user_id"],
            ["id"],
        )

    # ---- 10. inference_results: retina artifacts ----
    with op.batch_alter_table("inference_results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("thumbnail_path", sa.String(length=500), nullable=True))
        batch_op.add_column(
            sa.Column("probability_chart_path", sa.String(length=500), nullable=True)
        )

    # ---- 11. audit_logs: actor_user_id + clinic + ip ----
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("actor_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("clinic_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("ip_address", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_audit_logs_actor_user", "users", ["actor_user_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_audit_logs_clinic", "clinics", ["clinic_id"], ["id"]
        )
        batch_op.create_index("ix_audit_logs_actor_user_id", ["actor_user_id"], unique=False)
        batch_op.create_index("ix_audit_logs_clinic_id", ["clinic_id"], unique=False)

    # backfill audit_logs.actor_user_id from old doctor_id
    bind.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET actor_user_id = (
                SELECT d.user_id FROM doctors d WHERE d.id = audit_logs.doctor_id LIMIT 1
            )
            WHERE doctor_id IS NOT NULL
            """
        )
        if _dialect() != "mysql"
        else sa.text(
            """
            UPDATE audit_logs a
            INNER JOIN doctors d ON d.id = a.doctor_id
            SET a.actor_user_id = d.user_id
            WHERE a.doctor_id IS NOT NULL
            """
        )
    )

    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        try:
            batch_op.drop_constraint("audit_logs_ibfk_1", type_="foreignkey")
        except Exception:  # noqa: BLE001
            pass
        batch_op.drop_column("doctor_id")


def downgrade() -> None:
    """Best-effort downgrade — schema rebuild is non-trivial; we drop the new tables."""

    # 11. audit_logs
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("doctor_id", sa.Integer(), nullable=True))
        batch_op.drop_index("ix_audit_logs_clinic_id")
        batch_op.drop_index("ix_audit_logs_actor_user_id")
        batch_op.drop_constraint("fk_audit_logs_clinic", type_="foreignkey")
        batch_op.drop_constraint("fk_audit_logs_actor_user", type_="foreignkey")
        batch_op.drop_column("ip_address")
        batch_op.drop_column("clinic_id")
        batch_op.drop_column("actor_user_id")

    # 10. inference_results
    with op.batch_alter_table("inference_results", schema=None) as batch_op:
        batch_op.drop_column("probability_chart_path")
        batch_op.drop_column("thumbnail_path")

    # 9. inference_jobs
    with op.batch_alter_table("inference_jobs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_inference_jobs_enqueued_by", type_="foreignkey")
        batch_op.drop_column("enqueued_by_user_id")
        batch_op.drop_column("priority")
        batch_op.drop_column("error_code")
        batch_op.drop_column("progress_message")
        batch_op.drop_column("progress_stage")

    # 8. exams
    with op.batch_alter_table("exams", schema=None) as batch_op:
        batch_op.drop_column("laterality")

    # 7. medical_folders
    with op.batch_alter_table("medical_folders", schema=None) as batch_op:
        batch_op.drop_index("ix_medical_folders_assigned_doctor_id")
        batch_op.drop_constraint("fk_medical_folders_closed_by_user", type_="foreignkey")
        batch_op.drop_constraint("fk_medical_folders_assigned_doctor", type_="foreignkey")
        batch_op.drop_column("closed_by_user_id")
        batch_op.drop_column("closed_at")
        batch_op.drop_column("closed_reason")
        batch_op.drop_column("notes_md")
        batch_op.drop_column("assigned_doctor_id")

    # 6. patients
    with op.batch_alter_table("patients", schema=None) as batch_op:
        try:
            batch_op.drop_constraint("uq_patients_clinic_mrn", type_="unique")
        except Exception:  # noqa: BLE001
            pass
        batch_op.drop_index("ix_patients_deleted_at")
        batch_op.drop_index("ix_patients_mrn")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("deleted_at")

    # 5. notifications
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    # 4. invitations / password_reset_tokens
    op.drop_index(
        "ix_password_reset_tokens_user_id", table_name="password_reset_tokens"
    )
    op.drop_index(
        "ix_password_reset_tokens_token_hash", table_name="password_reset_tokens"
    )
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_index("ix_invitations_clinic_id", table_name="invitations")
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.drop_table("invitations")

    # 3. doctors revert
    with op.batch_alter_table("doctors", schema=None) as batch_op:
        batch_op.add_column(sa.Column("full_name", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_active_account",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.drop_constraint("fk_doctors_user_id", type_="foreignkey")
        batch_op.drop_constraint("uq_doctors_user_id", type_="unique")
        batch_op.drop_column("user_id")

    # 2. users
    op.drop_index("ix_users_clinic_id", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    # 1. clinics revert
    with op.batch_alter_table("clinics", schema=None) as batch_op:
        batch_op.drop_index("ix_clinics_slug")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_by_user_id")
        batch_op.drop_column("is_active")
        batch_op.drop_column("plan")
        batch_op.drop_column("country")
        batch_op.drop_column("phone")
        batch_op.drop_column("email")
        batch_op.drop_column("slug")
