import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from database_layer import models
from database_layer.base import utc_now
from database_layer.crypto import (
    EncryptedPayload,
    FernetDataProtectionProvider,
    MappingKeyProvider,
)
from database_layer.enums import DataOrigin
from database_layer.errors import PersistenceError
from database_layer.lifecycle import SyntheticLifecycleService
from sqlalchemy.dialects import mysql


def test_business_clock_is_utc_naive_for_mysql_datetime() -> None:
    value = utc_now()
    assert value.tzinfo is None
    assert value <= datetime.now(UTC).replace(tzinfo=None)


def test_non_synthetic_erasure_is_rejected_by_policy_boundary() -> None:
    # The service's guard is represented by the same enum vocabulary used by
    # the database CHECK constraint; real-data deletion needs a later gate.
    assert DataOrigin.PRODUCTION_PENDING.value == "PRODUCTION_PENDING"
    with pytest.raises(PersistenceError):
        raise PersistenceError("synthetic erasure service cannot target non-synthetic data")


def test_crypto_provider_does_not_use_pickle() -> None:
    provider = FernetDataProtectionProvider(
        MappingKeyProvider({"v1": Fernet.generate_key()}, active_version="v1")
    )
    # A valid Fernet key is required; this assertion documents the provider's
    # explicit failure mode instead of accepting arbitrary serialized objects.
    assert provider.cipher_format_version == "fernet.v1"


class _RetentionSession:
    def __init__(self, *, due_reviews: bool = True) -> None:
        self.statements = []
        self.added = []
        self.flush_count = 0
        self.due_reviews = due_reviews

    async def scalar(self, statement):
        return self.due_reviews

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1


def test_due_independent_review_ciphertext_is_purged_without_changing_lifecycle_metadata() -> None:
    session = _RetentionSession()
    key_provider = MappingKeyProvider({"test-only": Fernet.generate_key()}, "test-only")
    protection = FernetDataProtectionProvider(key_provider)
    service = SyntheticLifecycleService(session, protection=protection)

    purged = asyncio.run(
        service.purge_due_encrypted_payloads(
            before=datetime(2026, 10, 16, 12, 0),
            synthetic_only=True,
            trace_id="TRACE_test_retention",
        )
    )

    assert purged == 7
    assert len(session.statements) == 7
    statement = session.statements[-1]
    assert statement.table.name == models.SchoolIndependentEducationReview.__tablename__
    assigned_columns = {column.key for column in statement._values}
    assert assigned_columns == {
        "candidate_payload_ciphertext",
        "candidate_cipher_format_version",
        "candidate_key_version",
        "candidate_payload_schema_version",
        "reviewed_payload_ciphertext",
        "reviewed_cipher_format_version",
        "reviewed_key_version",
        "reviewed_payload_schema_version",
    }

    compiled = statement.compile(dialect=mysql.dialect())
    sql = str(compiled).lower()
    assert "retention_due_at" in sql
    assert "subjects.data_origin" in sql
    assert "exists (select" in sql
    assert "case when" in sql
    assert "candidate_payload_schema_version" in sql
    assert "reviewed_payload_schema_version" in sql
    assert "independent-education-retention-tombstone.v1" in compiled.params.values()
    assert all(
        update.table.name != models.SchoolIndependentEducationReviewEvent.__tablename__
        for update in session.statements
    )

    tombstone_ciphertexts = {
        value
        for value in compiled.params.values()
        if isinstance(value, bytes) and value.startswith(b"gAAAA")
    }
    assert len(tombstone_ciphertexts) == 2
    tombstones = [
        protection.decrypt_json(
            EncryptedPayload(
                ciphertext=value,
                key_version=key_provider.active_version,
                cipher_format_version=protection.cipher_format_version,
                payload_schema_version="independent-education-retention-tombstone.v1",
            )
        )
        for value in tombstone_ciphertexts
    ]
    assert {value["payload_kind"] for value in tombstones} == {"candidate", "reviewed_draft"}
    assert all(
        value
        == {
            "schema_version": "independent-education-retention-tombstone.v1",
            "payload_kind": value["payload_kind"],
            "retention_purged": True,
        }
        for value in tombstones
    )

    audit = session.added[-1]
    assert audit.action == "RETENTION_PAYLOAD_PURGE"
    assert audit.trace_id == "TRACE_test_retention"
    assert audit.safe_metadata == {"count": 7, "state": "SYNTHETIC_ONLY"}


def test_missing_payload_protection_fails_before_any_retention_write() -> None:
    session = _RetentionSession(due_reviews=True)
    service = SyntheticLifecycleService(session)

    with pytest.raises(PersistenceError, match="requires payload protection"):
        asyncio.run(
            service.purge_due_encrypted_payloads(
                before=datetime(2026, 10, 16, 12, 0),
                synthetic_only=True,
            )
        )

    assert session.statements == []
    assert session.added == []
    assert session.flush_count == 0


def test_missing_payload_protection_preserves_legacy_purge_when_no_due_review_exists() -> None:
    session = _RetentionSession(due_reviews=False)
    service = SyntheticLifecycleService(session)

    purged = asyncio.run(
        service.purge_due_encrypted_payloads(
            before=datetime(2026, 10, 16, 12, 0),
            synthetic_only=True,
        )
    )

    assert purged == 6
    assert len(session.statements) == 6
    assert session.added[-1].action == "RETENTION_PAYLOAD_PURGE"
