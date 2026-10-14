"""Content-free education-support outbox for completed research CAT sessions.

The caller owns the unit of work and all authorization. This repository stores
only exact session scope and a fixed disposition; it never reads snapshots,
decrypts data, contacts a model, or commits a transaction.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import SchoolResearchEducationJob, SchoolResearchSession

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_POLICY_VERSION = "NO_RESEARCH_PERSONALIZED_POLICY_V1"
STAFF_PROGRAMME_POLICY_VERSION = "RESEARCH_STAFF_PROGRAMME_POLICY_V1"
_POLICY_VERSIONS = frozenset({_POLICY_VERSION, STAFF_PROGRAMME_POLICY_VERSION})
_TERMINAL_STATES = frozenset(
    {"HELD", "ABSTAINED", "REVIEW_REQUIRED", "CRISIS_ROUTED", "FAILED", "CANCELLED"}
)


class ResearchEducationJobErrorCode(StrEnum):
    """Allowlisted, content-free error classifications."""

    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    SOURCE_UNQUALIFIED = "SOURCE_UNQUALIFIED"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    UPSTREAM_TRANSIENT = "UPSTREAM_TRANSIENT"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    DEPENDENCY_INVALID_RESPONSE = "DEPENDENCY_INVALID_RESPONSE"
    GENERATION_FAILED = "GENERATION_FAILED"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"
    INTERNAL_FAILURE_AUTHORIZATION = "INTERNAL_FAILURE_AUTHORIZATION"
    INTERNAL_FAILURE_GENERATION = "INTERNAL_FAILURE_GENERATION"
    INTERNAL_FAILURE_OUTCOME_VALIDATION = "INTERNAL_FAILURE_OUTCOME_VALIDATION"
    INTERNAL_FAILURE_CANDIDATE_PROJECTION = "INTERNAL_FAILURE_CANDIDATE_PROJECTION"
    INTERNAL_FAILURE_CANDIDATE_STORE = "INTERNAL_FAILURE_CANDIDATE_STORE"
    INTERNAL_FAILURE_DISPOSITION = "INTERNAL_FAILURE_DISPOSITION"
    INTERNAL_FAILURE_FINALIZATION = "INTERNAL_FAILURE_FINALIZATION"
    LEASE_EXPIRED_MAX_ATTEMPTS = "LEASE_EXPIRED_MAX_ATTEMPTS"
    MAX_ATTEMPTS_EXHAUSTED = "MAX_ATTEMPTS_EXHAUSTED"


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationJobDTO:
    """Internal status receipt; repr intentionally omits scope and pin values."""

    id: int = field(repr=False)
    job_ref: str
    school_id: int = field(repr=False)
    research_session_id: int = field(repr=False)
    task_id: int = field(repr=False)
    class_id: int = field(repr=False)
    task_enrollment_id: int = field(repr=False)
    subject_id: int = field(repr=False)
    task_binding_id: int = field(repr=False)
    profile_version_id: int = field(repr=False)
    profile_ref: str = field(repr=False)
    profile_version_number: int = field(repr=False)
    profile_sha256: str = field(repr=False)
    response_origin: str = field(repr=False)
    policy_version: str
    policy_hash: str | None = field(repr=False)
    purpose: str
    research_only: bool
    publication_status: str
    status: str
    attempt_count: int
    next_attempt_at: datetime | None
    lease_expires_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationJobClaim(ResearchEducationJobDTO):
    """A live worker capability; owner and token are excluded from repr."""

    lease_owner: str = field(repr=False)
    lease_token: str = field(repr=False)


def _require_id(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_token(value: str, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or not value.isascii()
        or _TOKEN.fullmatch(value) is None
    ):
        raise ValueError(f"{name} must be a bounded ASCII token")
    return value


def _optional_hash(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        value = datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None else None


def _dto(job: SchoolResearchEducationJob) -> ResearchEducationJobDTO:
    return ResearchEducationJobDTO(
        id=job.id,
        job_ref=job.job_ref,
        school_id=job.school_id,
        research_session_id=job.research_session_id,
        task_id=job.task_id,
        class_id=job.class_id,
        task_enrollment_id=job.task_enrollment_id,
        subject_id=job.subject_id,
        task_binding_id=job.task_binding_id,
        profile_version_id=job.profile_version_id,
        profile_ref=job.profile_ref,
        profile_version_number=job.profile_version_number,
        profile_sha256=job.profile_sha256,
        response_origin=job.response_origin,
        policy_version=job.policy_version,
        policy_hash=job.policy_hash,
        purpose=job.purpose,
        research_only=job.research_only,
        publication_status=job.publication_status,
        status=job.status,
        attempt_count=job.attempt_count,
        next_attempt_at=_utc_aware(job.next_attempt_at),
        lease_expires_at=_utc_aware(job.lease_expires_at),
        last_error_code=job.last_error_code,
        created_at=_utc_aware(job.created_at),  # type: ignore[arg-type]
        updated_at=_utc_aware(job.updated_at),  # type: ignore[arg-type]
    )


def _claim(job: SchoolResearchEducationJob) -> ResearchEducationJobClaim:
    if job.lease_owner is None or job.lease_token is None:
        raise RuntimeError("claimed research outbox row is missing its lease")
    return ResearchEducationJobClaim(
        **{name: getattr(_dto(job), name) for name in ResearchEducationJobDTO.__dataclass_fields__},
        lease_owner=job.lease_owner,
        lease_token=job.lease_token,
    )


class SchoolResearchEducationJobRepository:
    """Research-session-specific outbox persistence, within caller UoW."""

    JOB_KIND = "EDUCATION_SUPPORT"
    PURPOSE = "RESEARCH_SIMULATION"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue_completed_session(
        self,
        *,
        school_id: int,
        research_session_id: int,
        task_id: int,
        class_id: int,
        task_enrollment_id: int,
        subject_id: int,
        task_binding_id: int,
        profile_version_id: int,
        profile_ref: str,
        profile_version_number: int,
        profile_sha256: str,
        response_origin: str,
        policy_version: str = _POLICY_VERSION,
        policy_hash: str | None = None,
        now: datetime | None = None,
    ) -> ResearchEducationJobDTO:
        """Enqueue/replay only for an exact, persisted completed CAT session."""
        ids = {
            name: _require_id(value, name)
            for name, value in {
                "school_id": school_id,
                "research_session_id": research_session_id,
                "task_id": task_id,
                "class_id": class_id,
                "task_enrollment_id": task_enrollment_id,
                "subject_id": subject_id,
                "task_binding_id": task_binding_id,
                "profile_version_id": profile_version_id,
            }.items()
        }
        profile_ref = _require_token(profile_ref, "profile_ref", 128)
        profile_sha256 = _optional_hash(profile_sha256, "profile_sha256")
        if profile_sha256 is None:
            raise ValueError("profile_sha256 is required")
        policy_hash = _optional_hash(policy_hash, "policy_hash")
        if (
            isinstance(profile_version_number, bool)
            or not isinstance(profile_version_number, int)
            or profile_version_number <= 0
        ):
            raise ValueError("profile_version_number must be positive")
        if type(policy_version) is not str or policy_version not in _POLICY_VERSIONS:
            raise ValueError("policy_version is not enabled for research sessions")
        if policy_version == STAFF_PROGRAMME_POLICY_VERSION and policy_hash is None:
            raise ValueError("staff programme policy requires a pinned policy hash")
        if not isinstance(response_origin, str) or response_origin not in {
            "PUBLIC_OBSERVED",
            "MODEL_GENERATED",
        }:
            raise ValueError("response_origin is not supported")
        if (
            policy_version == STAFF_PROGRAMME_POLICY_VERSION
            and response_origin != "PUBLIC_OBSERVED"
        ):
            raise ValueError("staff programme jobs require public observed sessions")
        _utc_naive(now)  # validate the caller's timestamp even though enqueue stores no clock field
        scope = {
            **ids,
            "profile_ref": profile_ref,
            "profile_version_number": profile_version_number,
            "profile_sha256": profile_sha256,
            "response_origin": response_origin,
        }
        session_row = await self.session.scalar(
            select(SchoolResearchSession)
            .where(
                SchoolResearchSession.id == research_session_id,
                *[
                    getattr(SchoolResearchSession, field) == value
                    for field, value in scope.items()
                    if field != "research_session_id"
                ],
            )
            .with_for_update()
        )
        if session_row is None:
            raise ForeignKeyConflict("completed research-session scope was not found")
        if (
            session_row.status != "COMPLETED"
            or session_row.completed_at is None
            or session_row.purpose != self.PURPOSE
            or session_row.research_only is not True
        ):
            raise OptimisticConcurrencyConflict("research session is not completed")

        lookup = self._key_query(
            school_id=school_id,
            research_session_id=research_session_id,
            policy_version=policy_version,
        )
        existing = await self.session.scalar(lookup.with_for_update())
        if existing is not None:
            self._ensure_replay(existing, scope, policy_version, policy_hash)
            return _dto(existing)

        stable_key = f"{school_id}:{research_session_id}:{self.JOB_KIND}:{policy_version}"
        job = SchoolResearchEducationJob(
            **scope,
            job_ref="REJ_" + hashlib.sha256(stable_key.encode("ascii")).hexdigest(),
            job_kind=self.JOB_KIND,
            purpose=self.PURPOSE,
            research_only=True,
            publication_status="not_approved_for_publication_or_operational_use",
            policy_version=policy_version,
            policy_hash=policy_hash,
            status="QUEUED",
            attempt_count=0,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(job)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(lookup.with_for_update())
            if existing is not None:
                self._ensure_replay(existing, scope, policy_version, policy_hash)
                return _dto(existing)
            raise ForeignKeyConflict("research outbox scope was rejected") from None
        return _dto(job)

    async def claim_next(
        self,
        *,
        school_id: int,
        lease_owner: str,
        limit: int = 1,
        lease_seconds: int = 60,
        max_attempts: int = 5,
        policy_version: str = _POLICY_VERSION,
        now: datetime | None = None,
    ) -> list[ResearchEducationJobClaim]:
        school_id = _require_id(school_id, "school_id")
        lease_owner = _require_token(lease_owner, "lease_owner", 128)
        _bounded_int(limit, "limit", 1, 100)
        _bounded_int(lease_seconds, "lease_seconds", 5, 3600)
        _bounded_int(max_attempts, "max_attempts", 1, 20)
        if type(policy_version) is not str or policy_version not in _POLICY_VERSIONS:
            raise ValueError("policy_version is not enabled for research sessions")
        clock = _utc_naive(now)
        eligible = or_(
            SchoolResearchEducationJob.status == "QUEUED",
            and_(
                SchoolResearchEducationJob.status == "RETRY",
                SchoolResearchEducationJob.next_attempt_at <= clock,
            ),
            and_(
                SchoolResearchEducationJob.status == "LEASED",
                SchoolResearchEducationJob.lease_expires_at <= clock,
            ),
        )
        policy_scope = (
            SchoolResearchEducationJob.response_origin == "PUBLIC_OBSERVED"
            if policy_version == STAFF_PROGRAMME_POLICY_VERSION
            else True
        )
        result = await self.session.scalars(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.school_id == school_id,
                SchoolResearchEducationJob.policy_version == policy_version,
                policy_scope,
                eligible,
            )
            .order_by(SchoolResearchEducationJob.created_at, SchoolResearchEducationJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = list(result.all())
        claims = []
        for job in jobs:
            if job.attempt_count >= max_attempts:
                expired_lease = job.status == "LEASED"
                job.status = "FAILED"
                job.last_error_code = (
                    ResearchEducationJobErrorCode.LEASE_EXPIRED_MAX_ATTEMPTS.value
                    if expired_lease
                    else ResearchEducationJobErrorCode.MAX_ATTEMPTS_EXHAUSTED.value
                )
                self._clear_lease(job)
                job.next_attempt_at = None
                continue
            job.status = "LEASED"
            job.attempt_count += 1
            job.next_attempt_at = None
            job.lease_owner = lease_owner
            job.lease_expires_at = clock + timedelta(seconds=lease_seconds)
            job.lease_token = "lease_" + secrets.token_urlsafe(32)
            claims.append(_claim(job))
        if jobs:
            await self.session.flush()
        return claims

    async def finish(
        self,
        *,
        school_id: int,
        research_session_id: int,
        job_id: int,
        lease_owner: str,
        lease_token: str,
        status: str = "HELD",
        error_code: ResearchEducationJobErrorCode | None = None,
        now: datetime | None = None,
    ) -> ResearchEducationJobDTO:
        if not isinstance(status, str) or status not in _TERMINAL_STATES:
            raise ValueError("status must be an allowed terminal disposition")
        error_code = _require_error_code(error_code)
        if status == "FAILED" and error_code is None:
            raise ValueError("FAILED requires a fixed error code")
        clock = _utc_naive(now)
        job = await self._locked_lease(
            school_id=school_id,
            research_session_id=research_session_id,
            job_id=job_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            clock=clock,
        )
        job.status = status
        job.last_error_code = error_code.value if error_code else None
        job.next_attempt_at = None
        self._clear_lease(job)
        await self.session.flush()
        return _dto(job)

    async def retry(
        self,
        *,
        school_id: int,
        research_session_id: int,
        job_id: int,
        lease_owner: str,
        lease_token: str,
        error_code: ResearchEducationJobErrorCode,
        max_attempts: int = 5,
        base_delay_seconds: int = 5,
        max_delay_seconds: int = 900,
        now: datetime | None = None,
    ) -> ResearchEducationJobDTO:
        error_code = _require_error_code(error_code)
        if error_code is None:
            raise ValueError("retry requires an allowlisted error code")
        _bounded_int(max_attempts, "max_attempts", 1, 20)
        _bounded_int(base_delay_seconds, "base_delay_seconds", 1, 300)
        _bounded_int(max_delay_seconds, "max_delay_seconds", base_delay_seconds, 3600)
        clock = _utc_naive(now)
        job = await self._locked_lease(
            school_id=school_id,
            research_session_id=research_session_id,
            job_id=job_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            clock=clock,
        )
        job.last_error_code = error_code.value
        self._clear_lease(job)
        if job.attempt_count >= max_attempts:
            job.status = "FAILED"
            job.next_attempt_at = None
        else:
            delay = min(base_delay_seconds * (2 ** (job.attempt_count - 1)), max_delay_seconds)
            job.status = "RETRY"
            job.next_attempt_at = clock + timedelta(seconds=delay)
        await self.session.flush()
        return _dto(job)

    async def _locked_lease(
        self,
        *,
        school_id: int,
        research_session_id: int,
        job_id: int,
        lease_owner: str,
        lease_token: str,
        clock: datetime,
    ) -> SchoolResearchEducationJob:
        job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.school_id == _require_id(school_id, "school_id"),
                SchoolResearchEducationJob.research_session_id
                == _require_id(research_session_id, "research_session_id"),
                SchoolResearchEducationJob.id == _require_id(job_id, "job_id"),
                SchoolResearchEducationJob.status == "LEASED",
                SchoolResearchEducationJob.lease_owner
                == _require_token(lease_owner, "lease_owner", 128),
                SchoolResearchEducationJob.lease_token
                == _require_token(lease_token, "lease_token", 128),
                SchoolResearchEducationJob.lease_expires_at > clock,
            )
            .with_for_update()
        )
        if job is None:
            raise OptimisticConcurrencyConflict("research job lease is stale or outside this scope")
        return job

    @staticmethod
    def _key_query(*, school_id: int, research_session_id: int, policy_version: str):
        return select(SchoolResearchEducationJob).where(
            SchoolResearchEducationJob.school_id == school_id,
            SchoolResearchEducationJob.research_session_id == research_session_id,
            SchoolResearchEducationJob.job_kind == SchoolResearchEducationJobRepository.JOB_KIND,
            SchoolResearchEducationJob.policy_version == policy_version,
        )

    @staticmethod
    def _ensure_replay(job, scope, policy_version, policy_hash) -> None:
        if (
            any(getattr(job, name) != value for name, value in scope.items())
            or job.policy_version != policy_version
            or job.policy_hash != policy_hash
            or job.job_kind != SchoolResearchEducationJobRepository.JOB_KIND
            or job.purpose != SchoolResearchEducationJobRepository.PURPOSE
            or job.research_only is not True
            or job.publication_status != "not_approved_for_publication_or_operational_use"
        ):
            raise UniqueConflict("research outbox idempotency key conflicts with scope")

    @staticmethod
    def _clear_lease(job) -> None:
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None


def _bounded_int(value: int, name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _require_error_code(value: ResearchEducationJobErrorCode | None):
    if value is not None and not isinstance(value, ResearchEducationJobErrorCode):
        raise ValueError("error_code must be an allowlisted fixed code")
    return value
