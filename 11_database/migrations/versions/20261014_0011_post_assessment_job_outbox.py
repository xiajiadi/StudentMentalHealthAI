"""Add a content-free durable post-assessment education-support outbox.

Revision ID: 20261014_0011
Revises: 20261013_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261014_0011"
down_revision: str | None = "20261013_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii_id(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    )


def upgrade() -> None:
    table = "school_post_assessment_jobs"
    op.create_table(
        table,
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        *_timestamps(),
        sa.Column("job_ref", _ascii_id(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("class_student_id", _id(), nullable=False),
        sa.Column("task_enrollment_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("assessment_session_id", _id(), nullable=False),
        sa.Column("job_kind", _ascii_id(32), nullable=False),
        sa.Column("policy_version", _ascii_id(64), nullable=False),
        sa.Column("policy_hash", _ascii_id(64), nullable=True),
        sa.Column("status", sa.String(24), server_default="QUEUED", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("lease_owner", _ascii_id(128), nullable=True),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("lease_token", _ascii_id(128), nullable=True),
        sa.Column("source_snapshot_ref", _ascii_id(128), nullable=True),
        sa.Column("source_snapshot_sha256", _ascii_id(64), nullable=True),
        sa.Column("source_qualification_status", _ascii_id(32), nullable=True),
        sa.Column("source_population", _ascii_id(64), nullable=True),
        sa.Column("source_layer", _ascii_id(32), nullable=True),
        sa.Column("source_rights_status", _ascii_id(32), nullable=True),
        sa.Column("source_review_status", _ascii_id(32), nullable=True),
        sa.Column("source_qualified_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_error_code", _ascii_id(128), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("public_id", name=f"uq_{table}_public_id"),
        sa.UniqueConstraint("job_ref", name="uq_school_post_assessment_jobs_job_ref"),
        sa.UniqueConstraint(
            "school_id",
            "assessment_session_id",
            "job_kind",
            "policy_version",
            name="school_post_assessment_job_idempotency_unique",
        ),
        sa.CheckConstraint("job_kind = 'EDUCATION_SUPPORT'", name="job_kind_allowed"),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'LEASED', 'RETRY', 'HELD', 'ABSTAINED', "
            "'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        sa.CheckConstraint(
            "(status = 'LEASED' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND lease_token IS NOT NULL) OR "
            "(status <> 'LEASED' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND lease_token IS NULL)",
            name="lease_matches_status",
        ),
        sa.CheckConstraint(
            "status <> 'RETRY' OR next_attempt_at IS NOT NULL",
            name="retry_has_next_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_post_assessment_jobs_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_post_assessment_jobs_task_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_student_id", "subject_id", "class_id", "school_id"],
            [
                "school_class_students.id", "school_class_students.subject_id",
                "school_class_students.class_id", "school_class_students.school_id",
            ],
            name="fk_school_post_assessment_jobs_roster_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ],
            name="fk_school_post_assessment_jobs_enrollment_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id", "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_post_assessment_jobs_assessment_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"], ["subjects.id", "subjects.school_id"],
            name="fk_school_post_assessment_jobs_subject_scope", ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_post_assessment_jobs_claim",
        table,
        ["status", "next_attempt_at", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "ix_school_post_assessment_jobs_student_status",
        table,
        ["school_id", "subject_id", "status", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM school_post_assessment_jobs")
    ).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade post-assessment jobs while rows exist")

    op.drop_index(
        "ix_school_post_assessment_jobs_student_status",
        table_name="school_post_assessment_jobs",
    )
    op.drop_index(
        "ix_school_post_assessment_jobs_claim",
        table_name="school_post_assessment_jobs",
    )
    op.drop_table("school_post_assessment_jobs")
