"""Add task-scoped professional assignments and review cases.

Revision ID: 20261012_0007
Revises: 20261012_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261012_0007"
down_revision: str | None = "20261012_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_NEW_TABLES = (
    "school_professional_review_events",
    "school_professional_review_cases",
    "school_task_specialist_assignments",
)
_BUSINESS_TABLES = (
    "school_task_specialist_assignments",
    "school_professional_review_cases",
    "school_professional_review_events",
)
_ADDED_UNIQUES = (
    ("assessment_sessions", "assessment_session_review_scope_unique"),
    ("task_enrollments", "task_enrollment_review_scope_unique"),
    ("measurement_tasks", "measurement_task_id_school_unique"),
)


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _public_id() -> sa.String:
    return sa.String(length=36, collation="ascii_bin")


def _ascii_id(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    )


def _identity_columns() -> tuple[sa.Column, sa.Column, sa.Column, sa.Column]:
    return (
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _public_id(), nullable=False),
        *_timestamps(),
    )


def _create_args(table: str) -> tuple[sa.PrimaryKeyConstraint, sa.UniqueConstraint]:
    return (
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("public_id", name=f"uq_{table}_public_id"),
    )


def upgrade() -> None:
    op.create_unique_constraint(
        "measurement_task_id_school_unique", "measurement_tasks", ["id", "school_id"]
    )
    op.create_unique_constraint(
        "task_enrollment_review_scope_unique",
        "task_enrollments",
        ["id", "task_id", "school_id", "subject_id"],
    )
    op.create_unique_constraint(
        "assessment_session_review_scope_unique",
        "assessment_sessions",
        ["id", "task_enrollment_id", "subject_id"],
    )

    op.create_table(
        "school_task_specialist_assignments",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("specialist_membership_role_id", _id(), nullable=False),
        sa.Column("assigned_by_membership_role_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="revocation_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_task_specialist_task_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["specialist_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_task_specialist_specialist_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_task_specialist_assigner_school",
            ondelete="RESTRICT",
        ),
        *_create_args("school_task_specialist_assignments"),
        sa.UniqueConstraint(
            "task_id",
            "specialist_membership_role_id",
            name="school_task_specialist_unique",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_school_task_specialist_scope_status",
        "school_task_specialist_assignments",
        ["school_id", "task_id", "status"],
    )
    op.create_index(
        "ix_school_task_specialist_role_status",
        "school_task_specialist_assignments",
        ["specialist_membership_role_id", "status"],
    )

    op.create_table(
        "school_professional_review_cases",
        sa.Column("review_ref", _ascii_id(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("task_enrollment_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("assessment_session_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("case_note_ciphertext", mysql.MEDIUMBLOB(), nullable=True),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=True),
        sa.Column("key_version", _ascii_id(64), nullable=True),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=True),
        sa.Column("closed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_professional_review_task_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id",
                "task_enrollments.task_id",
                "task_enrollments.school_id",
                "task_enrollments.subject_id",
            ],
            name="fk_school_professional_review_enrollment_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id",
                "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_professional_review_assessment_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_school_professional_review_subject_scope",
            ondelete="RESTRICT",
        ),
        *_create_args("school_professional_review_cases"),
        sa.UniqueConstraint("review_ref", name="school_professional_review_ref_unique"),
        sa.UniqueConstraint(
            "task_enrollment_id", name="school_professional_review_enrollment_unique"
        ),
        sa.UniqueConstraint(
            "assessment_session_id", name="school_professional_review_assessment_unique"
        ),
        sa.UniqueConstraint("id", "school_id", name="school_professional_review_id_school_unique"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_school_professional_review_scope_status",
        "school_professional_review_cases",
        ["school_id", "task_id", "status", "created_at"],
    )
    op.create_index(
        "ix_school_professional_review_subject_created",
        "school_professional_review_cases",
        ["subject_id", "created_at"],
    )

    op.create_table(
        "school_professional_review_events",
        sa.Column("review_case_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("actor_membership_role_id", _id(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii_id(128), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint("event_type IN ('CREATED', 'TRANSITION')", name="event_type_allowed"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED')",
            name="from_status_allowed",
        ),
        sa.CheckConstraint(
            "to_status IN ('OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED')",
            name="to_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id", "school_id"],
            ["school_professional_review_cases.id", "school_professional_review_cases.school_id"],
            name="fk_school_professional_review_events_case_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_professional_review_events_actor_school",
            ondelete="RESTRICT",
        ),
        *_create_args("school_professional_review_events"),
        sa.UniqueConstraint(
            "review_case_id",
            "version",
            name="school_professional_review_event_version_unique",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_school_professional_review_events_case_created",
        "school_professional_review_events",
        ["review_case_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _BUSINESS_TABLES:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if count:
            raise RuntimeError(
                "cannot downgrade school professional review while business rows exist"
            )

    op.drop_index(
        "ix_school_professional_review_events_case_created",
        table_name="school_professional_review_events",
    )
    op.drop_table("school_professional_review_events")
    op.drop_index(
        "ix_school_professional_review_subject_created",
        table_name="school_professional_review_cases",
    )
    op.drop_index(
        "ix_school_professional_review_scope_status",
        table_name="school_professional_review_cases",
    )
    op.drop_table("school_professional_review_cases")
    op.drop_index(
        "ix_school_task_specialist_role_status",
        table_name="school_task_specialist_assignments",
    )
    op.drop_index(
        "ix_school_task_specialist_scope_status",
        table_name="school_task_specialist_assignments",
    )
    op.drop_table("school_task_specialist_assignments")
    for table_name, constraint_name in _ADDED_UNIQUES:
        op.drop_constraint(constraint_name, table_name, type_="unique")
