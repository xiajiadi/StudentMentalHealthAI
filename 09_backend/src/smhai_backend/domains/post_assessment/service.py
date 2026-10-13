"""Fail-closed worker for durable post-assessment education-support jobs.

The worker only sees allowlisted job metadata. It never reads assessment
responses, results, report bodies, or credentials. Persistence transactions
are short and complete before processor work begins.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

NO_PERSONALIZED_POLICY_VERSION = "NO_PERSONALIZED_POLICY_V1"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PostAssessmentJobStatus(StrEnum):
    HELD = "HELD"
    ABSTAINED = "ABSTAINED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CRISIS_ROUTED = "CRISIS_ROUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRY = "RETRY"


class PostAssessmentWorkerResult(StrEnum):
    IDLE = "IDLE"
    APPLIED = "APPLIED"
    STALE_LEASE = "STALE_LEASE"


class PersistenceStage(StrEnum):
    CLAIM = "CLAIM"
    HEARTBEAT = "HEARTBEAT"
    RETRY = "RETRY"
    FINALIZE = "FINALIZE"


class PostAssessmentErrorCode(StrEnum):
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    SOURCE_UNQUALIFIED = "SOURCE_UNQUALIFIED"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    UPSTREAM_TRANSIENT = "UPSTREAM_TRANSIENT"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    GENERATION_FAILED = "GENERATION_FAILED"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


@dataclass(frozen=True, slots=True)
class PostAssessmentAuthorizationScope:
    """Identifiers the authorization hook must freshly recheck."""

    school_id: int
    task_id: int
    class_id: int
    class_student_id: int
    task_enrollment_id: int
    subject_id: int
    assessment_session_id: int


@dataclass(frozen=True, slots=True)
class EducationJobInput:
    """Processor projection with no lease capability or assessment content."""

    job_id: int
    job_ref: str
    scope: PostAssessmentAuthorizationScope
    job_kind: str
    policy_version: str
    policy_hash: str | None
    source_snapshot_ref: str | None
    source_snapshot_sha256: str | None
    source_qualification_status: str | None
    source_population: str | None
    source_layer: str | None
    source_rights_status: str | None
    source_review_status: str | None
    source_qualified_at: datetime | None


@dataclass(frozen=True, slots=True)
class PostAssessmentJobOutcome:
    """A fixed terminal disposition or bounded retry request; never a report."""

    status: PostAssessmentJobStatus
    error_code: PostAssessmentErrorCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, PostAssessmentJobStatus):
            raise ValueError("outcome status must be an allowlisted job status")
        if self.error_code is not None and not isinstance(
            self.error_code, PostAssessmentErrorCode
        ):
            raise ValueError("outcome error code must be allowlisted")
        if self.status in {PostAssessmentJobStatus.ABSTAINED, PostAssessmentJobStatus.RETRY}:
            if self.error_code is None:
                raise ValueError("abstention and retry outcomes require a fixed error code")
        if self.status is PostAssessmentJobStatus.FAILED and self.error_code is None:
            raise ValueError("FAILED outcomes require a fixed error code")


class EducationProcessor(Protocol):
    async def process(self, job: EducationJobInput) -> PostAssessmentJobOutcome: ...


class AuthorizationCheck(Protocol):
    async def is_authorized(self, scope: PostAssessmentAuthorizationScope) -> bool: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[object]: ...


class PersistenceErrorMapper(Protocol):
    def to_persistence_error_code(self, error_code: PostAssessmentErrorCode) -> object: ...
    def is_stale_lease_error(self, error: BaseException) -> bool: ...


class PostAssessmentPersistenceFailure(RuntimeError):
    """Fixed public failure without leaking driver or content exception text."""

    def __init__(self, stage: PersistenceStage) -> None:
        self.stage = stage
        super().__init__(f"post-assessment persistence failed during {stage.value.lower()}")


class PostAssessmentAuthorizationFailure(RuntimeError):
    """Fixed failure for an unavailable/invalid live authorization decision."""

    def __init__(self) -> None:
        super().__init__("post-assessment authorization check failed")


@dataclass(frozen=True, slots=True)
class DatabasePersistenceErrorMapper:
    """Explicit bridge to the optional database module's enums and errors."""

    error_code_type: type
    stale_error_type: type[BaseException]

    def to_persistence_error_code(self, error_code: PostAssessmentErrorCode) -> object:
        return self.error_code_type(error_code.value)

    def is_stale_lease_error(self, error: BaseException) -> bool:
        return isinstance(error, self.stale_error_type)


def database_persistence_error_mapper() -> DatabasePersistenceErrorMapper:
    """Load the DB bridge explicitly; missing DB runtime is a startup failure."""
    try:
        from database_layer.errors import OptimisticConcurrencyConflict
        from database_layer.school_post_assessment_jobs import PostAssessmentJobErrorCode
    except ImportError:
        raise RuntimeError("database persistence error mapping is unavailable") from None
    return DatabasePersistenceErrorMapper(
        PostAssessmentJobErrorCode, OptimisticConcurrencyConflict
    )


class RetryablePostAssessmentError(Exception):
    """A known transient failure represented only by a fixed error code."""

    def __init__(self, error_code: PostAssessmentErrorCode) -> None:
        if error_code not in {
            PostAssessmentErrorCode.UPSTREAM_TRANSIENT,
            PostAssessmentErrorCode.UPSTREAM_RATE_LIMITED,
            PostAssessmentErrorCode.UPSTREAM_TIMEOUT,
        }:
            raise ValueError("retryable error code is not transient")
        self.error_code = error_code
        super().__init__(error_code.value)


class _FailClosedProcessor:
    async def process(self, _job: EducationJobInput) -> PostAssessmentJobOutcome:
        return PostAssessmentJobOutcome(
            PostAssessmentJobStatus.ABSTAINED,
            PostAssessmentErrorCode.POLICY_UNAVAILABLE,
        )


class PostAssessmentWorker:
    """Single-concurrency, lease-protected worker for one school tenant.

    The caller supplies the UoW factory and a mandatory live authorization
    hook. Processor work is always outside persistence transactions.
    """

    def __init__(
        self,
        *,
        school_id: int,
        unit_of_work_factory: UnitOfWorkFactory,
        authorization: AuthorizationCheck,
        persistence_errors: PersistenceErrorMapper,
        processor: EducationProcessor | None = None,
        concurrency_lock: asyncio.Lock | None = None,
        worker_id: str = "post-assessment-worker",
        policy_version: str = NO_PERSONALIZED_POLICY_VERSION,
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 60,
        heartbeat_interval_seconds: float | None = None,
        max_attempts: int = 5,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        if type(school_id) is not int or school_id <= 0:
            raise ValueError("school_id must be positive")
        if not callable(unit_of_work_factory):
            raise ValueError("unit_of_work_factory is required")
        if authorization is None or not callable(getattr(authorization, "is_authorized", None)):
            raise ValueError("a live authorization check is required")
        if (
            persistence_errors is None
            or not callable(getattr(persistence_errors, "to_persistence_error_code", None))
            or not callable(getattr(persistence_errors, "is_stale_lease_error", None))
        ):
            raise ValueError("a persistence error mapper is required")
        if (
            type(worker_id) is not str
            or len(worker_id) > 128
            or _SAFE_IDENTIFIER.fullmatch(worker_id) is None
        ):
            raise ValueError("worker_id must be a bounded identifier")
        if (
            type(policy_version) is not str
            or len(policy_version) > 64
            or _SAFE_IDENTIFIER.fullmatch(policy_version) is None
        ):
            raise ValueError("policy_version must be a bounded identifier")
        if (
            not isinstance(poll_interval_seconds, (int, float))
            or not 0.01 <= poll_interval_seconds <= 60
        ):
            raise ValueError("poll interval must be between 0.01 and 60 seconds")
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 5 and 3600")
        heartbeat_interval = (
            heartbeat_interval_seconds
            if heartbeat_interval_seconds is not None
            else lease_seconds / 3
        )
        if (
            not isinstance(heartbeat_interval, (int, float))
            or not 0 < heartbeat_interval < lease_seconds
        ):
            raise ValueError("heartbeat interval must be positive and less than lease duration")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if not callable(clock):
            raise ValueError("clock must be callable")

        self.school_id = school_id
        self.unit_of_work_factory = unit_of_work_factory
        self.authorization = authorization
        self.persistence_errors = persistence_errors
        self.processor = processor or _FailClosedProcessor()
        self._processor_is_default = processor is None
        self.worker_id = worker_id
        self.policy_version = policy_version
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = float(heartbeat_interval)
        self.max_attempts = max_attempts
        self.clock = clock
        self._stop_event = asyncio.Event()
        self._run_lock = concurrency_lock or asyncio.Lock()
        self._run_task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        """Start polling once; concurrent calls reuse the active task."""
        if self._run_task is not None and not self._run_task.done():
            return self._run_task
        self._stop_event = asyncio.Event()
        self._run_task = asyncio.create_task(self.run(), name=f"{self.worker_id}-poller")
        return self._run_task

    async def stop(self, *, drain: bool = True) -> None:
        """Drain the current job, or cancel it and let the lease expire."""
        self._stop_event.set()
        task = self._run_task
        if task is None:
            return
        if not drain and not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            if drain:
                raise

    async def run(self) -> None:
        """Poll until stopped; expired persisted leases are claimed on later polls."""
        while not self._stop_event.is_set():
            result = await self.run_once()
            if result is PostAssessmentWorkerResult.IDLE:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_seconds
                    )
                except TimeoutError:
                    pass

    async def run_once(self) -> PostAssessmentWorkerResult:
        """Claim at most one job and process it with one live lease."""
        async with self._run_lock:
            if self._stop_event.is_set():
                return PostAssessmentWorkerResult.IDLE
            claims = await self._claim_one()
            if not claims:
                return PostAssessmentWorkerResult.IDLE
            claim = claims[0]
            if claim.school_id != self.school_id or claim.job_kind != "EDUCATION_SUPPORT":
                # The repository should already enforce school scope. Do not
                # process a mismatched DTO if an adapter violates that boundary.
                return await self._terminal(claim, PostAssessmentJobStatus.CANCELLED)
            return await self._process_claim(claim)

    async def _claim_one(self):
        try:
            async with self.unit_of_work_factory() as uow:
                repository = getattr(uow, "post_assessment_jobs", None)
                if repository is None:
                    raise RuntimeError("post-assessment job repository is unavailable")
                claims = await repository.claim_ready(
                    school_id=self.school_id,
                    lease_owner=self.worker_id,
                    limit=1,
                    lease_seconds=self.lease_seconds,
                    max_attempts=self.max_attempts,
                    now=self._now(),
                )
                return list(claims)
        except Exception:
            raise PostAssessmentPersistenceFailure(PersistenceStage.CLAIM) from None

    async def _process_claim(self, claim) -> PostAssessmentWorkerResult:
        scope = self._scope(claim)
        if not await self._reauthorized(scope):
            return await self._terminal(claim, PostAssessmentJobStatus.CANCELLED)

        gate = self._qualification_outcome(claim)
        if gate is not None:
            return await self._terminal(claim, gate.status, error_code=gate.error_code)

        processor_job = self._processor_input(claim, scope)
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat_failed = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._renew_lease(claim, heartbeat_stop, lease_lost, heartbeat_failed),
            name=f"{self.worker_id}-lease-heartbeat",
        )
        processor_task = asyncio.create_task(
            self.processor.process(processor_job), name=f"{self.worker_id}-processor"
        )
        lost_task = asyncio.create_task(lease_lost.wait())
        failure_task = asyncio.create_task(heartbeat_failed.wait())
        outcome: PostAssessmentJobOutcome | None = None
        try:
            done, _pending = await asyncio.wait(
                {processor_task, lost_task, failure_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if (lost_task in done and lease_lost.is_set()) or (
                failure_task in done and heartbeat_failed.is_set()
            ):
                processor_task.cancel()
                await self._await_cancel(processor_task)
            else:
                try:
                    outcome = processor_task.result()
                    if not isinstance(outcome, PostAssessmentJobOutcome):
                        raise TypeError("processor returned an invalid outcome")
                except RetryablePostAssessmentError as exc:
                    outcome = PostAssessmentJobOutcome(
                        PostAssessmentJobStatus.RETRY, exc.error_code
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Exception text may contain prompts or source content; only
                    # persist a fixed, non-sensitive classification.
                    outcome = PostAssessmentJobOutcome(
                        PostAssessmentJobStatus.RETRY,
                        PostAssessmentErrorCode.INTERNAL_FAILURE,
                    )
        except asyncio.CancelledError:
            processor_task.cancel()
            await self._await_cancel(processor_task)
            raise
        finally:
            heartbeat_stop.set()
            lost_task.cancel()
            await self._await_cancel(lost_task)
            failure_task.cancel()
            await self._await_cancel(failure_task)
            if not heartbeat.done():
                heartbeat.cancel()
            await self._await_cancel(heartbeat)

        if heartbeat_failed.is_set():
            raise PostAssessmentPersistenceFailure(PersistenceStage.HEARTBEAT) from None
        if lease_lost.is_set():
            return PostAssessmentWorkerResult.STALE_LEASE
        if outcome is None:
            return PostAssessmentWorkerResult.STALE_LEASE
        if not await self._reauthorized(scope):
            outcome = PostAssessmentJobOutcome(PostAssessmentJobStatus.CANCELLED)
        if outcome.status is PostAssessmentJobStatus.RETRY:
            return await self._retry(
                claim, outcome.error_code or PostAssessmentErrorCode.INTERNAL_FAILURE
            )
        return await self._terminal(claim, outcome.status, error_code=outcome.error_code)

    async def _renew_lease(
        self,
        claim,
        stop_event: asyncio.Event,
        lost_event: asyncio.Event,
        persistence_failed_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.heartbeat_interval_seconds
                )
                return
            except TimeoutError:
                pass
            try:
                async with self.unit_of_work_factory() as uow:
                    repository = getattr(uow, "post_assessment_jobs", None)
                    if repository is None:
                        raise RuntimeError("post-assessment job repository is unavailable")
                    await repository.extend_lease(
                        school_id=claim.school_id,
                        subject_id=claim.subject_id,
                        job_id=claim.id,
                        lease_owner=claim.lease_owner,
                        lease_token=claim.lease_token,
                        lease_seconds=self.lease_seconds,
                        now=self._now(),
                    )
            except Exception as exc:
                # Fail closed: cancel processing and let persistence reclaim the
                # lease after expiry rather than completing with uncertain ownership.
                if self._is_stale_lease_error(exc):
                    lost_event.set()
                else:
                    persistence_failed_event.set()
                return

    async def _retry(
        self, claim, error_code: PostAssessmentErrorCode
    ) -> PostAssessmentWorkerResult:
        try:
            async with self.unit_of_work_factory() as uow:
                repository = getattr(uow, "post_assessment_jobs", None)
                if repository is None:
                    raise RuntimeError("post-assessment job repository is unavailable")
                await repository.retry(
                    school_id=claim.school_id,
                    subject_id=claim.subject_id,
                    job_id=claim.id,
                    lease_owner=claim.lease_owner,
                    lease_token=claim.lease_token,
                    error_code=self.persistence_errors.to_persistence_error_code(error_code),
                    max_attempts=self.max_attempts,
                    now=self._now(),
                )
        except Exception as exc:
            if self._is_stale_lease_error(exc):
                return PostAssessmentWorkerResult.STALE_LEASE
            raise PostAssessmentPersistenceFailure(PersistenceStage.RETRY) from None
        return PostAssessmentWorkerResult.APPLIED

    async def _terminal(
        self,
        claim,
        status: PostAssessmentJobStatus,
        *,
        error_code: PostAssessmentErrorCode | None = None,
    ) -> PostAssessmentWorkerResult:
        try:
            async with self.unit_of_work_factory() as uow:
                repository = getattr(uow, "post_assessment_jobs", None)
                if repository is None:
                    raise RuntimeError("post-assessment job repository is unavailable")
                await repository.complete(
                    school_id=claim.school_id,
                    subject_id=claim.subject_id,
                    job_id=claim.id,
                    lease_owner=claim.lease_owner,
                    lease_token=claim.lease_token,
                    status=status.value,
                    error_code=(
                        self.persistence_errors.to_persistence_error_code(error_code)
                        if error_code is not None
                        else None
                    ),
                    now=self._now(),
                )
        except Exception as exc:
            # Classification occurs only after __aexit__ has rolled back the
            # failed UOW. Other failures remain visible as a fixed safe error.
            if self._is_stale_lease_error(exc):
                return PostAssessmentWorkerResult.STALE_LEASE
            raise PostAssessmentPersistenceFailure(PersistenceStage.FINALIZE) from None
        return PostAssessmentWorkerResult.APPLIED

    async def _reauthorized(self, scope: PostAssessmentAuthorizationScope) -> bool:
        try:
            decision = await self.authorization.is_authorized(scope)
        except Exception:
            raise PostAssessmentAuthorizationFailure() from None
        if decision is True:
            return True
        if decision is False:
            return False
        raise PostAssessmentAuthorizationFailure()

    def _is_stale_lease_error(self, error: BaseException) -> bool:
        try:
            return self.persistence_errors.is_stale_lease_error(error) is True
        except Exception:
            return False

    def _qualification_outcome(self, claim) -> PostAssessmentJobOutcome | None:
        if (
            claim.policy_version != self.policy_version
            or claim.policy_version == NO_PERSONALIZED_POLICY_VERSION
            or self._processor_is_default
        ):
            return PostAssessmentJobOutcome(
                PostAssessmentJobStatus.ABSTAINED,
                PostAssessmentErrorCode.POLICY_UNAVAILABLE,
            )
        if (
            claim.job_kind != "EDUCATION_SUPPORT"
            or not claim.source_snapshot_ref
            or not isinstance(claim.policy_hash, str)
            or _SHA256.fullmatch(claim.policy_hash) is None
            or not isinstance(claim.source_snapshot_sha256, str)
            or _SHA256.fullmatch(claim.source_snapshot_sha256) is None
            or claim.source_qualification_status != "QUALIFIED"
            or not claim.source_population
            or not claim.source_layer
            or claim.source_rights_status != "verified"
            or claim.source_review_status != "approved"
            or not isinstance(claim.source_qualified_at, datetime)
            or claim.source_qualified_at.tzinfo is None
            or claim.source_qualified_at.utcoffset() != timedelta(0)
        ):
            return PostAssessmentJobOutcome(
                PostAssessmentJobStatus.ABSTAINED,
                PostAssessmentErrorCode.SOURCE_UNQUALIFIED,
            )
        return None

    @staticmethod
    def _scope(claim) -> PostAssessmentAuthorizationScope:
        return PostAssessmentAuthorizationScope(
            school_id=claim.school_id,
            task_id=claim.task_id,
            class_id=claim.class_id,
            class_student_id=claim.class_student_id,
            task_enrollment_id=claim.task_enrollment_id,
            subject_id=claim.subject_id,
            assessment_session_id=claim.assessment_session_id,
        )

    @staticmethod
    def _processor_input(
        claim, scope: PostAssessmentAuthorizationScope
    ) -> EducationJobInput:
        return EducationJobInput(
            job_id=claim.id,
            job_ref=claim.job_ref,
            scope=scope,
            job_kind=claim.job_kind,
            policy_version=claim.policy_version,
            policy_hash=claim.policy_hash,
            source_snapshot_ref=claim.source_snapshot_ref,
            source_snapshot_sha256=claim.source_snapshot_sha256,
            source_qualification_status=claim.source_qualification_status,
            source_population=claim.source_population,
            source_layer=claim.source_layer,
            source_rights_status=claim.source_rights_status,
            source_review_status=claim.source_review_status,
            source_qualified_at=(
                claim.source_qualified_at.astimezone(UTC)
                if claim.source_qualified_at is not None
                else None
            ),
        )

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return a timezone-aware timestamp")
        return value.astimezone(UTC)

    @staticmethod
    async def _await_cancel(task: asyncio.Task) -> None:
        try:
            await task
        except asyncio.CancelledError:
            pass
