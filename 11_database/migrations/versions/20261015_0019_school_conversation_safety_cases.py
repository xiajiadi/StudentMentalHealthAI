"""Persist school-scoped safety cases for independent conversations.

Revision ID: 20261015_0019
Revises: 20261014_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261015_0019"
down_revision: str | None = "20261014_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def upgrade() -> None:
    op.create_unique_constraint(
        "support_session_id_subject_unique", "support_sessions", ["id", "subject_id"]
    )
    op.create_unique_constraint(
        "support_run_id_session_unique", "support_runs", ["id", "support_session_id"]
    )
    op.create_unique_constraint(
        "safety_decision_id_run_unique", "safety_decisions", ["id", "support_run_id"]
    )
    op.create_table(
        "school_conversation_safety_cases",
        sa.Column("case_ref", _ascii(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("subject_id", _id(), nullable=False),
        sa.Column("support_session_id", _id(), nullable=False),
        sa.Column("support_run_id", _id(), nullable=False),
        sa.Column("safety_decision_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=True),
        sa.Column("class_student_id", _id(), nullable=True),
        sa.Column("action", _ascii(32), nullable=False),
        sa.Column("reason_codes", mysql.JSON(), nullable=False),
        sa.Column("safety_review_reference", _ascii(128), nullable=True),
        sa.Column("status", _ascii(24), server_default="UNASSIGNED_PENDING", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("decision_code", _ascii(40), nullable=True),
        sa.Column("assigned_membership_role_id", _id(), nullable=True),
        sa.Column("review_note_ciphertext", mysql.MEDIUMBLOB(), nullable=True),
        sa.Column("review_note_cipher_format_version", _ascii(32), nullable=True),
        sa.Column("review_note_key_version", _ascii(64), nullable=True),
        sa.Column("review_note_payload_schema_version", _ascii(64), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("assigned_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("closed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_conversation_safety_cases"),
        sa.UniqueConstraint("public_id", name="uq_school_conversation_safety_cases_public_id"),
        sa.UniqueConstraint("case_ref", name="school_conversation_safety_case_ref_unique"),
        sa.UniqueConstraint(
            "safety_decision_id", name="school_conversation_safety_decision_unique"
        ),
        sa.UniqueConstraint("id", "school_id", name="conversation_safety_case_id_school_unique"),
        sa.CheckConstraint(
            "action IN ('REVIEW_REQUIRED', 'CRISIS_ROUTE')",
            name="ck_school_conversation_safety_cases_action_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('UNASSIGNED_PENDING', 'ASSIGNED', 'IN_REVIEW', 'REVIEWED', "
            "'ESCALATION_NEEDED', 'CLOSED', 'REVOKED')",
            name="ck_school_conversation_safety_cases_status_allowed",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_school_conversation_safety_cases_state_version_positive",
        ),
        sa.CheckConstraint(
            "(class_id IS NULL AND class_student_id IS NULL) OR "
            "(class_id IS NOT NULL AND class_student_id IS NOT NULL)",
            name="ck_school_conversation_safety_cases_class_binding_shape",
        ),
        sa.CheckConstraint(
            "(status = 'UNASSIGNED_PENDING' AND assigned_membership_role_id IS NULL) OR "
            "(status = 'REVOKED' AND "
            "((assigned_membership_role_id IS NULL AND class_id IS NULL) OR "
            "(assigned_membership_role_id IS NOT NULL AND class_id IS NOT NULL))) OR "
            "(status NOT IN ('UNASSIGNED_PENDING', 'REVOKED') "
            "AND assigned_membership_role_id IS NOT NULL "
            "AND class_id IS NOT NULL AND class_student_id IS NOT NULL)",
            name="ck_school_conversation_safety_cases_assignment_matches_state",
        ),
        sa.CheckConstraint(
            "(status IN ('REVIEWED', 'ESCALATION_NEEDED', 'CLOSED') "
            "AND decision_code IS NOT NULL "
            "AND decision_code = 'UNRESOLVED_NEEDS_CONTEXT') OR "
            "(status NOT IN ('REVIEWED', 'ESCALATION_NEEDED', 'CLOSED') AND decision_code IS NULL)",
            name="ck_school_conversation_safety_cases_decision_code_matches_state",
        ),
        sa.CheckConstraint(
            "(review_note_ciphertext IS NULL AND review_note_cipher_format_version IS NULL "
            "AND review_note_key_version IS NULL AND review_note_payload_schema_version IS NULL) "
            "OR (review_note_ciphertext IS NOT NULL AND "
            "review_note_cipher_format_version IS NOT NULL AND review_note_key_version IS NOT NULL "
            "AND review_note_payload_schema_version IS NOT NULL)",
            name="ck_school_conversation_safety_cases_note_cipher_envelope",
        ),
        sa.ForeignKeyConstraint(
            ["support_session_id", "subject_id"],
            ["support_sessions.id", "support_sessions.subject_id"],
            name="fk_conversation_safety_session_subject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["support_run_id", "support_session_id"],
            ["support_runs.id", "support_runs.support_session_id"],
            name="fk_conversation_safety_run_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["safety_decision_id", "support_run_id"],
            ["safety_decisions.id", "safety_decisions.support_run_id"],
            name="fk_conversation_safety_decision_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_conversation_safety_subject_school",
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
            name="fk_conversation_safety_roster_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_conversation_safety_assignee_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_conversation_safety_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_conversation_safety_school_status_created",
        "school_conversation_safety_cases",
        ["school_id", "status", "created_at"],
    )
    op.create_index(
        "ix_conversation_safety_assignee_status",
        "school_conversation_safety_cases",
        ["school_id", "assigned_membership_role_id", "status", "created_at"],
    )
    op.create_table(
        "school_conversation_safety_events",
        sa.Column("case_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("actor_membership_role_id", _id(), nullable=False),
        sa.Column("assigned_membership_role_id", _id(), nullable=True),
        sa.Column("class_id", _id(), nullable=True),
        sa.Column("class_student_id", _id(), nullable=True),
        sa.Column("event_type", _ascii(24), nullable=False),
        sa.Column("from_status", _ascii(24), nullable=True),
        sa.Column("to_status", _ascii(24), nullable=False),
        sa.Column("decision_code", _ascii(40), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_conversation_safety_events"),
        sa.UniqueConstraint("public_id", name="uq_school_conversation_safety_events_public_id"),
        sa.UniqueConstraint(
            "case_id", "state_version", name="school_conversation_safety_event_version_unique"
        ),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'ASSIGNED', 'REASSIGNED', 'UNASSIGNED', "
            "'NOTE_DRAFTED', 'TRANSITIONED', 'REVOKED')",
            name="ck_school_conversation_safety_events_event_type_allowed",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_school_conversation_safety_events_state_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "school_id"],
            ["school_conversation_safety_cases.id", "school_conversation_safety_cases.school_id"],
            name="fk_conversation_safety_event_case_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_conversation_safety_event_actor_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_conversation_safety_event_assignee_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_conversation_safety_events_case_created",
        "school_conversation_safety_events",
        ["case_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    case_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM `school_conversation_safety_cases`")
    ).scalar_one()
    event_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM `school_conversation_safety_events`")
    ).scalar_one()
    if type(case_count) is not int or type(event_count) is not int or case_count or event_count:
        raise RuntimeError("0019 downgrade refused because conversation safety data exists")
    op.drop_table("school_conversation_safety_events")
    op.drop_table("school_conversation_safety_cases")
    op.drop_constraint("safety_decision_id_run_unique", "safety_decisions", type_="unique")
    op.drop_constraint("support_run_id_session_unique", "support_runs", type_="unique")
    op.drop_constraint("support_session_id_subject_unique", "support_sessions", type_="unique")
