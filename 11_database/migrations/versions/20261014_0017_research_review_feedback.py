"""Add isolated research review and feedback workflow tables.

Revision ID: 20261014_0017
Revises: 20261014_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261014_0017"
down_revision: str | None = "20261014_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_RESEARCH_SCOPE = (
    "research_session_id",
    "school_id",
    "task_id",
    "class_id",
    "task_enrollment_id",
    "subject_id",
    "task_binding_id",
    "profile_version_id",
    "profile_ref",
    "profile_version_number",
    "profile_sha256",
    "response_origin",
)
_RESEARCH_SESSION_SCOPE = [
    "school_research_sessions.id",
    "school_research_sessions.school_id",
    "school_research_sessions.task_id",
    "school_research_sessions.class_id",
    "school_research_sessions.task_enrollment_id",
    "school_research_sessions.subject_id",
    "school_research_sessions.task_binding_id",
    "school_research_sessions.profile_version_id",
    "school_research_sessions.profile_ref",
    "school_research_sessions.profile_version_number",
    "school_research_sessions.profile_sha256",
    "school_research_sessions.response_origin",
]
_REVIEW_STATUSES = "'OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED'"
_FEEDBACK_STATUSES = "'DRAFT', 'PUBLISHED', 'REVOKED'"
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _ascii_id(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("research_session_id", _id(), nullable=False),
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
    ]


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii_id(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    ]


def _session_scope_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        list(_RESEARCH_SCOPE),
        list(_RESEARCH_SESSION_SCOPE),
        name="fk_school_research_review_session_exact_scope",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "school_research_review_cases",
        sa.Column("review_ref", _ascii_id(128), nullable=False),
        *_scope_columns(),
        sa.Column("specialist_membership_role_id", _id(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("purpose", _ascii_id(32), server_default="RESEARCH_SIMULATION", nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "publication_status",
            _ascii_id(64),
            server_default=_PUBLICATION_STATUS,
            nullable=False,
        ),
        sa.Column("case_note_ciphertext", mysql.MEDIUMBLOB(), nullable=True),
        sa.Column("case_note_cipher_format_version", _ascii_id(32), nullable=True),
        sa.Column("case_note_key_version", _ascii_id(64), nullable=True),
        sa.Column("case_note_payload_schema_version", _ascii_id(64), nullable=True),
        sa.Column("trace_id", _ascii_id(128), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_review_cases"),
        sa.UniqueConstraint("public_id", name="uq_school_research_review_cases_public_id"),
        sa.UniqueConstraint("review_ref", name="school_research_review_ref_unique"),
        sa.UniqueConstraint("research_session_id", name="school_research_review_session_unique"),
        sa.UniqueConstraint(
            "id",
            *_RESEARCH_SCOPE,
            name="school_research_review_exact_scope_unique",
        ),
        sa.CheckConstraint(
            f"status IN ({_REVIEW_STATUSES})",
            name="ck_school_research_review_cases_status_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="ck_school_research_review_cases_version_positive"),
        sa.CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'",
            name="ck_school_research_review_cases_purpose_research_only",
        ),
        sa.CheckConstraint(
            "research_only = 1", name="ck_school_research_review_cases_research_only_locked"
        ),
        sa.CheckConstraint(
            f"publication_status = '{_PUBLICATION_STATUS}'",
            name="ck_school_research_review_cases_publication_not_approved",
        ),
        _session_scope_fk(),
        sa.ForeignKeyConstraint(
            ["task_id", "specialist_membership_role_id"],
            [
                "school_task_specialist_assignments.task_id",
                "school_task_specialist_assignments.specialist_membership_role_id",
            ],
            name="fk_school_research_review_specialist_assignment",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_review_scope_status",
        "school_research_review_cases",
        ["school_id", "task_id", "specialist_membership_role_id", "status"],
    )
    op.create_table(
        "school_research_review_events",
        sa.Column("review_case_id", _id(), nullable=False),
        *_scope_columns(),
        sa.Column("actor_membership_role_id", _id(), nullable=False),
        sa.Column("event_type", _ascii_id(16), nullable=False),
        sa.Column("from_status", _ascii_id(16), nullable=True),
        sa.Column("to_status", _ascii_id(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii_id(128), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_review_events"),
        sa.UniqueConstraint("public_id", name="uq_school_research_review_events_public_id"),
        sa.UniqueConstraint(
            "review_case_id",
            "version",
            name="school_research_review_event_version_unique",
        ),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'TRANSITION')",
            name="ck_school_research_review_events_event_type_allowed",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_school_research_review_events_version_positive"
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_REVIEW_STATUSES})",
            name="ck_school_research_review_events_from_status_allowed",
        ),
        sa.CheckConstraint(
            f"to_status IN ({_REVIEW_STATUSES})",
            name="ck_school_research_review_events_to_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id", *_RESEARCH_SCOPE],
            [
                "school_research_review_cases.id",
                *[f"school_research_review_cases.{name}" for name in _RESEARCH_SCOPE],
            ],
            name="fk_school_research_review_events_case_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_review_events_actor_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_review_events_case_created",
        "school_research_review_events",
        ["review_case_id", "created_at"],
    )
    op.create_table(
        "school_research_feedback_records",
        sa.Column("feedback_ref", _ascii_id(128), nullable=False),
        sa.Column("review_case_id", _id(), nullable=False),
        *_scope_columns(),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "feedback_kind",
            _ascii_id(40),
            server_default="GENERAL_EDUCATIONAL_SUPPORT",
            nullable=False,
        ),
        sa.Column("purpose", _ascii_id(32), server_default="RESEARCH_SIMULATION", nullable=False),
        sa.Column("research_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "psychological_interpretation_allowed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "publication_status", _ascii_id(64), server_default=_PUBLICATION_STATUS, nullable=False
        ),
        sa.Column("payload_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("cipher_format_version", _ascii_id(32), nullable=False),
        sa.Column("key_version", _ascii_id(64), nullable=False),
        sa.Column("payload_schema_version", _ascii_id(64), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("published_by_membership_role_id", _id(), nullable=True),
        sa.Column("revoked_by_membership_role_id", _id(), nullable=True),
        sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("trace_id", _ascii_id(128), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_feedback_records"),
        sa.UniqueConstraint("public_id", name="uq_school_research_feedback_records_public_id"),
        sa.UniqueConstraint("feedback_ref", name="school_research_feedback_ref_unique"),
        sa.UniqueConstraint(
            "review_case_id",
            "content_revision",
            name="school_research_feedback_case_revision_unique",
        ),
        sa.UniqueConstraint(
            "id",
            "review_case_id",
            *_RESEARCH_SCOPE,
            "content_revision",
            name="school_research_feedback_exact_scope_unique",
        ),
        sa.CheckConstraint(
            f"status IN ({_FEEDBACK_STATUSES})",
            name="ck_school_research_feedback_records_status_allowed",
        ),
        sa.CheckConstraint(
            "content_revision >= 1",
            name="ck_school_research_feedback_records_content_revision_positive",
        ),
        sa.CheckConstraint(
            "case_version >= 1", name="ck_school_research_feedback_records_case_version_positive"
        ),
        sa.CheckConstraint(
            "state_version >= 1", name="ck_school_research_feedback_records_state_version_positive"
        ),
        sa.CheckConstraint(
            "feedback_kind = 'GENERAL_EDUCATIONAL_SUPPORT'",
            name="ck_school_research_feedback_records_feedback_kind_locked",
        ),
        sa.CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'",
            name="ck_school_research_feedback_records_purpose_research_only",
        ),
        sa.CheckConstraint(
            "research_only = 1",
            name="ck_school_research_feedback_records_research_only_locked",
        ),
        sa.CheckConstraint(
            "psychological_interpretation_allowed = 0",
            name="ck_school_research_feedback_records_interpretation_disabled",
        ),
        sa.CheckConstraint(
            f"publication_status = '{_PUBLICATION_STATUS}'",
            name="ck_school_research_feedback_records_publication_not_approved",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL AND revoked_at IS NULL "
            "AND published_by_membership_role_id IS NULL "
            "AND revoked_by_membership_role_id IS NULL) OR "
            "(status = 'PUBLISHED' AND published_at IS NOT NULL AND revoked_at IS NULL "
            "AND published_by_membership_role_id IS NOT NULL "
            "AND revoked_by_membership_role_id IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL "
            "AND revoked_by_membership_role_id IS NOT NULL AND "
            "((published_at IS NULL AND published_by_membership_role_id IS NULL) OR "
            "(published_at IS NOT NULL AND published_by_membership_role_id IS NOT NULL)))",
            name="ck_school_research_feedback_records_status_timestamps_match",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id", *_RESEARCH_SCOPE],
            [
                "school_research_review_cases.id",
                *[f"school_research_review_cases.{name}" for name in _RESEARCH_SCOPE],
            ],
            name="fk_school_research_feedback_case_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_feedback_creator_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_feedback_publisher_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_feedback_revoker_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_feedback_student_status_created",
        "school_research_feedback_records",
        ["school_id", "subject_id", "status", "created_at"],
    )
    op.create_index(
        "ix_school_research_feedback_case_revision",
        "school_research_feedback_records",
        ["school_id", "review_case_id", "content_revision"],
    )
    op.create_table(
        "school_research_feedback_events",
        sa.Column("feedback_id", _id(), nullable=False),
        sa.Column("review_case_id", _id(), nullable=False),
        *_scope_columns(),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("actor_membership_role_id", _id(), nullable=False),
        sa.Column("event_type", _ascii_id(16), nullable=False),
        sa.Column("from_status", _ascii_id(16), nullable=True),
        sa.Column("to_status", _ascii_id(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("trace_id", _ascii_id(128), nullable=True),
        sa.Column("retention_due_at", mysql.DATETIME(fsp=6), nullable=True),
        *_identity_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_school_research_feedback_events"),
        sa.UniqueConstraint("public_id", name="uq_school_research_feedback_events_public_id"),
        sa.UniqueConstraint(
            "feedback_id",
            "state_version",
            name="school_research_feedback_event_state_version_unique",
        ),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'PUBLISHED', 'REVOKED')",
            name="ck_school_research_feedback_events_event_type_allowed",
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_FEEDBACK_STATUSES})",
            name="ck_school_research_feedback_events_from_status_allowed",
        ),
        sa.CheckConstraint(
            f"to_status IN ({_FEEDBACK_STATUSES})",
            name="ck_school_research_feedback_events_to_status_allowed",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_school_research_feedback_events_state_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id", "review_case_id", *_RESEARCH_SCOPE, "content_revision"],
            [
                "school_research_feedback_records.id",
                "school_research_feedback_records.review_case_id",
                *[f"school_research_feedback_records.{name}" for name in _RESEARCH_SCOPE],
                "school_research_feedback_records.content_revision",
            ],
            name="fk_school_research_feedback_events_record_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_feedback_events_actor_school",
            ondelete="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_research_feedback_events_case_created",
        "school_research_feedback_events",
        ["school_id", "review_case_id", "created_at"],
    )


def downgrade() -> None:
    tables = (
        "school_research_feedback_events",
        "school_research_feedback_records",
        "school_research_review_events",
        "school_research_review_cases",
    )
    connection = op.get_bind()
    for table_name in tables:
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar_one()
        if type(count) is not int or count != 0:
            raise RuntimeError("0017 downgrade refused because research review/feedback rows exist")
    for table_name in tables:
        op.drop_table(table_name)
