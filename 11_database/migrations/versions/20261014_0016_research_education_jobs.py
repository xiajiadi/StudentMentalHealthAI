"""Add a content-free education-support outbox for research CAT sessions.

Revision ID: 20261014_0016
Revises: 20261014_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261014_0016"
down_revision: str | None = "20261014_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii_id(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def upgrade() -> None:
    op.create_table(
        "school_research_education_jobs",
        sa.Column("job_ref", _ascii_id(128), nullable=False),
        sa.Column("research_session_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("task_enrollment_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("task_binding_id", _id(), nullable=False),
        sa.Column("profile_version_id", _id(), nullable=False),
        sa.Column("profile_ref", _ascii_id(128), nullable=False),
        sa.Column("profile_version_number", sa.Integer(), nullable=False),
        sa.Column("profile_sha256", _ascii_id(64), nullable=False),
        sa.Column("response_origin", _ascii_id(32), nullable=False),
        sa.Column("job_kind", _ascii_id(32), server_default="EDUCATION_SUPPORT", nullable=False),
        sa.Column("purpose", _ascii_id(32), server_default="RESEARCH_SIMULATION", nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "publication_status",
            _ascii_id(64),
            server_default="not_approved_for_publication_or_operational_use",
            nullable=False,
        ),
        sa.Column("policy_version", _ascii_id(64), nullable=False),
        sa.Column("policy_hash", _ascii_id(64), nullable=True),
        sa.Column("status", sa.String(24), server_default="QUEUED", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("lease_owner", _ascii_id(128), nullable=True),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("lease_token", _ascii_id(128), nullable=True),
        sa.Column("last_error_code", _ascii_id(128), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_education_jobs"),
        sa.UniqueConstraint("public_id", name="uq_school_research_education_jobs_public_id"),
        sa.UniqueConstraint("job_ref", name="uq_school_research_education_jobs_job_ref"),
        sa.UniqueConstraint(
            "school_id",
            "research_session_id",
            "job_kind",
            "policy_version",
            name="school_research_education_job_idempotency_unique",
        ),
        sa.CheckConstraint(
            "job_kind = 'EDUCATION_SUPPORT'",
            name="ck_school_research_education_jobs_job_kind_allowed",
        ),
        sa.CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'",
            name="ck_school_research_education_jobs_purpose_research_only",
        ),
        sa.CheckConstraint(
            "research_only = 1", name="ck_school_research_education_jobs_research_only_locked"
        ),
        sa.CheckConstraint(
            "publication_status = 'not_approved_for_publication_or_operational_use'",
            name="ck_school_research_education_jobs_publication_not_approved",
        ),
        sa.CheckConstraint(
            "response_origin IN ('PUBLIC_OBSERVED', 'MODEL_GENERATED')",
            name="ck_school_research_education_jobs_response_origin_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'LEASED', 'RETRY', 'HELD', 'ABSTAINED', "
            "'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED')",
            name="ck_school_research_education_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 20",
            name="ck_school_research_education_jobs_attempt_count_bounded",
        ),
        sa.CheckConstraint(
            "(status = 'LEASED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_token IS NOT NULL) OR "
            "(status <> 'LEASED' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND lease_token IS NULL)",
            name="ck_school_research_education_jobs_lease_matches_status",
        ),
        sa.CheckConstraint(
            "status <> 'RETRY' OR next_attempt_at IS NOT NULL",
            name="ck_school_research_education_jobs_retry_has_next_attempt",
        ),
        sa.ForeignKeyConstraint(
            [
                "research_session_id",
                "school_id",
                "task_id",
                "class_id",
                "task_enrollment_id",
                "subject_id",
                "task_binding_id",
                "profile_version_id",
                "profile_ref",
                "profile_version_number",
                "profile_sha256",
                "response_origin",
            ],
            [
                "school_research_sessions.id",
                "school_research_sessions.school_id",
                "school_research_sessions.task_id",
                "school_research_sessions.class_id",
                "school_research_sessions.task_enrollment_id",
                "school_research_sessions.subject_id",
                "school_research_sessions.task_binding_id",
                "school_research_sessions.profile_version_id",
                "school_research_sessions.profile_ref",
                "school_research_sessions.profile_version_number",
                "school_research_sessions.profile_sha256",
                "school_research_sessions.response_origin",
            ],
            name="fk_school_research_education_jobs_session_exact_scope",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_education_jobs_claim",
        "school_research_education_jobs",
        ["status", "next_attempt_at", "lease_expires_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_school_research_education_jobs_claim",
        table_name="school_research_education_jobs",
    )
    op.drop_table("school_research_education_jobs")
