from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from database_layer.base import Base
from database_layer.models import (  # noqa: F401
    Account,
    AuthSession,
    SchoolAccountCredential,
    SchoolPasswordRecoveryTicket,
    SchoolRosterImportRun,
    SchoolRosterImportRunBatch,
    SchoolStaffInvitation,
    SchoolStaffInvitationClass,
)
from sqlalchemy import CheckConstraint, ForeignKeyConstraint


def test_account_lifecycle_migration_is_additive_from_live_revision() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    directory = ScriptDirectory.from_config(config)
    revision = directory.get_revision("20261024_0025")

    assert revision is not None
    assert revision.down_revision == "20261016_0024"
    assert directory.get_current_head() == "20261024_0025"


def test_account_lifecycle_schema_has_scoped_receipts_and_no_raw_secrets() -> None:
    assert {
        "school_roster_import_runs",
        "school_roster_import_run_batches",
        "school_account_credentials",
        "school_staff_invitations",
        "school_staff_invitation_classes",
        "school_password_recovery_tickets",
    }.issubset(Base.metadata.tables)
    assert Account.__table__.c.failed_login_count.server_default is not None
    assert Account.__table__.c.must_change_password.server_default is not None
    assert Account.__table__.c.must_change_password.nullable is False
    assert Account.__table__.c.password_changed_at.nullable
    assert Account.__table__.c.locked_until.nullable
    assert AuthSession.__table__.c.reauthenticated_at.nullable
    assert SchoolAccountCredential.__table__.c.token_hash.type.python_type is bytes
    assert SchoolStaffInvitation.__table__.c.work_contact_ciphertext.type.python_type is bytes
    assert SchoolStaffInvitation.__table__.c.work_contact_cipher_format_version.nullable is False
    assert SchoolStaffInvitation.__table__.c.work_contact_key_version.nullable is False
    assert SchoolStaffInvitation.__table__.c.work_contact_payload_schema_version.nullable is False
    assert "token" not in SchoolAccountCredential.__table__.c
    assert "work_contact" not in SchoolStaffInvitation.__table__.c

    parent = SchoolRosterImportRun.__table__
    child = SchoolRosterImportRunBatch.__table__
    constraints = [item for item in parent.constraints if isinstance(item, CheckConstraint)]
    assert any("row_count BETWEEN 1 AND 200" in str(item.sqltext) for item in constraints)
    child_limits = [item for item in child.constraints if isinstance(item, CheckConstraint)]
    assert any("row_count BETWEEN 1 AND 100" in str(item.sqltext) for item in child_limits)
    child_fks = [item for item in child.constraints if isinstance(item, ForeignKeyConstraint)]
    assert any(
        tuple(element.parent.name for element in item.elements)
        == ("batch_id", "school_id", "class_id")
        for item in child_fks
    )

    invitation_classes = SchoolStaffInvitationClass.__table__
    invitation_scope_fks = [
        item for item in invitation_classes.constraints if isinstance(item, ForeignKeyConstraint)
    ]
    assert any(
        tuple(element.target_fullname for element in item.elements)
        == ("school_staff_invitations.id", "school_staff_invitations.school_id")
        for item in invitation_scope_fks
    )

    ticket = SchoolPasswordRecoveryTicket.__table__
    assert ticket.c.reason_code.nullable is False
    assert ticket.c.credential_ref.nullable is True
