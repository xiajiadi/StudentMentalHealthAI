from database_layer.base import Base
from database_layer.models import (  # noqa: F401
    Account,
    AccountRole,
    AssessmentResponse,
    AssessmentResult,
    AssessmentSession,
    AuditEvent,
    AuthSession,
    ConsentRecord,
    IdempotencyRecord,
    ReviewCase,
    ReviewEvent,
    Role,
    SafetyDecision,
    Subject,
    SubjectAccessGrant,
    SupportEvidence,
    SupportMessage,
    SupportRun,
    SupportSession,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def test_round1_domain_table_count_and_explicit_mysql_defaults() -> None:
    assert len(Base.metadata.tables) == 19
    assert set(Base.metadata.tables) == {
        "accounts",
        "roles",
        "account_roles",
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
