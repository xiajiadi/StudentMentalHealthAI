"""Persist encrypted programme candidates pending specialist adoption.

Revision ID: 20261014_0018
Revises: 20261014_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261014_0018"
down_revision: str | None = "20261014_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def upgrade() -> None:
    op.create_table(
        "school_research_programme_candidates",
        sa.Column("candidate_ref", _ascii(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("task_binding_id", _id(), nullable=False),
        sa.Column("profile_version_id", _id(), nullable=False),
        sa.Column("profile_ref", _ascii(128), nullable=False),
        sa.Column("profile_version_number", sa.Integer(), nullable=False),
        sa.Column("profile_sha256", _ascii(64), nullable=False),
        sa.Column("response_origin", _ascii(32), nullable=False),
        sa.Column("study_ref", _ascii(128), nullable=False),
        sa.Column("study_policy_sha256", _ascii(64), nullable=False),
        sa.Column("processor_policy_sha256", _ascii(64), nullable=False),
        sa.Column("programme_ref", _ascii(128), nullable=False),
        sa.Column("source_manifest_sha256", _ascii(64), nullable=False),
        sa.Column("source_set_sha256", _ascii(64), nullable=False),
        sa.Column("retrieval_id", _ascii(128), nullable=False),
        sa.Column("retrieval_bundle_sha256", _ascii(64), nullable=False),
        sa.Column("chunk_set_sha256", _ascii(64), nullable=False),
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
        sa.Column("claim_boundary_version", _ascii(64), nullable=False),
        sa.Column("claim_boundary_status", _ascii(16), nullable=False),
        sa.Column("purpose", _ascii(32), server_default="RESEARCH_SIMULATION", nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "psychological_interpretation_allowed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "publication_status", _ascii(64), server_default=_PUBLICATION_STATUS,
            nullable=False,
        ),
        sa.Column(
            "output_boundary", _ascii(32), server_default="STAFF_REFERENCE_ONLY",
            nullable=False,
        ),
        sa.Column("status", _ascii(16), server_default="HELD", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii(32), nullable=False),
        sa.Column("key_version", _ascii(64), nullable=False),
        sa.Column("payload_schema_version", _ascii(64), nullable=False),
        sa.Column("resolved_by_membership_role_id", _id(), nullable=True),
        sa.Column("resolved_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_programme_candidates"),
        sa.UniqueConstraint("public_id", name="uq_school_research_programme_candidates_public_id"),
        sa.UniqueConstraint("candidate_ref", name="school_research_programme_candidate_ref_unique"),
        sa.UniqueConstraint(
            "school_id", "task_id", "task_binding_id", "study_ref", "study_policy_sha256",
            "processor_policy_sha256",
            "programme_ref", "source_manifest_sha256", "prompt_ref", "prompt_version",
            "prompt_sha256", "model_ref", "model_digest_sha256", "runtime_version",
            "safety_policy_version", "claim_boundary_version",
            name="school_research_programme_candidate_pin_unique",
        ),
        sa.CheckConstraint(
            "status IN ('HELD', 'ADOPTED', 'DISCARDED')",
            name="ck_school_research_programme_candidates_status_allowed",
        ),
        sa.CheckConstraint(
            "state_version IN (1, 2)",
            name="ck_school_research_programme_candidates_state_version_allowed",
        ),
        sa.CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'",
            name="ck_school_research_programme_candidates_purpose_research_only",
        ),
        sa.CheckConstraint(
            "research_only = 1",
            name="ck_school_research_programme_candidates_research_only_locked",
        ),
        sa.CheckConstraint(
            "psychological_interpretation_allowed = 0",
            name="ck_school_research_programme_candidates_interpretation_disabled",
        ),
        sa.CheckConstraint(
            f"publication_status = '{_PUBLICATION_STATUS}'",
            name="ck_school_research_programme_candidates_publication_not_approved",
        ),
        sa.CheckConstraint(
            "output_boundary = 'STAFF_REFERENCE_ONLY'",
            name="ck_school_research_programme_candidates_output_staff_only",
        ),
        sa.CheckConstraint(
            "input_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
            "retrieval_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY') AND "
            "output_safety_action IN ('PROCEED', 'PROCEED_WITH_BOUNDARY')",
            name="ck_school_research_programme_candidates_safety_actions_allowed",
        ),
        sa.CheckConstraint(
            "claim_boundary_status = 'ACCEPTED'",
            name="ck_school_research_programme_candidates_claim_boundary_accepted",
        ),
        sa.CheckConstraint(
            "(status = 'HELD' AND state_version = 1 AND resolved_at IS NULL "
            "AND resolved_by_membership_role_id IS NULL) OR "
            "(status = 'ADOPTED' AND state_version = 2 AND resolved_at IS NOT NULL "
            "AND resolved_by_membership_role_id IS NOT NULL) OR "
            "(status = 'DISCARDED' AND state_version = 2 AND resolved_at IS NOT NULL "
            "AND resolved_by_membership_role_id IS NOT NULL)",
            name="ck_school_research_programme_candidates_resolution_state",
        ),
        sa.ForeignKeyConstraint(
            [
                "task_binding_id", "school_id", "task_id", "class_id", "profile_version_id",
                "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
            ],
            [
                "school_research_task_bindings.id", "school_research_task_bindings.school_id",
                "school_research_task_bindings.task_id", "school_research_task_bindings.class_id",
                "school_research_task_bindings.profile_version_id",
                "school_research_task_bindings.profile_ref",
                "school_research_task_bindings.profile_version_number",
                "school_research_task_bindings.profile_sha256",
                "school_research_task_bindings.response_origin",
            ],
            name="fk_school_research_programme_candidate_binding_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_programme_candidate_resolver_school", ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_programme_candidate_task_status",
        "school_research_programme_candidates",
        ["school_id", "task_id", "status", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM `school_research_programme_candidates`")
    ).scalar_one()
    if type(count) is not int or count != 0:
        raise RuntimeError("0018 downgrade refused because programme candidate rows exist")
    op.drop_table("school_research_programme_candidates")
