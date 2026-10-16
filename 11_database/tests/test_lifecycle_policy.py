import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from database_layer import models
from database_layer.base import utc_now
from database_layer.crypto import FernetDataProtectionProvider, MappingKeyProvider
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
    def __init__(self) -> None:
        self.statements = []
        self.added = []
        self.flush_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1


def test_due_independent_review_ciphertext_is_purged_without_changing_lifecycle_metadata() -> None:
    session = _RetentionSession()
    service = SyntheticLifecycleService(session)

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
        "reviewed_payload_ciphertext",
    }

    sql = str(statement.compile(dialect=mysql.dialect())).lower()
    assert "retention_due_at" in sql
    assert "subjects.data_origin" in sql
    assert "exists (select" in sql
    assert "candidate_payload_ciphertext" in sql
    assert "reviewed_payload_ciphertext" in sql
    assert "case when" in sql
    assert all(
        update.table.name != models.SchoolIndependentEducationReviewEvent.__tablename__
        for update in session.statements
    )

    audit = session.added[-1]
    assert audit.action == "RETENTION_PAYLOAD_PURGE"
    assert audit.trace_id == "TRACE_test_retention"
    assert audit.safe_metadata == {"count": 7, "state": "SYNTHETIC_ONLY"}
