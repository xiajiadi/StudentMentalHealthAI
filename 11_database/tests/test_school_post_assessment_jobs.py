from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from database_layer.errors import (
    ForeignKeyConflict,
    NotFound,
    OptimisticConcurrencyConflict,
    UniqueConflict,
)
from database_layer.school_post_assessment_jobs import (
    PostAssessmentJobErrorCode,
    SchoolPostAssessmentJobRepository,
)
from database_layer.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

NOW = datetime(2026, 10, 14, 4, 5, 6, tzinfo=UTC)
SCOPE = {
    "school_id": 21,
    "task_id": 31,
    "class_id": 41,
    "class_student_id": 51,
    "task_enrollment_id": 61,
    "subject_id": 71,
    "assessment_session_id": 81,
    "policy_version": "edu-policy-v1",
}


class _Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class _FakeSession:
    def __init__(self, *, scalar_values=(), scalar_rows=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = list(scalar_rows)
        self.statements = []
        self.pending = []
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.nested_count = 0

    async def scalar(self, statement):
        self.statements.append(statement)
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return None

    async def scalars(self, statement):
        self.statements.append(statement)
        values = self.scalar_rows.pop(0) if self.scalar_rows else []
        return _Rows(values)

    def add(self, value):
        self.pending.append(value)

    async def flush(self):
        self.flush_count += 1
        for value in self.pending:
            if getattr(value, "id", None) is None:
                value.id = 901
            if getattr(value, "created_at", None) is None:
                value.created_at = NOW.replace(tzinfo=None)
            if getattr(value, "updated_at", None) is None:
                value.updated_at = NOW.replace(tzinfo=None)

    @asynccontextmanager
    async def begin_nested(self):
        self.nested_count += 1
        yield

    async def begin(self):
        return None

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1

    async def close(self):
        self.close_count += 1


def _live_job(**changes):
    job = SimpleNamespace(
        id=901,
        job_ref="PAJ_example",
        school_id=SCOPE["school_id"],
        task_id=SCOPE["task_id"],
        class_id=SCOPE["class_id"],
        class_student_id=SCOPE["class_student_id"],
        task_enrollment_id=SCOPE["task_enrollment_id"],
        subject_id=SCOPE["subject_id"],
        assessment_session_id=SCOPE["assessment_session_id"],
        job_kind="EDUCATION_SUPPORT",
        policy_version="edu-policy-v1",
        policy_hash=None,
        status="LEASED",
        attempt_count=1,
        next_attempt_at=None,
        lease_owner="worker-a",
        lease_token="lease-token-current",
        lease_expires_at=(NOW + timedelta(seconds=60)).replace(tzinfo=None),
        source_snapshot_ref=None,
        source_snapshot_sha256=None,
        source_qualification_status="PENDING",
        source_population="synthetic-demo",
        source_layer="policy",
        source_rights_status="verified",
        source_review_status="pending",
        source_qualified_at=None,
        last_error_code=None,
        created_at=NOW.replace(tzinfo=None),
        updated_at=NOW.replace(tzinfo=None),
    )
    for name, value in changes.items():
        setattr(job, name, value)
    return job


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_scoped_and_does_not_commit():
    session = _FakeSession(scalar_values=[None])
    repository = SchoolPostAssessmentJobRepository(cast(Any, session))
    created = await repository.enqueue(**SCOPE)
    inserted = session.pending[0]
    repeated_session = _FakeSession(scalar_values=[inserted])
    repeated = await SchoolPostAssessmentJobRepository(cast(Any, repeated_session)).enqueue(**SCOPE)

    assert created.id == repeated.id == 901
    assert created.job_ref == repeated.job_ref
    assert created.status == "QUEUED"
    assert created.job_kind == "EDUCATION_SUPPORT"
    assert created.assessment_session_id == SCOPE["assessment_session_id"]
    assert "lease_token" not in created.__dataclass_fields__
    assert session.nested_count == 1 and repeated_session.nested_count == 0
    assert session.flush_count == 1 and session.commit_count == 0
    assert repeated_session.flush_count == 0

    conflicting_session = _FakeSession(scalar_values=[inserted])
    with pytest.raises(UniqueConflict, match="idempotency key"):
        await SchoolPostAssessmentJobRepository(cast(Any, conflicting_session)).enqueue(
            **SCOPE, policy_hash="a" * 64
        )


@pytest.mark.asyncio
async def test_enqueue_validates_ascii_hash_and_timezone_metadata():
    session = _FakeSession()
    repository = SchoolPostAssessmentJobRepository(cast(Any, session))
    with pytest.raises(ValueError, match="policy_version"):
        await repository.enqueue(**{**SCOPE, "policy_version": "含中文"})
    with pytest.raises(ValueError, match="SHA-256"):
        await repository.enqueue(**SCOPE, source_snapshot_sha256="not-a-hash")
    with pytest.raises(ValueError, match="bounded ASCII token"):
        await repository.enqueue(**SCOPE, source_snapshot_ref="staging/private/source.json")
    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.enqueue(**SCOPE, source_qualified_at=datetime(2026, 10, 14))
    assert session.nested_count == 0 and session.flush_count == 0


@pytest.mark.asyncio
async def test_claim_reclaims_expired_lease_and_compiles_skip_locked():
    queued = _live_job(
        status="QUEUED", attempt_count=0, lease_owner=None, lease_token=None,
        lease_expires_at=None,
    )
    expired = _live_job(
        id=902,
        status="LEASED",
        attempt_count=1,
        lease_owner="old-worker",
        lease_token="old-token",
        lease_expires_at=(NOW - timedelta(seconds=1)).replace(tzinfo=None),
    )
    session = _FakeSession(scalar_rows=[[queued, expired]])
    claims = await SchoolPostAssessmentJobRepository(cast(Any, session)).claim_ready(
        school_id=SCOPE["school_id"],
        lease_owner="worker-b",
        limit=2,
        lease_seconds=30,
        now=NOW,
    )

    assert len(claims) == 2
    assert [claim.attempt_count for claim in claims] == [1, 2]
    assert all(claim.status == "LEASED" and claim.lease_owner == "worker-b" for claim in claims)
    assert all(claim.lease_token and claim.lease_token != "old-token" for claim in claims)
    assert all(claim.lease_expires_at == NOW + timedelta(seconds=30) for claim in claims)
    sql = str(session.statements[0].compile(dialect=mysql.dialect())).upper()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_claim_fails_exhausted_expired_job_and_clears_lease():
    expired = _live_job(attempt_count=3)
    session = _FakeSession(scalar_rows=[[expired]])
    claims = await SchoolPostAssessmentJobRepository(cast(Any, session)).claim_ready(
        school_id=SCOPE["school_id"], lease_owner="worker-c", max_attempts=3, now=NOW
    )
    assert claims == []
    assert expired.status == "FAILED"
    assert expired.last_error_code == "LEASE_EXPIRED_MAX_ATTEMPTS"
    assert expired.lease_owner is None and expired.lease_token is None
    assert expired.lease_expires_at is None and expired.next_attempt_at is None


@pytest.mark.asyncio
async def test_retry_uses_bounded_exponential_backoff_and_clears_lease():
    job = _live_job(attempt_count=2)
    session = _FakeSession(scalar_values=[job])
    dto = await SchoolPostAssessmentJobRepository(cast(Any, session)).retry(
        school_id=job.school_id,
        subject_id=job.subject_id,
        job_id=job.id,
        lease_owner=job.lease_owner,
        lease_token=job.lease_token,
        error_code=PostAssessmentJobErrorCode.UPSTREAM_TIMEOUT,
        base_delay_seconds=5,
        max_delay_seconds=20,
        now=NOW,
    )
    assert dto.status == "RETRY"
    assert dto.next_attempt_at == NOW + timedelta(seconds=10)
    assert dto.last_error_code == PostAssessmentJobErrorCode.UPSTREAM_TIMEOUT.value
    assert job.lease_owner is None and job.lease_token is None and job.lease_expires_at is None
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_retry_exhaustion_becomes_failed_and_has_no_active_lease():
    job = _live_job(attempt_count=3)
    session = _FakeSession(scalar_values=[job])
    dto = await SchoolPostAssessmentJobRepository(cast(Any, session)).retry(
        school_id=job.school_id,
        subject_id=job.subject_id,
        job_id=job.id,
        lease_owner=job.lease_owner,
        lease_token=job.lease_token,
        error_code=PostAssessmentJobErrorCode.GENERATION_FAILED,
        max_attempts=3,
        now=NOW,
    )
    assert dto.status == "FAILED"
    assert dto.next_attempt_at is None
    assert dto.last_error_code == PostAssessmentJobErrorCode.GENERATION_FAILED.value
    assert job.lease_owner is None and job.lease_token is None and job.lease_expires_at is None


@pytest.mark.asyncio
async def test_extend_lease_requires_live_claim_and_returns_same_capability():
    job = _live_job()
    session = _FakeSession(scalar_values=[job])
    claim = await SchoolPostAssessmentJobRepository(cast(Any, session)).extend_lease(
        school_id=job.school_id,
        subject_id=job.subject_id,
        job_id=job.id,
        lease_owner=job.lease_owner,
        lease_token=job.lease_token,
        lease_seconds=120,
        now=NOW,
    )
    assert claim.lease_owner == "worker-a"
    assert claim.lease_token == "lease-token-current"
    assert claim.lease_expires_at == NOW + timedelta(seconds=120)


@pytest.mark.asyncio
async def test_complete_rejects_unapproved_status_and_requires_error_code_for_failed():
    repository = SchoolPostAssessmentJobRepository(cast(Any, _FakeSession()))
    args = {
        "school_id": SCOPE["school_id"],
        "subject_id": SCOPE["subject_id"],
        "job_id": 901,
        "lease_owner": "worker-a",
        "lease_token": "lease-token-current",
    }
    with pytest.raises(ValueError, match="terminal state"):
        await repository.complete(**args, status="PUBLISHED", now=NOW)
    with pytest.raises(ValueError, match="FAILED requires"):
        await repository.complete(**args, status="FAILED", now=NOW)


@pytest.mark.asyncio
async def test_stale_owner_or_token_cannot_extend_or_finish():
    session = _FakeSession(scalar_values=[None, None])
    repository = SchoolPostAssessmentJobRepository(cast(Any, session))
    with pytest.raises(OptimisticConcurrencyConflict, match="lease is stale"):
        await repository.extend_lease(
            school_id=SCOPE["school_id"], subject_id=SCOPE["subject_id"], job_id=901,
            lease_owner="former-worker", lease_token="stale-token", now=NOW,
        )
    with pytest.raises(OptimisticConcurrencyConflict, match="lease is stale"):
        await repository.complete(
            school_id=SCOPE["school_id"], subject_id=SCOPE["subject_id"], job_id=901,
            lease_owner="worker-a", lease_token="stale-token", status="HELD", now=NOW,
        )
    assert session.flush_count == 0
    sql = str(session.statements[0].compile(dialect=mysql.dialect())).upper()
    for column in (
        "SCHOOL_ID", "SUBJECT_ID", "ID", "LEASE_OWNER", "LEASE_TOKEN", "LEASE_EXPIRES_AT"
    ):
        assert column in sql


@pytest.mark.asyncio
async def test_finish_requires_live_lease_and_leaves_no_terminal_lease():
    job = _live_job()
    session = _FakeSession(scalar_values=[job])
    dto = await SchoolPostAssessmentJobRepository(cast(Any, session)).complete(
        school_id=job.school_id,
        subject_id=job.subject_id,
        job_id=job.id,
        lease_owner=job.lease_owner,
        lease_token=job.lease_token,
        status="REVIEW_REQUIRED",
        now=NOW,
    )
    assert dto.status == "REVIEW_REQUIRED"
    assert job.lease_owner is None and job.lease_token is None and job.lease_expires_at is None
    assert job.next_attempt_at is None
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_scoped_get_returns_only_allowlisted_dto_or_not_found():
    job = _live_job()
    session = _FakeSession(scalar_values=[job, None])
    repository = SchoolPostAssessmentJobRepository(cast(Any, session))
    dto = await repository.get(school_id=job.school_id, subject_id=job.subject_id, job_id=job.id)
    assert dto.id == job.id and dto.subject_id == job.subject_id
    assert not hasattr(dto, "lease_token")
    with pytest.raises(NotFound):
        await repository.get(school_id=999, subject_id=999, job_id=job.id)
    assert "SCHOOL_ID" in str(session.statements[0].compile(dialect=mysql.dialect())).upper()
    assert "SUBJECT_ID" in str(session.statements[0].compile(dialect=mysql.dialect())).upper()


@pytest.mark.asyncio
async def test_uow_registers_repository_on_its_transaction_session():
    session = _FakeSession()

    def factory():
        return session

    async with SqlAlchemyUnitOfWork(cast(Any, factory), cast(Any, object())) as unit:
        assert unit.post_assessment_jobs is not None
        assert unit.post_assessment_jobs.session is session
        assert session.commit_count == 0
    assert session.commit_count == 1 and session.close_count == 1


@pytest.mark.asyncio
async def test_enqueue_integrity_race_reads_winner_with_locking_query():
    existing = _live_job(
        status="QUEUED", lease_owner=None, lease_token=None, lease_expires_at=None,
        source_qualification_status=None, source_population=None, source_layer=None,
        source_rights_status=None, source_review_status=None,
    )
    session = _FakeSession(scalar_values=[None, existing])

    async def flush_conflict():
        raise IntegrityError("insert", {}, Exception("private db details"))

    session.flush = flush_conflict
    dto = await SchoolPostAssessmentJobRepository(cast(Any, session)).enqueue(**SCOPE)
    assert dto.id == existing.id
    assert "FOR UPDATE" in str(session.statements[-1].compile(dialect=mysql.dialect())).upper()


@pytest.mark.asyncio
async def test_enqueue_fk_failure_is_sanitized_and_does_not_commit():
    session = _FakeSession(scalar_values=[None, None])

    async def flush_conflict():
        raise IntegrityError("insert", {}, Exception("sensitive database diagnostic"))

    session.flush = flush_conflict
    with pytest.raises(ForeignKeyConflict) as captured:
        await SchoolPostAssessmentJobRepository(cast(Any, session)).enqueue(**SCOPE)
    assert "sensitive database diagnostic" not in str(captured.value)
    assert session.commit_count == 0
