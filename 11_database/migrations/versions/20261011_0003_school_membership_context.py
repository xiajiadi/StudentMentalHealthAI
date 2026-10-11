"""Add school-scoped memberships, subject tenancy, and session context.

Revision ID: 20261011_0003
Revises: 20260906_0002

Existing subjects, access grants, and sessions remain NULL-scoped. This
migration deliberately does not infer or backfill a school for legacy data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261011_0003"
down_revision: str | None = "20260906_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _public_id() -> sa.String:
    return sa.String(length=36, collation="ascii_bin")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    )


def _identity_columns() -> tuple[sa.Column, sa.Column, sa.Column, sa.Column]:
    return (
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _public_id(), nullable=False),
        *_timestamps(),
    )


def upgrade() -> None:
    op.create_table(
        "schools",
        sa.Column("school_ref", sa.String(128, collation="ascii_bin"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("data_origin", sa.String(24), nullable=False),
        sa.Column("provenance_ref", sa.String(48, collation="ascii_bin"), nullable=False),
        *_identity_columns(),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_schools_status_allowed"),
        sa.CheckConstraint(
            "data_origin IN ('SYNTHETIC', 'PRODUCTION_PENDING')",
            name="ck_schools_data_origin_allowed",
        ),
        sa.CheckConstraint(
            "provenance_ref = 'SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1'",
            name="ck_schools_provenance_ref_token",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_schools"),
        sa.UniqueConstraint("public_id", name="uq_schools_public_id"),
        sa.UniqueConstraint("school_ref", name="uq_schools_school_ref"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )

    op.create_table(
        "account_school_memberships",
        sa.Column("account_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("valid_from", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("valid_until", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'REVOKED')",
            name="ck_account_school_memberships_status_allowed",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_account_school_memberships_validity_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_memberships_account", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_memberships_school", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_school_memberships"),
        sa.UniqueConstraint("public_id", name="uq_account_school_memberships_public_id"),
        sa.UniqueConstraint(
            "account_id", "school_id", name="account_school_unique"
        ),
        sa.UniqueConstraint(
            "id", "school_id", name="membership_id_school_unique"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_memberships_account_status", "account_school_memberships", ["account_id", "status"]
    )
    op.create_index(
        "ix_memberships_school_status", "account_school_memberships", ["school_id", "status"]
    )

    op.create_table(
        "membership_roles",
        sa.Column("membership_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("role_code", sa.String(64, collation="ascii_bin"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("valid_from", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("valid_until", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint(
            "role_code IN ('student', 'teacher', 'psychological_specialist', 'admin')",
            name="ck_membership_roles_role_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'REVOKED')",
            name="ck_membership_roles_status_allowed",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_membership_roles_validity_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["account_school_memberships.id"],
            name="fk_membership_roles_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_membership_roles_school", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "school_id"],
            ["account_school_memberships.id", "account_school_memberships.school_id"],
            name="fk_membership_roles_membership_school",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_membership_roles"),
        sa.UniqueConstraint("public_id", name="uq_membership_roles_public_id"),
        sa.UniqueConstraint("membership_id", "role_code", name="membership_role_unique"),
        sa.UniqueConstraint("id", "school_id", name="membership_role_id_school_unique"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_membership_roles_membership_status", "membership_roles", ["membership_id", "status"]
    )

    # Nullable additions intentionally preserve every legacy row as unscoped.
    op.add_column("subjects", sa.Column("school_id", _id(), nullable=True))
    op.create_foreign_key(
        "fk_subjects_school_id_schools",
        "subjects",
        "schools",
        ["school_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("subject_id_school_unique", "subjects", ["id", "school_id"])

    op.add_column("subject_access_grants", sa.Column("school_id", _id(), nullable=True))
    op.create_foreign_key(
        "fk_subject_access_grants_school_id_schools",
        "subject_access_grants",
        "schools",
        ["school_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_subject_grants_subject_school",
        "subject_access_grants",
        "subjects",
        ["subject_id", "school_id"],
        ["id", "school_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_subject_grants_membership_school",
        "subject_access_grants",
        "account_school_memberships",
        ["principal_account_id", "school_id"],
        ["account_id", "school_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_subject_grants_school_subject_status",
        "subject_access_grants",
        ["school_id", "subject_id", "status"],
    )

    op.add_column("auth_sessions", sa.Column("active_school_id", _id(), nullable=True))
    op.add_column("auth_sessions", sa.Column("active_membership_role_id", _id(), nullable=True))
    op.create_foreign_key(
        "fk_auth_sessions_active_role_school",
        "auth_sessions",
        "membership_roles",
        ["active_membership_role_id", "active_school_id"],
        ["id", "school_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_auth_sessions_active_context_complete",
        "auth_sessions",
        "(active_membership_role_id IS NULL AND active_school_id IS NULL) OR "
        "(active_membership_role_id IS NOT NULL AND active_school_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_auth_sessions_active_context_complete", "auth_sessions", type_="check")
    op.drop_constraint(
        "fk_auth_sessions_active_role_school", "auth_sessions", type_="foreignkey"
    )
    op.drop_column("auth_sessions", "active_membership_role_id")
    op.drop_column("auth_sessions", "active_school_id")

    op.drop_index("ix_subject_grants_school_subject_status", table_name="subject_access_grants")
    op.drop_constraint(
        "fk_subject_grants_membership_school", "subject_access_grants", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_subject_grants_subject_school", "subject_access_grants", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_subject_access_grants_school_id_schools", "subject_access_grants", type_="foreignkey"
    )
    op.drop_column("subject_access_grants", "school_id")

    op.drop_constraint("subject_id_school_unique", "subjects", type_="unique")
    op.drop_constraint("fk_subjects_school_id_schools", "subjects", type_="foreignkey")
    op.drop_column("subjects", "school_id")

    op.drop_index("ix_membership_roles_membership_status", table_name="membership_roles")
    op.drop_table("membership_roles")
    op.drop_index("ix_memberships_school_status", table_name="account_school_memberships")
    op.drop_index("ix_memberships_account_status", table_name="account_school_memberships")
    op.drop_table("account_school_memberships")
    op.drop_table("schools")
