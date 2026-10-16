"""Create encrypted independent research education review resources.

Revision ID: 20261016_0024
Revises: 20261016_0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261016_0024"
down_revision: str | None = "20261016_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _dt() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "school_independent_education_reviews",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.Column("review_ref", _ascii(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("support_session_id", _id(), nullable=False),
        sa.Column("support_run_id", _id(), nullable=False),
        sa.Column("reviewer_membership_role_id", _id(), nullable=True),
        sa.Column("consent_notice_version", _ascii(64), nullable=True),
        sa.Column("status", _ascii(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("purpose", _ascii(32), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("professional_approval", sa.Boolean(), nullable=False),
        sa.Column("clinical_approval", sa.Boolean(), nullable=False),
        sa.Column("psychometric_approval", sa.Boolean(), nullable=False),
        sa.Column("ethics_approval", sa.Boolean(), nullable=False),
        sa.Column("school_production_approval", sa.Boolean(), nullable=False),
        sa.Column("source_study_ref", _ascii(128), nullable=False),
        sa.Column("source_package_ref", _ascii(128), nullable=False),
        sa.Column("source_manifest_sha256", _ascii(64), nullable=False),
        sa.Column("retrieval_id", _ascii(128), nullable=False),
        sa.Column("retrieval_bundle_sha256", _ascii(64), nullable=False),
        sa.Column("prompt_id", _ascii(128), nullable=False),
        sa.Column("prompt_version", _ascii(64), nullable=False),
        sa.Column("prompt_sha256", _ascii(64), nullable=True),
        sa.Column("model_id", _ascii(128), nullable=False),
        sa.Column("logical_model_id", _ascii(128), nullable=False),
        sa.Column("model_version", _ascii(128), nullable=False),
        sa.Column("model_digest_sha256", _ascii(64), nullable=False),
        sa.Column("runtime_version", _ascii(64), nullable=False),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("input_safety_action", _ascii(32), nullable=False),
        sa.Column("input_safety_reason_codes", mysql.JSON(), nullable=False),
        sa.Column("retrieval_safety_action", _ascii(32), nullable=False),
        sa.Column("retrieval_safety_reason_codes", mysql.JSON(), nullable=False),
        sa.Column("output_safety_action", _ascii(32), nullable=False),
        sa.Column("output_safety_reason_codes", mysql.JSON(), nullable=False),
        sa.Column("claim_boundary_status", _ascii(16), nullable=False),
        sa.Column("citation_binding_status", _ascii(16), nullable=False),
        sa.Column("candidate_content_sha256", _ascii(64), nullable=False),
        sa.Column("candidate_payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("candidate_cipher_format_version", _ascii(32), nullable=False),
        sa.Column("candidate_key_version", _ascii(64), nullable=False),
        sa.Column("candidate_payload_schema_version", _ascii(64), nullable=False),
        sa.Column("reviewed_content_sha256", _ascii(64), nullable=True),
        sa.Column("reviewed_payload_ciphertext", mysql.MEDIUMBLOB(), nullable=True),
        sa.Column("reviewed_cipher_format_version", _ascii(32), nullable=True),
        sa.Column("reviewed_key_version", _ascii(64), nullable=True),
        sa.Column("reviewed_payload_schema_version", _ascii(64), nullable=True),
        sa.Column("reviewed_at", _dt(), nullable=True),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("shared_at", _dt(), nullable=True),
        sa.Column("published_at", _dt(), nullable=True),
        sa.Column("revoked_at", _dt(), nullable=True),
        sa.Column("withdrawn_at", _dt(), nullable=True),
        sa.Column("retention_due_at", _dt(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_school_independent_education_reviews"),
        sa.UniqueConstraint("public_id", name="uq_school_independent_education_reviews_public_id"),
        sa.UniqueConstraint(
            "review_ref", name="uq_school_independent_education_reviews_review_ref"
        ),
        sa.UniqueConstraint(
            "support_run_id", name="uq_school_independent_education_reviews_support_run_id"
        ),
        sa.UniqueConstraint(
            "id", "school_id", name="uq_school_independent_education_reviews_id_school"
        ),
        sa.UniqueConstraint(
            "id",
            "school_id",
            "subject_id",
            "support_session_id",
            name="uq_school_independent_education_reviews_scope",
        ),
        sa.CheckConstraint(
            "status IN ('HELD', 'SHARED', 'DRAFT', 'PUBLISHED', 'REVOKED', 'WITHDRAWN')",
            name="ck_school_independent_education_reviews_status_allowed",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_school_independent_education_reviews_state_version_positive",
        ),
        sa.CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'",
            name="ck_school_independent_education_reviews_purpose_research_only",
        ),
        sa.CheckConstraint(
            "research_only = 1", name="ck_school_independent_education_reviews_research_only_locked"
        ),
        sa.CheckConstraint(
            "professional_approval = 0",
            name="ck_school_independent_education_reviews_professional_false",
        ),
        sa.CheckConstraint(
            "clinical_approval = 0", name="ck_school_independent_education_reviews_clinical_false"
        ),
        sa.CheckConstraint(
            "psychometric_approval = 0",
            name="ck_school_independent_education_reviews_psychometric_false",
        ),
        sa.CheckConstraint(
            "ethics_approval = 0", name="ck_school_independent_education_reviews_ethics_false"
        ),
        sa.CheckConstraint(
            "school_production_approval = 0",
            name="ck_school_independent_education_reviews_production_false",
        ),
        sa.CheckConstraint(
            "(reviewer_membership_role_id IS NULL AND shared_at IS NULL "
            "AND consent_notice_version IS NULL) OR "
            "(reviewer_membership_role_id IS NOT NULL AND shared_at IS NOT NULL "
            "AND consent_notice_version IS NOT NULL)",
            name="ck_school_independent_education_reviews_share_assignment_pair",
        ),
        sa.CheckConstraint(
            "(reviewed_payload_ciphertext IS NULL AND reviewed_cipher_format_version IS NULL "
            "AND reviewed_key_version IS NULL AND reviewed_payload_schema_version IS NULL "
            "AND reviewed_content_sha256 IS NULL AND reviewed_at IS NULL "
            "AND content_revision = 0) OR "
            "(reviewed_payload_ciphertext IS NOT NULL "
            "AND reviewed_cipher_format_version IS NOT NULL "
            "AND reviewed_key_version IS NOT NULL AND reviewed_payload_schema_version IS NOT NULL "
            "AND reviewed_content_sha256 IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND content_revision >= 1)",
            name="ck_school_independent_education_reviews_reviewed_cipher_envelope",
        ),
        sa.CheckConstraint(
            "input_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
            "retrieval_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
            "output_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY')",
            name="ck_school_independent_education_reviews_safety_actions_passed",
        ),
        sa.CheckConstraint(
            "(status = 'HELD' AND reviewer_membership_role_id IS NULL AND shared_at IS NULL "
            "AND published_at IS NULL AND revoked_at IS NULL AND withdrawn_at IS NULL) OR "
            "(status = 'SHARED' AND reviewer_membership_role_id IS NOT NULL "
            "AND shared_at IS NOT NULL "
            "AND published_at IS NULL AND revoked_at IS NULL AND withdrawn_at IS NULL) OR "
            "(status = 'DRAFT' AND reviewer_membership_role_id IS NOT NULL "
            "AND shared_at IS NOT NULL AND content_revision >= 1 "
            "AND published_at IS NULL AND revoked_at IS NULL AND withdrawn_at IS NULL) OR "
            "(status = 'PUBLISHED' AND reviewer_membership_role_id IS NOT NULL "
            "AND shared_at IS NOT NULL AND content_revision >= 1 "
            "AND published_at IS NOT NULL AND revoked_at IS NULL AND withdrawn_at IS NULL) OR "
            "(status = 'REVOKED' AND reviewer_membership_role_id IS NOT NULL "
            "AND shared_at IS NOT NULL AND content_revision >= 1 "
            "AND published_at IS NOT NULL AND revoked_at IS NOT NULL AND withdrawn_at IS NULL) OR "
            "(status = 'WITHDRAWN' AND withdrawn_at IS NOT NULL AND "
            "(revoked_at IS NULL OR (published_at IS NOT NULL AND content_revision >= 1)) AND "
            "((reviewer_membership_role_id IS NULL AND shared_at IS NULL) OR "
            "(reviewer_membership_role_id IS NOT NULL AND shared_at IS NOT NULL)))",
            name="ck_school_independent_education_reviews_state_timestamps_match",
        ),
        sa.CheckConstraint(
            "claim_boundary_status = 'ACCEPTED' AND citation_binding_status = 'BOUND'",
            name="ck_school_independent_education_reviews_claims_citations_bound",
        ),
        sa.ForeignKeyConstraint(
            ["support_session_id", "subject_id"],
            ["support_sessions.id", "support_sessions.subject_id"],
            name="fk_ind_edu_review_session_subject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["support_run_id", "support_session_id"],
            ["support_runs.id", "support_runs.support_session_id"],
            name="fk_ind_edu_review_run_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_ind_edu_review_subject_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_ind_edu_review_reviewer_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_ind_edu_review_owner_status",
        "school_independent_education_reviews",
        ["school_id", "subject_id", "status", "created_at"],
    )
    op.create_index(
        "ix_ind_edu_review_reviewer_status",
        "school_independent_education_reviews",
        ["school_id", "reviewer_membership_role_id", "status", "created_at"],
    )
    op.create_table(
        "school_independent_education_review_events",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("review_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("actor_membership_role_id", _id(), nullable=False),
        sa.Column("event_type", _ascii(16), nullable=False),
        sa.Column("from_status", _ascii(16), nullable=True),
        sa.Column("to_status", _ascii(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("retention_due_at", _dt(), nullable=True),
        sa.Column("created_at", _dt(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_independent_education_review_events"),
        sa.UniqueConstraint(
            "public_id", name="uq_school_independent_education_review_events_public_id"
        ),
        sa.UniqueConstraint(
            "review_id",
            "state_version",
            name="uq_school_independent_education_review_events_version",
        ),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'SHARED', 'DRAFT_SAVED', 'PUBLISHED', "
            "'REVOKED', 'WITHDRAWN')",
            name="ck_school_independent_education_review_events_event_type_allowed",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_school_independent_education_review_events_state_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "school_id"],
            [
                "school_independent_education_reviews.id",
                "school_independent_education_reviews.school_id",
            ],
            name="fk_ind_edu_review_event_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_ind_edu_review_event_actor",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_ind_edu_review_events_created",
        "school_independent_education_review_events",
        ["review_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "school_independent_education_review_events",
        "school_independent_education_reviews",
    ):
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError("0024 downgrade refuses to delete independent education review data")
    op.drop_table("school_independent_education_review_events")
    op.drop_table("school_independent_education_reviews")
