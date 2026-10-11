"""Add school classes, typed class links and task enrollment snapshots.

Revision ID: 20261011_0005
Revises: 20261011_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261011_0005"
down_revision: str | None = "20261011_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BUSINESS_TABLES = (
    "school_classes",
    "school_class_students",
    "school_class_teachers",
    "measurement_tasks",
    "task_enrollments",
)


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
    op.create_table(
        "school_classes",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("class_ref", _ascii_id(128), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')", name="status_allowed"
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_school_classes_school", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_classes_creator_role_school",
            ondelete="RESTRICT",
        ),
        *(_create_args("school_classes")),
        sa.UniqueConstraint("school_id", "class_ref", name="school_class_ref_unique"),
        sa.UniqueConstraint("id", "school_id", name="school_class_id_school_unique"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_school_classes_school_status", "school_classes", ["school_id", "status"]
    )

    op.create_table(
        "school_class_students",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("valid_from", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("valid_until", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'REVOKED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="validity_ordered",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'",
            name="revocation_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_class_students_class_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_class_students_subject_school",
            ondelete="RESTRICT",
        ),
        *(_create_args("school_class_students")),
        sa.UniqueConstraint("class_id", "subject_id", name="school_class_student_unique"),
        sa.UniqueConstraint(
            "id",
            "subject_id",
            "class_id",
            "school_id",
            name="class_student_subject_scope_unique",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_class_students_school_class_status",
        "school_class_students",
        ["school_id", "class_id", "status"],
    )
    op.create_index(
        "ix_class_students_subject_status", "school_class_students", ["subject_id", "status"]
    )

    op.create_table(
        "school_class_teachers",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("membership_role_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("valid_from", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("valid_until", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'REVOKED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="validity_ordered",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'",
            name="revocation_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_class_teachers_class_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_class_teachers_role_school",
            ondelete="RESTRICT",
        ),
        *(_create_args("school_class_teachers")),
        sa.UniqueConstraint(
            "class_id", "membership_role_id", name="school_class_teacher_unique"
        ),
        sa.UniqueConstraint("id", "class_id", "school_id", name="class_teacher_scope_unique"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_class_teachers_school_class_status",
        "school_class_teachers",
        ["school_id", "class_id", "status"],
    )
    op.create_index(
        "ix_class_teachers_role_status",
        "school_class_teachers",
        ["membership_role_id", "status"],
    )

    op.create_table(
        "measurement_tasks",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("task_ref", _ascii_id(128), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("instrument_id", _ascii_id(128), nullable=False),
        sa.Column("instrument_version", _ascii_id(64), nullable=False),
        sa.Column("item_bank_version", _ascii_id(64), nullable=True),
        sa.Column("config_version", _ascii_id(64), nullable=True),
        sa.Column("opens_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PUBLISHED"),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('PUBLISHED', 'CLOSED', 'CANCELLED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "due_at IS NULL OR due_at >= opens_at",
            name="task_window_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_measurement_tasks_class_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_measurement_tasks_creator_role_school",
            ondelete="RESTRICT",
        ),
        *(_create_args("measurement_tasks")),
        sa.UniqueConstraint("task_ref", name="measurement_task_ref_unique"),
        sa.UniqueConstraint(
            "id", "school_id", "class_id", name="measurement_task_scope_unique"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_measurement_tasks_school_class_status",
        "measurement_tasks",
        ["school_id", "class_id", "status"],
    )
    op.create_index(
        "ix_measurement_tasks_open_due",
        "measurement_tasks",
        ["status", "opens_at", "due_at"],
    )

    op.create_table(
        "task_enrollments",
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("task_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("class_student_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')", name="status_allowed"
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'",
            name="revocation_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_task_enrollments_task_scope",
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
            name="fk_task_enrollments_roster_scope",
            ondelete="RESTRICT",
        ),
        *(_create_args("task_enrollments")),
        sa.UniqueConstraint(
            "task_id", "class_student_id", name="task_student_enrollment_unique"
        ),
        sa.UniqueConstraint("id", "subject_id", name="task_enrollment_subject_unique"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_task_enrollments_school_task_status",
        "task_enrollments",
        ["school_id", "task_id", "status"],
    )
    op.create_index(
        "ix_task_enrollments_student_status",
        "task_enrollments",
        ["class_student_id", "status"],
    )

    op.add_column(
        "assessment_sessions",
        sa.Column("task_enrollment_id", _id(), nullable=True),
    )
    op.create_unique_constraint(
        "assessment_task_enrollment_unique", "assessment_sessions", ["task_enrollment_id"]
    )
    op.create_unique_constraint(
        "assessment_session_subject_unique", "assessment_sessions", ["id", "subject_id"]
    )
    op.create_foreign_key(
        "fk_assessment_sessions_task_enrollment_subject",
        "assessment_sessions",
        "task_enrollments",
        ["task_enrollment_id", "subject_id"],
        ["id", "subject_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    checked_tables = (*_BUSINESS_TABLES, "assessment_sessions")
    for table_name in checked_tables:
        predicate = (
            " WHERE task_enrollment_id IS NOT NULL"
            if table_name == "assessment_sessions"
            else ""
        )
        count = connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name}{predicate}")
        ).scalar_one()
        if count:
            raise RuntimeError(
                "cannot downgrade school task operations while business rows exist"
            )

    op.drop_constraint(
        "fk_assessment_sessions_task_enrollment_subject",
        "assessment_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "assessment_session_subject_unique", "assessment_sessions", type_="unique"
    )
    op.drop_constraint(
        "assessment_task_enrollment_unique", "assessment_sessions", type_="unique"
    )
    op.drop_column("assessment_sessions", "task_enrollment_id")

    op.drop_index("ix_task_enrollments_student_status", table_name="task_enrollments")
    op.drop_index("ix_task_enrollments_school_task_status", table_name="task_enrollments")
    op.drop_table("task_enrollments")
    op.drop_index("ix_measurement_tasks_open_due", table_name="measurement_tasks")
    op.drop_index("ix_measurement_tasks_school_class_status", table_name="measurement_tasks")
    op.drop_table("measurement_tasks")
    op.drop_index("ix_class_teachers_role_status", table_name="school_class_teachers")
    op.drop_index("ix_class_teachers_school_class_status", table_name="school_class_teachers")
    op.drop_table("school_class_teachers")
    op.drop_index("ix_class_students_subject_status", table_name="school_class_students")
    op.drop_index("ix_class_students_school_class_status", table_name="school_class_students")
    op.drop_table("school_class_students")
    op.drop_index("ix_school_classes_school_status", table_name="school_classes")
    op.drop_table("school_classes")
