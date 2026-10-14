"""Seal a school-wide public-observation cohort and exact private mappings.

Revision ID: 20261014_0015
Revises: 20261014_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261014_0015"
down_revision: str | None = "20261014_0014"
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
    # Exact composite keys make the cohort/member links enforceable by the DB.
    op.create_unique_constraint(
        "school_account_batch_id_school_class_unique",
        "school_account_batches",
        ["id", "school_id", "class_id"],
    )
    op.create_unique_constraint(
        "school_account_provision_cohort_scope_unique",
        "school_account_provisions",
        ["id", "batch_id", "account_id", "membership_id", "membership_role_id", "school_id"],
    )
    op.create_unique_constraint(
        "subject_grant_cohort_scope_unique",
        "subject_access_grants",
        ["id", "principal_account_id", "subject_id", "school_id"],
    )
    op.create_unique_constraint(
        "school_research_profile_manifest_scope_unique",
        "school_research_profile_versions",
        ["id", "school_id", "profile_ref", "version_number", "profile_sha256", "manifest_sha256"],
    )

    op.create_table(
        "school_research_cohorts",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("cohort_ref", _ascii_id(128), nullable=False),
        sa.Column("study_ref", _ascii_id(128), nullable=False),
        sa.Column("profile_version_id", _id(), nullable=False),
        sa.Column("profile_ref", _ascii_id(128), nullable=False),
        sa.Column("profile_version_number", sa.Integer(), nullable=False),
        sa.Column("profile_sha256", _ascii_id(64), nullable=False),
        sa.Column("manifest_sha256", _ascii_id(64), nullable=False),
        sa.Column("corpus_sha256", _ascii_id(64), nullable=False),
        sa.Column("assignment_sha256", _ascii_id(64), nullable=False),
        sa.Column("case_count", sa.Integer(), server_default="800", nullable=False),
        sa.Column("class_count", sa.Integer(), server_default="8", nullable=False),
        sa.Column("subject_count", sa.Integer(), server_default="800", nullable=False),
        sa.Column("status", _ascii_id(16), server_default="SEALED", nullable=False),
        sa.Column("purpose", _ascii_id(32), server_default="RESEARCH_SIMULATION", nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("human_curated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "psychological_interpretation_allowed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("sealed_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_cohorts"),
        sa.UniqueConstraint("public_id", name="uq_school_research_cohorts_public_id"),
        sa.UniqueConstraint("school_id", "cohort_ref", name="school_research_cohort_ref_unique"),
        sa.UniqueConstraint("id", "school_id", name="school_research_cohort_id_school_unique"),
        sa.UniqueConstraint(
            "id",
            "school_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "manifest_sha256",
            "corpus_sha256",
            "case_count",
            name="school_research_cohort_exact_pin_unique",
        ),
        sa.UniqueConstraint(
            "id",
            "school_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "corpus_sha256",
            "case_count",
            name="school_research_cohort_binding_exact_unique",
        ),
        sa.CheckConstraint(
            "status = 'SEALED'", name="ck_school_research_cohorts_status_sealed_only"
        ),
        sa.CheckConstraint("case_count = 800", name="ck_school_research_cohorts_case_count_fixed"),
        sa.CheckConstraint("class_count = 8", name="ck_school_research_cohorts_class_count_fixed"),
        sa.CheckConstraint(
            "subject_count = 800", name="ck_school_research_cohorts_subject_count_fixed"
        ),
        sa.CheckConstraint(
            "length(profile_sha256) = 64", name="ck_school_research_cohorts_profile_sha_shape"
        ),
        sa.CheckConstraint(
            "length(manifest_sha256) = 64", name="ck_school_research_cohorts_manifest_sha_shape"
        ),
        sa.CheckConstraint(
            "length(corpus_sha256) = 64", name="ck_school_research_cohorts_corpus_sha_shape"
        ),
        sa.CheckConstraint(
            "length(assignment_sha256) = 64",
            name="ck_school_research_cohorts_assignment_sha_shape",
        ),
        sa.CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'",
            name="ck_school_research_cohorts_purpose_research_only",
        ),
        sa.CheckConstraint(
            "research_only = 1", name="ck_school_research_cohorts_research_only_locked"
        ),
        sa.CheckConstraint(
            "human_curated = 0", name="ck_school_research_cohorts_human_curated_false"
        ),
        sa.CheckConstraint(
            "psychological_interpretation_allowed = 0",
            name="ck_school_research_cohorts_interpretation_forbidden",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_research_cohorts_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "profile_version_id",
                "school_id",
                "profile_ref",
                "profile_version_number",
                "profile_sha256",
                "manifest_sha256",
            ],
            [
                "school_research_profile_versions.id",
                "school_research_profile_versions.school_id",
                "school_research_profile_versions.profile_ref",
                "school_research_profile_versions.version_number",
                "school_research_profile_versions.profile_sha256",
                "school_research_profile_versions.manifest_sha256",
            ],
            name="fk_school_research_cohorts_profile_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_cohorts_creator_school",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_school_research_cohorts_school_study", "school_id", "study_ref"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "school_research_cohort_batches",
        sa.Column("cohort_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("batch_id", _id(), nullable=False),
        sa.Column("class_ref", _ascii_id(128), nullable=False),
        sa.Column("batch_ref", _ascii_id(128), nullable=False),
        sa.Column("row_count", sa.Integer(), server_default="100", nullable=False),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_cohort_batches"),
        sa.UniqueConstraint("public_id", name="uq_school_research_cohort_batches_public_id"),
        sa.UniqueConstraint("cohort_id", "class_id", name="school_research_cohort_class_unique"),
        sa.UniqueConstraint("cohort_id", "batch_id", name="school_research_cohort_batch_unique"),
        sa.UniqueConstraint(
            "id",
            "cohort_id",
            "school_id",
            "class_id",
            "batch_id",
            name="school_research_cohort_batch_exact_unique",
        ),
        sa.CheckConstraint(
            "row_count = 100", name="ck_school_research_cohort_batches_row_count_fixed"
        ),
        sa.ForeignKeyConstraint(
            ["cohort_id", "school_id"],
            ["school_research_cohorts.id", "school_research_cohorts.school_id"],
            name="fk_school_research_cohort_batches_cohort",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "school_id", "class_id"],
            [
                "school_account_batches.id",
                "school_account_batches.school_id",
                "school_account_batches.class_id",
            ],
            name="fk_school_research_cohort_batches_batch_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_school_research_cohort_batches_class",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_school_research_cohort_batches_cohort", "cohort_id", "class_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "school_research_cohort_assignments",
        sa.Column("cohort_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("cohort_batch_id", _id(), nullable=False),
        sa.Column("batch_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("provision_id", _id(), nullable=False),
        sa.Column("account_id", _id(), nullable=False),
        sa.Column("membership_id", _id(), nullable=False),
        sa.Column("membership_role_id", _id(), nullable=False),
        sa.Column("class_student_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("self_grant_id", _id(), nullable=False),
        sa.Column("case_index", sa.Integer(), nullable=False),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_cohort_assignments"),
        sa.UniqueConstraint("public_id", name="uq_school_research_cohort_assignments_public_id"),
        sa.UniqueConstraint("cohort_id", "case_index", name="school_research_cohort_case_unique"),
        sa.UniqueConstraint(
            "cohort_id", "subject_id", name="school_research_cohort_subject_unique"
        ),
        sa.UniqueConstraint(
            "id",
            "cohort_id",
            "school_id",
            "subject_id",
            "case_index",
            name="school_research_cohort_assignment_exact_unique",
        ),
        sa.CheckConstraint(
            "case_index >= 0 AND case_index < 800",
            name="ck_school_research_cohort_assignments_case_index_range",
        ),
        sa.ForeignKeyConstraint(
            ["cohort_batch_id", "cohort_id", "school_id", "class_id", "batch_id"],
            [
                "school_research_cohort_batches.id",
                "school_research_cohort_batches.cohort_id",
                "school_research_cohort_batches.school_id",
                "school_research_cohort_batches.class_id",
                "school_research_cohort_batches.batch_id",
            ],
            name="fk_school_research_cohort_assignments_batch_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "provision_id",
                "batch_id",
                "account_id",
                "membership_id",
                "membership_role_id",
                "school_id",
            ],
            [
                "school_account_provisions.id",
                "school_account_provisions.batch_id",
                "school_account_provisions.account_id",
                "school_account_provisions.membership_id",
                "school_account_provisions.membership_role_id",
                "school_account_provisions.school_id",
            ],
            name="fk_school_research_cohort_assignments_provision_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_student_id", "subject_id", "class_id", "school_id"],
            [
                "school_class_students.id",
                "school_class_students.subject_id",
                "school_class_students.class_id",
                "school_class_students.school_id",
            ],
            name="fk_school_research_cohort_assignments_roster_exact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["self_grant_id", "account_id", "subject_id", "school_id"],
            [
                "subject_access_grants.id",
                "subject_access_grants.principal_account_id",
                "subject_access_grants.subject_id",
                "subject_access_grants.school_id",
            ],
            name="fk_school_research_cohort_assignments_self_exact",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_school_research_cohort_assignments_subject", "school_id", "subject_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.add_column("school_research_task_bindings", sa.Column("cohort_id", _id(), nullable=True))
    op.create_unique_constraint(
        "school_research_binding_cohort_id_unique",
        "school_research_task_bindings",
        ["id", "cohort_id"],
    )
    op.create_check_constraint(
        "ck_school_research_task_bindings_cohort_requires_corpus_pin",
        "school_research_task_bindings",
        "cohort_id IS NULL OR (corpus_sha256 IS NOT NULL AND case_count = 800)",
    )
    op.create_foreign_key(
        "fk_school_research_bindings_cohort_exact",
        "school_research_task_bindings",
        "school_research_cohorts",
        [
            "cohort_id",
            "school_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "corpus_sha256",
            "case_count",
        ],
        [
            "id",
            "school_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "corpus_sha256",
            "case_count",
        ],
        ondelete="RESTRICT",
    )

    op.add_column("school_research_case_assignments", sa.Column("cohort_id", _id(), nullable=True))
    op.add_column(
        "school_research_case_assignments", sa.Column("cohort_assignment_id", _id(), nullable=True)
    )
    op.create_foreign_key(
        "fk_school_research_case_assignments_binding_cohort",
        "school_research_case_assignments",
        "school_research_task_bindings",
        ["task_binding_id", "cohort_id"],
        ["id", "cohort_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_school_research_case_assignments_cohort_assignment_pair",
        "school_research_case_assignments",
        "(cohort_id IS NULL AND cohort_assignment_id IS NULL) OR "
        "(cohort_id IS NOT NULL AND cohort_assignment_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_school_research_case_assignments_cohort_exact",
        "school_research_case_assignments",
        "school_research_cohort_assignments",
        ["cohort_assignment_id", "cohort_id", "school_id", "subject_id", "case_index"],
        ["id", "cohort_id", "school_id", "subject_id", "case_index"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    counts = [
        connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        for table in (
            "school_research_cohort_assignments",
            "school_research_cohort_batches",
            "school_research_cohorts",
        )
    ]
    linked_bindings = connection.execute(
        sa.text("SELECT COUNT(*) FROM school_research_task_bindings WHERE cohort_id IS NOT NULL")
    ).scalar_one()
    linked_assignments = connection.execute(
        sa.text("SELECT COUNT(*) FROM school_research_case_assignments WHERE cohort_id IS NOT NULL")
    ).scalar_one()
    if any(counts) or linked_bindings or linked_assignments:
        raise RuntimeError("cannot downgrade while sealed cohort records or links exist")

    op.drop_constraint(
        "fk_school_research_case_assignments_cohort_exact",
        "school_research_case_assignments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_school_research_case_assignments_cohort_assignment_pair",
        "school_research_case_assignments",
        type_="check",
    )
    op.drop_constraint(
        "fk_school_research_case_assignments_binding_cohort",
        "school_research_case_assignments",
        type_="foreignkey",
    )
    op.drop_column("school_research_case_assignments", "cohort_assignment_id")
    op.drop_column("school_research_case_assignments", "cohort_id")
    op.drop_constraint(
        "fk_school_research_bindings_cohort_exact",
        "school_research_task_bindings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "school_research_binding_cohort_id_unique",
        "school_research_task_bindings",
        type_="unique",
    )
    op.drop_constraint(
        "ck_school_research_task_bindings_cohort_requires_corpus_pin",
        "school_research_task_bindings",
        type_="check",
    )
    op.drop_column("school_research_task_bindings", "cohort_id")
    op.drop_table("school_research_cohort_assignments")
    op.drop_table("school_research_cohort_batches")
    op.drop_table("school_research_cohorts")
    op.drop_constraint(
        "school_research_profile_manifest_scope_unique",
        "school_research_profile_versions",
        type_="unique",
    )
    op.drop_constraint("subject_grant_cohort_scope_unique", "subject_access_grants", type_="unique")
    op.drop_constraint(
        "school_account_provision_cohort_scope_unique", "school_account_provisions", type_="unique"
    )
    op.drop_constraint(
        "school_account_batch_id_school_class_unique", "school_account_batches", type_="unique"
    )
