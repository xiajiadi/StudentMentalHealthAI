from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.core.errors import BackendError, ErrorCode


class _Column:
    def __init__(self, name: str):
        self.name = name

    def __eq__(self, value):
        return self.name, value


class _Receipt:
    scope = _Column("scope")
    key_hash = _Column("key_hash")

    def __init__(self, **values):
        self.__dict__.update(values)


class _Query:
    def __init__(self, model):
        self.model = model
        self.criteria = ()
        self.row_lock_requested = False

    def where(self, *criteria):
        self.criteria = criteria
        return self

    def with_for_update(self):
        self.row_lock_requested = True
        return self


class _Session:
    def __init__(self):
        self.record = None
        self.flush_count = 0
        self.queries = []

    async def scalar(self, query):
        self.queries.append(query)
        return self.record

    def add(self, record):
        self.record = record

    async def flush(self):
        self.flush_count += 1


class _UnitOfWork:
    def __init__(self, session):
        self.session = session
        self._before = None

    async def __aenter__(self):
        self._before = deepcopy(self.session.record)
        return self

    async def __aexit__(self, exc_type, _exc, _traceback):
        if exc_type is not None:
            self.session.record = self._before
        return False


def _adapter(session):
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter._db_models = SimpleNamespace(IdempotencyRecord=_Receipt)
    adapter._db_enums = SimpleNamespace(
        IdempotencyState=SimpleNamespace(
            IN_PROGRESS=SimpleNamespace(value="IN_PROGRESS"),
            COMPLETED=SimpleNamespace(value="COMPLETED"),
        )
    )
    adapter._select = _Query
    adapter._integrity_error = RuntimeError
    adapter._utc_now = lambda: datetime(2026, 10, 11, tzinfo=UTC)
    adapter.session_for_test = session
    return adapter


@pytest.mark.asyncio
async def test_school_idempotency_claim_completes_and_same_key_replays_receipt():
    session = _Session()
    adapter = _adapter(session)
    uow = SimpleNamespace(session=session)
    request = ("synthetic-key", "a" * 64, "scope-school-role")

    claim = await adapter._school_idempotency_begin(uow, request)
    assert claim.replayed is False
    assert claim.record is session.record
    assert claim.record.state == "IN_PROGRESS"

    await adapter._school_idempotency_complete(
        uow, claim, resource_type="school_class", result_ref="synthetic-ref"
    )
    assert session.record.state == "COMPLETED"
    assert session.record.result_public_id == "synthetic-ref"

    replay = await adapter._school_idempotency_begin(uow, request)
    assert replay.replayed is True
    assert replay.record is session.record
    assert all(query.row_lock_requested for query in session.queries)
    assert session.flush_count == 2


@pytest.mark.asyncio
async def test_expired_receipt_reclaim_locks_existing_row_before_replacing_fingerprint():
    session = _Session()
    session.record = _Receipt(
        scope="scope-school-role",
        key_hash=hashlib.sha256(b"synthetic-key").digest(),
        request_hash=bytes.fromhex("e" * 64),
        state="COMPLETED",
        result_resource_type="school_class",
        result_public_id="old-ref",
        expires_at=datetime(2026, 10, 10, tzinfo=UTC),
    )
    adapter = _adapter(session)
    uow = SimpleNamespace(session=session)

    claim = await adapter._school_idempotency_begin(
        uow, ("synthetic-key", "f" * 64, "scope-school-role")
    )

    assert session.queries[0].row_lock_requested is True
    assert claim.replayed is False
    assert claim.record is session.record
    assert claim.record.request_hash == bytes.fromhex("f" * 64)
    assert claim.record.state == "IN_PROGRESS"
    assert claim.record.result_public_id is None


@pytest.mark.asyncio
async def test_school_write_failure_rolls_back_new_receipt_without_fake_completion():
    session = _Session()
    adapter = _adapter(session)
    request = ("synthetic-key", "b" * 64, "scope-school-role")

    with pytest.raises(RuntimeError, match="business write failed"):
        async with _UnitOfWork(session) as uow:
            claim = await adapter._school_idempotency_begin(uow, request)
            assert claim.record.state == "IN_PROGRESS"
            raise RuntimeError("business write failed")

    assert session.record is None


@pytest.mark.asyncio
async def test_school_idempotency_rejects_fingerprint_reuse_without_completing():
    session = _Session()
    adapter = _adapter(session)
    uow = SimpleNamespace(session=session)
    request = ("synthetic-key", "c" * 64, "scope-school-role")
    claim = await adapter._school_idempotency_begin(uow, request)
    await adapter._school_idempotency_complete(
        uow, claim, resource_type="school_class", result_ref="synthetic-ref"
    )

    with pytest.raises(BackendError) as caught:
        await adapter._school_idempotency_begin(uow, (request[0], "d" * 64, request[2]))
    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert session.record.state == "COMPLETED"
    assert session.record.result_public_id == "synthetic-ref"
