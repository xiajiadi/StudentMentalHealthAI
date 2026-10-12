"""Add immutable school-scoped CAT bank and plan versions.

Revision ID: 20261012_0008
Revises: 20261012_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261012_0008"
down_revision: str | None = "20261012_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_BUSINESS_TABLES = (
    "school_cat_plan_versions",
    "school_cat_plans",
    "school_cat_item_bank_versions",
    "school_cat_item_banks",
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
    op.create_table(
        "school_cat_item_banks",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("creator_membership_role_id", _id(), nullable=False),
        *_identity_columns("school_cat_item_banks"),
        sa.UniqueConstraint("id", "school_id", name="school_cat_item_bank_id_school_unique"),
        sa.CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="status_allowed"),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_item_banks_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_item_banks_creator_role_school", ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_cat_item_banks_school_status",
        "school_cat_item_banks",
        ["school_id", "status"],
    )

    op.create_table(
        "school_cat_item_bank_versions",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("bank_id", _id(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("creator_membership_role_id", _id(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("dimension_count", sa.Integer(), nullable=False),
        sa.Column("payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=False),
        sa.Column("key_version", _ascii_id(64), nullable=False),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=False),
        *_identity_columns("school_cat_item_bank_versions"),
        sa.UniqueConstraint(
            "id", "school_id", name="school_cat_item_bank_version_id_school_unique"
        ),
        sa.UniqueConstraint(
            "bank_id", "version_number", name="school_cat_item_bank_version_number_unique"
        ),
        sa.CheckConstraint("version_number >= 1", name="version_number_positive"),
        sa.CheckConstraint("item_count BETWEEN 1 AND 100", name="item_count_allowed"),
        sa.CheckConstraint("dimension_count = 1", name="dimension_count_allowed"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_item_bank_versions_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["bank_id", "school_id"],
            ["school_cat_item_banks.id", "school_cat_item_banks.school_id"],
            name="fk_school_cat_item_bank_versions_bank_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_item_bank_versions_creator_role_school", ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_cat_item_bank_versions_school_bank",
        "school_cat_item_bank_versions",
        ["school_id", "bank_id"],
    )

    op.create_table(
        "school_cat_plans",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("creator_membership_role_id", _id(), nullable=False),
        *_identity_columns("school_cat_plans"),
        sa.UniqueConstraint("id", "school_id", name="school_cat_plan_id_school_unique"),
        sa.CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="status_allowed"),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_plans_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_plans_creator_role_school", ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_cat_plans_school_status", "school_cat_plans", ["school_id", "status"]
    )

    op.create_table(
        "school_cat_plan_versions",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("plan_id", _id(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("bank_version_id", _id(), nullable=False),
        sa.Column("creator_membership_role_id", _id(), nullable=False),
        sa.Column("payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=False),
        sa.Column("key_version", _ascii_id(64), nullable=False),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=False),
        *_identity_columns("school_cat_plan_versions"),
        sa.UniqueConstraint(
            "id", "school_id", name="school_cat_plan_version_id_school_unique"
        ),
        sa.UniqueConstraint(
            "plan_id", "version_number", name="school_cat_plan_version_number_unique"
        ),
        sa.CheckConstraint("version_number >= 1", name="version_number_positive"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_plan_versions_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "school_id"],
            ["school_cat_plans.id", "school_cat_plans.school_id"],
            name="fk_school_cat_plan_versions_plan_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["bank_version_id", "school_id"],
            ["school_cat_item_bank_versions.id", "school_cat_item_bank_versions.school_id"],
            name="fk_school_cat_plan_versions_bank_version_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_plan_versions_creator_role_school", ondelete="RESTRICT",
        ),
        **_table_options(),
    )
    op.create_index(
        "ix_school_cat_plan_versions_school_plan",
        "school_cat_plan_versions",
        ["school_id", "plan_id"],
    )
    op.create_index(
        "ix_school_cat_plan_versions_bank_version",
        "school_cat_plan_versions",
        ["bank_version_id", "school_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _BUSINESS_TABLES:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if count:
            raise RuntimeError("cannot downgrade school CAT assets while business rows exist")

    op.drop_index("ix_school_cat_plan_versions_bank_version", table_name="school_cat_plan_versions")
    op.drop_index("ix_school_cat_plan_versions_school_plan", table_name="school_cat_plan_versions")
    op.drop_table("school_cat_plan_versions")
    op.drop_index("ix_school_cat_plans_school_status", table_name="school_cat_plans")
    op.drop_table("school_cat_plans")
    op.drop_index(
        "ix_school_cat_item_bank_versions_school_bank",
        table_name="school_cat_item_bank_versions",
    )
    op.drop_table("school_cat_item_bank_versions")
    op.drop_index("ix_school_cat_item_banks_school_status", table_name="school_cat_item_banks")
    op.drop_table("school_cat_item_banks")
