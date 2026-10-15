"""Add one-shot, explicitly authorized research education continuation.

Revision ID: 20261015_0022
Revises: 20261015_0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261015_0022"
down_revision: str | None = "20261015_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def upgrade() -> None:
    # Existing rows become round 0. Add the replacement uniqueness before
    # removing the old key so every existing idempotency row remains protected.
    op.add_column(
        "school_research_education_jobs",
        sa.Column(
            "generation_round",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "school_research_education_jobs",
        sa.Column("input_review_id", _id(), nullable=True),
    )
    op.create_unique_constraint(
        "school_research_education_job_round_scope_unique",
        "school_research_education_jobs",
        ["id", "generation_round", "research_session_id", "school_id"],
    )
    op.create_unique_constraint(
        "school_research_education_job_review_scope_unique",
        "school_research_education_jobs",
        ["id", "input_review_id", "research_session_id", "school_id"],
    )
    op.create_unique_constraint(
        "school_research_education_job_input_review_unique",
        "school_research_education_jobs",
        ["input_review_id"],
    )
    op.create_check_constraint(
        "ck_school_research_education_jobs_round_matches_review",
        "school_research_education_jobs",
        "(generation_round = 0 AND input_review_id IS NULL) OR "
        "(generation_round = 1 AND input_review_id IS NOT NULL AND "
        "attempt_count <= 1 AND status <> 'RETRY')",
    )
    op.create_check_constraint(
        "ck_school_research_education_jobs_generation_round_allowed",
        "school_research_education_jobs",
        "generation_round IN (0, 1)",
    )
    op.drop_constraint(
        "school_research_education_job_idempotency_unique",
        "school_research_education_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        "school_research_education_job_idempotency_unique",
        "school_research_education_jobs",
        [
            "school_id",
            "research_session_id",
            "job_kind",
            "policy_version",
            "generation_round",
        ],
    )

    # The review row continues to reference its original round-0 job. Widen
    # every status-shaped event field to fit CONTINUATION_AUTHORIZED (23 chars).
    op.add_column(
        "school_research_education_input_reviews",
        sa.Column(
            "original_job_generation_round",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "school_research_education_input_reviews",
        sa.Column("grant_policy_version", _ascii(64), nullable=True),
    )
    op.add_column(
        "school_research_education_input_reviews",
        sa.Column("grant_policy_hash", _ascii(64), nullable=True),
    )
    op.add_column(
        "school_research_education_input_reviews",
        sa.Column("authorized_by_membership_role_id", _id(), nullable=True),
    )
    op.add_column(
        "school_research_education_input_reviews",
        sa.Column("authorized_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.add_column(
        "school_research_education_input_reviews",
        sa.Column("consumed_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.alter_column(
        "school_research_education_input_reviews",
        "status",
        existing_type=_ascii(16),
        type_=_ascii(24),
        existing_nullable=False,
        existing_server_default="PENDING",
    )
    op.drop_constraint(
        "ck_school_research_education_input_reviews_status_allowed",
        "school_research_education_input_reviews",
        type_="check",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_reviews_status_allowed",
        "school_research_education_input_reviews",
        "status IN ('PENDING', 'CONTINUATION_AUTHORIZED', 'REJECTED', 'REVOKED', 'CONSUMED')",
    )
    op.drop_constraint(
        "ck_school_research_education_input_reviews_state_ver",
        "school_research_education_input_reviews",
        type_="check",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_reviews_state_ver",
        "school_research_education_input_reviews",
        "state_version IN (1, 2, 3)",
    )
    op.drop_constraint(
        "ck_school_research_education_input_reviews_resolution",
        "school_research_education_input_reviews",
        type_="check",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_reviews_resolution",
        "school_research_education_input_reviews",
        "(status = 'PENDING' AND state_version = 1 AND resolved_at IS NULL "
        "AND resolved_by_membership_role_id IS NULL AND authorized_at IS NULL "
        "AND authorized_by_membership_role_id IS NULL AND grant_policy_version IS NULL "
        "AND grant_policy_hash IS NULL AND consumed_at IS NULL) OR "
        "(status IN ('REJECTED', 'REVOKED') AND state_version = 2 "
        "AND resolved_at IS NOT NULL AND resolved_by_membership_role_id IS NOT NULL "
        "AND authorized_at IS NULL AND authorized_by_membership_role_id IS NULL "
        "AND grant_policy_version IS NULL AND grant_policy_hash IS NULL "
        "AND consumed_at IS NULL) OR "
        "(status = 'CONTINUATION_AUTHORIZED' AND state_version = 2 "
        "AND resolved_at IS NULL AND resolved_by_membership_role_id IS NULL "
        "AND authorized_at IS NOT NULL AND authorized_by_membership_role_id IS NOT NULL "
        "AND grant_policy_version IS NOT NULL AND grant_policy_hash IS NOT NULL "
        "AND consumed_at IS NULL) OR "
        "(status = 'REVOKED' AND state_version = 3 "
        "AND resolved_at IS NOT NULL AND resolved_by_membership_role_id IS NOT NULL "
        "AND authorized_at IS NOT NULL AND authorized_by_membership_role_id IS NOT NULL "
        "AND grant_policy_version IS NOT NULL AND grant_policy_hash IS NOT NULL "
        "AND consumed_at IS NULL) OR "
        "(status = 'CONSUMED' AND state_version = 3 AND resolved_at IS NULL "
        "AND resolved_by_membership_role_id IS NULL AND authorized_at IS NOT NULL "
        "AND authorized_by_membership_role_id IS NOT NULL "
        "AND grant_policy_version IS NOT NULL AND grant_policy_hash IS NOT NULL "
        "AND consumed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_reviews_original_round_zero",
        "school_research_education_input_reviews",
        "original_job_generation_round = 0",
    )
    op.create_unique_constraint(
        "school_research_education_input_review_status_scope_unique",
        "school_research_education_input_reviews",
        ["id", "status", "research_session_id", "school_id"],
    )
    op.drop_constraint(
        "fk_school_research_education_input_review_job_exact_scope",
        "school_research_education_input_reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_school_research_education_input_review_job_round_scope",
        "school_research_education_input_reviews",
        "school_research_education_jobs",
        ["job_id", "original_job_generation_round", "research_session_id", "school_id"],
        ["id", "generation_round", "research_session_id", "school_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_school_research_education_input_review_authorizer_school",
        "school_research_education_input_reviews",
        "membership_roles",
        ["authorized_by_membership_role_id", "school_id"],
        ["id", "school_id"],
        ondelete="RESTRICT",
    )

    for name in (
        "ck_school_research_education_input_review_events_event_type",
        "ck_school_research_education_input_review_events_from_status",
        "ck_school_research_education_input_review_events_to_status",
        "ck_school_research_education_input_review_events_state_ver",
        "ck_school_research_education_input_review_events_shape",
    ):
        op.drop_constraint(name, "school_research_education_input_review_events", type_="check")
    for column in ("event_type", "from_status", "to_status"):
        op.alter_column(
            "school_research_education_input_review_events",
            column,
            existing_type=_ascii(16),
            type_=_ascii(24),
            existing_nullable=column == "from_status",
        )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_event_type",
        "school_research_education_input_review_events",
        "event_type IN ('PENDING', 'CONTINUATION_AUTHORIZED', 'REJECTED', 'REVOKED', 'CONSUMED')",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_from_status",
        "school_research_education_input_review_events",
        "from_status IS NULL OR from_status IN "
        "('PENDING', 'CONTINUATION_AUTHORIZED', 'REJECTED', 'REVOKED', 'CONSUMED')",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_to_status",
        "school_research_education_input_review_events",
        "to_status IN ('PENDING', 'CONTINUATION_AUTHORIZED', 'REJECTED', 'REVOKED', 'CONSUMED')",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_state_ver",
        "school_research_education_input_review_events",
        "state_version IN (1, 2, 3)",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_shape",
        "school_research_education_input_review_events",
        "(event_type = 'PENDING' AND from_status IS NULL AND to_status = 'PENDING' "
        "AND state_version = 1 AND actor_membership_role_id IS NULL) OR "
        "(event_type = 'CONTINUATION_AUTHORIZED' AND from_status = 'PENDING' "
        "AND to_status = event_type AND state_version = 2 "
        "AND actor_membership_role_id IS NOT NULL) OR "
        "(event_type IN ('REJECTED', 'REVOKED') AND from_status = 'PENDING' "
        "AND to_status = event_type AND state_version = 2 "
        "AND actor_membership_role_id IS NOT NULL) OR "
        "(event_type = 'REVOKED' AND from_status = 'CONTINUATION_AUTHORIZED' "
        "AND to_status = event_type AND state_version = 3 "
        "AND actor_membership_role_id IS NOT NULL) OR "
        "(event_type = 'CONSUMED' AND from_status = 'CONTINUATION_AUTHORIZED' "
        "AND to_status = event_type AND state_version = 3 "
        "AND actor_membership_role_id IS NULL)",
    )

    # Add the reciprocal job->review FK only after both tables and parent
    # indexes exist. Round-0 jobs stay NULL; round-1 jobs point at an authorized
    # review that already exists.
    op.create_foreign_key(
        "fk_school_research_education_job_review_scope",
        "school_research_education_jobs",
        "school_research_education_input_reviews",
        ["input_review_id", "research_session_id", "school_id"],
        ["id", "research_session_id", "school_id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "school_research_education_candidates",
        sa.Column(
            "generation_round",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "school_research_education_candidates",
        sa.Column("input_review_id", _id(), nullable=True),
    )
    op.add_column(
        "school_research_education_candidates",
        sa.Column("input_review_state", _ascii(24), nullable=True),
    )
    op.create_unique_constraint(
        "school_research_education_candidate_job_round_scope_unique",
        "school_research_education_candidates",
        ["job_id", "generation_round", "research_session_id", "school_id"],
    )
    op.drop_constraint(
        "ck_school_research_education_candidates_safety_actions_allowed",
        "school_research_education_candidates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_school_research_education_candidates_safety_actions_allowed",
        "school_research_education_candidates",
        "((generation_round = 0 AND input_review_id IS NULL "
        "AND input_review_state IS NULL AND input_safety_action IN "
        "('PROCEED', 'PROCEED_WITH_BOUNDARY')) OR "
        "(generation_round = 1 AND input_review_id IS NOT NULL "
        "AND input_review_state IS NOT NULL AND input_review_state = 'CONSUMED' "
        "AND input_safety_action = 'REVIEW_REQUIRED')) AND "
        "retrieval_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
        "output_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY')",
    )
    op.create_foreign_key(
        "fk_school_research_education_candidate_job_round_scope",
        "school_research_education_candidates",
        "school_research_education_jobs",
        ["job_id", "generation_round", "research_session_id", "school_id"],
        ["id", "generation_round", "research_session_id", "school_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_school_research_education_candidate_job_review_scope",
        "school_research_education_candidates",
        "school_research_education_jobs",
        ["job_id", "input_review_id", "research_session_id", "school_id"],
        ["id", "input_review_id", "research_session_id", "school_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_school_research_education_candidate_consumed_review",
        "school_research_education_candidates",
        "school_research_education_input_reviews",
        ["input_review_id", "input_review_state", "research_session_id", "school_id"],
        ["id", "status", "research_session_id", "school_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    bind = op.get_bind()
    checks = (
        (
            "school_research_education_jobs",
            "generation_round <> 0 OR input_review_id IS NOT NULL",
        ),
        (
            "school_research_education_candidates",
            "generation_round <> 0 OR input_review_id IS NOT NULL "
            "OR input_review_state IS NOT NULL OR input_safety_action = 'REVIEW_REQUIRED'",
        ),
        (
            "school_research_education_input_reviews",
            "status = 'CONTINUATION_AUTHORIZED' OR status = 'CONSUMED' "
            "OR state_version = 3 OR grant_policy_version IS NOT NULL "
            "OR grant_policy_hash IS NOT NULL OR consumed_at IS NOT NULL",
        ),
        (
            "school_research_education_input_review_events",
            "event_type = 'CONTINUATION_AUTHORIZED' OR event_type = 'CONSUMED' "
            "OR state_version = 3 OR from_status = 'CONTINUATION_AUTHORIZED' "
            "OR to_status IN ('CONTINUATION_AUTHORIZED', 'CONSUMED')",
        ),
    )
    for table, predicate in checks:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE {predicate} LIMIT 1")).first():
            raise RuntimeError(f"0022 downgrade refused because {table} has continuation data")

    op.drop_constraint(
        "fk_school_research_education_candidate_consumed_review",
        "school_research_education_candidates",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_school_research_education_candidate_job_review_scope",
        "school_research_education_candidates",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_school_research_education_candidate_job_round_scope",
        "school_research_education_candidates",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_school_research_education_candidates_safety_actions_allowed",
        "school_research_education_candidates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_school_research_education_candidates_safety_actions_allowed",
        "school_research_education_candidates",
        "input_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
        "retrieval_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
        "output_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY')",
    )
    op.drop_constraint(
        "school_research_education_candidate_job_round_scope_unique",
        "school_research_education_candidates",
        type_="unique",
    )
    op.drop_column("school_research_education_candidates", "input_review_state")
    op.drop_column("school_research_education_candidates", "input_review_id")
    op.drop_column("school_research_education_candidates", "generation_round")

    op.drop_constraint(
        "fk_school_research_education_job_review_scope",
        "school_research_education_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_school_research_education_input_review_authorizer_school",
        "school_research_education_input_reviews",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_school_research_education_input_review_job_round_scope",
        "school_research_education_input_reviews",
        type_="foreignkey",
    )
    op.drop_constraint(
        "school_research_education_input_review_status_scope_unique",
        "school_research_education_input_reviews",
        type_="unique",
    )
    for name in (
        "ck_school_research_education_input_reviews_original_round_zero",
        "ck_school_research_education_input_reviews_resolution",
        "ck_school_research_education_input_reviews_state_ver",
        "ck_school_research_education_input_reviews_status_allowed",
    ):
        op.drop_constraint(name, "school_research_education_input_reviews", type_="check")
    op.create_check_constraint(
        "ck_school_research_education_input_reviews_status_allowed",
        "school_research_education_input_reviews",
        "status IN ('PENDING', 'REJECTED', 'REVOKED')",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_reviews_state_ver",
        "school_research_education_input_reviews",
        "state_version IN (1, 2)",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_reviews_resolution",
        "school_research_education_input_reviews",
        "(status = 'PENDING' AND state_version = 1 AND resolved_at IS NULL "
        "AND resolved_by_membership_role_id IS NULL) OR "
        "(status IN ('REJECTED', 'REVOKED') AND state_version = 2 "
        "AND resolved_at IS NOT NULL AND resolved_by_membership_role_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_school_research_education_input_review_events_shape",
        "school_research_education_input_review_events",
        type_="check",
    )
    for name in (
        "ck_school_research_education_input_review_events_event_type",
        "ck_school_research_education_input_review_events_from_status",
        "ck_school_research_education_input_review_events_to_status",
        "ck_school_research_education_input_review_events_state_ver",
    ):
        op.drop_constraint(name, "school_research_education_input_review_events", type_="check")
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_event_type",
        "school_research_education_input_review_events",
        "event_type IN ('PENDING', 'REJECTED', 'REVOKED')",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_from_status",
        "school_research_education_input_review_events",
        "from_status IS NULL OR from_status IN ('PENDING', 'REJECTED', 'REVOKED')",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_to_status",
        "school_research_education_input_review_events",
        "to_status IN ('PENDING', 'REJECTED', 'REVOKED')",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_state_ver",
        "school_research_education_input_review_events",
        "state_version IN (1, 2)",
    )
    op.create_check_constraint(
        "ck_school_research_education_input_review_events_shape",
        "school_research_education_input_review_events",
        "(event_type = 'PENDING' AND from_status IS NULL AND to_status = 'PENDING' "
        "AND state_version = 1 AND actor_membership_role_id IS NULL) OR "
        "(event_type IN ('REJECTED', 'REVOKED') AND from_status = 'PENDING' "
        "AND to_status = event_type AND state_version = 2 "
        "AND actor_membership_role_id IS NOT NULL)",
    )
    for column in ("event_type", "from_status", "to_status"):
        op.alter_column(
            "school_research_education_input_review_events",
            column,
            existing_type=_ascii(24),
            type_=_ascii(16),
            existing_nullable=column == "from_status",
        )
    op.alter_column(
        "school_research_education_input_reviews",
        "status",
        existing_type=_ascii(24),
        type_=_ascii(16),
        existing_nullable=False,
        existing_server_default="PENDING",
    )
    op.drop_column("school_research_education_input_reviews", "consumed_at")
    op.drop_column("school_research_education_input_reviews", "authorized_at")
    op.drop_column(
        "school_research_education_input_reviews", "authorized_by_membership_role_id"
    )
    op.drop_column("school_research_education_input_reviews", "grant_policy_hash")
    op.drop_column("school_research_education_input_reviews", "grant_policy_version")
    op.drop_column(
        "school_research_education_input_reviews", "original_job_generation_round"
    )
    op.create_foreign_key(
        "fk_school_research_education_input_review_job_exact_scope",
        "school_research_education_input_reviews",
        "school_research_education_jobs",
        ["job_id", "research_session_id", "school_id"],
        ["id", "research_session_id", "school_id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "ck_school_research_education_jobs_generation_round_allowed",
        "school_research_education_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_school_research_education_jobs_round_matches_review",
        "school_research_education_jobs",
        type_="check",
    )
    op.drop_constraint(
        "school_research_education_job_input_review_unique",
        "school_research_education_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "school_research_education_job_review_scope_unique",
        "school_research_education_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "school_research_education_job_round_scope_unique",
        "school_research_education_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "school_research_education_job_idempotency_unique",
        "school_research_education_jobs",
        type_="unique",
    )
    op.drop_column("school_research_education_jobs", "input_review_id")
    op.drop_column("school_research_education_jobs", "generation_round")
    op.create_unique_constraint(
        "school_research_education_job_idempotency_unique",
        "school_research_education_jobs",
        ["school_id", "research_session_id", "job_kind", "policy_version"],
    )
