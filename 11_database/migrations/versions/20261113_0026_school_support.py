"""Add school support cases, actions, and append-only events.

Revision ID: 20261113_0026
Revises: 20261024_0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261113_0026"
down_revision: str | None = "20261024_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_BUSINESS_TABLES = (
    "school_support_events",
    "school_support_actions",
    "school_support_cases",
)


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _dt() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "school_support_cases",
        sa.Column("case_ref", _ascii(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("class_student_id", _id(), nullable=False),
        sa.Column("source_type", _ascii(16), nullable=False),
        sa.Column("category_code", _ascii(48), nullable=False),
        sa.Column("status", _ascii(16), server_default="SUBMITTED", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("owner_membership_role_id", _id(), nullable=True),
        sa.Column("source_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("source_cipher_format_version", _ascii(32), nullable=False),
        sa.Column("source_key_version", _ascii(64), nullable=False),
        sa.Column("source_payload_schema_version", _ascii(64), nullable=False),
        sa.Column("professional_plan_ciphertext", mysql.MEDIUMBLOB(), nullable=True),
        sa.Column("professional_plan_cipher_format_version", _ascii(32), nullable=True),
        sa.Column("professional_plan_key_version", _ascii(64), nullable=True),
        sa.Column("professional_plan_payload_schema_version", _ascii(64), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("triaged_at", _dt(), nullable=True),
        sa.Column("planned_at", _dt(), nullable=True),
        sa.Column("following_at", _dt(), nullable=True),
        sa.Column("review_requested_at", _dt(), nullable=True),
        sa.Column("closed_at", _dt(), nullable=True),
        sa.Column("retention_due_at", _dt(), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_support_cases"),
        sa.UniqueConstraint("public_id", name="uq_school_support_cases_public_id"),
        sa.UniqueConstraint("case_ref", name="school_support_case_ref_unique"),
        sa.UniqueConstraint("id", "school_id", name="school_support_case_id_school_unique"),
        sa.UniqueConstraint(
            "id",
            "school_id",
            "subject_id",
            "class_id",
            "class_student_id",
            name="school_support_case_scope_unique",
        ),
        sa.CheckConstraint(
            "source_type IN ('TEACHER', 'STUDENT')",
            name="ck_school_support_cases_source_type_allowed",
        ),
        sa.CheckConstraint(
            "LENGTH(category_code) BETWEEN 1 AND 48",
            name="ck_school_support_cases_category_code_length",
        ),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'TRIAGED', 'PLANNED', 'FOLLOWING', 'REVIEW', 'CLOSED')",
            name="ck_school_support_cases_status_allowed",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_school_support_cases_version_positive",
        ),
        sa.CheckConstraint(
            "(status = 'SUBMITTED' AND owner_membership_role_id IS NULL) OR "
            "(status <> 'SUBMITTED' AND owner_membership_role_id IS NOT NULL)",
            name="ck_school_support_cases_owner_matches_status",
        ),
        sa.CheckConstraint(
            "source_ciphertext IS NOT NULL AND source_cipher_format_version IS NOT NULL "
            "AND source_key_version IS NOT NULL AND source_payload_schema_version IS NOT NULL",
            name="ck_school_support_cases_source_cipher_envelope",
        ),
        sa.CheckConstraint(
            "(status IN ('SUBMITTED', 'TRIAGED') "
            "AND professional_plan_ciphertext IS NULL "
            "AND professional_plan_cipher_format_version IS NULL "
            "AND professional_plan_key_version IS NULL "
            "AND professional_plan_payload_schema_version IS NULL) OR "
            "(status IN ('PLANNED', 'FOLLOWING', 'REVIEW', 'CLOSED') "
            "AND professional_plan_ciphertext IS NOT NULL "
            "AND professional_plan_cipher_format_version IS NOT NULL "
            "AND professional_plan_key_version IS NOT NULL "
            "AND professional_plan_payload_schema_version IS NOT NULL)",
            name="ck_school_support_cases_plan_cipher_matches_status",
        ),
        sa.CheckConstraint(
            "(status = 'SUBMITTED' AND triaged_at IS NULL AND planned_at IS NULL "
            "AND following_at IS NULL AND review_requested_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'TRIAGED' AND triaged_at IS NOT NULL AND planned_at IS NULL "
            "AND following_at IS NULL AND review_requested_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'PLANNED' AND triaged_at IS NOT NULL AND planned_at IS NOT NULL "
            "AND following_at IS NULL AND review_requested_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'FOLLOWING' AND triaged_at IS NOT NULL AND planned_at IS NOT NULL "
            "AND following_at IS NOT NULL AND review_requested_at IS NULL "
            "AND closed_at IS NULL) OR "
            "(status = 'REVIEW' AND triaged_at IS NOT NULL AND planned_at IS NOT NULL "
            "AND following_at IS NOT NULL AND review_requested_at IS NOT NULL "
            "AND closed_at IS NULL) OR "
            "(status = 'CLOSED' AND triaged_at IS NOT NULL AND planned_at IS NOT NULL "
            "AND following_at IS NOT NULL AND review_requested_at IS NOT NULL "
            "AND closed_at IS NOT NULL)",
            name="ck_school_support_cases_state_timestamps_match",
        ),
        sa.ForeignKeyConstraint(
            ["class_student_id", "subject_id", "class_id", "school_id"],
            [
                "school_class_students.id",
                "school_class_students.subject_id",
                "school_class_students.class_id",
                "school_class_students.school_id",
            ],
            name="fk_school_support_cases_roster_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_school_support_cases_class_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_school_support_cases_subject_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_support_cases_creator_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_support_cases_owner_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_support_cases_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_support_cases_school_status_created",
        "school_support_cases",
        ["school_id", "status", "created_at"],
    )
    op.create_index(
        "ix_school_support_cases_owner_status",
        "school_support_cases",
        ["school_id", "owner_membership_role_id", "status", "created_at"],
    )
    op.create_index(
        "ix_school_support_cases_subject_created",
        "school_support_cases",
        ["school_id", "subject_id", "created_at"],
    )
    op.create_table(
        "school_support_actions",
        sa.Column("action_ref", _ascii(128), nullable=False),
        sa.Column("case_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("class_student_id", _id(), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("assigned_teacher_membership_role_id", _id(), nullable=False),
        sa.Column("assigned_class_teacher_id", _id(), nullable=False),
        sa.Column("status", _ascii(16), server_default="PENDING", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("due_at", _dt(), nullable=False),
        sa.Column("instruction_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("instruction_cipher_format_version", _ascii(32), nullable=False),
        sa.Column("instruction_key_version", _ascii(64), nullable=False),
        sa.Column("instruction_payload_schema_version", _ascii(64), nullable=False),
        sa.Column("feedback_ciphertext", mysql.MEDIUMBLOB(), nullable=True),
        sa.Column("feedback_cipher_format_version", _ascii(32), nullable=True),
        sa.Column("feedback_key_version", _ascii(64), nullable=True),
        sa.Column("feedback_payload_schema_version", _ascii(64), nullable=True),
        sa.Column("feedback_submitted_at", _dt(), nullable=True),
        sa.Column("accepted_at", _dt(), nullable=True),
        sa.Column("returned_at", _dt(), nullable=True),
        sa.Column("cancelled_at", _dt(), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("retention_due_at", _dt(), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_support_actions"),
        sa.UniqueConstraint("public_id", name="uq_school_support_actions_public_id"),
        sa.UniqueConstraint("action_ref", name="school_support_action_ref_unique"),
        sa.UniqueConstraint(
            "id", "case_id", "school_id", name="school_support_action_case_scope_unique"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUBMITTED', 'ACCEPTED', 'RETURNED', 'CANCELLED')",
            name="ck_school_support_actions_status_allowed",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_school_support_actions_version_positive",
        ),
        sa.CheckConstraint(
            "instruction_ciphertext IS NOT NULL "
            "AND instruction_cipher_format_version IS NOT NULL "
            "AND instruction_key_version IS NOT NULL "
            "AND instruction_payload_schema_version IS NOT NULL",
            name="ck_school_support_actions_instruction_cipher_envelope",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND feedback_ciphertext IS NULL "
            "AND feedback_cipher_format_version IS NULL AND feedback_key_version IS NULL "
            "AND feedback_payload_schema_version IS NULL AND feedback_submitted_at IS NULL) OR "
            "(status IN ('SUBMITTED', 'ACCEPTED', 'RETURNED') "
            "AND feedback_ciphertext IS NOT NULL "
            "AND feedback_cipher_format_version IS NOT NULL "
            "AND feedback_key_version IS NOT NULL "
            "AND feedback_payload_schema_version IS NOT NULL "
            "AND feedback_submitted_at IS NOT NULL) OR "
            "(status = 'CANCELLED' AND "
            "((feedback_ciphertext IS NULL AND feedback_cipher_format_version IS NULL "
            "AND feedback_key_version IS NULL AND feedback_payload_schema_version IS NULL "
            "AND feedback_submitted_at IS NULL) OR "
            "(feedback_ciphertext IS NOT NULL AND feedback_cipher_format_version IS NOT NULL "
            "AND feedback_key_version IS NOT NULL "
            "AND feedback_payload_schema_version IS NOT NULL "
            "AND feedback_submitted_at IS NOT NULL)))",
            name="ck_school_support_actions_feedback_cipher_matches_status",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND accepted_at IS NULL AND returned_at IS NULL "
            "AND cancelled_at IS NULL) OR "
            "(status = 'SUBMITTED' AND accepted_at IS NULL AND returned_at IS NULL "
            "AND cancelled_at IS NULL) OR "
            "(status = 'ACCEPTED' AND accepted_at IS NOT NULL AND returned_at IS NULL "
            "AND cancelled_at IS NULL) OR "
            "(status = 'RETURNED' AND accepted_at IS NULL AND returned_at IS NOT NULL "
            "AND cancelled_at IS NULL) OR "
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL "
            "AND accepted_at IS NULL AND returned_at IS NULL)",
            name="ck_school_support_actions_state_timestamps_match",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "school_id", "subject_id", "class_id", "class_student_id"],
            [
                "school_support_cases.id",
                "school_support_cases.school_id",
                "school_support_cases.subject_id",
                "school_support_cases.class_id",
                "school_support_cases.class_student_id",
            ],
            name="fk_school_support_actions_case_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_support_actions_creator_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_class_teacher_id", "class_id", "school_id"],
            [
                "school_class_teachers.id",
                "school_class_teachers.class_id",
                "school_class_teachers.school_id",
            ],
            name="fk_school_support_actions_assigned_class_teacher_scope",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_support_actions_case_status_created",
        "school_support_actions",
        ["case_id", "status", "created_at"],
    )
    op.create_index(
        "ix_school_support_actions_teacher_status_due",
        "school_support_actions",
        ["school_id", "assigned_teacher_membership_role_id", "status", "due_at"],
    )
    op.create_table(
        "school_support_events",
        sa.Column("case_id", _id(), nullable=False),
        sa.Column("action_id", _id(), nullable=True),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("actor_membership_role_id", _id(), nullable=False),
        sa.Column("event_type", _ascii(32), nullable=False),
        sa.Column("from_status", _ascii(16), nullable=True),
        sa.Column("to_status", _ascii(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("retention_due_at", _dt(), nullable=True),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_support_events"),
        sa.UniqueConstraint("public_id", name="uq_school_support_events_public_id"),
        sa.CheckConstraint(
            "event_type IN ('CASE_SUBMITTED', 'CASE_TRIAGED', 'CASE_PLANNED', "
            "'CASE_FOLLOWING', 'CASE_REVIEW_REQUESTED', 'CASE_CLOSED', 'ACTION_CREATED', "
            "'ACTION_FEEDBACK_SUBMITTED', 'ACTION_ACCEPTED', 'ACTION_RETURNED', "
            "'ACTION_CANCELLED')",
            name="ck_school_support_events_event_type_allowed",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_school_support_events_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "school_id"],
            ["school_support_cases.id", "school_support_cases.school_id"],
            name="fk_school_support_events_case_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_id", "case_id", "school_id"],
            [
                "school_support_actions.id",
                "school_support_actions.case_id",
                "school_support_actions.school_id",
            ],
            name="fk_school_support_events_action_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_support_events_actor_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_support_events_case_created",
        "school_support_events",
        ["case_id", "created_at"],
    )
    op.create_index(
        "ix_school_support_events_action_created",
        "school_support_events",
        ["action_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in _BUSINESS_TABLES:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM `{table}`")).scalar_one()
        if type(count) is not int or count:
            raise RuntimeError("0026 downgrade refused because school support data exists")
    op.drop_table("school_support_events")
    op.drop_table("school_support_actions")
    op.drop_table("school_support_cases")
