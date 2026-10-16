"""Bounded single-attempt consumer for general-education research jobs."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.research_general_education.input_review_policy import (
    INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
    INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
    ResearchGeneralEducationOutcome,
    ResearchGeneralEducationReviewedInputAuthorization,
)

_SAFE_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_GENERATION_FAILURE_AUDIT_REASON = "WORKER_GENERATION_FAILURE_V1"


class ResearchGeneralEducationWorkerResult(StrEnum):
    IDLE = "IDLE"
    HELD = "HELD"
    ABSTAINED = "ABSTAINED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CRISIS_ROUTED = "CRISIS_ROUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRY = "RETRY"
    STALE_LEASE = "STALE_LEASE"


class ResearchGeneralEducationWorker:
    """Process one exact leased job under the shared local-generation lock."""

    MAX_ATTEMPTS = 1

    def __init__(
        self,
        *,
        school_id: int,
        policy_hash: str,
        persistence,
        persistence_adapter,
        generation_service,
        concurrency_lock: asyncio.Lock,
        worker_id: str,
        input_review_continuation_enabled: bool = False,
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 300,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        if type(school_id) is not int or school_id <= 0:
            raise ValueError("school_id must be positive")
        if type(policy_hash) is not str or _SHA256.fullmatch(policy_hash) is None:
            raise ValueError("general-education policy hash is invalid")
        if not isinstance(concurrency_lock, asyncio.Lock):
            raise TypeError("a shared worker concurrency lock is required")
        if type(input_review_continuation_enabled) is not bool:
            raise ValueError("input-review continuation opt-in must be boolean")
        if not callable(getattr(generation_service, "generate", None)):
            raise ValueError("general-education generation service is required")
        for method in (
            "authorize_education_claim",
            "finalize_education_job",
            "store_generated_candidate",
        ):
            if not callable(getattr(persistence_adapter, method, None)):
                raise ValueError("general-education persistence adapter is incomplete")
        if type(worker_id) is not str or _SAFE_WORKER_ID.fullmatch(worker_id) is None:
            raise ValueError("worker_id must be a bounded identifier")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0.01 <= poll_interval_seconds <= 60
            or type(lease_seconds) is not int
            or not 120 <= lease_seconds <= 3600
            or not callable(clock)
        ):
            raise ValueError("general-education worker bounds are invalid")
        self.school_id = school_id
        self.policy_hash = policy_hash
        self.persistence = persistence
        self.persistence_adapter = persistence_adapter
        adapter_continuation_enabled = (
            getattr(persistence_adapter, "input_review_continuation_enabled", False) is True
        )
        if input_review_continuation_enabled and not adapter_continuation_enabled:
            raise ValueError("input-review continuation adapter is not enabled")
        self.input_review_continuation_enabled = (
            input_review_continuation_enabled and adapter_continuation_enabled
        )
        self.generation_service = generation_service
        self.concurrency_lock = concurrency_lock
        self.worker_id = worker_id
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.lease_seconds = lease_seconds
        self.clock = clock
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        """Start one poller; repeated calls reuse its active task."""
        if self._task is not None and not self._task.done():
            return self._task
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self.run(), name=f"{self.worker_id}-poller")
        return self._task

    async def stop(self, *, drain: bool = True) -> None:
        """Drain the current job, or cancel it and let the one-attempt lease expire."""
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
            try:
                result = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                result = ResearchGeneralEducationWorkerResult.RETRY
            if result in {
                ResearchGeneralEducationWorkerResult.IDLE,
                ResearchGeneralEducationWorkerResult.RETRY,
                ResearchGeneralEducationWorkerResult.STALE_LEASE,
            }:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_seconds
                    )
                except TimeoutError:
                    pass

    async def run_once(self) -> ResearchGeneralEducationWorkerResult:
        async with self.concurrency_lock:
            if self._stop_event.is_set():
                return ResearchGeneralEducationWorkerResult.IDLE
            try:
                claims = await self._claim_one()
            except Exception:
                # Claim failure never starts a generation attempt.
                return ResearchGeneralEducationWorkerResult.RETRY
            if not claims:
                return ResearchGeneralEducationWorkerResult.IDLE
            claim = claims[0]
            if not self._claim_identity_is_live(claim):
                return ResearchGeneralEducationWorkerResult.STALE_LEASE
            if not self._valid_claim(claim):
                return await self._finalize(
                    claim,
                    status="CANCELLED",
                    result=ResearchGeneralEducationWorkerResult.CANCELLED,
                )

            try:
                authorized = await self.persistence_adapter.authorize_education_claim(claim)
            except asyncio.CancelledError:
                raise
            except BackendError as exc:
                if exc.code in {
                    ErrorCode.FORBIDDEN,
                    ErrorCode.RESOURCE_NOT_FOUND,
                    ErrorCode.WORKFLOW_CONFLICT,
                }:
                    return await self._finalize(
                        claim,
                        status="CANCELLED",
                        result=ResearchGeneralEducationWorkerResult.CANCELLED,
                    )
                return await self._finalize(
                    claim,
                    status="REVIEW_REQUIRED",
                    error_code=self._error_codes().INTERNAL_FAILURE_AUTHORIZATION,
                    result=ResearchGeneralEducationWorkerResult.REVIEW_REQUIRED,
                )
            except Exception:
                return await self._finalize(
                    claim,
                    status="REVIEW_REQUIRED",
                    error_code=self._error_codes().INTERNAL_FAILURE_AUTHORIZATION,
                    result=ResearchGeneralEducationWorkerResult.REVIEW_REQUIRED,
                )
            if authorized is not True:
                return await self._finalize(
                    claim,
                    status="CANCELLED",
                    result=ResearchGeneralEducationWorkerResult.CANCELLED,
                )

            generation_round = getattr(claim, "generation_round", 0)
            reviewed_authorization = None
            if type(generation_round) is not int or generation_round not in {0, 1}:
                return await self._finalize(
                    claim,
                    status="CANCELLED",
                    result=ResearchGeneralEducationWorkerResult.CANCELLED,
                )
            if generation_round == 0:
                if getattr(claim, "input_review_id", None) is not None:
                    return await self._finalize(
                        claim,
                        status="CANCELLED",
                        result=ResearchGeneralEducationWorkerResult.CANCELLED,
                    )
            else:
                if not self.input_review_continuation_enabled:
                    return await self._finalize(
                        claim,
                        status="CANCELLED",
                        result=ResearchGeneralEducationWorkerResult.CANCELLED,
                    )
                review_id = getattr(claim, "input_review_id", None)
                loader = getattr(self.persistence_adapter, "load_input_review_authorization", None)
                if type(review_id) is not int or review_id <= 0 or not callable(loader):
                    return await self._finalize(
                        claim,
                        status="CANCELLED",
                        result=ResearchGeneralEducationWorkerResult.CANCELLED,
                    )
                try:
                    reviewed_authorization = await loader(claim)
                except asyncio.CancelledError:
                    raise
                except BackendError as exc:
                    if exc.code in {
                        ErrorCode.FORBIDDEN,
                        ErrorCode.RESOURCE_NOT_FOUND,
                        ErrorCode.WORKFLOW_CONFLICT,
                    }:
                        return await self._finalize(
                            claim,
                            status="CANCELLED",
                            result=ResearchGeneralEducationWorkerResult.CANCELLED,
                        )
                    return await self._finalize(
                        claim,
                        status="FAILED",
                        error_code=self._error_codes().INTERNAL_FAILURE_AUTHORIZATION,
                        result=ResearchGeneralEducationWorkerResult.FAILED,
                    )
                except Exception:
                    return await self._finalize(
                        claim,
                        status="FAILED",
                        error_code=self._error_codes().INTERNAL_FAILURE_AUTHORIZATION,
                        result=ResearchGeneralEducationWorkerResult.FAILED,
                    )
                context = self._context(claim)
                if (
                    type(reviewed_authorization)
                    is not ResearchGeneralEducationReviewedInputAuthorization
                    or reviewed_authorization.continuation_job_ref != claim.job_ref
                    or reviewed_authorization.continuation_trace_id != context.trace_id
                    or reviewed_authorization.continuation_policy_version
                    != INPUT_REVIEW_CONTINUATION_POLICY_VERSION
                    or reviewed_authorization.continuation_policy_hash
                    != INPUT_REVIEW_CONTINUATION_POLICY_SHA256
                    or reviewed_authorization.expires_at.astimezone(UTC) <= self._now()
                    or not callable(
                        getattr(self.generation_service, "generate_reviewed_input", None)
                    )
                ):
                    return await self._finalize(
                        claim,
                        status="CANCELLED",
                        result=ResearchGeneralEducationWorkerResult.CANCELLED,
                    )

            try:
                if generation_round == 0:
                    outcome = await self.generation_service.generate(
                        caller_role="SYSTEM",
                        request_context=self._context(claim),
                    )
                else:
                    outcome = await self.generation_service.generate_reviewed_input(
                        caller_role="SYSTEM",
                        request_context=self._context(claim),
                        authorization=reviewed_authorization,
                    )
            except asyncio.CancelledError:
                # Leave the active lease to expire. max_attempts=1 prevents regeneration.
                raise
            except BackendError as exc:
                return await self._generation_failure(
                    claim, self._upstream_code(exc.code)
                )
            except TimeoutError:
                return await self._generation_failure(
                    claim, self._error_codes().UPSTREAM_TIMEOUT
                )
            except Exception:
                return await self._generation_failure(
                    claim, self._error_codes().INTERNAL_FAILURE_GENERATION
                )

            if type(outcome) is not ResearchGeneralEducationOutcome:
                return await self._generation_failure(
                    claim, self._error_codes().INTERNAL_FAILURE_OUTCOME_VALIDATION
                )
            if outcome.status == "HELD":
                if type(outcome.candidate) is not ResearchGeneralEducationCandidatePayload:
                    return await self._generation_failure(
                        claim, self._error_codes().INTERNAL_FAILURE_OUTCOME_VALIDATION
                    )
                try:
                    store_kwargs = {"trace_id": self._context(claim).trace_id}
                    if reviewed_authorization is not None:
                        store_kwargs["input_review"] = reviewed_authorization
                    stored = await self.persistence_adapter.store_generated_candidate(
                        claim, outcome.candidate, **store_kwargs
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return await self._generation_failure(
                        claim, self._error_codes().INTERNAL_FAILURE_CANDIDATE_STORE
                    )
                if not self._held_receipt_is_valid(stored):
                    return await self._generation_failure(
                        claim, self._error_codes().INTERNAL_FAILURE_CANDIDATE_STORE
                    )
                return ResearchGeneralEducationWorkerResult.HELD

            status, code, result = self._disposition(outcome)
            return await self._finalize(
                claim,
                status=status,
                error_code=code,
                reason_code=outcome.reason_code,
                private_output_safety_failure=outcome.private_output_safety_failure,
                boundary_diagnostic=outcome.boundary_diagnostic,
                output_safety_diagnostic=outcome.output_safety_diagnostic,
                output_review_payload=outcome.output_review_payload,
                result=result,
                input_review=outcome.input_review,
            )

    async def _claim_one(self) -> list[Any]:
        from database_layer.school_research_education_jobs import (
            GENERAL_EDUCATION_POLICY_VERSION,
        )

        now = self._now()
        async with self.persistence._uow() as uow:
            claim_kwargs = dict(
                school_id=self.school_id,
                lease_owner=self.worker_id,
                limit=1,
                lease_seconds=self.lease_seconds,
                max_attempts=self.MAX_ATTEMPTS,
                policy_version=GENERAL_EDUCATION_POLICY_VERSION,
                now=now,
            )
            if self.input_review_continuation_enabled:
                reviewed_claims = await uow.research_education_jobs.claim_next(
                    **claim_kwargs,
                    generation_round=1,
                )
                if reviewed_claims:
                    return list(reviewed_claims)
            ordinary_claims = await uow.research_education_jobs.claim_next(
                **claim_kwargs,
                generation_round=0,
            )
            return list(ordinary_claims)

    def _valid_claim(self, claim: Any) -> bool:
        from database_layer.school_research_education_jobs import (
            GENERAL_EDUCATION_POLICY_VERSION,
        )

        return (
            self._claim_identity_is_live(claim)
            and claim.policy_version == GENERAL_EDUCATION_POLICY_VERSION
            and claim.policy_hash == self.policy_hash
            and claim.response_origin == "PUBLIC_OBSERVED"
            and claim.purpose == "RESEARCH_SIMULATION"
            and claim.research_only is True
            and claim.publication_status == _PUBLICATION_STATUS
            and claim.attempt_count == self.MAX_ATTEMPTS
        )

    def _claim_identity_is_live(self, claim: Any) -> bool:
        from database_layer.school_research_education_jobs import ResearchEducationJobClaim

        if type(claim) is not ResearchEducationJobClaim:
            return False
        positive_ids = (
            "id",
            "school_id",
            "research_session_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "task_binding_id",
            "profile_version_id",
            "profile_version_number",
        )
        return (
            all(type(getattr(claim, name, None)) is int and getattr(claim, name) > 0
                for name in positive_ids)
            and type(claim.job_ref) is str
            and _SAFE_WORKER_ID.fullmatch(claim.job_ref) is not None
            and type(claim.lease_owner) is str
            and claim.lease_owner == self.worker_id
            and type(claim.lease_token) is str
            and bool(claim.lease_token)
            and claim.status == "LEASED"
            and claim.school_id == self.school_id
        )

    async def _generation_failure(self, claim, error_code):
        return await self._finalize(
            claim,
            status="FAILED",
            error_code=error_code,
            reason_code=_GENERATION_FAILURE_AUDIT_REASON,
            result=ResearchGeneralEducationWorkerResult.FAILED,
        )

    async def _finalize(
        self,
        claim,
        *,
        status: str,
        result: ResearchGeneralEducationWorkerResult,
        error_code=None,
        input_review=None,
        reason_code=None,
        boundary_diagnostic=None,
        output_safety_diagnostic=None,
        output_review_payload=None,
        private_output_safety_failure=None,
    ) -> ResearchGeneralEducationWorkerResult:
        try:
            review_kwargs = {} if input_review is None else {"input_review": input_review}
            reason_kwargs = {} if reason_code is None else {"reason_code": reason_code}
            private_output_failure_kwargs = (
                {}
                if private_output_safety_failure is None
                else {"private_output_safety_failure": private_output_safety_failure}
            )
            boundary_kwargs = (
                {}
                if boundary_diagnostic is None
                else {"boundary_diagnostic": boundary_diagnostic}
            )
            output_safety_kwargs = (
                {}
                if output_safety_diagnostic is None
                else {"output_safety_diagnostic": output_safety_diagnostic}
            )
            output_review_kwargs = (
                {}
                if output_review_payload is None
                else {"output_review_payload": output_review_payload}
            )
            persisted = await self.persistence_adapter.finalize_education_job(
                claim,
                status=status,
                error_code=error_code,
                **review_kwargs,
                **reason_kwargs,
                **private_output_failure_kwargs,
                **boundary_kwargs,
                **output_safety_kwargs,
                **output_review_kwargs,
            )
        except BackendError as exc:
            if exc.code in {
                ErrorCode.FORBIDDEN,
                ErrorCode.RESOURCE_NOT_FOUND,
                ErrorCode.WORKFLOW_CONFLICT,
            }:
                return ResearchGeneralEducationWorkerResult.STALE_LEASE
            return ResearchGeneralEducationWorkerResult.RETRY
        except Exception:
            return ResearchGeneralEducationWorkerResult.RETRY
        if persisted == "CANCELLED":
            return ResearchGeneralEducationWorkerResult.CANCELLED
        if persisted == status:
            return result
        return ResearchGeneralEducationWorkerResult.STALE_LEASE

    @staticmethod
    def _held_receipt_is_valid(receipt: object) -> bool:
        return (
            isinstance(receipt, dict)
            and isinstance(receipt.get("candidate_ref"), str)
            and receipt.get("status") == "HELD"
            and receipt.get("state_version") == 1
            and receipt.get("purpose") == "RESEARCH_SIMULATION"
            and receipt.get("research_only") is True
            and receipt.get("psychological_interpretation_allowed") is False
            and receipt.get("publication_status") == _PUBLICATION_STATUS
            and receipt.get("student_feedback_eligible") is False
        )

    @staticmethod
    def _disposition(outcome):
        codes = ResearchGeneralEducationWorker._error_codes()
        reason = outcome.reason_code
        if outcome.status == "CRISIS_ROUTED":
            return (
                "CRISIS_ROUTED",
                codes.SAFETY_BLOCKED,
                ResearchGeneralEducationWorkerResult.CRISIS_ROUTED,
            )
        if outcome.status == "REVIEW_REQUIRED":
            code = (
                codes.SAFETY_BLOCKED
                if "SAFETY" in reason or "CRISIS" in reason
                else codes.SOURCE_UNQUALIFIED
                if "SOURCE" in reason or "EVIDENCE" in reason or "CITATION" in reason
                else codes.GENERATION_FAILED
            )
            return "REVIEW_REQUIRED", code, ResearchGeneralEducationWorkerResult.REVIEW_REQUIRED
        if outcome.status == "ABSTAINED":
            code = (
                codes.SOURCE_UNQUALIFIED
                if "SOURCE" in reason or "EVIDENCE" in reason or "CITATION" in reason
                else codes.SAFETY_BLOCKED
                if "SAFETY" in reason or "CRISIS" in reason
                else codes.GENERATION_FAILED
            )
            return "ABSTAINED", code, ResearchGeneralEducationWorkerResult.ABSTAINED
        if outcome.status == "FAILED":
            code = (
                codes.UPSTREAM_TIMEOUT
                if "TIMEOUT" in reason
                else codes.UPSTREAM_TRANSIENT
                if "UNAVAILABLE" in reason
                else codes.GENERATION_FAILED
            )
            return "FAILED", code, ResearchGeneralEducationWorkerResult.FAILED
        return (
            "FAILED",
            codes.INTERNAL_FAILURE_OUTCOME_VALIDATION,
            ResearchGeneralEducationWorkerResult.FAILED,
        )

    @staticmethod
    def _upstream_code(code):
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        if code is ErrorCode.DEPENDENCY_TIMEOUT:
            return ResearchEducationJobErrorCode.UPSTREAM_TIMEOUT
        if code is ErrorCode.RATE_LIMITED:
            return ResearchEducationJobErrorCode.UPSTREAM_RATE_LIMITED
        if code is ErrorCode.DEPENDENCY_UNAVAILABLE:
            return ResearchEducationJobErrorCode.UPSTREAM_TRANSIENT
        return ResearchEducationJobErrorCode.GENERATION_FAILED

    @staticmethod
    def _error_codes():
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        return ResearchEducationJobErrorCode

    def _context(self, claim) -> RequestContext:
        token = hashlib.sha256(
            f"{claim.job_ref}:{claim.attempt_count}".encode("ascii")
        ).hexdigest()[:32]
        return RequestContext(f"REQ_{token}", f"TRACE_{token}")

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return an aware timestamp")
        return value.astimezone(UTC)
