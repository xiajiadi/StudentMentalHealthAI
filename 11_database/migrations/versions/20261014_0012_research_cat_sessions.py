"""Add isolated research CAT profiles, task bindings, and sessions.

Revision ID: 20261014_0012
Revises: 20261014_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261014_0012"
down_revision: str | None = "20261014_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_BUSINESS_TABLES = (
    "school_research_sessions",
    "school_research_task_bindings",
    "school_research_profile_versions",
)
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_PURPOSE = "RESEARCH_SIMULATION"


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
    # Existing rows retain their FIXTURE default and their stored values. This
    # adds a routing marker only; AssessmentSession remains unchanged.
    op.drop_constraint("cat_binding_mode_allowed", "measurement_tasks", type_="check")
    op.create_check_constraint(
        "cat_binding_mode_allowed",
        "measurement_tasks",
        "cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION', 'RESEARCH_PROFILE')",
    )

    op.create_table(
        "school_research_profile_versions",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("profile_ref", _ascii_id(128), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("instrument_id", _ascii_id(128), nullable=False),
        sa.Column("dimension", _ascii_id(64), nullable=False),
        sa.Column("source_population_scope", _ascii_id(64), nullable=False),
        sa.Column("profile_sha256", _ascii_id(64), nullable=False),
        sa.Column("manifest_sha256", _ascii_id(64), nullable=False),
        sa.Column("fit_sha256", _ascii_id(64), nullable=False),
        sa.Column("calibration_sha256", _ascii_id(64), nullable=False),
        sa.Column("rights_status", sa.String(16), nullable=False),
        sa.Column("execution_status", sa.String(32), nullable=False),
        sa.Column("purpose", _ascii_id(32), server_default=_PURPOSE, nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("human_curated", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "psychological_interpretation_allowed",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "publication_status",
            _ascii_id(64),
            server_default=_PUBLICATION_STATUS,
            nullable=False,
        ),
        sa.Column("payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=False),
        sa.Column("key_version", _ascii_id(64), nullable=False),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("status_changed_by_membership_role_id", _id(), nullable=True),
        sa.Column("simulation_enabled_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("rights_revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("disabled_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns("school_research_profile_versions"),
        sa.UniqueConstraint(
            "school_id",
            "profile_ref",
            "version_number",
            name="school_research_profile_version_unique",
        ),
        sa.UniqueConstraint(
            "id",
            "school_id",
            "profile_ref",
            "version_number",
            "profile_sha256",
            name="school_research_profile_exact_scope_unique",
        ),
        sa.CheckConstraint("version_number >= 1", name="version_positive"),
        sa.CheckConstraint(
            "rights_status IN ('PENDING', 'VERIFIED', 'REVOKED')",
            name="rights_status_allowed",
        ),
        sa.CheckConstraint(
            "execution_status IN ('CANDIDATE_RESEARCH_ONLY', 'SIMULATION_ENABLED', 'DISABLED')",
            name="execution_status_allowed",
        ),
        sa.CheckConstraint(
            "execution_status <> 'SIMULATION_ENABLED' OR rights_status = 'VERIFIED'",
            name="sim_rights_verified",
        ),
        sa.CheckConstraint(
            "rights_status <> 'REVOKED' OR execution_status = 'DISABLED'",
            name="revoked_disables",
        ),
        sa.CheckConstraint("research_only = 1", name="research_only_locked"),
        sa.CheckConstraint("human_curated = 0", name="human_curated_false"),
        sa.CheckConstraint(
            "psychological_interpretation_allowed = 0",
            name="interpretation_forbidden",
        ),
        sa.CheckConstraint("purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"),
        sa.CheckConstraint(
            "publication_status = 'not_approved_for_publication_or_operational_use'",
            name="publication_unapproved",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_research_profile_versions_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_profiles_creator_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["status_changed_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_profiles_status_actor_school",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_school_research_profiles_school_status",
            "school_id",
            "execution_status",
            "rights_status",
        ),
        **_table_options(),
    )

    op.create_table(
        "school_research_task_bindings",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("profile_version_id", _id(), nullable=False),
        sa.Column("profile_ref", _ascii_id(128), nullable=False),
        sa.Column("profile_version_number", sa.Integer(), nullable=False),
        sa.Column("profile_sha256", _ascii_id(64), nullable=False),
        sa.Column("response_origin", _ascii_id(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("purpose", _ascii_id(32), server_default=_PURPOSE, nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("config_version", _ascii_id(64), nullable=False),
        sa.Column("config_sha256", _ascii_id(64), nullable=False),
        sa.Column("config_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=False),
        sa.Column("key_version", _ascii_id(64), nullable=False),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("revoked_by_membership_role_id", _id(), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns("school_research_task_bindings"),
        sa.UniqueConstraint("task_id", name="school_research_task_binding_task_unique"),
        sa.UniqueConstraint(
            "id",
            "school_id",
            "task_id",
            "class_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "response_origin",
            name="school_research_binding_exact_scope_unique",
        ),
        sa.CheckConstraint(
            "response_origin IN ('PUBLIC_OBSERVED', 'MODEL_GENERATED')",
            name="response_origin_allowed",
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'",
            name="revocation_matches_status",
        ),
        sa.CheckConstraint("research_only = 1", name="research_only_locked"),
        sa.CheckConstraint("purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_research_bindings_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_research_bindings_task_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "profile_version_id",
                "school_id",
                "profile_ref",
                "profile_version_number",
                "profile_sha256",
            ],
            [
                "school_research_profile_versions.id",
                "school_research_profile_versions.school_id",
                "school_research_profile_versions.profile_ref",
                "school_research_profile_versions.version_number",
                "school_research_profile_versions.profile_sha256",
            ],
            name="fk_school_research_bindings_profile_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_bindings_creator_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_bindings_revoker_school",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_school_research_bindings_school_task", "school_id", "task_id"),
        **_table_options(),
    )

    op.create_table(
        "school_research_sessions",
        sa.Column("session_ref", _ascii_id(128), nullable=False),
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
        sa.Column("config_version", _ascii_id(64), nullable=False),
        sa.Column("config_sha256", _ascii_id(64), nullable=False),
        sa.Column("purpose", _ascii_id(32), server_default=_PURPOSE, nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(16), server_default="IN_PROGRESS", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("items_answered", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stop_reason", _ascii_id(64), nullable=True),
        sa.Column("snapshot_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("snapshot_sha256", _ascii_id(64), nullable=False),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=False),
        sa.Column("key_version", _ascii_id(64), nullable=False),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("trace_id", _ascii_id(128), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns("school_research_sessions"),
        sa.UniqueConstraint("session_ref", name="school_research_session_ref_unique"),
        sa.UniqueConstraint("task_enrollment_id", name="school_research_session_enrollment_unique"),
        sa.UniqueConstraint(
            "id",
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
            name="school_research_session_exact_scope_unique",
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'COMPLETED', 'ABANDONED', 'FAILED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("state_version >= 1", name="state_version_positive"),
        sa.CheckConstraint("items_answered >= 0", name="items_answered_nonnegative"),
        sa.CheckConstraint("research_only = 1", name="research_only_locked"),
        sa.CheckConstraint("purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"),
        sa.CheckConstraint(
            "response_origin IN ('PUBLIC_OBSERVED', 'MODEL_GENERATED')",
            name="response_origin_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'IN_PROGRESS' AND completed_at IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL) OR "
            "(status IN ('ABANDONED', 'FAILED') AND completed_at IS NULL)",
            name="status_timestamps_match",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_research_sessions_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_research_sessions_task_scope",
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
            name="fk_school_research_sessions_enrollment_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "task_binding_id",
                "school_id",
                "task_id",
                "class_id",
                "profile_version_id",
                "profile_ref",
                "profile_version_number",
                "profile_sha256",
                "response_origin",
            ],
            [
                "school_research_task_bindings.id",
                "school_research_task_bindings.school_id",
                "school_research_task_bindings.task_id",
                "school_research_task_bindings.class_id",
                "school_research_task_bindings.profile_version_id",
                "school_research_task_bindings.profile_ref",
                "school_research_task_bindings.profile_version_number",
                "school_research_task_bindings.profile_sha256",
                "school_research_task_bindings.response_origin",
            ],
            name="fk_school_research_sessions_binding_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_school_research_sessions_subject_scope",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_school_research_sessions_school_task_status",
            "school_id",
            "task_id",
            "status",
        ),
        sa.Index(
            "ix_school_research_sessions_school_subject_status",
            "school_id",
            "subject_id",
            "status",
        ),
        **_table_options(),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _BUSINESS_TABLES:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if count:
            raise RuntimeError(
                "cannot downgrade research CAT persistence while business rows exist"
            )

    research_task_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM measurement_tasks WHERE cat_binding_mode = 'RESEARCH_PROFILE'"
        )
    ).scalar_one()
    if research_task_count:
        raise RuntimeError("cannot downgrade research CAT persistence while research tasks exist")

    for table_name, index_names in (
        (
            "school_research_sessions",
            (
                "ix_school_research_sessions_school_subject_status",
                "ix_school_research_sessions_school_task_status",
            ),
        ),
        ("school_research_task_bindings", ("ix_school_research_bindings_school_task",)),
        ("school_research_profile_versions", ("ix_school_research_profiles_school_status",)),
    ):
        for index_name in index_names:
            op.drop_index(index_name, table_name=table_name)
        op.drop_table(table_name)

    op.drop_constraint("cat_binding_mode_allowed", "measurement_tasks", type_="check")
    op.create_check_constraint(
        "cat_binding_mode_allowed",
        "measurement_tasks",
        "cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION')",
    )
