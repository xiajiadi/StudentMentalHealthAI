"""Additive school account lifecycle, one-time credentials and roster receipts.

Revision ID: 20261024_0025
Revises: 20261016_0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261024_0025"
down_revision: str | None = "20261016_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


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
    op.add_column(
        "accounts",
        sa.Column("failed_login_count", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "accounts",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("accounts", sa.Column("locked_until", _dt(), nullable=True))
    op.add_column("accounts", sa.Column("password_changed_at", _dt(), nullable=True))
    op.add_column("school_classes", sa.Column("grade_level", _ascii(32), nullable=True))
    op.create_check_constraint(
        "failed_login_count_allowed",
        "accounts",
        "failed_login_count BETWEEN 0 AND 32767",
    )
    op.add_column("auth_sessions", sa.Column("reauthenticated_at", _dt(), nullable=True))

    op.create_table(
        "school_roster_import_runs",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.Column("run_ref", _ascii(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("created_by_membership_role_id", _id(), nullable=False),
        sa.Column("idempotency_key_hash", mysql.BINARY(32), nullable=False),
        sa.Column("request_fingerprint", mysql.BINARY(32), nullable=False),
        sa.Column("source_sha256", mysql.BINARY(32), nullable=True),
        sa.Column("row_count", sa.SmallInteger(), nullable=False),
        sa.Column("created_count", sa.SmallInteger(), nullable=False),
        sa.Column("status", _ascii(16), nullable=False),
        sa.Column("summary", mysql.JSON(), nullable=False),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_roster_import_runs"),
        sa.UniqueConstraint("public_id", name="uq_school_roster_import_runs_public_id"),
        sa.UniqueConstraint("run_ref", name="school_roster_import_run_ref_unique"),
        sa.UniqueConstraint(
            "id", "school_id", name="school_roster_import_run_id_school_unique"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_roster_import_runs_creator_school",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_roster_import_runs_school", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "row_count BETWEEN 1 AND 200",
            name="row_count_allowed",
        ),
        sa.CheckConstraint(
            "created_count BETWEEN 0 AND row_count",
            name="created_count_allowed",
        ),
        sa.CheckConstraint(
            "status = 'COMPLETED'",
            name="status_allowed",
        ),
        sa.Index("ix_school_roster_import_runs_school_created", "school_id", "created_at"),
        **_options(),
    )

    op.create_table(
        "school_roster_import_run_batches",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.Column("run_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("batch_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("row_count", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_roster_import_run_batches"),
        sa.UniqueConstraint("public_id", name="uq_school_roster_import_run_batches_public_id"),
        sa.UniqueConstraint(
            "run_id", "batch_id", name="school_roster_run_batch_unique"
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "school_id"],
            ["school_roster_import_runs.id", "school_roster_import_runs.school_id"],
            name="fk_school_roster_run_batches_run_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "school_id", "class_id"],
            [
                "school_account_batches.id",
                "school_account_batches.school_id",
                "school_account_batches.class_id",
            ],
            name="fk_school_roster_run_batches_batch_school_class", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "row_count BETWEEN 1 AND 100",
            name="row_count_allowed",
        ),
        sa.Index("ix_school_roster_run_batches_run", "run_id", "school_id"),
        **_options(),
    )

    op.create_table(
        "school_account_credentials",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.Column("credential_ref", _ascii(128), nullable=False),
        sa.Column("account_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("issued_by_membership_role_id", _id(), nullable=True),
        sa.Column("purpose", _ascii(24), nullable=False),
        sa.Column("resource_ref", _ascii(128), nullable=True),
        sa.Column("token_hash", mysql.BINARY(32), nullable=False),
        sa.Column("status", _ascii(16), nullable=False),
        sa.Column("delivery_channel", _ascii(16), nullable=False),
        sa.Column("expires_at", _dt(), nullable=False),
        sa.Column("consumed_at", _dt(), nullable=True),
        sa.Column("revoked_at", _dt(), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_account_credentials"),
        sa.UniqueConstraint("public_id", name="uq_school_account_credentials_public_id"),
        sa.UniqueConstraint("credential_ref", name="school_account_credential_ref_unique"),
        sa.UniqueConstraint("token_hash", name="school_account_credential_token_hash_unique"),
        sa.ForeignKeyConstraint(
            ["account_id", "school_id"],
            ["account_school_memberships.account_id", "account_school_memberships.school_id"],
            name="fk_school_account_credentials_account_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_account_credentials_issuer_school", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "purpose IN ('INITIAL_ACTIVATION', 'STAFF_INVITATION', 'PASSWORD_RESET')",
            name="purpose_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ISSUED', 'CONSUMED', 'REVOKED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "delivery_channel IN ('MANUAL', 'EMAIL', 'SMS')",
            name="delivery_channel_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'ISSUED' AND consumed_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'CONSUMED' AND consumed_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="status_matches_timestamps",
        ),
        sa.Index(
            "ix_school_account_credentials_account_purpose_status",
            "account_id", "purpose", "status", "expires_at",
        ),
        sa.Index(
            "ix_school_account_credentials_school_status",
            "school_id", "status", "created_at",
        ),
        **_options(),
    )

    op.create_table(
        "school_staff_invitations",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.Column("invitation_ref", _ascii(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("account_id", _id(), nullable=False),
        sa.Column("membership_id", _id(), nullable=False),
        sa.Column("membership_role_id", _id(), nullable=False),
        sa.Column("issued_by_membership_role_id", _id(), nullable=False),
        sa.Column("role_code", _ascii(32), nullable=False),
        sa.Column("employee_ref", _ascii(128), nullable=False),
        sa.Column("status", _ascii(16), nullable=False),
        sa.Column("delivery_channel", _ascii(16), nullable=False),
        sa.Column("work_contact_ciphertext", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("work_contact_cipher_format_version", _ascii(32), nullable=False),
        sa.Column("work_contact_key_version", _ascii(64), nullable=False),
        sa.Column("work_contact_payload_schema_version", _ascii(64), nullable=False),
        sa.Column("work_contact_verified_at", _dt(), nullable=False),
        sa.Column("expires_at", _dt(), nullable=False),
        sa.Column("accepted_at", _dt(), nullable=True),
        sa.Column("revoked_at", _dt(), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_staff_invitations"),
        sa.UniqueConstraint("public_id", name="uq_school_staff_invitations_public_id"),
        sa.UniqueConstraint("invitation_ref", name="school_staff_invitation_ref_unique"),
        sa.UniqueConstraint(
            "id", "school_id", name="school_staff_invitation_id_school_unique"
        ),
        sa.UniqueConstraint("account_id", name="school_staff_invitation_account_unique"),
        sa.UniqueConstraint(
            "school_id", "employee_ref", name="school_staff_invitation_employee_unique"
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "school_id"],
            ["account_school_memberships.account_id", "account_school_memberships.school_id"],
            name="fk_school_staff_invitations_account_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_staff_invitations_membership_role_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "account_id", "school_id"],
            [
                "account_school_memberships.id",
                "account_school_memberships.account_id",
                "account_school_memberships.school_id",
            ],
            name="fk_school_staff_invitations_membership_account_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_role_id", "membership_id", "school_id"],
            ["membership_roles.id", "membership_roles.membership_id", "membership_roles.school_id"],
            name="fk_school_staff_invitations_role_membership_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_staff_invitations_issuer_school", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "role_code IN ('teacher', 'psychological_specialist')",
            name="role_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ISSUED', 'ACCEPTED', 'REVOKED', 'EXPIRED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "delivery_channel IN ('MANUAL', 'EMAIL', 'SMS')",
            name="delivery_channel_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'ISSUED' AND accepted_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'ACCEPTED' AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL) OR status = 'EXPIRED'",
            name="status_matches_timestamps",
        ),
        sa.Index("ix_school_staff_invitations_school_status", "school_id", "status", "created_at"),
        **_options(),
    )

    op.create_table(
        "school_staff_invitation_classes",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.Column("invitation_id", _id(), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_staff_invitation_classes"),
        sa.UniqueConstraint("public_id", name="uq_school_staff_invitation_classes_public_id"),
        sa.UniqueConstraint(
            "invitation_id", "class_id", name="invitation_class_unique"
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "school_id"],
            ["school_staff_invitations.id", "school_staff_invitations.school_id"],
            name="fk_school_staff_invitation_classes_invitation_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_school_staff_invitation_classes_class_school", ondelete="RESTRICT",
        ),
        **_options(),
    )

    op.create_table(
        "school_password_recovery_tickets",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("public_id", _ascii(36), nullable=False),
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
        sa.Column("ticket_ref", _ascii(128), nullable=False),
        sa.Column("school_id", _id(), nullable=False),
        sa.Column("account_id", _id(), nullable=False),
        sa.Column("class_id", _id(), nullable=False),
        sa.Column("reason_code", _ascii(32), nullable=False),
        sa.Column("status", _ascii(24), nullable=False),
        sa.Column("verified_by_membership_role_id", _id(), nullable=True),
        sa.Column("approved_by_membership_role_id", _id(), nullable=True),
        sa.Column("verified_at", _dt(), nullable=True),
        sa.Column("approved_at", _dt(), nullable=True),
        sa.Column("completed_at", _dt(), nullable=True),
        sa.Column("expires_at", _dt(), nullable=True),
        sa.Column("credential_ref", _ascii(128), nullable=True),
        sa.Column("trace_id", _ascii(128), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_password_recovery_tickets"),
        sa.UniqueConstraint("public_id", name="uq_school_password_recovery_tickets_public_id"),
        sa.UniqueConstraint("ticket_ref", name="school_password_recovery_ticket_ref_unique"),
        sa.UniqueConstraint(
            "id", "school_id", name="school_password_recovery_ticket_id_school_unique"
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "school_id"],
            ["account_school_memberships.account_id", "account_school_memberships.school_id"],
            name="fk_school_password_recovery_tickets_account_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_school_password_recovery_tickets_class_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_password_recovery_tickets_verifier_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_password_recovery_tickets_approver_school", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credential_ref"], ["school_account_credentials.credential_ref"],
            name="fk_school_password_recovery_tickets_credential_ref", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('REQUESTED', 'TEACHER_VERIFIED', 'APPROVED', 'REJECTED', "
            "'COMPLETED', 'EXPIRED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "reason_code IN ('CREDENTIAL_LOST', 'ACCOUNT_LOCKED', 'ACCESS_PROBLEM', 'OTHER')",
            name="reason_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'REQUESTED' AND verified_at IS NULL AND approved_at IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'TEACHER_VERIFIED' AND verified_at IS NOT NULL AND approved_at IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'APPROVED' AND verified_at IS NOT NULL AND approved_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'REJECTED' AND completed_at IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL) OR status = 'EXPIRED'",
            name="status_matches_timestamps",
        ),
        sa.Index(
            "ix_school_password_recovery_tickets_school_status", "school_id", "status", "created_at"
        ),
        sa.Index(
            "ix_school_password_recovery_tickets_account_status",
            "account_id", "status", "created_at",
        ),
        **_options(),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "school_password_recovery_tickets",
        "school_staff_invitation_classes",
        "school_staff_invitations",
        "school_account_credentials",
        "school_roster_import_run_batches",
        "school_roster_import_runs",
    ):
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM `{table}`")).scalar_one()
        if count:
            raise RuntimeError(
                "refusing to downgrade account lifecycle data; export/retention review is required"
            )
    account_state = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM accounts "
            "WHERE must_change_password = 1 OR failed_login_count <> 0 OR locked_until IS NOT NULL "
            "OR password_changed_at IS NOT NULL"
        )
    ).scalar_one()
    session_state = bind.execute(
        sa.text("SELECT COUNT(*) FROM auth_sessions WHERE reauthenticated_at IS NOT NULL")
    ).scalar_one()
    class_state = bind.execute(
        sa.text("SELECT COUNT(*) FROM school_classes WHERE grade_level IS NOT NULL")
    ).scalar_one()
    if account_state or session_state or class_state:
        raise RuntimeError("refusing to downgrade non-default account/session state")

    for table in (
        "school_password_recovery_tickets",
        "school_staff_invitation_classes",
        "school_staff_invitations",
        "school_account_credentials",
        "school_roster_import_run_batches",
        "school_roster_import_runs",
    ):
        op.drop_table(table)
    op.drop_constraint(
        "ck_accounts_failed_login_count_allowed", "accounts", type_="check"
    )
    op.drop_column("auth_sessions", "reauthenticated_at")
    op.drop_column("school_classes", "grade_level")
    op.drop_column("accounts", "password_changed_at")
    op.drop_column("accounts", "locked_until")
    op.drop_column("accounts", "failed_login_count")
    op.drop_column("accounts", "must_change_password")
