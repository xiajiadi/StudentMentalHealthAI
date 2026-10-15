"""Persist encrypted, exact-session education candidates for specialist review.

Revision ID: 20261015_0020
Revises: 20261015_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261015_0020"
down_revision: str | None = "20261015_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_SESSION_SCOPE = (
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
_FEEDBACK_PAIR_CHECK = "ck_school_research_feedback_records_source_candidate_pair_matches"
_FEEDBACK_CANDIDATE_FK = "fk_school_research_feedback_source_candidate_exact_scope"


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def upgrade() -> None:
    with op.batch_alter_table("school_research_education_jobs") as batch:
        batch.create_unique_constraint(
            "school_research_education_job_id_session_school_unique",
            ["id", "research_session_id", "school_id"],
        )

    op.create_table(
        "school_research_education_candidates",
        sa.Column("candidate_ref", _ascii(128), nullable=False),
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
        sa.Column("study_ref", _ascii(128), nullable=False),
        sa.Column("policy_version", _ascii(64), nullable=False),
        sa.Column("policy_hash", _ascii(64), nullable=False),
        sa.Column("source_manifest_sha256", _ascii(64), nullable=False),
        sa.Column("retrieval_id", _ascii(128), nullable=False),
        sa.Column("retrieval_bundle_sha256", _ascii(64), nullable=False),
        sa.Column("prompt_ref", _ascii(128), nullable=False),
        sa.Column("prompt_version", _ascii(64), nullable=False),
        sa.Column("prompt_sha256", _ascii(64), nullable=False),
        sa.Column("model_ref", _ascii(128), nullable=False),
        sa.Column("model_digest_sha256", _ascii(64), nullable=False),
        sa.Column("runtime_version", _ascii(64), nullable=False),
        sa.Column("safety_policy_version", _ascii(64), nullable=False),
        sa.Column("input_safety_action", _ascii(32), nullable=False),
        sa.Column("retrieval_safety_action", _ascii(32), nullable=False),
        sa.Column("output_safety_action", _ascii(32), nullable=False),
        sa.Column("purpose", _ascii(32), server_default="RESEARCH_SIMULATION", nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "psychological_interpretation_allowed", sa.Boolean(), server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "publication_status", _ascii(64),
            server_default="not_approved_for_publication_or_operational_use", nullable=False,
        ),
        sa.Column("content_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_sha256", _ascii(64), nullable=False),
        sa.Column("status", _ascii(16), server_default="HELD", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii(32), nullable=False),
        sa.Column("key_version", _ascii(64), nullable=False),
        sa.Column("payload_schema_version", _ascii(64), nullable=False),
        sa.Column("resolved_by_membership_role_id", _id(), nullable=True),
        sa.Column("resolved_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_education_candidates"),
        sa.UniqueConstraint(
            "public_id", name="uq_school_research_education_candidates_public_id"
        ),
        sa.UniqueConstraint(
            "candidate_ref", name="school_research_education_candidate_ref_unique"
        ),
        sa.UniqueConstraint(
            "job_id", name="school_research_education_candidate_job_unique"
        ),
        sa.UniqueConstraint(
            "id", "research_session_id", "school_id",
            name="school_research_education_candidate_id_session_school_unique",
        ),
        sa.CheckConstraint(
            "content_revision = 1",
            name="ck_school_research_education_candidates_content_revision_fixed",
        ),
        sa.CheckConstraint(
            "status IN ('HELD', 'ADOPTED', 'DISCARDED')",
            name="ck_school_research_education_candidates_status_allowed",
        ),
        sa.CheckConstraint(
            "state_version IN (1, 2)",
            name="ck_school_research_education_candidates_state_version_allowed",
        ),
        sa.CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'",
            name="ck_school_research_education_candidates_purpose_research_only",
        ),
        sa.CheckConstraint(
            "research_only = 1",
            name="ck_school_research_education_candidates_research_only_locked",
        ),
        sa.CheckConstraint(
            "psychological_interpretation_allowed = 0",
            name="ck_school_research_education_candidates_interpretation_disabled",
        ),
        sa.CheckConstraint(
            "publication_status = 'not_approved_for_publication_or_operational_use'",
            name="ck_school_research_education_candidates_publication_not_approved",
        ),
        sa.CheckConstraint(
            "policy_version = 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'",
            name="ck_school_research_education_candidates_policy_version_fixed",
        ),
        sa.CheckConstraint(
            "response_origin = 'PUBLIC_OBSERVED'",
            name="ck_school_research_education_candidates_public_observed_only",
        ),
        sa.CheckConstraint(
            "input_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
            "retrieval_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
            "output_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY')",
            name="ck_school_research_education_candidates_safety_actions_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'HELD' AND state_version = 1 AND resolved_at IS NULL "
            "AND resolved_by_membership_role_id IS NULL) OR "
            "(status IN ('ADOPTED', 'DISCARDED') AND state_version = 2 "
            "AND resolved_at IS NOT NULL AND resolved_by_membership_role_id IS NOT NULL)",
            name="ck_school_research_education_candidates_resolution_state",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "research_session_id", "school_id"],
            [
                "school_research_education_jobs.id",
                "school_research_education_jobs.research_session_id",
                "school_research_education_jobs.school_id",
            ],
            name="fk_school_research_education_candidate_job_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            list(_SESSION_SCOPE),
            [
                "school_research_sessions.id",
                *[f"school_research_sessions.{name}" for name in _SESSION_SCOPE[1:]],
            ],
            name="fk_school_research_education_candidate_session_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_education_candidate_resolver_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_education_candidate_task_status",
        "school_research_education_candidates",
        ["school_id", "task_id", "status", "created_at"],
    )

    op.create_table(
        "school_research_education_candidate_events",
        sa.Column("candidate_id", _id(), nullable=False),
        sa.Column("research_session_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("candidate_ref", _ascii(128), nullable=False),
        sa.Column("candidate_revision", sa.Integer(), server_default="1", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_school_research_education_candidate_events"),
        sa.UniqueConstraint(
            "public_id", name="uq_school_research_education_candidate_events_public_id"
        ),
        sa.UniqueConstraint(
            "candidate_id", "state_version",
            name="school_research_education_candidate_event_version_unique",
        ),
        sa.CheckConstraint(
            "event_type IN ('HELD', 'ADOPTED', 'DISCARDED')",
            name="ck_school_research_education_candidate_events_event_type_allowed",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('HELD', 'ADOPTED', 'DISCARDED')",
            name="ck_school_research_education_candidate_events_from_statu_9335",
        ),
        sa.CheckConstraint(
            "to_status IN ('HELD', 'ADOPTED', 'DISCARDED')",
            name="ck_school_research_education_candidate_events_to_status_allowed",
        ),
        sa.CheckConstraint(
            "candidate_revision = 1",
            name="ck_school_research_education_candidate_events_candidate__b62a",
        ),
        sa.CheckConstraint(
            "state_version IN (1, 2)",
            name="ck_school_research_education_candidate_events_state_vers_9036",
        ),
        sa.CheckConstraint(
            "(event_type = 'HELD' AND from_status IS NULL AND to_status = 'HELD' "
            "AND state_version = 1 AND actor_membership_role_id IS NULL) OR "
            "(event_type IN ('ADOPTED', 'DISCARDED') AND from_status = 'HELD' "
            "AND to_status = event_type AND state_version = 2 "
            "AND actor_membership_role_id IS NOT NULL)",
            name="ck_school_research_education_candidate_events_event_shap_1daf",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "research_session_id", "school_id"],
            [
                "school_research_education_candidates.id",
                "school_research_education_candidates.research_session_id",
                "school_research_education_candidates.school_id",
            ],
            name="fk_school_research_education_candidate_event_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_education_candidate_event_actor_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_education_candidate_event_candidate_version",
        "school_research_education_candidate_events",
        ["candidate_id", "state_version"],
    )

    with op.batch_alter_table("school_research_feedback_records") as batch:
        batch.add_column(sa.Column("source_candidate_id", _id(), nullable=True))
        batch.add_column(sa.Column("source_candidate_revision", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "source_candidate_pair_matches",
            "(source_candidate_id IS NULL AND source_candidate_revision IS NULL) OR "
            "(source_candidate_id IS NOT NULL AND "
            "source_candidate_revision IS NOT NULL AND source_candidate_revision = 1)",
        )
        batch.create_foreign_key(
            "fk_school_research_feedback_source_candidate_exact_scope",
            "school_research_education_candidates",
            ["source_candidate_id", "research_session_id", "school_id"],
            ["id", "research_session_id", "school_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in (
        "school_research_education_candidate_events",
        "school_research_education_candidates",
    ):
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar_one()
        if type(count) is not int or count != 0:
            raise RuntimeError(
                "0020 downgrade refused because education candidate rows exist"
            )
    feedback_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM `school_research_feedback_records` "
            "WHERE `source_candidate_id` IS NOT NULL"
        )
    ).scalar_one()
    if type(feedback_count) is not int or feedback_count != 0:
        raise RuntimeError("0020 downgrade refused because feedback lineage exists")

    with op.batch_alter_table("school_research_feedback_records") as batch:
        batch.drop_constraint(_FEEDBACK_CANDIDATE_FK, type_="foreignkey")
        batch.drop_constraint(_FEEDBACK_PAIR_CHECK, type_="check")
        batch.drop_column("source_candidate_revision")
        batch.drop_column("source_candidate_id")
    op.drop_index(
        "ix_school_research_education_candidate_event_candidate_version",
        table_name="school_research_education_candidate_events",
    )
    op.drop_table("school_research_education_candidate_events")
    op.drop_index(
        "ix_school_research_education_candidate_task_status",
        table_name="school_research_education_candidates",
    )
    op.drop_table("school_research_education_candidates")
    with op.batch_alter_table("school_research_education_jobs") as batch:
        batch.drop_constraint(
            "school_research_education_job_id_session_school_unique", type_="unique"
        )
