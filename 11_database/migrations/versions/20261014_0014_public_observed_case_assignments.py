"""Pin public observed corpus metadata and private task case assignments.

Revision ID: 20261014_0014
Revises: 20261014_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261014_0014"
down_revision: str | None = "20261014_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_BINDING_TABLE = "school_research_task_bindings"
_ASSIGNMENT_TABLE = "school_research_case_assignments"


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
    # Null pins remain valid for pre-existing metadata-only bindings.
    op.add_column(_BINDING_TABLE, sa.Column("corpus_sha256", _ascii_id(64), nullable=True))
    op.add_column(_BINDING_TABLE, sa.Column("case_count", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "corpus_pin_shape",
        _BINDING_TABLE,
        "(corpus_sha256 IS NULL AND case_count IS NULL) OR "
        "(corpus_sha256 IS NOT NULL AND case_count IS NOT NULL AND case_count = 800)",
    )
    op.create_unique_constraint(
        "school_research_binding_corpus_scope_unique",
        _BINDING_TABLE,
        [
            "id", "school_id", "task_id", "class_id", "profile_version_id",
            "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
            "corpus_sha256", "case_count",
        ],
    )

    op.create_table(
        _ASSIGNMENT_TABLE,
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
        sa.Column("corpus_sha256", _ascii_id(64), nullable=False),
        sa.Column("case_count", sa.Integer(), server_default="800", nullable=False),
        sa.Column("case_index", sa.Integer(), nullable=False),
        sa.Column(
            "purpose", _ascii_id(32), server_default="RESEARCH_SIMULATION", nullable=False
        ),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_ASSIGNMENT_TABLE}"),
        sa.UniqueConstraint("public_id", name=f"uq_{_ASSIGNMENT_TABLE}_public_id"),
        sa.UniqueConstraint(
            "task_enrollment_id", name="school_research_case_enrollment_unique"
        ),
        sa.UniqueConstraint(
            "task_id", "case_index", name="school_research_case_task_index_unique"
        ),
        sa.CheckConstraint(
            "response_origin = 'PUBLIC_OBSERVED'", name="response_origin_public_observed"
        ),
        sa.CheckConstraint(
            "case_index >= 0 AND case_index < 800", name="case_index_range"
        ),
        sa.CheckConstraint("case_count = 800", name="case_count_fixed"),
        sa.CheckConstraint("purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_research_case_assignments_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_research_case_assignments_task_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ],
            name="fk_school_research_case_assignments_enrollment_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"], ["subjects.id", "subjects.school_id"],
            name="fk_school_research_case_assignments_subject_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id", "school_id", "profile_ref", "profile_version_number",
             "profile_sha256"],
            [
                "school_research_profile_versions.id",
                "school_research_profile_versions.school_id",
                "school_research_profile_versions.profile_ref",
                "school_research_profile_versions.version_number",
                "school_research_profile_versions.profile_sha256",
            ],
            name="fk_school_research_case_assignments_profile_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "task_binding_id", "school_id", "task_id", "class_id", "profile_version_id",
                "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
                "corpus_sha256", "case_count",
            ],
            [
                "school_research_task_bindings.id", "school_research_task_bindings.school_id",
                "school_research_task_bindings.task_id", "school_research_task_bindings.class_id",
                "school_research_task_bindings.profile_version_id",
                "school_research_task_bindings.profile_ref",
                "school_research_task_bindings.profile_version_number",
                "school_research_task_bindings.profile_sha256",
                "school_research_task_bindings.response_origin",
                "school_research_task_bindings.corpus_sha256",
                "school_research_task_bindings.case_count",
            ],
            name="fk_school_research_case_assignments_binding_exact",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_school_research_case_assignments_scope",
            "school_id", "task_id", "task_binding_id",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade() -> None:
    connection = op.get_bind()
    assignment_count = connection.execute(
        sa.text(f"SELECT COUNT(*) FROM {_ASSIGNMENT_TABLE}")
    ).scalar_one()
    pinned_binding_count = connection.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {_BINDING_TABLE} "
            "WHERE corpus_sha256 IS NOT NULL OR case_count IS NOT NULL"
        )
    ).scalar_one()
    if assignment_count or pinned_binding_count:
        raise RuntimeError(
            "cannot downgrade public case assignments while assignments or corpus pins exist"
        )

    op.drop_table(_ASSIGNMENT_TABLE)
    op.drop_constraint(
        "school_research_binding_corpus_scope_unique", _BINDING_TABLE, type_="unique"
    )
    op.drop_constraint("corpus_pin_shape", _BINDING_TABLE, type_="check")
    op.drop_column(_BINDING_TABLE, "case_count")
    op.drop_column(_BINDING_TABLE, "corpus_sha256")
