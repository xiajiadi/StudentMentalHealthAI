"""Add school directory names and account import provenance.

Revision ID: 20261012_0006
Revises: 20261011_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261012_0006"
down_revision: str | None = "20261011_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_NEW_TABLES = ("school_account_batches", "school_account_provisions")
_NAMED_TABLES = ("schools", "school_classes", "account_school_memberships")


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _public_id() -> sa.String:
    return sa.String(length=36, collation="ascii_bin")


def _ascii_id(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


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


def _create_args(table: str) -> tuple[sa.PrimaryKeyConstraint, sa.UniqueConstraint]:
    return (
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("public_id", name=f"uq_{table}_public_id"),
    )


def upgrade() -> None:
    for table_name in _NAMED_TABLES:
        op.add_column(table_name, sa.Column("display_name", sa.String(120), nullable=True))
    op.create_unique_constraint(
        "membership_account_school_unique", "account_school_memberships",
        ["id", "account_id", "school_id"],
    )
    op.create_unique_constraint(
        "role_membership_school_unique", "membership_roles", ["id", "membership_id", "school_id"]
    )

    op.create_table(
        "school_account_batches",
        sa.Column("batch_ref", _ascii_id(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        *_identity_columns(),
        sa.CheckConstraint("row_count BETWEEN 1 AND 100", name="row_count_allowed"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_school_account_batches_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_account_batches_creator_role_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_school_account_batches_class_school",
            ondelete="RESTRICT",
        ),
        *_create_args("school_account_batches"),
        sa.UniqueConstraint("batch_ref", name="school_account_batch_ref_unique"),
        sa.UniqueConstraint(
            "id", "school_id", name="school_account_batch_id_school_unique"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_school_account_batches_school_created",
        "school_account_batches",
        ["school_id", "created_at"],
    )

    op.create_table(
        "school_account_provisions",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("batch_id", _id(), nullable=False),
        sa.Column("account_id", _id(), nullable=False),
        sa.Column("membership_id", _id(), nullable=False),
        sa.Column("membership_role_id", _id(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("role_code", _ascii_id(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("activated_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint("role_code IN ('student', 'teacher')", name="role_allowed"),
        sa.CheckConstraint(
            "status IN ('PENDING_ACTIVATION', 'ACTIVE')", name="status_allowed"
        ),
        sa.CheckConstraint(
            "(status = 'PENDING_ACTIVATION' AND activated_at IS NULL) OR "
            "(status = 'ACTIVE' AND activated_at IS NOT NULL)",
            name="activation_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_school_account_provisions_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "school_id"],
            ["school_account_batches.id", "school_account_batches.school_id"],
            name="fk_school_account_provisions_batch_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "account_id", "school_id"],
            [
                "account_school_memberships.id", "account_school_memberships.account_id",
                "account_school_memberships.school_id",
            ],
            name="fk_school_account_provisions_membership_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_role_id", "membership_id", "school_id"],
            ["membership_roles.id", "membership_roles.membership_id", "membership_roles.school_id"],
            name="fk_school_account_provisions_role_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_school_account_provisions_account",
            ondelete="RESTRICT",
        ),
        *_create_args("school_account_provisions"),
        sa.UniqueConstraint("account_id", name="school_account_provision_account_unique"),
        sa.UniqueConstraint(
            "batch_id", "row_no", name="school_account_provision_batch_row_unique"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_school_account_provisions_school_status",
        "school_account_provisions",
        ["school_id", "status"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _NEW_TABLES:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if count:
            raise RuntimeError(
                "cannot downgrade school account directory while business rows exist"
            )
    for table_name in _NAMED_TABLES:
        count = connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE display_name IS NOT NULL")
        ).scalar_one()
        if count:
            raise RuntimeError(
                "cannot downgrade school account directory while display names exist"
            )

    op.drop_index(
        "ix_school_account_provisions_school_status", table_name="school_account_provisions"
    )
    op.drop_table("school_account_provisions")
    op.drop_index(
        "ix_school_account_batches_school_created", table_name="school_account_batches"
    )
    op.drop_table("school_account_batches")
    op.drop_constraint("role_membership_school_unique", "membership_roles", type_="unique")
    op.drop_constraint(
        "membership_account_school_unique", "account_school_memberships", type_="unique"
    )
    for table_name in reversed(_NAMED_TABLES):
        op.drop_column(table_name, "display_name")
