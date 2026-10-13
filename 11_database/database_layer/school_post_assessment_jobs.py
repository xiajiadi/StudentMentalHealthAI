"""Scoped persistence operations for the content-free education-support outbox.

This repository participates in the caller's transaction. It never commits,
rolls back, or returns SQLAlchemy ORM instances to application callers.
Authorization remains the responsibility of the service that owns the UoW.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, NotFound, OptimisticConcurrencyConflict, UniqueConflict
from .models import SchoolPostAssessmentJob

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATES = frozenset(
    {"HELD", "ABSTAINED", "REVIEW_REQUIRED", "CRISIS_ROUTED", "FAILED", "CANCELLED"}
)


class PostAssessmentJobErrorCode(StrEnum):
    """Fixed, content-free failure classifications; never store exception text."""

    LEASE_EXPIRED_MAX_ATTEMPTS = "LEASE_EXPIRED_MAX_ATTEMPTS"
    MAX_ATTEMPTS_EXHAUSTED = "MAX_ATTEMPTS_EXHAUSTED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    SOURCE_UNQUALIFIED = "SOURCE_UNQUALIFIED"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    UPSTREAM_TRANSIENT = "UPSTREAM_TRANSIENT"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    GENERATION_FAILED = "GENERATION_FAILED"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


@dataclass(frozen=True, slots=True)
class PostAssessmentJobDTO:
    """Allowlisted non-secret projection for scoped status reads."""

    id: int
    job_ref: str
    school_id: int
    task_id: int
    class_id: int
    class_student_id: int
    task_enrollment_id: int
    subject_id: int
    assessment_session_id: int
    job_kind: str
    policy_version: str
    policy_hash: str | None
    status: str
    attempt_count: int
    next_attempt_at: datetime | None
    lease_expires_at: datetime | None
    source_snapshot_ref: str | None
    source_snapshot_sha256: str | None
    source_qualification_status: str | None
    source_population: str | None
    source_layer: str | None
    source_rights_status: str | None
    source_review_status: str | None
    source_qualified_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PostAssessmentJobClaim(PostAssessmentJobDTO):
    """One worker claim; lease_token is a capability and must stay in memory."""

    lease_owner: str
    lease_token: str


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


def _optional_token(value: str | None, name: str, limit: int) -> str | None:
    return None if value is None else _require_token(value, name, limit)


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


def _dto(job: SchoolPostAssessmentJob) -> PostAssessmentJobDTO:
    return PostAssessmentJobDTO(
        id=job.id,
        job_ref=job.job_ref,
        school_id=job.school_id,
        task_id=job.task_id,
        class_id=job.class_id,
        class_student_id=job.class_student_id,
        task_enrollment_id=job.task_enrollment_id,
        subject_id=job.subject_id,
        assessment_session_id=job.assessment_session_id,
        job_kind=job.job_kind,
        policy_version=job.policy_version,
        policy_hash=job.policy_hash,
        status=job.status,
        attempt_count=job.attempt_count,
        next_attempt_at=_utc_aware(job.next_attempt_at),
        lease_expires_at=_utc_aware(job.lease_expires_at),
        source_snapshot_ref=job.source_snapshot_ref,
        source_snapshot_sha256=job.source_snapshot_sha256,
        source_qualification_status=job.source_qualification_status,
        source_population=job.source_population,
        source_layer=job.source_layer,
        source_rights_status=job.source_rights_status,
        source_review_status=job.source_review_status,
        source_qualified_at=_utc_aware(job.source_qualified_at),
        last_error_code=job.last_error_code,
        created_at=_utc_aware(job.created_at),  # type: ignore[arg-type]
        updated_at=_utc_aware(job.updated_at),  # type: ignore[arg-type]
    )


def _claim(job: SchoolPostAssessmentJob) -> PostAssessmentJobClaim:
    if job.lease_owner is None or job.lease_token is None:
        raise RuntimeError("claimed outbox row is missing its lease")
    return PostAssessmentJobClaim(
        **{field: getattr(_dto(job), field) for field in PostAssessmentJobDTO.__dataclass_fields__},
        lease_owner=job.lease_owner,
        lease_token=job.lease_token,
    )


class SchoolPostAssessmentJobRepository:
    """School-scoped outbox enqueue, lease, retry, and terminal transitions."""

    JOB_KIND = "EDUCATION_SUPPORT"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        school_id: int,
        task_id: int,
        class_id: int,
        class_student_id: int,
        task_enrollment_id: int,
        subject_id: int,
        assessment_session_id: int,
        policy_version: str,
        policy_hash: str | None = None,
        source_snapshot_ref: str | None = None,
        source_snapshot_sha256: str | None = None,
        source_qualification_status: str | None = None,
        source_population: str | None = None,
        source_layer: str | None = None,
        source_rights_status: str | None = None,
        source_review_status: str | None = None,
        source_qualified_at: datetime | None = None,
    ) -> PostAssessmentJobDTO:
        """Insert once for an exact assessment/policy key in the caller's transaction."""
        scope = {
            "school_id": _require_id(school_id, "school_id"),
            "task_id": _require_id(task_id, "task_id"),
            "class_id": _require_id(class_id, "class_id"),
            "class_student_id": _require_id(class_student_id, "class_student_id"),
            "task_enrollment_id": _require_id(task_enrollment_id, "task_enrollment_id"),
            "subject_id": _require_id(subject_id, "subject_id"),
            "assessment_session_id": _require_id(assessment_session_id, "assessment_session_id"),
        }
        policy_version = _require_token(policy_version, "policy_version", 64)
        policy_hash = _optional_hash(policy_hash, "policy_hash")
        source_snapshot_ref = _optional_token(source_snapshot_ref, "source_snapshot_ref", 128)
        source_snapshot_sha256 = _optional_hash(source_snapshot_sha256, "source_snapshot_sha256")
        source_qualification_status = _optional_token(
            source_qualification_status, "source_qualification_status", 32
        )
        source_population = _optional_token(source_population, "source_population", 64)
        source_layer = _optional_token(source_layer, "source_layer", 32)
        source_rights_status = _optional_token(source_rights_status, "source_rights_status", 32)
        source_review_status = _optional_token(source_review_status, "source_review_status", 32)
        qualified_at = _utc_naive(source_qualified_at) if source_qualified_at is not None else None

        lookup = self._key_query(
            school_id=school_id,
            assessment_session_id=assessment_session_id,
            policy_version=policy_version,
        )
        existing = await self.session.scalar(lookup)
        if existing is not None:
            self._ensure_replay_matches(
                existing,
                scope=scope,
                policy_version=policy_version,
                policy_hash=policy_hash,
                source_snapshot_ref=source_snapshot_ref,
                source_snapshot_sha256=source_snapshot_sha256,
                source_qualification_status=source_qualification_status,
                source_population=source_population,
                source_layer=source_layer,
                source_rights_status=source_rights_status,
                source_review_status=source_review_status,
                source_qualified_at=qualified_at,
            )
            return _dto(existing)

        stable_key = ":".join(
            str(part)
            for part in (school_id, assessment_session_id, self.JOB_KIND, policy_version)
        )
        job = SchoolPostAssessmentJob(
            **scope,
            job_ref=f"PAJ_{hashlib.sha256(stable_key.encode('ascii')).hexdigest()}",
            job_kind=self.JOB_KIND,
            policy_version=policy_version,
            policy_hash=policy_hash,
            status="QUEUED",
            attempt_count=0,
            source_snapshot_ref=source_snapshot_ref,
            source_snapshot_sha256=source_snapshot_sha256,
            source_qualification_status=source_qualification_status,
            source_population=source_population,
            source_layer=source_layer,
            source_rights_status=source_rights_status,
            source_review_status=source_review_status,
            source_qualified_at=qualified_at,
        )
        try:
            # The savepoint contains a concurrent duplicate-key race without
            # rolling back the caller's outer unit of work.
            async with self.session.begin_nested():
                self.session.add(job)
                await self.session.flush()
        except IntegrityError:
            # A locking read uses InnoDB's current-read view, so a row that
            # won the unique-key race is visible even under REPEATABLE READ.
            existing = await self.session.scalar(lookup.with_for_update())
            if existing is not None:
                self._ensure_replay_matches(
                    existing,
                    scope=scope,
                    policy_version=policy_version,
                    policy_hash=policy_hash,
                    source_snapshot_ref=source_snapshot_ref,
                    source_snapshot_sha256=source_snapshot_sha256,
                    source_qualification_status=source_qualification_status,
                    source_population=source_population,
                    source_layer=source_layer,
                    source_rights_status=source_rights_status,
                    source_review_status=source_review_status,
                    source_qualified_at=qualified_at,
                )
                return _dto(existing)
            raise ForeignKeyConflict(
                "outbox scope does not match an existing school assessment"
            ) from None
        return _dto(job)

    async def claim_ready(
        self,
        *,
        school_id: int,
        lease_owner: str,
        limit: int = 1,
        lease_seconds: int = 60,
        max_attempts: int = 5,
        now: datetime | None = None,
    ) -> list[PostAssessmentJobClaim]:
        """Claim due jobs with row locks; reclaim expired leases and bound retries."""
        school_id = _require_id(school_id, "school_id")
        lease_owner = _require_token(lease_owner, "lease_owner", 128)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or not 5 <= lease_seconds <= 3600
        ):
            raise ValueError("lease_seconds must be between 5 and 3600")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 20
        ):
            raise ValueError("max_attempts must be between 1 and 20")
        clock = _utc_naive(now)
        eligible = or_(
            SchoolPostAssessmentJob.status == "QUEUED",
            and_(
                SchoolPostAssessmentJob.status == "RETRY",
                SchoolPostAssessmentJob.next_attempt_at <= clock,
            ),
            and_(
                SchoolPostAssessmentJob.status == "LEASED",
                SchoolPostAssessmentJob.lease_expires_at <= clock,
            ),
        )
        statement = (
            select(SchoolPostAssessmentJob)
            .where(SchoolPostAssessmentJob.school_id == school_id, eligible)
            .order_by(SchoolPostAssessmentJob.created_at, SchoolPostAssessmentJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.scalars(statement)
        jobs = list(result.all())
        claims: list[PostAssessmentJobClaim] = []
        for job in jobs:
            if job.attempt_count >= max_attempts:
                expired_lease = job.status == "LEASED"
                job.status = "FAILED"
                error_code = (
                    PostAssessmentJobErrorCode.LEASE_EXPIRED_MAX_ATTEMPTS
                    if expired_lease
                    else PostAssessmentJobErrorCode.MAX_ATTEMPTS_EXHAUSTED
                )
                job.last_error_code = error_code.value
                self._clear_lease(job)
                job.next_attempt_at = None
                continue
            job.status = "LEASED"
            job.attempt_count += 1
            job.next_attempt_at = None
            job.lease_owner = lease_owner
            job.lease_expires_at = clock + timedelta(seconds=lease_seconds)
            job.lease_token = secrets.token_urlsafe(32)
            claims.append(_claim(job))
        if jobs:
            await self.session.flush()
        return claims

    async def get(self, *, school_id: int, subject_id: int, job_id: int) -> PostAssessmentJobDTO:
        """Read a job only by explicit tenant, subject, and row identifiers."""
        job = await self.session.scalar(
            select(SchoolPostAssessmentJob).where(
                SchoolPostAssessmentJob.school_id == _require_id(school_id, "school_id"),
                SchoolPostAssessmentJob.subject_id == _require_id(subject_id, "subject_id"),
                SchoolPostAssessmentJob.id == _require_id(job_id, "job_id"),
            )
        )
        if job is None:
            raise NotFound("post-assessment job was not found in this scope")
        return _dto(job)

    async def extend_lease(
        self,
        *,
        school_id: int,
        subject_id: int,
        job_id: int,
        lease_owner: str,
        lease_token: str,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> PostAssessmentJobClaim:
        """Extend only a live lease held by the presented owner/token pair."""
        clock = _utc_naive(now)
        job = await self._locked_lease(
            school_id=school_id,
            subject_id=subject_id,
            job_id=job_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            clock=clock,
        )
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or not 5 <= lease_seconds <= 3600
        ):
            raise ValueError("lease_seconds must be between 5 and 3600")
        candidate = clock + timedelta(seconds=lease_seconds)
        job.lease_expires_at = max(job.lease_expires_at, candidate)  # type: ignore[arg-type]
        await self.session.flush()
        return _claim(job)

    async def retry(
        self,
        *,
        school_id: int,
        subject_id: int,
        job_id: int,
        lease_owner: str,
        lease_token: str,
        error_code: PostAssessmentJobErrorCode,
        max_attempts: int = 5,
        base_delay_seconds: int = 5,
        max_delay_seconds: int = 900,
        now: datetime | None = None,
    ) -> PostAssessmentJobDTO:
        """Schedule bounded exponential retry or fail after the attempt budget."""
        error_code = self._error_code(error_code)
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 20
        ):
            raise ValueError("max_attempts must be between 1 and 20")
        if (
            isinstance(base_delay_seconds, bool)
            or not isinstance(base_delay_seconds, int)
            or not 1 <= base_delay_seconds <= 300
        ):
            raise ValueError("base_delay_seconds must be between 1 and 300")
        if (
            isinstance(max_delay_seconds, bool)
            or not isinstance(max_delay_seconds, int)
            or not base_delay_seconds <= max_delay_seconds <= 3600
        ):
            raise ValueError("max_delay_seconds must be between base delay and 3600")
        clock = _utc_naive(now)
        job = await self._locked_lease(
            school_id=school_id,
            subject_id=subject_id,
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
            delay = min(
                base_delay_seconds * (2 ** max(0, job.attempt_count - 1)),
                max_delay_seconds,
            )
            job.status = "RETRY"
            job.next_attempt_at = clock + timedelta(seconds=delay)
        await self.session.flush()
        return _dto(job)

    async def complete(
        self,
        *,
        school_id: int,
        subject_id: int,
        job_id: int,
        lease_owner: str,
        lease_token: str,
        status: str = "HELD",
        error_code: PostAssessmentJobErrorCode | None = None,
        now: datetime | None = None,
    ) -> PostAssessmentJobDTO:
        """Record a terminal disposition; this never means reviewed or published."""
        if not isinstance(status, str) or status not in _TERMINAL_STATES:
            raise ValueError("status must be an allowed terminal state")
        if status == "FAILED" and error_code is None:
            raise ValueError("FAILED requires a fixed error code")
        if error_code is not None:
            error_code = self._error_code(error_code)
        clock = _utc_naive(now)
        job = await self._locked_lease(
            school_id=school_id,
            subject_id=subject_id,
            job_id=job_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            clock=clock,
        )
        job.status = status
        job.last_error_code = error_code.value if error_code is not None else None
        job.next_attempt_at = None
        self._clear_lease(job)
        await self.session.flush()
        return _dto(job)

    @staticmethod
    def _error_code(value: PostAssessmentJobErrorCode) -> PostAssessmentJobErrorCode:
        if not isinstance(value, PostAssessmentJobErrorCode):
            raise ValueError("error_code must be an allowlisted fixed code")
        return value

    @staticmethod
    def _ensure_replay_matches(
        job: SchoolPostAssessmentJob,
        *,
        scope: dict[str, int],
        policy_version: str,
        policy_hash: str | None,
        source_snapshot_ref: str | None,
        source_snapshot_sha256: str | None,
        source_qualification_status: str | None,
        source_population: str | None,
        source_layer: str | None,
        source_rights_status: str | None,
        source_review_status: str | None,
        source_qualified_at: datetime | None,
    ) -> None:
        replay = {
            **scope,
            "policy_version": policy_version,
            "policy_hash": policy_hash,
            "source_snapshot_ref": source_snapshot_ref,
            "source_snapshot_sha256": source_snapshot_sha256,
            "source_qualification_status": source_qualification_status,
            "source_population": source_population,
            "source_layer": source_layer,
            "source_rights_status": source_rights_status,
            "source_review_status": source_review_status,
            "source_qualified_at": source_qualified_at,
        }
        if any(getattr(job, field) != value for field, value in replay.items()):
            raise UniqueConflict("outbox idempotency key conflicts with existing scope metadata")

    @staticmethod
    def _clear_lease(job: SchoolPostAssessmentJob) -> None:
        job.lease_owner = None
        job.lease_expires_at = None
        job.lease_token = None

    async def _locked_lease(
        self,
        *,
        school_id: int,
        subject_id: int,
        job_id: int,
        lease_owner: str,
        lease_token: str,
        clock: datetime,
    ) -> SchoolPostAssessmentJob:
        job = await self.session.scalar(
            select(SchoolPostAssessmentJob)
            .where(
                SchoolPostAssessmentJob.school_id == _require_id(school_id, "school_id"),
                SchoolPostAssessmentJob.subject_id == _require_id(subject_id, "subject_id"),
                SchoolPostAssessmentJob.id == _require_id(job_id, "job_id"),
                SchoolPostAssessmentJob.status == "LEASED",
                SchoolPostAssessmentJob.lease_owner
                == _require_token(lease_owner, "lease_owner", 128),
                SchoolPostAssessmentJob.lease_token
                == _require_token(lease_token, "lease_token", 128),
                SchoolPostAssessmentJob.lease_expires_at > clock,
            )
            .with_for_update()
        )
        if job is None:
            raise OptimisticConcurrencyConflict("lease is stale, expired, or outside this scope")
        return job

    @staticmethod
    def _key_query(*, school_id: int, assessment_session_id: int, policy_version: str):
        return select(SchoolPostAssessmentJob).where(
            SchoolPostAssessmentJob.school_id == school_id,
            SchoolPostAssessmentJob.assessment_session_id == assessment_session_id,
            SchoolPostAssessmentJob.job_kind == SchoolPostAssessmentJobRepository.JOB_KIND,
            SchoolPostAssessmentJob.policy_version == policy_version,
        )
