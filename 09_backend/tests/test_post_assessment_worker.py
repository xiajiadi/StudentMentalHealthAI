from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from smhai_backend.domains.post_assessment.service import (
    NO_PERSONALIZED_POLICY_VERSION,
    EducationJobInput,
    PersistenceStage,
    PostAssessmentAuthorizationFailure,
    PostAssessmentAuthorizationScope,
    PostAssessmentErrorCode,
    PostAssessmentJobOutcome,
    PostAssessmentJobStatus,
    PostAssessmentPersistenceFailure,
    PostAssessmentWorker,
    PostAssessmentWorkerResult,
    RetryablePostAssessmentError,
    database_persistence_error_mapper,
)

NOW = datetime(2026, 10, 14, 8, 30, tzinfo=UTC)
POLICY = "education-policy-v2"


@dataclass
class _Claim:
    id: int = 901
    job_ref: str = "PAJ_fixture"
    school_id: int = 11
    task_id: int = 21
    class_id: int = 31
    class_student_id: int = 41
    task_enrollment_id: int = 51
    subject_id: int = 61
    assessment_session_id: int = 71
    job_kind: str = "EDUCATION_SUPPORT"
    policy_version: str = POLICY
    policy_hash: str | None = "a" * 64
    status: str = "LEASED"
    attempt_count: int = 1
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = NOW + timedelta(seconds=60)
    source_snapshot_ref: str | None = "policy-source-v1"
    source_snapshot_sha256: str | None = "b" * 64
    source_qualification_status: str | None = "QUALIFIED"
    source_population: str | None = "synthetic-demo"
    source_layer: str | None = "policy"
    source_rights_status: str | None = "verified"
    source_review_status: str | None = "approved"
    source_qualified_at: datetime | None = NOW
    last_error_code: str | None = None
    created_at: datetime = NOW
    updated_at: datetime = NOW
    lease_owner: str = "worker-test"
    lease_token: str = "memory-only-lease-capability"


class _Repository:
    def __init__(self, claims=()):
        self.claims = list(claims)
        self.calls = []
        self.extend_event = asyncio.Event()
        self.raise_complete: Exception | None = None
        self.raise_extend: Exception | None = None
        self.raise_retry: Exception | None = None

    async def claim_ready(self, **values):
        self.calls.append(("claim", values))
        result = self.claims[: values["limit"]]
        self.claims = self.claims[len(result) :]
        return result

    async def extend_lease(self, **values):
        self.calls.append(("extend", values))
        if self.raise_extend is not None:
            raise self.raise_extend
        self.extend_event.set()

    async def retry(self, **values):
        self.calls.append(("retry", values))
        if self.raise_retry is not None:
            raise self.raise_retry

    async def complete(self, **values):
        self.calls.append(("complete", values))
        if self.raise_complete is not None:
            raise self.raise_complete


class _Uow:
    def __init__(self, repository, state):
        self.post_assessment_jobs = repository
        self.state = state

    async def __aenter__(self):
        self.state["active"] += 1
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        self.state["active"] -= 1
        if _exc_type is None:
            self.state["commits"] = self.state.get("commits", 0) + 1
        else:
            self.state["rollbacks"] = self.state.get("rollbacks", 0) + 1
            self.state["partial_write"] = False


class _StaleLeaseError(Exception):
    pass


class _PersistenceErrors:
    def to_persistence_error_code(self, error_code):
        return error_code.value

    def is_stale_lease_error(self, error):
        return isinstance(error, _StaleLeaseError)


class _Authorization:
    def __init__(self, decisions=(True, True)):
        self.decisions = list(decisions)
        self.scopes = []

    async def is_authorized(self, scope):
        self.scopes.append(scope)
        if not self.decisions:
            return True
        return self.decisions.pop(0)


class _Processor:
    def __init__(self, outcome=None, *, callback=None):
        self.outcome = outcome
        self.callback = callback
        self.calls = []

    async def process(self, job):
        self.calls.append(job)
        if self.callback is not None:
            return await self.callback(job)
        return self.outcome


def _worker(
    repository,
    *,
    authorization=None,
    processor=None,
    state=None,
    policy_version=POLICY,
    clock=None,
    persistence_errors=None,
    **options,
):
    state = state if state is not None else {"active": 0}
    auth = authorization or _Authorization()
    worker = PostAssessmentWorker(
        school_id=11,
        unit_of_work_factory=lambda: _Uow(repository, state),
        authorization=auth,
        persistence_errors=persistence_errors or _PersistenceErrors(),
        processor=processor,
        worker_id="worker-test",
        policy_version=policy_version,
        clock=clock or (lambda: NOW),
        **options,
    )
    return worker, auth, state


@pytest.mark.asyncio
async def test_held_processor_runs_outside_uow_and_gets_only_safe_metadata():
    repository = _Repository([_Claim()])
    state = {"active": 0}

    async def process(job):
        assert state["active"] == 0
        assert isinstance(job, EducationJobInput)
        assert not hasattr(job, "lease_token")
        assert not hasattr(job, "raw_answers")
        assert not hasattr(job, "report_body")
        return PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD)

    processor = _Processor(callback=process)
    worker, authorization, _ = _worker(repository, processor=processor, state=state)
    assert await worker.run_once() is PostAssessmentWorkerResult.APPLIED

    assert [call[0] for call in repository.calls] == ["claim", "complete"]
    assert repository.calls[-1][1]["status"] == "HELD"
    assert len(authorization.scopes) == 2
    assert authorization.scopes[0] == authorization.scopes[1]
    assert isinstance(authorization.scopes[0], PostAssessmentAuthorizationScope)
    assert repository.calls[-1][1]["lease_token"] == _Claim.lease_token
    assert state["active"] == 0


@pytest.mark.asyncio
async def test_default_no_personalized_policy_abstains_without_calling_processor():
    claim = _Claim(policy_version=NO_PERSONALIZED_POLICY_VERSION)
    repository = _Repository([claim])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    worker, _, _ = _worker(
        repository,
        processor=processor,
        policy_version=NO_PERSONALIZED_POLICY_VERSION,
    )
    await worker.run_once()

    assert processor.calls == []
    completion = repository.calls[-1][1]
    assert completion["status"] == "ABSTAINED"
    assert completion["error_code"] == "POLICY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_missing_or_unqualified_source_abstains_before_processor():
    claim = _Claim(source_snapshot_ref=None)
    repository = _Repository([claim])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    worker, _, _ = _worker(repository, processor=processor)
    await worker.run_once()

    assert processor.calls == []
    assert repository.calls[-1][1]["status"] == "ABSTAINED"
    assert repository.calls[-1][1]["error_code"] == "SOURCE_UNQUALIFIED"


@pytest.mark.asyncio
async def test_crisis_disposition_does_not_retrieve_or_call_any_rag_client():
    repository = _Repository([_Claim()])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.CRISIS_ROUTED))
    worker, _, _ = _worker(repository, processor=processor)
    rag_spy = SimpleNamespace(calls=0)

    await worker.run_once()

    assert processor.calls and repository.calls[-1][1]["status"] == "CRISIS_ROUTED"
    assert not hasattr(worker, "rag")
    assert rag_spy.calls == 0


@pytest.mark.asyncio
async def test_transient_and_unknown_processor_failures_use_fixed_bounded_retry_codes():
    async def transient(_job):
        raise RetryablePostAssessmentError(PostAssessmentErrorCode.UPSTREAM_TIMEOUT)

    repository = _Repository([_Claim()])
    worker, _, _ = _worker(repository, processor=_Processor(callback=transient), max_attempts=4)
    await worker.run_once()
    call = repository.calls[-1]
    assert call[0] == "retry"
    assert call[1]["error_code"] == "UPSTREAM_TIMEOUT"
    assert call[1]["max_attempts"] == 4

    async def private_error(_job):
        raise RuntimeError("raw prompt or source text must never be persisted")

    second = _Repository([_Claim()])
    worker, _, _ = _worker(second, processor=_Processor(callback=private_error))
    await worker.run_once()
    failure = second.calls[-1]
    assert failure[0] == "retry"
    assert failure[1]["error_code"] == "INTERNAL_FAILURE"
    assert "raw prompt" not in repr(failure[1])


@pytest.mark.asyncio
async def test_lease_heartbeat_renews_with_token_while_processor_runs():
    repository = _Repository([_Claim()])

    async def process(_job):
        await asyncio.wait_for(repository.extend_event.wait(), timeout=1)
        return PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD)

    worker, _, _ = _worker(
        repository,
        processor=_Processor(callback=process),
        heartbeat_interval_seconds=0.01,
        lease_seconds=10,
    )
    await worker.run_once()

    extensions = [values for name, values in repository.calls if name == "extend"]
    assert extensions
    assert all(extension["lease_token"] == _Claim.lease_token for extension in extensions)
    assert all(extension["now"] == NOW for extension in extensions)
    assert repository.calls[-1][0] == "complete"


@pytest.mark.asyncio
async def test_expired_claim_is_available_again_on_a_later_poll_with_fake_clock():
    class _Clock:
        value = NOW

        def __call__(self):
            return self.value

    clock = _Clock()
    reclaimed = _Claim(
        attempt_count=2,
        lease_token="new-owner-token",
        lease_owner="worker-test",
        lease_expires_at=NOW + timedelta(seconds=60),
    )

    class _ExpiryRepository(_Repository):
        def __init__(self):
            super().__init__()
            self.poll_count = 0

        async def claim_ready(self, **values):
            self.calls.append(("claim", values))
            self.poll_count += 1
            if self.poll_count == 1 or values["now"] < NOW + timedelta(seconds=61):
                return []
            return [reclaimed]

    repository = _ExpiryRepository()
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    worker, _, _ = _worker(repository, processor=processor, clock=clock)
    assert await worker.run_once() is PostAssessmentWorkerResult.IDLE
    clock.value = NOW + timedelta(seconds=61)
    assert await worker.run_once() is PostAssessmentWorkerResult.APPLIED

    polls = [values for name, values in repository.calls if name == "claim"]
    assert [poll["now"] for poll in polls] == [NOW, NOW + timedelta(seconds=61)]
    assert processor.calls[0].job_id == reclaimed.id
    assert repository.calls[-1][1]["lease_token"] == "new-owner-token"


@pytest.mark.asyncio
async def test_lease_extension_failure_cancels_processor_without_finalizing():
    state = {"active": 0, "partial_write": False}
    repository = _Repository([_Claim()])
    repository.raise_extend = RuntimeError("private stale-token details")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def process(_job):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    worker, _, _ = _worker(
        repository,
        state=state,
        processor=_Processor(callback=process),
        heartbeat_interval_seconds=0.01,
        lease_seconds=10,
    )
    with pytest.raises(PostAssessmentPersistenceFailure) as captured:
        await worker.run_once()

    assert started.is_set() and cancelled.is_set()
    assert captured.value.stage is PersistenceStage.HEARTBEAT
    assert not any(name in {"complete", "retry"} for name, _ in repository.calls)
    assert "private stale-token details" not in repr(repository.calls)
    assert state["rollbacks"] == 1


@pytest.mark.asyncio
async def test_stale_heartbeat_returns_stale_disposition_not_persistence_failure():
    repository = _Repository([_Claim()])
    repository.raise_extend = _StaleLeaseError("private expired lease detail")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def process(_job):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    worker, _, _ = _worker(
        repository,
        processor=_Processor(callback=process),
        heartbeat_interval_seconds=0.01,
        lease_seconds=10,
    )
    result = await worker.run_once()

    assert result is PostAssessmentWorkerResult.STALE_LEASE
    assert started.is_set() and cancelled.is_set()
    assert not any(name in {"complete", "retry"} for name, _ in repository.calls)
    assert "private expired lease detail" not in repr(repository.calls)


@pytest.mark.asyncio
async def test_reauthorization_is_rechecked_after_processing_and_cancels_on_revocation():
    repository = _Repository([_Claim()])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    authorization = _Authorization((True, False))
    worker, _, _ = _worker(repository, processor=processor, authorization=authorization)
    await worker.run_once()

    assert len(processor.calls) == 1
    assert repository.calls[-1][1]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_authorization_failure_before_processing_fails_closed():
    repository = _Repository([_Claim()])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    worker, _, _ = _worker(
        repository, processor=processor, authorization=_Authorization((False,))
    )
    await worker.run_once()

    assert processor.calls == []
    assert repository.calls[-1][1]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_authorization_lookup_failure_is_not_misclassified_as_revocation():
    repository = _Repository([_Claim()])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))

    class _DatabaseFailure:
        async def is_authorized(self, _scope):
            raise RuntimeError("private database connection detail")

    worker, _, _ = _worker(repository, processor=processor, authorization=_DatabaseFailure())
    with pytest.raises(PostAssessmentAuthorizationFailure) as captured:
        await worker.run_once()

    assert processor.calls == []
    assert [name for name, _ in repository.calls] == ["claim"]
    assert "private database connection detail" not in str(captured.value)


@pytest.mark.asyncio
async def test_non_boolean_authorization_decision_is_a_visible_contract_failure():
    repository = _Repository([_Claim()])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    worker, _, _ = _worker(
        repository, processor=processor, authorization=_Authorization((None,))
    )

    with pytest.raises(PostAssessmentAuthorizationFailure):
        await worker.run_once()

    assert processor.calls == []
    assert [name for name, _ in repository.calls] == ["claim"]


@pytest.mark.asyncio
async def test_stale_token_finalization_returns_only_fixed_stale_disposition():
    state = {"active": 0, "partial_write": False}

    class _StaleRepository(_Repository):
        async def complete(self, **values):
            self.calls.append(("complete", values))
            state["partial_write"] = True
            raise _StaleLeaseError("private stale-token detail")

    repository = _StaleRepository([_Claim()])
    worker, _, _ = _worker(
        repository,
        state=state,
        processor=_Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD)),
    )
    result = await worker.run_once()
    assert result is PostAssessmentWorkerResult.STALE_LEASE
    assert repository.calls[-1][0] == "complete"
    assert len([call for call in repository.calls if call[0] == "retry"]) == 0
    assert "private stale-token detail" not in repr(repository.calls)
    assert state["rollbacks"] == 1 and state["partial_write"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "expected_status"),
    [
        ("source_rights_status", "not_verified", "ABSTAINED"),
        ("source_review_status", "pending", "ABSTAINED"),
        ("policy_hash", "invalid", "ABSTAINED"),
        ("source_snapshot_sha256", "invalid", "ABSTAINED"),
        ("source_qualified_at", None, "ABSTAINED"),
        ("job_kind", "OTHER", "CANCELLED"),
    ],
)
async def test_unverified_or_incomplete_source_fails_closed(field, value, expected_status):
    claim = _Claim(**{field: value})
    repository = _Repository([claim])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    worker, _, _ = _worker(repository, processor=processor)
    result = await worker.run_once()

    assert result is PostAssessmentWorkerResult.APPLIED
    assert processor.calls == []
    assert repository.calls[-1][1]["status"] == expected_status
    if expected_status == "ABSTAINED":
        assert repository.calls[-1][1]["error_code"] == "SOURCE_UNQUALIFIED"


@pytest.mark.asyncio
async def test_naive_qualification_timestamp_fails_closed():
    claim = _Claim(source_qualified_at=NOW.replace(tzinfo=None))
    repository = _Repository([claim])
    processor = _Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD))
    worker, _, _ = _worker(repository, processor=processor)
    await worker.run_once()
    assert processor.calls == []
    assert repository.calls[-1][1]["error_code"] == "SOURCE_UNQUALIFIED"


@pytest.mark.asyncio
async def test_failed_finalize_rolls_back_and_raises_fixed_safe_error():
    state = {"active": 0, "partial_write": False}

    class _PartialWriteRepository(_Repository):
        async def complete(self, **values):
            self.calls.append(("complete", values))
            state["partial_write"] = True
            raise RuntimeError("private partial-write diagnostics")

    repository = _PartialWriteRepository([_Claim()])
    worker, _, _ = _worker(
        repository,
        state=state,
        processor=_Processor(PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD)),
    )
    with pytest.raises(PostAssessmentPersistenceFailure) as captured:
        await worker.run_once()

    assert captured.value.stage is PersistenceStage.FINALIZE
    assert "private partial-write diagnostics" not in str(captured.value)
    assert state["rollbacks"] == 1
    assert state["commits"] == 1  # only the earlier claim transaction committed
    assert state["partial_write"] is False


@pytest.mark.asyncio
async def test_failed_retry_rolls_back_and_raises_fixed_safe_error():
    state = {"active": 0, "partial_write": False}

    class _PartialWriteRepository(_Repository):
        async def retry(self, **values):
            self.calls.append(("retry", values))
            state["partial_write"] = True
            raise RuntimeError("private retry diagnostics")

    repository = _PartialWriteRepository([_Claim()])

    async def transient(_job):
        raise RetryablePostAssessmentError(PostAssessmentErrorCode.UPSTREAM_TIMEOUT)

    worker, _, _ = _worker(
        repository,
        state=state,
        processor=_Processor(callback=transient),
    )
    with pytest.raises(PostAssessmentPersistenceFailure) as captured:
        await worker.run_once()

    assert captured.value.stage is PersistenceStage.RETRY
    assert "private retry diagnostics" not in str(captured.value)
    assert state["rollbacks"] == 1
    assert state["commits"] == 1
    assert state["partial_write"] is False


@pytest.mark.asyncio
async def test_stale_retry_returns_fixed_disposition_after_rollback():
    state = {"active": 0, "partial_write": False}

    class _StaleRetryRepository(_Repository):
        async def retry(self, **values):
            self.calls.append(("retry", values))
            state["partial_write"] = True
            raise _StaleLeaseError("private stale retry detail")

    repository = _StaleRetryRepository([_Claim()])

    async def transient(_job):
        raise RetryablePostAssessmentError(PostAssessmentErrorCode.UPSTREAM_TIMEOUT)

    worker, _, _ = _worker(
        repository, state=state, processor=_Processor(callback=transient)
    )
    result = await worker.run_once()

    assert result is PostAssessmentWorkerResult.STALE_LEASE
    assert state["rollbacks"] == 1 and state["partial_write"] is False
    assert "private stale retry detail" not in repr(repository.calls)


def test_database_error_mapper_dependency_is_explicit_and_required(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def reject_database_layer(name, *args, **kwargs):
        if name.startswith("database_layer"):
            raise ImportError("hidden dependency details")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_database_layer)
    with pytest.raises(RuntimeError, match="database persistence error mapping is unavailable"):
        database_persistence_error_mapper()


@pytest.mark.asyncio
async def test_drain_waits_for_current_job_then_stops_polling():
    repository = _Repository([_Claim()])
    started = asyncio.Event()
    release = asyncio.Event()

    async def process(_job):
        started.set()
        await release.wait()
        return PostAssessmentJobOutcome(PostAssessmentJobStatus.HELD)

    worker, _, _ = _worker(repository, processor=_Processor(callback=process))
    task = worker.start()
    await asyncio.wait_for(started.wait(), timeout=1)
    stopping = asyncio.create_task(worker.stop(drain=True))
    await asyncio.sleep(0)
    assert not stopping.done()
    release.set()
    await asyncio.wait_for(stopping, timeout=1)
    assert task.done()
    assert repository.calls[-1][1]["status"] == "HELD"


@pytest.mark.asyncio
async def test_cancel_shutdown_cancels_processor_and_leaves_lease_for_reclaim():
    repository = _Repository([_Claim()])
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def process(_job):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    worker, _, _ = _worker(repository, processor=_Processor(callback=process))
    task = worker.start()
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.wait_for(worker.stop(drain=False), timeout=1)

    assert task.done() and cancelled.is_set()
    assert not any(name in {"complete", "retry"} for name, _ in repository.calls)
