"""Bounded consumer for the explicitly enabled staff programme queue."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.research_programme_generation.schemas import (
    STUDY_REF as SOURCE_STUDY_REF,
)
from smhai_backend.domains.research_programme_generation.schemas import (
    ResearchProgrammeOutcome,
)
from smhai_backend.domains.school_research_programme_candidates.schemas import (
    GeneratedProgrammeCandidate,
    ProgrammeCandidateContent,
    ProgrammeCandidateJobLease,
    ProgrammeCitation,
    ProgrammeTaskScope,
)

_LOGGER = logging.getLogger(__name__)
_STAFF_POLICY = "RESEARCH_STAFF_PROGRAMME_POLICY_V1"


class ResearchProgrammeWorkerResult(StrEnum):
    IDLE = "IDLE"
    HELD = "HELD"
    ABSTAINED = "ABSTAINED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CANCELLED = "CANCELLED"
    RETRY = "RETRY"
    STALE_LEASE = "STALE_LEASE"


class ResearchProgrammeWorker:
    """Claims only staff-programme jobs and never sends session data upstream."""

    def __init__(
        self,
        *,
        school_id: int,
        persistence,
        persistence_adapter,
        generation_service,
        concurrency_lock: asyncio.Lock,
        worker_id: str,
        processor_policy_sha256: str,
        study_policy_sha256: str,
        school_study_ref: str,
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 60,
        max_attempts: int = 5,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        if type(school_id) is not int or school_id <= 0:
            raise ValueError("school_id must be positive")
        if not isinstance(concurrency_lock, asyncio.Lock):
            raise TypeError("a shared worker concurrency lock is required")
        if not callable(getattr(generation_service, "generate", None)):
            raise ValueError("staff programme generation service is required")
        if not callable(getattr(persistence_adapter, "store_generated_candidate", None)):
            raise ValueError("staff programme persistence adapter is required")
        if not callable(getattr(persistence_adapter, "authorize_programme_claim", None)):
            raise ValueError("staff programme scope authorization is required")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0.01 <= poll_interval_seconds <= 60
            or type(lease_seconds) is not int
            or not 5 <= lease_seconds <= 3600
            or type(max_attempts) is not int
            or not 1 <= max_attempts <= 20
        ):
            raise ValueError("staff programme worker bounds are invalid")
        if type(processor_policy_sha256) is not str or len(processor_policy_sha256) != 64:
            raise ValueError("staff programme processor pin is invalid")
        if type(study_policy_sha256) is not str or len(study_policy_sha256) != 64:
            raise ValueError("staff programme study pin is invalid")
        if type(school_study_ref) is not str or not school_study_ref or len(school_study_ref) > 128:
            raise ValueError("staff programme school study reference is invalid")
        self.school_id = school_id
        self.persistence = persistence
        self.persistence_adapter = persistence_adapter
        self.generation_service = generation_service
        self.concurrency_lock = concurrency_lock
        self.worker_id = worker_id
        self.processor_policy_sha256 = processor_policy_sha256
        self.study_policy_sha256 = study_policy_sha256
        self.school_study_ref = school_study_ref
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.clock = clock
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self.run(), name=f"{self.worker_id}-poller")
        return self._task

    async def stop(self, *, drain: bool = True) -> None:
        self._stop_event.set()
        task = self._task
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
        while not self._stop_event.is_set():
            result = await self.run_once()
            if result in {
                ResearchProgrammeWorkerResult.IDLE,
                ResearchProgrammeWorkerResult.RETRY,
                ResearchProgrammeWorkerResult.STALE_LEASE,
            }:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_seconds
                    )
                except TimeoutError:
                    pass

    async def run_once(self) -> ResearchProgrammeWorkerResult:
        async with self.concurrency_lock:
            if self._stop_event.is_set():
                return ResearchProgrammeWorkerResult.IDLE
            try:
                claims = await self._claim_one()
            except Exception:
                return ResearchProgrammeWorkerResult.RETRY
            if not claims:
                return ResearchProgrammeWorkerResult.IDLE
            claim = claims[0]
            if not self._valid_claim(claim):
                if (
                    getattr(claim, "school_id", None) == self.school_id
                    and getattr(claim, "policy_version", None) == _STAFF_POLICY
                ):
                    try:
                        result = await self.persistence_adapter.finalize_programme_job(
                            claim, status="ABSTAINED"
                        )
                        if result == "CANCELLED":
                            return ResearchProgrammeWorkerResult.CANCELLED
                    except Exception:
                        return ResearchProgrammeWorkerResult.RETRY
                return ResearchProgrammeWorkerResult.STALE_LEASE
            try:
                if not await self.persistence_adapter.authorize_programme_claim(claim):
                    result = await self.persistence_adapter.finalize_programme_job(
                        claim, status="ABSTAINED"
                    )
                    return (
                        ResearchProgrammeWorkerResult.CANCELLED
                        if result == "CANCELLED"
                        else ResearchProgrammeWorkerResult.STALE_LEASE
                    )
                outcome = await self.generation_service.generate(
                    actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
                    request_context=self._context(claim),
                )
                if type(outcome) is not ResearchProgrammeOutcome:
                    raise ValueError("research generation result is invalid")
                if outcome.status == "HELD":
                    generated = self._generated_candidate(claim, outcome)
                    await self.persistence_adapter.store_generated_candidate(generated)
                    return ResearchProgrammeWorkerResult.HELD
                status, code = self._disposition(outcome)
                result = await self.persistence_adapter.finalize_programme_job(
                    claim, status=status, error_code=code
                )
                return (
                    ResearchProgrammeWorkerResult.CANCELLED
                    if result == "CANCELLED"
                    else ResearchProgrammeWorkerResult.ABSTAINED
                )
            except asyncio.CancelledError:
                raise
            except BackendError as exc:
                if exc.code in {
                    ErrorCode.FORBIDDEN,
                    ErrorCode.RESOURCE_NOT_FOUND,
                    ErrorCode.WORKFLOW_CONFLICT,
                }:
                    try:
                        result = await self.persistence_adapter.finalize_programme_job(
                            claim, status="ABSTAINED"
                        )
                        return (
                            ResearchProgrammeWorkerResult.CANCELLED
                            if result == "CANCELLED"
                            else ResearchProgrammeWorkerResult.STALE_LEASE
                        )
                    except Exception:
                        return ResearchProgrammeWorkerResult.RETRY
                if exc.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE:
                    try:
                        from database_layer.school_research_education_jobs import (
                            ResearchEducationJobErrorCode,
                        )

                        result = await self.persistence_adapter.finalize_programme_job(
                            claim,
                            status="REVIEW_REQUIRED",
                            error_code=ResearchEducationJobErrorCode.DEPENDENCY_INVALID_RESPONSE,
                        )
                        return (
                            ResearchProgrammeWorkerResult.CANCELLED
                            if result == "CANCELLED"
                            else ResearchProgrammeWorkerResult.REVIEW_REQUIRED
                            if result == "REVIEW_REQUIRED"
                            else ResearchProgrammeWorkerResult.STALE_LEASE
                        )
                    except Exception:
                        return ResearchProgrammeWorkerResult.RETRY
                return await self._retry(claim, self._upstream_code(exc.code))
            except Exception:
                return await self._retry(claim)

    async def _claim_one(self):
        from database_layer.school_research_education_jobs import STAFF_PROGRAMME_POLICY_VERSION

        async with self.persistence._uow() as uow:
            return list(
                await uow.research_education_jobs.claim_next(
                    school_id=self.school_id,
                    lease_owner=self.worker_id,
                    limit=1,
                    lease_seconds=self.lease_seconds,
                    max_attempts=self.max_attempts,
                    policy_version=STAFF_PROGRAMME_POLICY_VERSION,
                    now=self._now(),
                )
            )

    async def _retry(self, claim, code=None) -> ResearchProgrammeWorkerResult:
        from database_layer.school_research_education_jobs import ResearchEducationJobErrorCode

        try:
            await self.persistence_adapter.retry_programme_job(
                claim,
                error_code=code or ResearchEducationJobErrorCode.INTERNAL_FAILURE,
            )
            return ResearchProgrammeWorkerResult.RETRY
        except BackendError as exc:
            if exc.code is ErrorCode.WORKFLOW_CONFLICT:
                return ResearchProgrammeWorkerResult.STALE_LEASE
            return ResearchProgrammeWorkerResult.RETRY
        except Exception:
            return ResearchProgrammeWorkerResult.RETRY

    def _valid_claim(self, claim: Any) -> bool:
        return (
            getattr(claim, "school_id", None) == self.school_id
            and type(getattr(claim, "research_session_id", None)) is int
            and type(getattr(claim, "task_id", None)) is int
            and type(getattr(claim, "class_id", None)) is int
            and type(getattr(claim, "task_enrollment_id", None)) is int
            and type(getattr(claim, "subject_id", None)) is int
            and type(getattr(claim, "task_binding_id", None)) is int
            and type(getattr(claim, "profile_version_id", None)) is int
            and getattr(claim, "response_origin", None) == "PUBLIC_OBSERVED"
            and getattr(claim, "policy_version", None) == _STAFF_POLICY
            and getattr(claim, "policy_hash", None) == self.processor_policy_sha256
            and bool(getattr(claim, "lease_owner", None))
            and bool(getattr(claim, "lease_token", None))
        )

    def _context(self, claim) -> RequestContext:
        token = hashlib.sha256(
            f"{claim.job_ref}:{claim.attempt_count}".encode("ascii")
        ).hexdigest()[:32]
        return RequestContext(f"REQ_{token}", f"TRACE_{token}")

    @staticmethod
    def _citation_locator(source) -> str:
        # Preserve license and attribution in the existing encrypted citation payload.
        value = (
            f"{source.locator}; {source.license}; {source.license_url}; "
            f"{source.attribution}"
        )
        if len(value) > 500:
            raise ValueError("research citation rights metadata exceeds storage limit")
        return value

    def _generated_candidate(self, claim, outcome: ResearchProgrammeOutcome):
        candidate = outcome.candidate
        if candidate is None or outcome.status != "HELD":
            raise ValueError("held research candidate is missing")
        if candidate.study_ref != SOURCE_STUDY_REF:
            raise ValueError("research source study reference is invalid")
        citations = [
            ProgrammeCitation(
                citation_id=f"S{index}",
                source_title=source.title,
                source_organization=source.publisher,
                source_url=source.source_url,
                source_locator=self._citation_locator(source),
            )
            for index, source in enumerate(candidate.citations, start=1)
        ]
        return GeneratedProgrammeCandidate(
            job=ProgrammeCandidateJobLease(
                job_id=claim.id,
                school_id=claim.school_id,
                research_session_id=claim.research_session_id,
                lease_owner=claim.lease_owner,
                lease_token=claim.lease_token,
                policy_version=claim.policy_version,
                policy_hash=claim.policy_hash,
            ),
            trace_id=candidate.trace_id,
            task_scope=ProgrammeTaskScope(
                school_id=claim.school_id,
                task_id=claim.task_id,
                class_id=claim.class_id,
                task_binding_id=claim.task_binding_id,
                profile_version_id=claim.profile_version_id,
                profile_ref=claim.profile_ref,
                profile_version_number=claim.profile_version_number,
                profile_sha256=claim.profile_sha256,
                response_origin=claim.response_origin,
            ),
            study_ref=self.school_study_ref,
            source_study_ref=candidate.study_ref,
            study_policy_sha256=self.study_policy_sha256,
            processor_policy_sha256=claim.policy_hash,
            programme_ref=candidate.programme_ref,
            source_manifest_sha256=candidate.source_manifest_sha256,
            source_set_sha256=candidate.source_set_sha256,
            retrieval_id=candidate.retrieval_id,
            retrieval_bundle_sha256=candidate.retrieval_bundle_sha256,
            chunk_set_sha256=candidate.chunk_set_sha256,
            prompt_ref=candidate.prompt_id,
            prompt_version=candidate.prompt_version,
            prompt_sha256=candidate.prompt_sha256,
            model_ref=candidate.model_id,
            model_digest_sha256=candidate.model_digest,
            runtime_version=candidate.runtime_version,
            safety_policy_version=candidate.safety_version,
            input_safety_action=candidate.safety_evidence[0].action,
            retrieval_safety_action=candidate.safety_evidence[1].action,
            output_safety_action=candidate.safety_evidence[2].action,
            claim_boundary_version=candidate.claim_boundary_version,
            claim_boundary_status="ACCEPTED",
            output_boundary="STAFF_REFERENCE_ONLY",
            content=ProgrammeCandidateContent(
                programme_ref=candidate.programme_ref,
                title=candidate.title,
                body=candidate.body,
                citations=citations,
            ),
        )

    @staticmethod
    def _disposition(outcome):
        from database_layer.school_research_education_jobs import ResearchEducationJobErrorCode

        if outcome.status == "HALTED":
            if outcome.safety_action == "CRISIS_ROUTE":
                return "CRISIS_ROUTED", ResearchEducationJobErrorCode.SAFETY_BLOCKED
            return "REVIEW_REQUIRED", ResearchEducationJobErrorCode.SAFETY_BLOCKED
        code = (
            ResearchEducationJobErrorCode.SOURCE_UNQUALIFIED
            if "EVIDENCE" in outcome.reason_code or "SOURCE" in outcome.reason_code
            else ResearchEducationJobErrorCode.GENERATION_FAILED
        )
        return "ABSTAINED", code

    @staticmethod
    def _upstream_code(code):
        from database_layer.school_research_education_jobs import ResearchEducationJobErrorCode

        if code is ErrorCode.DEPENDENCY_TIMEOUT:
            return ResearchEducationJobErrorCode.UPSTREAM_TIMEOUT
        if code is ErrorCode.RATE_LIMITED:
            return ResearchEducationJobErrorCode.UPSTREAM_RATE_LIMITED
        if code is ErrorCode.DEPENDENCY_UNAVAILABLE:
            return ResearchEducationJobErrorCode.UPSTREAM_TRANSIENT
        return ResearchEducationJobErrorCode.GENERATION_FAILED

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return aware UTC")
        return value.astimezone(UTC)


class ResearchProgrammeWorkerManager:
    """Create one current-school poller per active synthetic school."""

    def __init__(
        self,
        *,
        persistence,
        persistence_adapter,
        generation_service,
        settings,
        concurrency_lock: asyncio.Lock,
        study_policy_sha256: str,
        school_study_ref: str,
        processor_policy_sha256: str,
    ) -> None:
        if not isinstance(concurrency_lock, asyncio.Lock):
            raise TypeError("a shared worker concurrency lock is required")
        self.persistence = persistence
        self.persistence_adapter = persistence_adapter
        self.generation_service = generation_service
        self.settings = settings
        self.concurrency_lock = concurrency_lock
        self.study_policy_sha256 = study_policy_sha256
        self.school_study_ref = school_study_ref
        self.processor_policy_sha256 = processor_policy_sha256
        self.workers: dict[int, ResearchProgrammeWorker] = {}
        self.health: dict[int, str] = {}
        self._started = False
        self._closing = False
        self._closed = False

    async def start(self) -> None:
        if self._closing or self._closed:
            raise RuntimeError("staff programme worker manager cannot restart")
        if self._started:
            return
        if (
            getattr(self.persistence, "identity_profile", None) != "school_tenant"
            or not getattr(self.persistence, "_started", False)
            or getattr(self.settings, "enabled", False) is not True
        ):
            raise RuntimeError(
                "staff programme worker requires enabled school research persistence"
            )
        study_school_id = getattr(
            self.persistence_adapter.study_use_policy, "school_id", None
        )
        if type(study_school_id) is not int or study_school_id <= 0:
            raise RuntimeError("staff programme worker requires a pinned study school")
        study_policy = self.persistence_adapter.study_use_policy
        if (
            study_policy.source_rights_verified is not True
            or study_policy.study_ref != self.school_study_ref
        ):
            raise RuntimeError("staff programme school/source study pins are unavailable")
        m = self.persistence._db_models
        async with self.persistence._uow() as uow:
            school_ids = list(
                (
                    await uow.session.scalars(
                        self.persistence._select(m.School.id)
                        .where(
                            m.School.id == study_school_id,
                            m.School.status == "ACTIVE",
                            m.School.data_origin == "SYNTHETIC",
                        )
                        .order_by(m.School.id)
                    )
                ).all()
            )
        if school_ids != [study_school_id]:
            raise RuntimeError("staff programme study school is unavailable")
        try:
            for school_id in school_ids:
                worker = ResearchProgrammeWorker(
                    school_id=int(school_id),
                    persistence=self.persistence,
                    persistence_adapter=self.persistence_adapter,
                    generation_service=self.generation_service,
                    concurrency_lock=self.concurrency_lock,
                    worker_id=f"staff-programme-{school_id}",
                    processor_policy_sha256=self.processor_policy_sha256,
                    study_policy_sha256=self.study_policy_sha256,
                    school_study_ref=self.school_study_ref,
                    poll_interval_seconds=self.settings.poll_interval_seconds,
                    lease_seconds=self.settings.lease_seconds,
                    max_attempts=self.settings.max_attempts,
                    clock=lambda: self.persistence._utc_now().replace(tzinfo=UTC),
                )
                self.workers[int(school_id)] = worker
                self.health[int(school_id)] = "RUNNING"
                worker.start().add_done_callback(
                    lambda task, sid=int(school_id): self._finished(sid, task)
                )
        except Exception:
            await self.close()
            raise
        self._started = True

    def _finished(self, school_id: int, task: asyncio.Task[Any]) -> None:
        if self._closing and task.cancelled():
            self.health[school_id] = "STOPPED"
            return
        try:
            failed = task.cancelled() or task.exception() is not None
        except asyncio.CancelledError:
            failed = not self._closing
        self.health[school_id] = "UNAVAILABLE" if failed or not self._closing else "STOPPED"
        if failed:
            _LOGGER.error(
                "staff programme worker stopped",
                extra={"school_id": school_id, "failure_code": "UNEXPECTED_WORKER_STOP"},
            )

    def dependency_status(self) -> dict[str, str]:
        if not self._started:
            return {"status": "STARTING", "integration": "RESEARCH_STAFF_PROGRAMME_OUTBOX"}
        failed = any(status == "UNAVAILABLE" for status in self.health.values())
        return {
            "status": "UNAVAILABLE" if failed else "READY",
            "integration": "RESEARCH_STAFF_PROGRAMME_OUTBOX",
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        stops = [asyncio.create_task(worker.stop(drain=True)) for worker in self.workers.values()]
        if stops:
            drain_seconds = float(self.settings.shutdown_drain_seconds)
            _done, pending = await asyncio.wait(stops, timeout=drain_seconds)
            if pending:
                for worker in self.workers.values():
                    if worker._task is not None and not worker._task.done():
                        worker._task.cancel()
                _done, pending = await asyncio.wait(pending, timeout=2.0)
                if pending:
                    raise RuntimeError("staff programme workers did not stop")
        for school_id, state in self.health.items():
            if state == "RUNNING":
                self.health[school_id] = "STOPPED"
        self._started = False
        self._closed = True
