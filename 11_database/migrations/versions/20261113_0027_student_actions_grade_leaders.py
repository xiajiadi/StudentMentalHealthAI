"""Add student support action targets and school grade leaders.

Revision ID: 20261113_0027
Revises: 20261113_0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261113_0027"
down_revision: str | None = "20261113_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_TARGET_ASSIGNMENT_CHECK = "ck_school_support_actions_target_assignment_complete"
_STUDENT_ACTION_INDEX = "ix_school_support_actions_student_status_due"
_RECIPIENT_SUBJECT_FK = "fk_school_support_actions_recipient_subject_school"
_ROLE_CHECK = "ck_membership_roles_role_allowed"
_CLASS_GRADE_INDEX = "ix_school_classes_school_grade_status"


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _dt() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _options() -> dict[str, str]:
    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }


def upgrade() -> None:
    op.alter_column(
        "school_support_actions",
        "assigned_teacher_membership_role_id",
        existing_type=_id(),
        nullable=True,
    )
    op.alter_column(
        "school_support_actions",
        "assigned_class_teacher_id",
        existing_type=_id(),
        nullable=True,
    )
    op.add_column(
        "school_support_actions",
        sa.Column("recipient_subject_id", _id(), nullable=True),
    )
    op.create_foreign_key(
        _RECIPIENT_SUBJECT_FK,
        "school_support_actions",
        "subjects",
        ["recipient_subject_id", "school_id"],
        ["id", "school_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        _TARGET_ASSIGNMENT_CHECK,
        "school_support_actions",
        "(assigned_teacher_membership_role_id IS NOT NULL "
        "AND assigned_class_teacher_id IS NOT NULL AND recipient_subject_id IS NULL) OR "
        "(assigned_teacher_membership_role_id IS NULL "
        "AND assigned_class_teacher_id IS NULL AND recipient_subject_id IS NOT NULL)",
    )
    op.create_index(
        _STUDENT_ACTION_INDEX,
        "school_support_actions",
        ["school_id", "recipient_subject_id", "status", "due_at"],
    )

    op.drop_constraint(_ROLE_CHECK, "membership_roles", type_="check")
    op.create_check_constraint(
        _ROLE_CHECK,
        "membership_roles",
        "role_code IN ('student', 'teacher', 'psychological_specialist', "
        "'admin', 'grade_lead')",
    )

    op.add_column("school_classes", sa.Column("grade_ref", _ascii(64), nullable=True))
    op.create_index(
        _CLASS_GRADE_INDEX,
        "school_classes",
        ["school_id", "grade_ref", "status"],
    )

    op.create_table(
        "school_grade_leaders",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("membership_role_id", _id(), nullable=False),
        sa.Column("grade_ref", _ascii(64), nullable=False),
        sa.Column("status", _ascii(16), server_default="ACTIVE", nullable=False),
        sa.Column("valid_from", _dt(), nullable=False),
        sa.Column("valid_until", _dt(), nullable=True),
        sa.Column("revoked_at", _dt(), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_grade_leaders"),
        sa.UniqueConstraint("public_id", name="uq_school_grade_leaders_public_id"),
        sa.UniqueConstraint(
            "school_id",
            "membership_role_id",
            "grade_ref",
            name="school_grade_leader_scope_unique",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')",
            name="ck_school_grade_leaders_status_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="ck_school_grade_leaders_revocation_matches_status",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_school_grade_leaders_validity_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_grade_leaders_membership_role_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_grade_leaders_school",
            ondelete="RESTRICT",
        ),
        **_options(),
    )
    op.create_index(
        "ix_school_grade_leaders_school_grade_status",
        "school_grade_leaders",
        ["school_id", "grade_ref", "status"],
    )
    op.create_index(
        "ix_school_grade_leaders_role_status",
        "school_grade_leaders",
        ["school_id", "membership_role_id", "status"],
    )


def _ensure_downgrade_safe() -> None:
    connection = op.get_bind()
    student_actions = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM school_support_actions "
            "WHERE recipient_subject_id IS NOT NULL "
            "OR assigned_teacher_membership_role_id IS NULL "
            "OR assigned_class_teacher_id IS NULL"
        )
    ).scalar_one()
    grade_leaders = connection.execute(
        sa.text("SELECT COUNT(*) FROM school_grade_leaders")
    ).scalar_one()
    class_grades = connection.execute(
        sa.text("SELECT COUNT(*) FROM school_classes WHERE grade_ref IS NOT NULL")
    ).scalar_one()
    grade_roles = connection.execute(
        sa.text("SELECT COUNT(*) FROM membership_roles WHERE role_code = 'grade_lead'")
    ).scalar_one()
    if student_actions or grade_leaders or class_grades or grade_roles:
        raise RuntimeError(
            "0027 downgrade refused because student actions, grade leaders, "
            "class grade references, or grade_lead roles exist"
        )


def downgrade() -> None:
    _ensure_downgrade_safe()

    op.drop_index(
        "ix_school_grade_leaders_role_status",
        table_name="school_grade_leaders",
    )
    op.drop_index(
        "ix_school_grade_leaders_school_grade_status",
        table_name="school_grade_leaders",
    )
    op.drop_table("school_grade_leaders")

    op.drop_index(_CLASS_GRADE_INDEX, table_name="school_classes")
    op.drop_column("school_classes", "grade_ref")

    op.drop_constraint(_ROLE_CHECK, "membership_roles", type_="check")
    op.create_check_constraint(
        _ROLE_CHECK,
        "membership_roles",
        "role_code IN ('student', 'teacher', 'psychological_specialist', 'admin')",
    )

    op.drop_index(_STUDENT_ACTION_INDEX, table_name="school_support_actions")
    op.drop_constraint(_TARGET_ASSIGNMENT_CHECK, "school_support_actions", type_="check")
    op.drop_constraint(
        _RECIPIENT_SUBJECT_FK,
        "school_support_actions",
        type_="foreignkey",
    )
    op.drop_column("school_support_actions", "recipient_subject_id")
    op.alter_column(
        "school_support_actions",
        "assigned_class_teacher_id",
        existing_type=_id(),
        nullable=False,
    )
    op.alter_column(
        "school_support_actions",
        "assigned_teacher_membership_role_id",
        existing_type=_id(),
        nullable=False,
    )
