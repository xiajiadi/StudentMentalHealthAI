from pathlib import Path

from database_layer.base import Base
from database_layer.models import (  # noqa: F401
    Account,
    AccountRole,
    AccountSchoolMembership,
    AssessmentResponse,
    AssessmentResult,
    AssessmentSession,
    AuditEvent,
    AuthSession,
    ConsentRecord,
    IdempotencyRecord,
    MembershipRole,
    ReviewCase,
    ReviewEvent,
    Role,
    SafetyDecision,
    School,
    Subject,
    SubjectAccessGrant,
    SupportEvidence,
    SupportMessage,
    SupportRun,
    SupportSession,
)
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def test_round1_domain_table_count_and_explicit_mysql_defaults() -> None:
    assert len(Base.metadata.tables) == 22
    assert set(Base.metadata.tables) == {
        "accounts",
        "roles",
        "account_roles",
        "schools",
        "account_school_memberships",
        "membership_roles",
        "subjects",
        "subject_access_grants",
        "consent_records",
        "auth_sessions",
        "assessment_sessions",
        "assessment_responses",
        "assessment_results",
        "support_sessions",
        "support_messages",
        "support_runs",
        "support_evidence",
        "safety_decisions",
        "review_cases",
        "review_events",
        "idempotency_records",
        "audit_events",
    }
    for table in Base.metadata.tables.values():
        assert table.dialect_options["mysql"]["engine"] == "InnoDB"
        assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
        assert table.dialect_options["mysql"]["collate"] == "utf8mb4_0900_ai_ci"
        CreateTable(table).compile(dialect=mysql.dialect())


def test_sensitive_columns_are_binary_and_raw_secret_columns_absent() -> None:
    forbidden = {"password", "session_token", "csrf_token", "client_ip", "ip_address"}
    for table in Base.metadata.tables.values():
        assert not forbidden.intersection(table.c.keys())

    encrypted_columns = {
        "assessment_responses.response_ciphertext",
        "assessment_results.payload_ciphertext",
        "support_messages.payload_ciphertext",
        "safety_decisions.detail_ciphertext",
        "review_cases.case_note_ciphertext",
        "review_events.note_ciphertext",
    }
    for dotted in encrypted_columns:
        table_name, column_name = dotted.split(".")
        column = Base.metadata.tables[table_name].c[column_name]
        assert column.type.python_type is bytes


def test_no_clinical_label_columns_and_no_universal_soft_delete() -> None:
    all_columns = {
        column.name for table in Base.metadata.tables.values() for column in table.columns
    }
    assert not {
        "depression_level",
        "suicide_risk_level",
        "diagnosis",
        "mental_disorder",
    }.intersection(all_columns)
    assert sum("deleted_at" in table.c for table in Base.metadata.tables.values()) == 0


def test_school_membership_and_legacy_scope_constraints_are_additive() -> None:
    memberships = Base.metadata.tables["account_school_memberships"]
    membership_roles = Base.metadata.tables["membership_roles"]
    schools = Base.metadata.tables["schools"]
    subjects = Base.metadata.tables["subjects"]
    grants = Base.metadata.tables["subject_access_grants"]
    sessions = Base.metadata.tables["auth_sessions"]

    assert subjects.c.school_id.nullable is True
    assert grants.c.school_id.nullable is True
    assert sessions.c.active_school_id.nullable is True
    assert sessions.c.active_membership_role_id.nullable is True
    assert schools.c.data_origin.nullable is False
    assert schools.c.provenance_ref.nullable is False
    assert isinstance(schools.c.provenance_ref.type, String)
    assert schools.c.provenance_ref.type.length == 48
    school_constraints = {
        constraint.name: str(getattr(constraint, "sqltext", ""))
        for constraint in schools.constraints
    }
    assert "'SYNTHETIC'" in school_constraints["ck_schools_data_origin_allowed"]
    assert "'PRODUCTION_PENDING'" in school_constraints["ck_schools_data_origin_allowed"]
    assert (
        school_constraints["ck_schools_provenance_ref_token"]
        == "provenance_ref = 'SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1'"
    )

    school_subject_fk = next(
        constraint
        for constraint in grants.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(element.parent.name for element in constraint.elements)
        == ("subject_id", "school_id")
    )
    assert tuple(element.target_fullname for element in school_subject_fk.elements) == (
        "subjects.id",
        "subjects.school_id",
    )
    principal_membership_fk = next(
        constraint
        for constraint in grants.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(element.parent.name for element in constraint.elements)
        == ("principal_account_id", "school_id")
    )
    assert tuple(element.target_fullname for element in principal_membership_fk.elements) == (
        "account_school_memberships.account_id",
        "account_school_memberships.school_id",
    )
    assert {"account_id", "school_id"}.issubset(memberships.c.keys())
    assert {"membership_id", "school_id", "role_code"}.issubset(membership_roles.c.keys())
    session_context_fk = next(
        constraint
        for constraint in sessions.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(element.parent.name for element in constraint.elements)
        == ("active_membership_role_id", "active_school_id")
    )
    assert tuple(element.target_fullname for element in session_context_fk.elements) == (
        "membership_roles.id",
        "membership_roles.school_id",
    )
    school_role_check = next(
        constraint
        for constraint in membership_roles.constraints
        if getattr(constraint, "name", None) == "ck_membership_roles_role_allowed"
    )
    assert isinstance(school_role_check, CheckConstraint)
    assert "reviewer" not in str(school_role_check.sqltext).lower()


def test_tenant_status_server_defaults_match_reviewed_migration_literals() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261011_0003_school_membership_context.py"
    )
    migration = migration_path.read_text(encoding="utf-8")
    expected_migration_column = (
        'sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE")'
    )
    assert migration.count(expected_migration_column) == 3

    for table_name in (
        "schools",
        "account_school_memberships",
        "membership_roles",
    ):
        table = Base.metadata.tables[table_name]
        status = table.c.status
        assert status.default is not None
        assert getattr(status.default, "arg", None) == "ACTIVE"
        assert status.server_default is not None
        assert getattr(status.server_default, "arg", None) == "ACTIVE"
        compiled = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'" in compiled


def test_migration_keeps_existing_legacy_rows_unscoped() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261011_0003_school_membership_context.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade()", maxsplit=1)[0]
    assert "nullable=True" in upgrade
    assert "does not infer or backfill a school" in migration
    assert "UPDATE subjects" not in upgrade
    assert "UPDATE subject_access_grants" not in upgrade
    assert "data_origin" in upgrade
    assert "provenance_ref" in upgrade
    assert "provenance_ref = 'SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1'" in upgrade
