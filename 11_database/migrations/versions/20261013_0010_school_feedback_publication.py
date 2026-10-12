"""Add isolated synthetic L3 feedback records and content-free events.

Revision ID: 20261013_0010
Revises: 20261013_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261013_0010"
down_revision: str | None = "20261013_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_BUSINESS_TABLES = ("school_feedback_events", "school_feedback_records")


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii_id(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    )


def _identity_columns(table: str) -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("public_id", name=f"uq_{table}_public_id"),
    )


def _table_options() -> dict[str, str]:
    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }


def upgrade() -> None:
    op.create_unique_constraint(
        "school_professional_review_feedback_scope_unique",
        "school_professional_review_cases",
        [
            "id",
            "school_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "assessment_session_id",
        ],
    )

    op.create_table(
        "school_feedback_records",
        sa.Column("feedback_ref", _ascii_id(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("task_enrollment_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("assessment_session_id", _id(), nullable=False),
        sa.Column("review_case_id", _id(), nullable=False),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("level", _ascii_id(2), server_default="L3", nullable=False),
        sa.Column("synthetic_only", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=False),
        sa.Column("key_version", _ascii_id(64), nullable=False),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=False),
        sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns("school_feedback_records"),
        sa.UniqueConstraint("feedback_ref", name="school_feedback_ref_unique"),
        sa.UniqueConstraint(
            "review_case_id",
            "content_revision",
            name="school_feedback_case_content_revision_unique",
        ),
        sa.UniqueConstraint(
            "id",
            "school_id",
            "review_case_id",
            "content_revision",
            name="school_feedback_event_scope_unique",
        ),
        sa.CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'REVOKED')", name="status_allowed"),
        sa.CheckConstraint("content_revision >= 1", name="content_revision_positive"),
        sa.CheckConstraint("case_version >= 1", name="case_version_positive"),
        sa.CheckConstraint("state_version >= 1", name="state_version_positive"),
        sa.CheckConstraint("level = 'L3'", name="level_synthetic_l3_only"),
        sa.CheckConstraint("synthetic_only = 1", name="synthetic_only_locked"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'PUBLISHED' AND published_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND published_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="status_timestamps_match",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_feedback_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "review_case_id",
                "school_id",
                "task_id",
                "class_id",
                "task_enrollment_id",
                "subject_id",
                "assessment_session_id",
            ],
            [
                "school_professional_review_cases.id",
                "school_professional_review_cases.school_id",
                "school_professional_review_cases.task_id",
                "school_professional_review_cases.class_id",
                "school_professional_review_cases.task_enrollment_id",
                "school_professional_review_cases.subject_id",
                "school_professional_review_cases.assessment_session_id",
            ],
            name="fk_school_feedback_review_case_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_feedback_task_scope",
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
            name="fk_school_feedback_enrollment_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id",
                "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_feedback_assessment_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_school_feedback_subject_scope",
            ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_feedback_student_status_created",
        "school_feedback_records",
        ["school_id", "subject_id", "status", "created_at"],
    )
    op.create_index(
        "ix_school_feedback_case_revision",
        "school_feedback_records",
        ["school_id", "review_case_id", "content_revision"],
    )

    op.create_table(
        "school_feedback_events",
        sa.Column("feedback_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("review_case_id", _id(), nullable=False),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("actor_membership_role_id", _id(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii_id(128), nullable=True),
        *_identity_columns("school_feedback_events"),
        sa.UniqueConstraint(
            "feedback_id",
            "state_version",
            name="school_feedback_event_state_version_unique",
        ),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'PUBLISHED', 'REVOKED')", name="event_type_allowed"
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('DRAFT', 'PUBLISHED', 'REVOKED')",
            name="from_status_allowed",
        ),
        sa.CheckConstraint(
            "to_status IN ('DRAFT', 'PUBLISHED', 'REVOKED')", name="to_status_allowed"
        ),
        sa.CheckConstraint("state_version >= 1", name="state_version_positive"),
        sa.ForeignKeyConstraint(
            ["feedback_id", "school_id", "review_case_id", "content_revision"],
            [
                "school_feedback_records.id",
                "school_feedback_records.school_id",
                "school_feedback_records.review_case_id",
                "school_feedback_records.content_revision",
            ],
            name="fk_school_feedback_events_record_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_feedback_events_actor_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_feedback_events_school",
            ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_feedback_events_case_created",
        "school_feedback_events",
        ["school_id", "review_case_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _BUSINESS_TABLES:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if count:
            raise RuntimeError("cannot downgrade school feedback while business rows exist")

    op.drop_index("ix_school_feedback_events_case_created", table_name="school_feedback_events")
    op.drop_table("school_feedback_events")
    op.drop_index("ix_school_feedback_case_revision", table_name="school_feedback_records")
    op.drop_index("ix_school_feedback_student_status_created", table_name="school_feedback_records")
    op.drop_table("school_feedback_records")
    op.drop_constraint(
        "school_professional_review_feedback_scope_unique",
        "school_professional_review_cases",
        type_="unique",
    )
