"""clinical clinics jobs sharing

Revision ID: f8a1c2b3d4e5
Revises: c659eb5a60d0
Create Date: 2026-05-01

"""
from alembic import op
import sqlalchemy as sa


revision = "f8a1c2b3d4e5"
down_revision = "c659eb5a60d0"
branch_labels = None
depends_on = None


def _dialect():
    return op.get_bind().dialect.name


def upgrade():
    op.create_table(
        "clinics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    conn = op.get_bind()
    if _dialect() == "mysql":
        conn.execute(sa.text("INSERT INTO clinics (name, created_at) VALUES ('Default Clinic', NOW())"))
    else:
        conn.execute(
            sa.text("INSERT INTO clinics (name, created_at) VALUES ('Default Clinic', CURRENT_TIMESTAMP)")
        )
    default_clinic_id = conn.scalar(sa.text("SELECT id FROM clinics ORDER BY id ASC LIMIT 1"))

    with op.batch_alter_table("doctors", schema=None) as batch_op:
        batch_op.add_column(sa.Column("clinic_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("title", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("phone", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("locale", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("preferences_json", sa.JSON(), nullable=True))

    conn.execute(
        sa.text("UPDATE doctors SET clinic_id = :cid WHERE clinic_id IS NULL"),
        {"cid": default_clinic_id},
    )

    with op.batch_alter_table("doctors", schema=None) as batch_op:
        batch_op.alter_column("clinic_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_doctors_clinic_id", "clinics", ["clinic_id"], ["id"])
        batch_op.create_index(batch_op.f("ix_doctors_clinic_id"), ["clinic_id"], unique=False)

    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("clinic_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("mrn", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("clinical_notes", sa.Text(), nullable=True))

    if _dialect() == "mysql":
        op.execute(
            """
            UPDATE patients p
            INNER JOIN (
                SELECT mf.patient_id AS pid, MIN(d.clinic_id) AS cid
                FROM medical_folders mf
                INNER JOIN doctors d ON d.id = mf.doctor_id
                GROUP BY mf.patient_id
            ) x ON p.id = x.pid
            SET p.clinic_id = x.cid
            """
        )
    else:
        op.execute(
            """
            UPDATE patients
            SET clinic_id = (
                SELECT d.clinic_id FROM medical_folders mf
                JOIN doctors d ON d.id = mf.doctor_id
                WHERE mf.patient_id = patients.id
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM medical_folders mf2
                WHERE mf2.patient_id = patients.id
            )
            """
        )

    conn.execute(
        sa.text("UPDATE patients SET clinic_id = :cid WHERE clinic_id IS NULL"),
        {"cid": default_clinic_id},
    )

    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.alter_column("clinic_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_patients_clinic_id", "clinics", ["clinic_id"], ["id"])
        batch_op.create_index(batch_op.f("ix_patients_clinic_id"), ["clinic_id"], unique=False)

    op.create_table(
        "folder_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("shared_with_doctor_id", sa.Integer(), nullable=False),
        sa.Column("shared_by_doctor_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["folder_id"], ["medical_folders.id"]),
        sa.ForeignKeyConstraint(["shared_by_doctor_id"], ["doctors.id"]),
        sa.ForeignKeyConstraint(["shared_with_doctor_id"], ["doctors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("folder_id", "shared_with_doctor_id", name="uq_folder_share_recipient"),
    )
    with op.batch_alter_table("folder_shares", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_folder_shares_folder_id"), ["folder_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_folder_shares_shared_with_doctor_id"),
            ["shared_with_doctor_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_folder_shares_shared_by_doctor_id"),
            ["shared_by_doctor_id"],
            unique=False,
        )

    with op.batch_alter_table("inference_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_progress_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_known_async_state", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))

    if _dialect() == "mysql":
        op.execute(
            """
            ALTER TABLE inference_jobs
            MODIFY COLUMN status ENUM(
                'queued','running','done','failed','timed_out','cancelled'
            ) NOT NULL
            """
        )
    else:
        pass


def downgrade():
    with op.batch_alter_table("inference_jobs", schema=None) as batch_op:
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("last_known_async_state")
        batch_op.drop_column("last_progress_at")

    if _dialect() == "mysql":
        op.execute(
            """
            ALTER TABLE inference_jobs
            MODIFY COLUMN status ENUM('queued','running','done','failed') NOT NULL
            """
        )

    op.drop_table("folder_shares")

    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.drop_constraint("fk_patients_clinic_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_patients_clinic_id"))
        batch_op.drop_column("clinical_notes")
        batch_op.drop_column("mrn")
        batch_op.drop_column("clinic_id")

    with op.batch_alter_table("doctors", schema=None) as batch_op:
        batch_op.drop_constraint("fk_doctors_clinic_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_doctors_clinic_id"))
        batch_op.drop_column("preferences_json")
        batch_op.drop_column("locale")
        batch_op.drop_column("phone")
        batch_op.drop_column("title")
        batch_op.drop_column("clinic_id")

    op.drop_table("clinics")
