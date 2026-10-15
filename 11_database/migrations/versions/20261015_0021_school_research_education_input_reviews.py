"""Preserve content-free stopped-input safety review receipts.

Revision ID: 20261015_0021
Revises: 20261015_0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261015_0021"
down_revision: str | None = "20261015_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_SCOPE = (
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
)


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def upgrade() -> None:
    op.create_table(
        "school_research_education_input_reviews",
        sa.Column("input_review_ref", _ascii(128), nullable=False),
        sa.Column("job_id", _id(), nullable=False),
        sa.Column("research_session_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("task_enrollment_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("task_binding_id", _id(), nullable=False),
        sa.Column("profile_version_id", _id(), nullable=False),
        sa.Column("profile_ref", _ascii(128), nullable=False),
        sa.Column("profile_version_number", sa.Integer(), nullable=False),
        sa.Column("profile_sha256", _ascii(64), nullable=False),
        sa.Column("response_origin", _ascii(32), nullable=False),
        sa.Column("safety_decision_id", _ascii(160), nullable=False),
        sa.Column("safety_review_ref", _ascii(160), nullable=False),
        sa.Column("safety_trace_id", _ascii(160), nullable=False),
        sa.Column("safety_operation", _ascii(16), nullable=False),
        sa.Column("safety_action", _ascii(24), nullable=False),
        sa.Column("safety_reason_code", _ascii(64), nullable=False),
        sa.Column("safety_requires_human", sa.Boolean(), nullable=False),
        sa.Column("canonical_input_sha256", _ascii(64), nullable=False),
        sa.Column("policy_version", _ascii(64), nullable=False),
        sa.Column("policy_hash", _ascii(64), nullable=False),
        sa.Column("source_package_ref", _ascii(128), nullable=False),
        sa.Column("source_study_ref", _ascii(128), nullable=False),
        sa.Column("source_manifest_sha256", _ascii(64), nullable=False),
        sa.Column("prompt_id", _ascii(128), nullable=False),
        sa.Column("prompt_version", _ascii(64), nullable=False),
        sa.Column("prompt_sha256", _ascii(64), nullable=False),
        sa.Column("status", _ascii(16), server_default="PENDING", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("resolved_by_membership_role_id", _id(), nullable=True),
        sa.Column("resolved_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_education_input_reviews"),
        sa.UniqueConstraint(
            "public_id", name="uq_school_research_education_input_reviews_public_id"
        ),
        sa.UniqueConstraint(
            "input_review_ref", name="school_research_education_input_review_ref_unique"
        ),
        sa.UniqueConstraint("job_id", name="school_research_education_input_review_job_unique"),
        sa.UniqueConstraint(
            "id",
            "research_session_id",
            "school_id",
            name="school_research_education_input_review_id_session_school_unique",
        ),
        sa.UniqueConstraint(
            "id",
            *_SCOPE,
            name="school_research_education_input_review_scope_unique",
        ),
        sa.CheckConstraint(
            "safety_operation = 'INPUT'",
            name="ck_school_research_education_input_reviews_safety_op",
        ),
        sa.CheckConstraint(
            "safety_action = 'REVIEW_REQUIRED'",
            name="ck_school_research_education_input_reviews_safety_action",
        ),
        sa.CheckConstraint(
            "safety_reason_code = 'CONTENT_CONTROVERSIAL'",
            name="ck_school_research_education_input_reviews_safety_reason",
        ),
        sa.CheckConstraint(
            "safety_requires_human = 1",
            name="ck_school_research_education_input_reviews_safety_human",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'REJECTED', 'REVOKED')",
            name="ck_school_research_education_input_reviews_status_allowed",
        ),
        sa.CheckConstraint(
            "state_version IN (1, 2)", name="ck_school_research_education_input_reviews_state_ver"
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_school_research_education_input_reviews_expiry"
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND state_version = 1 AND resolved_at IS NULL "
            "AND resolved_by_membership_role_id IS NULL) OR "
            "(status IN ('REJECTED', 'REVOKED') AND state_version = 2 "
            "AND resolved_at IS NOT NULL AND resolved_by_membership_role_id IS NOT NULL)",
            name="ck_school_research_education_input_reviews_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "research_session_id", "school_id"],
            [
                "school_research_education_jobs.id",
                "school_research_education_jobs.research_session_id",
                "school_research_education_jobs.school_id",
            ],
            name="fk_school_research_education_input_review_job_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            list(_SCOPE),
            [
                "school_research_sessions.id",
                *[f"school_research_sessions.{name}" for name in _SCOPE[1:]],
            ],
            name="fk_school_research_education_input_review_session_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_education_input_review_actor_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_education_input_review_task_status",
        "school_research_education_input_reviews",
        ["school_id", "task_id", "status", "created_at"],
    )

    op.create_table(
        "school_research_education_input_review_events",
        sa.Column("input_review_id", _id(), nullable=False),
        sa.Column("research_session_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("input_review_ref", _ascii(128), nullable=False),
        sa.Column("actor_membership_role_id", _id(), nullable=True),
        sa.Column("event_type", _ascii(16), nullable=False),
        sa.Column("from_status", _ascii(16), nullable=True),
        sa.Column("to_status", _ascii(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_education_input_review_events"),
        sa.UniqueConstraint(
            "public_id", name="uq_school_research_education_input_review_events_public_id"
        ),
        sa.UniqueConstraint(
            "input_review_id",
            "state_version",
            name="school_research_education_input_review_event_version_unique",
        ),
        sa.CheckConstraint(
            "event_type IN ('PENDING', 'REJECTED', 'REVOKED')",
            name="ck_school_research_education_input_review_events_event_type",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('PENDING', 'REJECTED', 'REVOKED')",
            name="ck_school_research_education_input_review_events_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('PENDING', 'REJECTED', 'REVOKED')",
            name="ck_school_research_education_input_review_events_to_status",
        ),
        sa.CheckConstraint(
            "state_version IN (1, 2)",
            name="ck_school_research_education_input_review_events_state_ver",
        ),
        sa.CheckConstraint(
            "(event_type = 'PENDING' AND from_status IS NULL AND to_status = 'PENDING' "
            "AND state_version = 1 AND actor_membership_role_id IS NULL) OR "
            "(event_type IN ('REJECTED', 'REVOKED') AND from_status = 'PENDING' "
            "AND to_status = event_type AND state_version = 2 "
            "AND actor_membership_role_id IS NOT NULL)",
            name="ck_school_research_education_input_review_events_shape",
        ),
        sa.ForeignKeyConstraint(
            ["input_review_id", "research_session_id", "school_id"],
            [
                "school_research_education_input_reviews.id",
                "school_research_education_input_reviews.research_session_id",
                "school_research_education_input_reviews.school_id",
            ],
            name="fk_school_research_education_input_review_event_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_education_input_review_event_actor_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "school_research_education_input_review_events",
        "school_research_education_input_reviews",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError(f"refusing downgrade: {table} contains review evidence")
    op.drop_table("school_research_education_input_review_events")
    op.drop_index(
        "ix_school_research_education_input_review_task_status",
        table_name="school_research_education_input_reviews",
    )
    op.drop_table("school_research_education_input_reviews")
