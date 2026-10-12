"""Persist exact synthetic CAT activation and task/session bindings.

Revision ID: 20261013_0009
Revises: 20261012_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261013_0009"
down_revision: str | None = "20261012_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_BUSINESS_TABLES = (
    "school_cat_session_bindings",
    "school_cat_task_bindings",
    "school_cat_activations",
)


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
    # A server default lets historical tasks/sessions read as the original fixed
    # fixture mode without issuing any UPDATE or interpreting legacy version text.
    op.add_column(
        "measurement_tasks",
        sa.Column("cat_binding_mode", sa.String(16), server_default="FIXTURE", nullable=False),
    )
    op.create_check_constraint(
        "cat_binding_mode_allowed",
        "measurement_tasks",
        "cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION')",
    )
    op.add_column(
        "assessment_sessions",
        sa.Column("cat_binding_mode", sa.String(16), server_default="FIXTURE", nullable=False),
    )
    op.create_check_constraint(
        "cat_binding_mode_allowed",
        "assessment_sessions",
        "cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION')",
    )

    op.create_table(
        "school_cat_activations",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("plan_version_id", _id(), nullable=False),
        sa.Column("creator_membership_role_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "purpose", _ascii_id(32), server_default="SYNTHETIC_ENGINEERING", nullable=False
        ),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns("school_cat_activations"),
        sa.UniqueConstraint(
            "id", "school_id", "plan_version_id",
            name="school_cat_activation_exact_version_unique",
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
        sa.CheckConstraint(
            "purpose = 'SYNTHETIC_ENGINEERING'", name="purpose_engineering_only"
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'", name="revocation_matches_status"
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_activations_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id", "school_id"],
            ["school_cat_plan_versions.id", "school_cat_plan_versions.school_id"],
            name="fk_school_cat_activations_plan_version_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_activations_creator_role_school", ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_cat_activations_school_status",
        "school_cat_activations",
        ["school_id", "status"],
    )
    op.create_index(
        "ix_school_cat_activations_school_version_status",
        "school_cat_activations",
        ["school_id", "plan_version_id", "status"],
    )

    op.create_table(
        "school_cat_task_bindings",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("activation_id", _id(), nullable=False),
        sa.Column("plan_version_id", _id(), nullable=False),
        *_identity_columns("school_cat_task_bindings"),
        sa.UniqueConstraint("task_id", name="school_cat_task_binding_task_unique"),
        sa.UniqueConstraint(
            "id", "school_id", "task_id", "activation_id", "plan_version_id",
            name="school_cat_task_binding_exact_scope_unique",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id"],
            name="fk_school_cat_task_bindings_task_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["activation_id", "school_id", "plan_version_id"],
            [
                "school_cat_activations.id", "school_cat_activations.school_id",
                "school_cat_activations.plan_version_id",
            ],
            name="fk_school_cat_task_bindings_activation_exact_version", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id", "school_id"],
            ["school_cat_plan_versions.id", "school_cat_plan_versions.school_id"],
            name="fk_school_cat_task_bindings_plan_version_school", ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_cat_task_bindings_school_task",
        "school_cat_task_bindings",
        ["school_id", "task_id"],
    )

    op.create_table(
        "school_cat_session_bindings",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("assessment_session_id", _id(), nullable=False),
        sa.Column("task_enrollment_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("task_binding_id", _id(), nullable=False),
        sa.Column("activation_id", _id(), nullable=False),
        sa.Column("plan_version_id", _id(), nullable=False),
        *_identity_columns("school_cat_session_bindings"),
        sa.UniqueConstraint(
            "assessment_session_id", name="school_cat_session_binding_assessment_unique"
        ),
        sa.ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id", "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_cat_session_bindings_assessment_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ],
            name="fk_school_cat_session_bindings_enrollment_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_binding_id", "school_id", "task_id", "activation_id", "plan_version_id"],
            [
                "school_cat_task_bindings.id", "school_cat_task_bindings.school_id",
                "school_cat_task_bindings.task_id", "school_cat_task_bindings.activation_id",
                "school_cat_task_bindings.plan_version_id",
            ],
            name="fk_school_cat_session_bindings_task_binding_exact", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["activation_id", "school_id", "plan_version_id"],
            [
                "school_cat_activations.id", "school_cat_activations.school_id",
                "school_cat_activations.plan_version_id",
            ],
            name="fk_school_cat_session_bindings_activation_exact_version",
            ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_cat_session_bindings_school_enrollment",
        "school_cat_session_bindings",
        ["school_id", "task_enrollment_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _BUSINESS_TABLES:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if count:
            raise RuntimeError("cannot downgrade synthetic CAT bindings while business rows exist")

    for table_name in ("measurement_tasks", "assessment_sessions"):
        count = connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE cat_binding_mode = 'SAVED_VERSION'")
        ).scalar_one()
        if count:
            raise RuntimeError("cannot downgrade synthetic CAT bindings while saved sessions exist")

    op.drop_index(
        "ix_school_cat_session_bindings_school_enrollment",
        table_name="school_cat_session_bindings",
    )
    op.drop_table("school_cat_session_bindings")
    op.drop_index(
        "ix_school_cat_task_bindings_school_task", table_name="school_cat_task_bindings"
    )
    op.drop_table("school_cat_task_bindings")
    op.drop_index(
        "ix_school_cat_activations_school_version_status",
        table_name="school_cat_activations",
    )
    op.drop_index(
        "ix_school_cat_activations_school_status", table_name="school_cat_activations"
    )
    op.drop_table("school_cat_activations")
    op.drop_constraint("cat_binding_mode_allowed", "assessment_sessions", type_="check")
    op.drop_column("assessment_sessions", "cat_binding_mode")
    op.drop_constraint("cat_binding_mode_allowed", "measurement_tasks", type_="check")
    op.drop_column("measurement_tasks", "cat_binding_mode")
