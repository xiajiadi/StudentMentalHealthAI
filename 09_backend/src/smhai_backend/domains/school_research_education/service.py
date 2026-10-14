"""Fixed-disposition worker for the research education-support outbox.

This lane intentionally has no processor hook: until a separately authorized
research policy exists, a current completed research session is abstained with
``POLICY_UNAVAILABLE``. No answer, CAT snapshot, score, or source payload is
loaded or passed to RAG/LLM/network code.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

RESEARCH_EDUCATION_POLICY_VERSION = "NO_RESEARCH_PERSONALIZED_POLICY_V1"
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class ResearchEducationWorkerResult(StrEnum):
    IDLE = "IDLE"
    ABSTAINED = "ABSTAINED"
    CANCELLED = "CANCELLED"
    RETRY = "RETRY"
    STALE_LEASE = "STALE_LEASE"


class ResearchEducationAuthorizationUnavailable(RuntimeError):
    """Fixed error without database or row contents."""

    def __init__(self) -> None:
        super().__init__("research education authorization is unavailable")


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[object]: ...


class LiveDispositionAdapter(Protocol):
    async def finalize_no_policy(self, claim: Any, *, now: datetime) -> str: ...


class ResearchEducationWorker:
    """One school-scoped poller with short UOWs and lease-based recovery."""

    def __init__(
        self,
        *,
        school_id: int,
        unit_of_work_factory: UnitOfWorkFactory,
        authorization: LiveDispositionAdapter,
        concurrency_lock: asyncio.Lock | None = None,
        worker_id: str = "research-education-worker",
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 60,
        max_attempts: int = 5,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        if type(school_id) is not int or school_id <= 0:
            raise ValueError("school_id must be positive")
        if not callable(unit_of_work_factory):
            raise ValueError("unit_of_work_factory is required")
        if not callable(getattr(authorization, "finalize_no_policy", None)):
            raise ValueError("live authorization adapter is required")
        if type(worker_id) is not str or not _SAFE_IDENTIFIER.fullmatch(worker_id):
            raise ValueError("worker_id must be a bounded identifier")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0.01 <= poll_interval_seconds <= 60
        ):
            raise ValueError("poll interval must be between 0.01 and 60 seconds")
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 5 and 3600")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if not callable(clock):
            raise ValueError("clock must be callable")

        self.school_id = school_id
        self.unit_of_work_factory = unit_of_work_factory
        self.authorization = authorization
        self.worker_id = worker_id
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.clock = clock
        self._stop_event = asyncio.Event()
        self._run_lock = concurrency_lock or asyncio.Lock()
        self._run_task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        """Start the poller once; repeated calls reuse its live task."""
        if self._run_task is not None and not self._run_task.done():
            return self._run_task
        self._stop_event = asyncio.Event()
        self._run_task = asyncio.create_task(self.run(), name=f"{self.worker_id}-poller")
        return self._run_task

    async def stop(self, *, drain: bool = True) -> None:
        """Stop after current short operation, or cancel and recover by lease expiry."""
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
        while not self._stop_event.is_set():
            result = await self.run_once()
            if result in {
                ResearchEducationWorkerResult.IDLE,
                ResearchEducationWorkerResult.RETRY,
                ResearchEducationWorkerResult.STALE_LEASE,
            }:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_seconds
                    )
                except TimeoutError:
                    pass

    async def run_once(self) -> ResearchEducationWorkerResult:
        async with self._run_lock:
            if self._stop_event.is_set():
                return ResearchEducationWorkerResult.IDLE
            try:
                claims = await self._claim_one()
            except Exception:
                # Database messages may carry values. The persisted error is
                # handled only by the repo's allowlisted error enum.
                return ResearchEducationWorkerResult.RETRY
            if not claims:
                return ResearchEducationWorkerResult.IDLE
            claim = claims[0]
            if not _valid_claim(claim) or claim.school_id != self.school_id:
                return ResearchEducationWorkerResult.STALE_LEASE
            if claim.lease_owner != self.worker_id:
                return ResearchEducationWorkerResult.STALE_LEASE
            if (
                claim.policy_version != RESEARCH_EDUCATION_POLICY_VERSION
                or claim.policy_hash is not None
            ):
                return await self._finish_unchecked(claim, status="CANCELLED")
            try:
                status = await self.authorization.finalize_no_policy(claim, now=self._now())
            except ResearchEducationAuthorizationUnavailable:
                return await self._retry_claim(claim)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never log exception text or turn an unknown failure into a
                # successful disposition. Try the bounded repository retry.
                return await self._retry_claim(claim)
            if status == "ABSTAINED":
                return ResearchEducationWorkerResult.ABSTAINED
            if status == "CANCELLED":
                return ResearchEducationWorkerResult.CANCELLED
            return ResearchEducationWorkerResult.STALE_LEASE

    async def _claim_one(self) -> list[Any]:
        async with self.unit_of_work_factory() as uow:
            repository = getattr(uow, "research_education_jobs", None)
            if repository is None:
                raise ResearchEducationAuthorizationUnavailable()
            claims = await repository.claim_next(
                school_id=self.school_id,
                lease_owner=self.worker_id,
                limit=1,
                lease_seconds=self.lease_seconds,
                max_attempts=self.max_attempts,
                now=self._now(),
            )
            return list(claims)

    async def _retry_claim(self, claim: Any) -> ResearchEducationWorkerResult:
        from database_layer.errors import OptimisticConcurrencyConflict
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        try:
            async with self.unit_of_work_factory() as uow:
                repository = getattr(uow, "research_education_jobs", None)
                if repository is None:
                    return ResearchEducationWorkerResult.RETRY
                await repository.retry(
                    school_id=claim.school_id,
                    research_session_id=claim.research_session_id,
                    job_id=claim.id,
                    lease_owner=claim.lease_owner,
                    lease_token=claim.lease_token,
                    error_code=ResearchEducationJobErrorCode.INTERNAL_FAILURE,
                    max_attempts=self.max_attempts,
                    now=self._now(),
                )
                return ResearchEducationWorkerResult.RETRY
        except OptimisticConcurrencyConflict:
            return ResearchEducationWorkerResult.STALE_LEASE
        except Exception:
            return ResearchEducationWorkerResult.RETRY

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return an aware timestamp")
        return value.astimezone(UTC)

    async def _finish_unchecked(self, claim: Any, *, status: str) -> ResearchEducationWorkerResult:
        if not _valid_claim(claim):
            return ResearchEducationWorkerResult.STALE_LEASE
        from database_layer.errors import OptimisticConcurrencyConflict

        try:
            async with self.unit_of_work_factory() as uow:
                repository = getattr(uow, "research_education_jobs", None)
                if repository is None:
                    return ResearchEducationWorkerResult.RETRY
                await repository.finish(
                    school_id=claim.school_id,
                    research_session_id=claim.research_session_id,
                    job_id=claim.id,
                    lease_owner=claim.lease_owner,
                    lease_token=claim.lease_token,
                    status=status,
                    now=self._now(),
                )
                return ResearchEducationWorkerResult.CANCELLED
        except OptimisticConcurrencyConflict:
            return ResearchEducationWorkerResult.STALE_LEASE
        except Exception:
            return ResearchEducationWorkerResult.RETRY


def _valid_claim(claim: Any) -> bool:
    return (
        type(getattr(claim, "school_id", None)) is int
        and claim.school_id > 0
        and all(
            type(getattr(claim, name, None)) is int and getattr(claim, name) > 0
            for name in (
                "id",
                "research_session_id",
                "task_id",
                "class_id",
                "task_enrollment_id",
                "subject_id",
                "task_binding_id",
                "profile_version_id",
                "profile_version_number",
            )
        )
        and type(getattr(claim, "profile_ref", None)) is str
        and type(getattr(claim, "profile_sha256", None)) is str
        and getattr(claim, "response_origin", None) == "PUBLIC_OBSERVED"
        and getattr(claim, "status", None) == "LEASED"
        and type(getattr(claim, "lease_owner", None)) is str
        and type(getattr(claim, "lease_token", None)) is str
        and bool(claim.lease_owner)
        and bool(claim.lease_token)
    )
