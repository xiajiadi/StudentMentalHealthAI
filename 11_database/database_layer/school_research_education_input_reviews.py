"""Content-free persistence for strictly bound stopped-input review receipts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    SchoolResearchEducationCandidate,
    SchoolResearchEducationInputReview,
    SchoolResearchEducationInputReviewEvent,
    SchoolResearchEducationJob,
    SchoolResearchEducationOutputReview,
    SchoolResearchSession,
)
from .school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    ResearchEducationJobClaim,
    ResearchEducationJobDTO,
)
from .school_research_education_jobs import (
    _dto as _job_dto,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_FIELDS = (
    "research_session_id",
    "school_id",
    "task_id",
    "class_id",
    "task_enrollment_id",
    "subject_id",
    "task_binding_id",
    "profile_version_id",
    "profile_ref",
    "profile_version_number",
    "profile_sha256",
    "response_origin",
)
_IMMUTABLE_FIELDS = (
    "safety_review_ref",
    "safety_trace_id",
    "safety_operation",
    "safety_action",
    "canonical_input_sha256",
    "policy_version",
    "policy_hash",
    "source_package_ref",
    "source_study_ref",
    "source_manifest_sha256",
    "prompt_id",
    "prompt_version",
    "prompt_sha256",
    "expires_at",
    "trace_id",
)


class ResearchEducationInputReviewError(ValueError):
    """Closed, content-free error classification."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationInputReviewScope:
    research_session_id: int = field(repr=False)
    school_id: int = field(repr=False)
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


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationInputReviewEvidence:
    decision_id: str = field(repr=False)
    safety_review_ref: str = field(repr=False)
    safety_trace_id: str = field(repr=False)
    safety_operation: str
    safety_action: str
    reason_codes: tuple[str, ...]
    requires_human: bool
    canonical_input_sha256: str = field(repr=False)
    policy_version: str
    policy_hash: str = field(repr=False)
    source_package_ref: str
    source_study_ref: str
    source_manifest_sha256: str = field(repr=False)
    prompt_id: str
    prompt_version: str
    prompt_sha256: str = field(repr=False)
    expires_at: datetime
    trace_id: str = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationInputReviewDTO:
    id: int = field(repr=False)
    input_review_ref: str
    job_id: int = field(repr=False)
    job_ref: str
    scope: ResearchEducationInputReviewScope = field(repr=False)
    decision_id: str = field(repr=False)
    safety_review_ref: str = field(repr=False)
    safety_trace_id: str = field(repr=False)
    safety_operation: str
    safety_action: str
    safety_reason_code: str
    safety_requires_human: bool
    canonical_input_sha256: str = field(repr=False)
    policy_version: str
    policy_hash: str = field(repr=False)
    source_package_ref: str
    source_study_ref: str
    source_manifest_sha256: str = field(repr=False)
    prompt_id: str
    prompt_version: str
    prompt_sha256: str = field(repr=False)
    status: str
    state_version: int
    expires_at: datetime
    resolved_by_membership_role_id: int | None = field(repr=False)
    resolved_at: datetime | None
    trace_id: str = field(repr=False)
    retention_due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    original_job_generation_round: int = field(default=0, kw_only=True)
    grant_policy_version: str | None = field(default=None, kw_only=True)
    grant_policy_hash: str | None = field(default=None, kw_only=True, repr=False)
    authorized_by_membership_role_id: int | None = field(default=None, kw_only=True, repr=False)
    authorized_at: datetime | None = field(default=None, kw_only=True)
    consumed_at: datetime | None = field(default=None, kw_only=True)


class SchoolResearchEducationInputReviewRepository:
    """Caller-UoW repository; it never commits or reads session snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(
        self,
        *,
        claim: ResearchEducationJobClaim,
        scope: ResearchEducationInputReviewScope,
        evidence: ResearchEducationInputReviewEvidence,
        now: datetime | None = None,
    ) -> ResearchEducationInputReviewDTO:
        _validate_scope(scope)
        _validate_claim(claim, scope)
        clock = _utc_naive(now)
        expires = _utc_naive(evidence.expires_at)
        _validate_evidence(evidence, claim)

        job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == claim.id,
                SchoolResearchEducationJob.job_ref == claim.job_ref,
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
                SchoolResearchEducationJob.policy_version == evidence.policy_version,
                SchoolResearchEducationJob.policy_hash == evidence.policy_hash,
                SchoolResearchEducationJob.response_origin == "PUBLIC_OBSERVED",
                SchoolResearchEducationJob.generation_round == 0,
                SchoolResearchEducationJob.input_review_id.is_(None),
            )
            .with_for_update()
        )
        if job is None or any(getattr(job, name) != getattr(scope, name) for name in _SCOPE_FIELDS):
            raise ForeignKeyConflict("research job scope was not found")

        existing = await self.session.scalar(
            select(SchoolResearchEducationInputReview)
            .where(SchoolResearchEducationInputReview.job_id == job.id)
            .with_for_update()
        )
        if existing is not None:
            if not _same_evidence(existing, scope, evidence, expires):
                raise UniqueConflict("input review replay does not match immutable evidence")
            return _dto(existing, job.job_ref)

        if expires <= clock or expires > clock + timedelta(hours=24):
            raise ResearchEducationInputReviewError("INPUT_REVIEW_NOT_ELIGIBLE")

        if (
            job.status != "LEASED"
            or job.lease_owner != claim.lease_owner
            or job.lease_token != claim.lease_token
            or job.lease_expires_at is None
            or _stored_utc_naive(job.lease_expires_at) <= clock
        ):
            raise OptimisticConcurrencyConflict("research job lease is stale")

        session_metadata = await self.session.execute(
            select(SchoolResearchSession.id, SchoolResearchSession.retention_due_at)
            .where(
                SchoolResearchSession.id == scope.research_session_id,
                *[
                    getattr(SchoolResearchSession, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS[1:]
                ],
            )
            .with_for_update()
        )
        session_row = session_metadata.first()
        if session_row is None:
            raise ForeignKeyConflict("research session scope was not found")
        retention_due_at = session_row.retention_due_at
        if retention_due_at is not None and expires > _stored_utc_naive(retention_due_at):
            raise ResearchEducationInputReviewError("EXPIRY_EXCEEDS_RETENTION")

        row = SchoolResearchEducationInputReview(
            input_review_ref=f"REIR_{uuid4().hex}",
            job_id=job.id,
            **_scope_values(scope),
            safety_decision_id=evidence.decision_id,
            safety_review_ref=evidence.safety_review_ref,
            safety_trace_id=evidence.safety_trace_id,
            safety_operation=evidence.safety_operation,
            safety_action=evidence.safety_action,
            safety_reason_code=evidence.reason_codes[0],
            safety_requires_human=evidence.requires_human,
            canonical_input_sha256=evidence.canonical_input_sha256,
            policy_version=evidence.policy_version,
            policy_hash=evidence.policy_hash,
            source_package_ref=evidence.source_package_ref,
            source_study_ref=evidence.source_study_ref,
            source_manifest_sha256=evidence.source_manifest_sha256,
            prompt_id=evidence.prompt_id,
            prompt_version=evidence.prompt_version,
            prompt_sha256=evidence.prompt_sha256,
            status="PENDING",
            state_version=1,
            expires_at=expires,
            resolved_by_membership_role_id=None,
            resolved_at=None,
            trace_id=evidence.trace_id,
            retention_due_at=retention_due_at,
            created_at=clock,
            updated_at=clock,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                self.session.add(
                    _event(
                        row,
                        actor_membership_role_id=None,
                        event_type="PENDING",
                        from_status=None,
                        to_status="PENDING",
                        state_version=1,
                        trace_id=evidence.trace_id,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            replay = await self.session.scalar(
                select(SchoolResearchEducationInputReview).where(
                    SchoolResearchEducationInputReview.job_id == job.id
                )
            )
            if replay is not None and _same_evidence(replay, scope, evidence, expires):
                return _dto(replay, job.job_ref)
            raise UniqueConflict("input review evidence conflicts with an existing review") from exc
        return _dto(row, job.job_ref)

    async def get_for_task(
        self,
        *,
        school_id: int,
        task_id: int,
        input_review_ref: str,
    ) -> ResearchEducationInputReviewDTO | None:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        input_review_ref = _require_token(input_review_ref, "input_review_ref", 128)
        row = await self.session.scalar(
            select(SchoolResearchEducationInputReview).where(
                SchoolResearchEducationInputReview.input_review_ref == input_review_ref,
                SchoolResearchEducationInputReview.school_id == school_id,
                SchoolResearchEducationInputReview.task_id == task_id,
            )
        )
        if row is None:
            return None
        return _dto(row, await _job_ref(self.session, row.job_id))

    async def list_for_task(
        self,
        *,
        school_id: int,
        task_id: int,
        offset: int = 0,
        limit: int = 25,
    ) -> list[ResearchEducationInputReviewDTO]:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        if type(offset) is not int or offset < 0 or offset > 100_000:
            raise ResearchEducationInputReviewError("INVALID_PAGINATION")
        if type(limit) is not int or not 1 <= limit <= 51:
            raise ResearchEducationInputReviewError("INVALID_PAGINATION")
        result = await self.session.execute(
            select(SchoolResearchEducationInputReview, SchoolResearchEducationJob.job_ref)
            .join(
                SchoolResearchEducationJob,
                SchoolResearchEducationInputReview.job_id == SchoolResearchEducationJob.id,
            )
            .where(
                SchoolResearchEducationInputReview.school_id == school_id,
                SchoolResearchEducationInputReview.task_id == task_id,
            )
            .order_by(
                SchoolResearchEducationInputReview.created_at.desc(),
                SchoolResearchEducationInputReview.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return [_dto(row, job_ref) for row, job_ref in result.all()]

    async def reject(
        self,
        *,
        input_review_ref: str,
        scope: ResearchEducationInputReviewScope,
        expected_state_version: int,
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationInputReviewDTO:
        return await self._resolve(
            event_type="REJECTED",
            input_review_ref=input_review_ref,
            scope=scope,
            expected_state_version=expected_state_version,
            actor_membership_role_id=actor_membership_role_id,
            trace_id=trace_id,
            now=now,
        )

    async def revoke(
        self,
        *,
        input_review_ref: str,
        scope: ResearchEducationInputReviewScope,
        expected_state_version: int,
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationInputReviewDTO:
        return await self._resolve(
            event_type="REVOKED",
            input_review_ref=input_review_ref,
            scope=scope,
            expected_state_version=expected_state_version,
            actor_membership_role_id=actor_membership_role_id,
            trace_id=trace_id,
            now=now,
        )

    async def authorize_and_enqueue_continuation(
        self,
        *,
        input_review_ref: str,
        scope: ResearchEducationInputReviewScope,
        expected_state_version: int,
        actor_membership_role_id: int,
        grant_policy_version: str,
        grant_policy_hash: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> tuple[ResearchEducationInputReviewDTO, ResearchEducationJobDTO]:
        """Authorize once and enqueue round 1 without committing the caller UoW."""
        _validate_scope(scope)
        input_review_ref = _require_token(input_review_ref, "input_review_ref", 128)
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        _require_token(grant_policy_version, "grant_policy_version", 64)
        _require_sha256(grant_policy_hash, "grant_policy_hash")
        trace_id = _require_token(trace_id, "trace_id", 128)
        if type(expected_state_version) is not int or expected_state_version != 1:
            raise OptimisticConcurrencyConflict("input review version is stale")
        clock = _utc_naive(now)

        row = await self.session.scalar(
            select(SchoolResearchEducationInputReview)
            .where(
                SchoolResearchEducationInputReview.input_review_ref == input_review_ref,
                *[
                    getattr(SchoolResearchEducationInputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
            .with_for_update()
        )
        if row is None:
            raise ForeignKeyConflict("input review was not found in this task scope")
        if row.status != "PENDING" or row.state_version != 1:
            raise OptimisticConcurrencyConflict("input review state changed")
        if _stored_utc_naive(row.expires_at) <= clock:
            raise OptimisticConcurrencyConflict("input review has expired")
        if (
            row.safety_operation != "INPUT"
            or row.safety_action != "REVIEW_REQUIRED"
            or row.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or row.safety_requires_human is not True
            or row.policy_version != GENERAL_EDUCATION_POLICY_VERSION
        ):
            raise ResearchEducationInputReviewError("INPUT_REVIEW_NOT_ELIGIBLE")

        source_job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == row.job_id,
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
            )
            .with_for_update()
        )
        if (
            source_job is None
            or source_job.generation_round != 0
            or source_job.input_review_id is not None
            or source_job.status != "REVIEW_REQUIRED"
            or source_job.policy_version != row.policy_version
            or source_job.policy_hash != row.policy_hash
            or any(getattr(source_job, name) != getattr(scope, name) for name in _SCOPE_FIELDS)
        ):
            raise ResearchEducationInputReviewError("SOURCE_JOB_NOT_ELIGIBLE")
        if await self.session.scalar(
            select(SchoolResearchEducationCandidate.id).where(
                SchoolResearchEducationCandidate.job_id == source_job.id
            )
        ) is not None:
            raise ResearchEducationInputReviewError("SOURCE_CANDIDATE_ALREADY_EXISTS")
        if row.retention_due_at is not None and _stored_utc_naive(row.retention_due_at) <= clock:
            raise ResearchEducationInputReviewError("INPUT_REVIEW_EXPIRED")
        if await self.session.scalar(
            select(SchoolResearchEducationJob.id).where(
                SchoolResearchEducationJob.input_review_id == row.id
            )
        ) is not None:
            raise UniqueConflict("input review already has a continuation job")

        stable_key = (
            f"{scope.school_id}:{scope.research_session_id}:EDUCATION_SUPPORT:"
            f"{row.policy_version}:1:{row.id}"
        )
        continuation = SchoolResearchEducationJob(
            **_scope_values(scope),
            job_ref="REJ_" + hashlib.sha256(stable_key.encode("ascii")).hexdigest(),
            job_kind="EDUCATION_SUPPORT",
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            publication_status="not_approved_for_publication_or_operational_use",
            policy_version=row.policy_version,
            policy_hash=row.policy_hash,
            generation_round=1,
            input_review_id=row.id,
            status="QUEUED",
            attempt_count=0,
        )
        try:
            async with self.session.begin_nested():
                row.status = "CONTINUATION_AUTHORIZED"
                row.state_version = 2
                row.authorized_by_membership_role_id = actor_membership_role_id
                row.authorized_at = clock
                row.grant_policy_version = grant_policy_version
                row.grant_policy_hash = grant_policy_hash
                row.updated_at = clock
                self.session.add(continuation)
                await self.session.flush()
                self.session.add(
                    _event(
                        row,
                        actor_membership_role_id=actor_membership_role_id,
                        event_type="CONTINUATION_AUTHORIZED",
                        from_status="PENDING",
                        to_status="CONTINUATION_AUTHORIZED",
                        state_version=2,
                        trace_id=trace_id,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            raise UniqueConflict("input review continuation was already created") from exc
        return _dto(row, source_job.job_ref), _job_dto(continuation)

    async def consume_for_candidate(
        self,
        *,
        claim: ResearchEducationJobClaim,
        scope: ResearchEducationInputReviewScope,
        grant_policy_version: str,
        grant_policy_hash: str,
        source_package_ref: str,
        source_study_ref: str,
        source_manifest_sha256: str,
        prompt_id: str,
        prompt_version: str,
        prompt_sha256: str,
        canonical_input_sha256: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationInputReviewDTO:
        """Consume an authorized grant under the live round-1 lease in caller UoW."""
        job, review, source_job, clock = await self._lock_authorized_continuation(
            claim=claim,
            scope=scope,
            grant_policy_version=grant_policy_version,
            grant_policy_hash=grant_policy_hash,
            source_package_ref=source_package_ref,
            source_study_ref=source_study_ref,
            source_manifest_sha256=source_manifest_sha256,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            canonical_input_sha256=canonical_input_sha256,
            now=now,
        )
        if job.input_review_id != review.id:
            raise ResearchEducationInputReviewError("CONTINUATION_REVIEW_NOT_CURRENT")
        trace_id = _require_token(trace_id, "trace_id", 128)
        async with self.session.begin_nested():
            review.status = "CONSUMED"
            review.state_version = 3
            review.consumed_at = clock
            review.updated_at = clock
            await self.session.flush()
            self.session.add(
                _event(
                    review,
                    actor_membership_role_id=None,
                    event_type="CONSUMED",
                    from_status="CONTINUATION_AUTHORIZED",
                    to_status="CONSUMED",
                    state_version=3,
                    trace_id=trace_id,
                )
            )
            await self.session.flush()
        return _dto(review, source_job.job_ref)

    async def consume_authorized_input_for_output_review_candidate(
        self,
        *,
        output_review_ref: str,
        scope: ResearchEducationInputReviewScope,
        grant_policy_version: str,
        grant_policy_hash: str,
        source_package_ref: str,
        source_study_ref: str,
        source_manifest_sha256: str,
        prompt_id: str,
        prompt_version: str,
        prompt_sha256: str,
        canonical_input_sha256: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationInputReviewDTO:
        """Consume current AUTHv2 for a terminal safety-stopped output review."""
        _validate_scope(scope)
        output_review_ref = _require_token(output_review_ref, "output_review_ref", 128)
        _require_token(grant_policy_version, "grant_policy_version", 64)
        _require_sha256(grant_policy_hash, "grant_policy_hash")
        _require_token(source_package_ref, "source_package_ref", 128)
        _require_token(source_study_ref, "source_study_ref", 128)
        _require_sha256(source_manifest_sha256, "source_manifest_sha256")
        _require_token(prompt_id, "prompt_id", 128)
        _require_token(prompt_version, "prompt_version", 64)
        _require_sha256(prompt_sha256, "prompt_sha256")
        _require_sha256(canonical_input_sha256, "canonical_input_sha256")
        trace_id = _require_token(trace_id, "trace_id", 128)
        clock = _utc_naive(now)

        output_review = await self.session.scalar(
            select(SchoolResearchEducationOutputReview).where(
                SchoolResearchEducationOutputReview.output_review_ref == output_review_ref,
                *[
                    getattr(SchoolResearchEducationOutputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
        )
        if (
            output_review is None
            or output_review.generation_round != 1
            or output_review.input_review_id is None
            or output_review.status != "PENDING"
            or output_review.state_version != 1
            or output_review.expires_at <= clock
            or output_review.safety_operation != "OUTPUT"
            or output_review.safety_action != "REVIEW_REQUIRED"
            or output_review.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or output_review.safety_requires_human is not True
        ):
            raise ResearchEducationInputReviewError("OUTPUT_REVIEW_NOT_CURRENT")

        review = await self.session.scalar(
            select(SchoolResearchEducationInputReview)
            .where(
                SchoolResearchEducationInputReview.id == output_review.input_review_id,
                *[
                    getattr(SchoolResearchEducationInputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
            .with_for_update()
        )
        if review is None:
            raise ForeignKeyConflict("authorized input review was not found")

        job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == output_review.job_id,
                SchoolResearchEducationJob.generation_round == 1,
                SchoolResearchEducationJob.input_review_id == review.id,
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
            )
            .with_for_update()
        )
        if (
            job is None
            or job.status != "REVIEW_REQUIRED"
            or job.last_error_code != "SAFETY_BLOCKED"
            or job.attempt_count != 1
            or job.lease_owner is not None
            or job.lease_token is not None
            or job.lease_expires_at is not None
            or any(getattr(job, name) != getattr(scope, name) for name in _SCOPE_FIELDS)
            or job.policy_version != review.policy_version
            or job.policy_hash != review.policy_hash
            or output_review.policy_version != review.policy_version
            or output_review.policy_hash != review.policy_hash
            or output_review.source_package_ref != source_package_ref
            or output_review.source_study_ref != source_study_ref
            or output_review.source_manifest_sha256 != source_manifest_sha256
            or output_review.prompt_id != prompt_id
            or output_review.prompt_version != prompt_version
            or output_review.prompt_sha256 != prompt_sha256
            or output_review.canonical_input_sha256 != canonical_input_sha256
        ):
            raise ResearchEducationInputReviewError("OUTPUT_REVIEW_JOB_NOT_CURRENT")

        source_job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == review.job_id,
                SchoolResearchEducationJob.generation_round == 0,
                SchoolResearchEducationJob.input_review_id.is_(None),
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
                SchoolResearchEducationJob.status == "REVIEW_REQUIRED",
            )
            .with_for_update()
        )
        expected_trace = f"TRACE_{hashlib.sha256(f'{job.job_ref}:{job.attempt_count}'.encode('ascii')).hexdigest()[:32]}"
        if (
            source_job is None
            or source_job.last_error_code != "SAFETY_BLOCKED"
            or source_job.attempt_count != 1
            or source_job.lease_owner is not None
            or source_job.lease_token is not None
            or source_job.lease_expires_at is not None
            or any(getattr(source_job, name) != getattr(scope, name) for name in _SCOPE_FIELDS)
            or source_job.policy_version != review.policy_version
            or source_job.policy_hash != review.policy_hash
            or review.status != "CONTINUATION_AUTHORIZED"
            or review.state_version != 2
            or review.consumed_at is not None
            or review.authorized_by_membership_role_id is None
            or review.authorized_at is None
            or review.grant_policy_version != grant_policy_version
            or review.grant_policy_hash != grant_policy_hash
            or review.canonical_input_sha256 != canonical_input_sha256
            or review.source_package_ref != source_package_ref
            or review.source_study_ref != source_study_ref
            or review.source_manifest_sha256 != source_manifest_sha256
            or review.prompt_id != prompt_id
            or review.prompt_version != prompt_version
            or review.prompt_sha256 != prompt_sha256
            or review.safety_operation != "INPUT"
            or review.safety_action != "REVIEW_REQUIRED"
            or review.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or review.safety_requires_human is not True
            or review.expires_at <= clock
            or (review.retention_due_at is not None and review.retention_due_at <= clock)
            or output_review.safety_trace_id != expected_trace
            or output_review.trace_id != expected_trace
        ):
            raise ResearchEducationInputReviewError("CONTINUATION_GRANT_NOT_CURRENT")

        async with self.session.begin_nested():
            review.status = "CONSUMED"
            review.state_version = 3
            review.consumed_at = clock
            review.updated_at = clock
            await self.session.flush()
            self.session.add(
                _event(
                    review,
                    actor_membership_role_id=None,
                    event_type="CONSUMED",
                    from_status="CONTINUATION_AUTHORIZED",
                    to_status="CONSUMED",
                    state_version=3,
                    trace_id=trace_id,
                )
            )
            await self.session.flush()
        return _dto(review, source_job.job_ref)

    async def require_authorized_continuation(
        self,
        *,
        claim: ResearchEducationJobClaim,
        scope: ResearchEducationInputReviewScope,
        grant_policy_version: str,
        grant_policy_hash: str,
        source_package_ref: str,
        source_study_ref: str,
        source_manifest_sha256: str,
        prompt_id: str,
        prompt_version: str,
        prompt_sha256: str,
        canonical_input_sha256: str,
        now: datetime | None = None,
    ) -> ResearchEducationInputReviewDTO:
        """Revalidate before dispatch; call again at storage after any concurrent revoke.

        Callers release this short-lived UoW before invoking a runtime. A revoke
        racing after this check may let an already-started RAM-only call finish,
        but ``consume_for_candidate`` will reject persistence.
        """
        _job, review, source_job, _clock = await self._lock_authorized_continuation(
            claim=claim,
            scope=scope,
            grant_policy_version=grant_policy_version,
            grant_policy_hash=grant_policy_hash,
            source_package_ref=source_package_ref,
            source_study_ref=source_study_ref,
            source_manifest_sha256=source_manifest_sha256,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            canonical_input_sha256=canonical_input_sha256,
            now=now,
        )
        return _dto(review, source_job.job_ref)

    async def _lock_authorized_continuation(
        self,
        *,
        claim: ResearchEducationJobClaim,
        scope: ResearchEducationInputReviewScope,
        grant_policy_version: str,
        grant_policy_hash: str,
        source_package_ref: str,
        source_study_ref: str,
        source_manifest_sha256: str,
        prompt_id: str,
        prompt_version: str,
        prompt_sha256: str,
        canonical_input_sha256: str,
        now: datetime | None,
    ) -> tuple[
        SchoolResearchEducationJob,
        SchoolResearchEducationInputReview,
        SchoolResearchEducationJob,
        datetime,
    ]:
        _validate_scope(scope)
        _validate_continuation_claim(claim, scope)
        _require_token(grant_policy_version, "grant_policy_version", 64)
        _require_sha256(grant_policy_hash, "grant_policy_hash")
        _require_token(source_package_ref, "source_package_ref", 128)
        _require_token(source_study_ref, "source_study_ref", 128)
        _require_sha256(source_manifest_sha256, "source_manifest_sha256")
        _require_token(prompt_id, "prompt_id", 128)
        _require_token(prompt_version, "prompt_version", 64)
        _require_sha256(prompt_sha256, "prompt_sha256")
        _require_sha256(canonical_input_sha256, "canonical_input_sha256")
        clock = _utc_naive(now)

        job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == claim.id,
                SchoolResearchEducationJob.job_ref == claim.job_ref,
                SchoolResearchEducationJob.generation_round == 1,
                SchoolResearchEducationJob.input_review_id == claim.input_review_id,
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
                SchoolResearchEducationJob.status == "LEASED",
                SchoolResearchEducationJob.lease_owner == claim.lease_owner,
                SchoolResearchEducationJob.lease_token == claim.lease_token,
                SchoolResearchEducationJob.lease_expires_at > clock,
            )
            .with_for_update()
        )
        if (
            job is None
            or job.attempt_count != 1
            or any(getattr(job, name) != getattr(scope, name) for name in _SCOPE_FIELDS)
        ):
            raise OptimisticConcurrencyConflict("continuation job lease is stale")
        review = await self.session.scalar(
            select(SchoolResearchEducationInputReview)
            .where(
                SchoolResearchEducationInputReview.id == job.input_review_id,
                *[
                    getattr(SchoolResearchEducationInputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
            .with_for_update()
        )
        if review is None:
            raise ForeignKeyConflict("continuation input review was not found")
        if (
            review.status != "CONTINUATION_AUTHORIZED"
            or review.state_version != 2
            or review.consumed_at is not None
            or review.authorized_by_membership_role_id is None
            or review.authorized_at is None
            or review.grant_policy_version != grant_policy_version
            or review.grant_policy_hash != grant_policy_hash
            or review.expires_at is None
            or _stored_utc_naive(review.expires_at) <= clock
            or review.retention_due_at is not None
            and _stored_utc_naive(review.retention_due_at) <= clock
            or review.canonical_input_sha256 != canonical_input_sha256
            or review.policy_version != job.policy_version
            or review.policy_hash != job.policy_hash
            or review.source_package_ref != source_package_ref
            or review.source_study_ref != source_study_ref
            or review.source_manifest_sha256 != source_manifest_sha256
            or review.prompt_id != prompt_id
            or review.prompt_version != prompt_version
            or review.prompt_sha256 != prompt_sha256
            or review.safety_operation != "INPUT"
            or review.safety_action != "REVIEW_REQUIRED"
            or review.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or review.safety_requires_human is not True
        ):
            raise ResearchEducationInputReviewError("CONTINUATION_REVIEW_NOT_CURRENT")
        source_job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == review.job_id,
                SchoolResearchEducationJob.generation_round == 0,
                SchoolResearchEducationJob.input_review_id.is_(None),
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
                SchoolResearchEducationJob.status == "REVIEW_REQUIRED",
            )
            .with_for_update()
        )
        if (
            source_job is None
            or source_job.policy_version != review.policy_version
            or source_job.policy_hash != review.policy_hash
            or any(getattr(source_job, name) != getattr(scope, name) for name in _SCOPE_FIELDS)
        ):
            raise ResearchEducationInputReviewError("SOURCE_JOB_NOT_CURRENT")
        return job, review, source_job, clock

    async def _resolve(
        self,
        *,
        event_type: str,
        input_review_ref: str,
        scope: ResearchEducationInputReviewScope,
        expected_state_version: int,
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime | None,
    ) -> ResearchEducationInputReviewDTO:
        _validate_scope(scope)
        input_review_ref = _require_token(input_review_ref, "input_review_ref", 128)
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        trace_id = _require_token(trace_id, "trace_id", 128)
        if event_type not in {"REJECTED", "REVOKED"}:
            raise ResearchEducationInputReviewError("INVALID_DISPOSITION")
        allowed_versions = {1} if event_type == "REJECTED" else {1, 2}
        if (
            type(expected_state_version) is not int
            or expected_state_version not in allowed_versions
        ):
            raise OptimisticConcurrencyConflict("input review version is stale")
        clock = _utc_naive(now)
        row = await self.session.scalar(
            select(SchoolResearchEducationInputReview)
            .where(
                SchoolResearchEducationInputReview.input_review_ref == input_review_ref,
                *[
                    getattr(SchoolResearchEducationInputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
            .with_for_update()
        )
        if row is None:
            raise ForeignKeyConflict("input review was not found in this task scope")
        pending_transition = row.status == "PENDING" and row.state_version == 1
        authorized_transition = (
            event_type == "REVOKED"
            and row.status == "CONTINUATION_AUTHORIZED"
            and row.state_version == 2
        )
        if (
            not pending_transition
            and not authorized_transition
            or row.state_version != expected_state_version
        ):
            raise OptimisticConcurrencyConflict("input review state changed")
        if pending_transition and _stored_utc_naive(row.expires_at) <= clock:
            raise OptimisticConcurrencyConflict("input review has expired")
        previous_status = row.status
        new_version = 3 if authorized_transition else 2
        try:
            async with self.session.begin_nested():
                row.status = event_type
                row.state_version = new_version
                row.resolved_by_membership_role_id = actor_membership_role_id
                row.resolved_at = clock
                row.updated_at = clock
                if authorized_transition:
                    continuation = await self.session.scalar(
                        select(SchoolResearchEducationJob)
                        .where(
                            SchoolResearchEducationJob.input_review_id == row.id,
                            SchoolResearchEducationJob.generation_round == 1,
                            SchoolResearchEducationJob.research_session_id
                            == row.research_session_id,
                            SchoolResearchEducationJob.school_id == row.school_id,
                        )
                        .with_for_update()
                    )
                    if continuation is not None and continuation.status in {
                        "QUEUED", "RETRY", "LEASED"
                    }:
                        continuation.status = "CANCELLED"
                        continuation.next_attempt_at = None
                        continuation.lease_owner = None
                        continuation.lease_expires_at = None
                        continuation.lease_token = None
                await self.session.flush()
                self.session.add(
                    _event(
                        row,
                        actor_membership_role_id=actor_membership_role_id,
                        event_type=event_type,
                        from_status=previous_status,
                        to_status=event_type,
                        state_version=new_version,
                        trace_id=trace_id,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            raise OptimisticConcurrencyConflict("input review disposition conflicted") from exc
        return _dto(row, await _job_ref(self.session, row.job_id))


def _validate_continuation_claim(
    claim: ResearchEducationJobClaim, scope: ResearchEducationInputReviewScope
) -> None:
    if (
        type(claim) is not ResearchEducationJobClaim
        or claim.status != "LEASED"
        or claim.response_origin != "PUBLIC_OBSERVED"
        or claim.policy_version != GENERAL_EDUCATION_POLICY_VERSION
        or claim.generation_round != 1
        or claim.input_review_id is None
        or claim.attempt_count != 1
        or any(getattr(claim, name) != getattr(scope, name) for name in _SCOPE_FIELDS)
    ):
        raise ResearchEducationInputReviewError("CONTINUATION_CLAIM_INVALID")
    _require_id(claim.id, "job_id")
    _require_id(claim.input_review_id, "input_review_id")
    _require_token(claim.job_ref, "job_ref", 128)
    _require_token(claim.lease_owner, "lease_owner", 128)
    _require_token(claim.lease_token, "lease_token", 128)
    _require_sha256(claim.policy_hash, "policy_hash")


def _validate_scope(scope: ResearchEducationInputReviewScope) -> None:
    if type(scope) is not ResearchEducationInputReviewScope:
        raise ResearchEducationInputReviewError("INVALID_SCOPE")
    for name in (
        "research_session_id",
        "school_id",
        "task_id",
        "class_id",
        "task_enrollment_id",
        "subject_id",
        "task_binding_id",
        "profile_version_id",
    ):
        _require_id(getattr(scope, name), name)
    _require_token(scope.profile_ref, "profile_ref", 128)
    if type(scope.profile_version_number) is not int or scope.profile_version_number <= 0:
        raise ResearchEducationInputReviewError("INVALID_SCOPE")
    _require_sha256(scope.profile_sha256, "profile_sha256")
    if scope.response_origin != "PUBLIC_OBSERVED":
        raise ResearchEducationInputReviewError("INVALID_SCOPE")


def _validate_claim(
    claim: ResearchEducationJobClaim, scope: ResearchEducationInputReviewScope
) -> None:
    if (
        type(claim) is not ResearchEducationJobClaim
        or claim.status != "LEASED"
        or claim.response_origin != "PUBLIC_OBSERVED"
        or claim.policy_version != GENERAL_EDUCATION_POLICY_VERSION
        or claim.generation_round != 0
        or claim.input_review_id is not None
        or any(getattr(claim, name) != getattr(scope, name) for name in _SCOPE_FIELDS)
    ):
        raise ResearchEducationInputReviewError("JOB_CLAIM_SCOPE_INVALID")
    _require_id(claim.id, "job_id")
    _require_token(claim.job_ref, "job_ref", 128)
    _require_token(claim.lease_owner, "lease_owner", 128)
    _require_token(claim.lease_token, "lease_token", 128)


def _validate_evidence(
    evidence: ResearchEducationInputReviewEvidence,
    claim: ResearchEducationJobClaim,
) -> None:
    if type(evidence) is not ResearchEducationInputReviewEvidence:
        raise ResearchEducationInputReviewError("INVALID_EVIDENCE")
    if (
        evidence.safety_operation != "INPUT"
        or evidence.safety_action != "REVIEW_REQUIRED"
        or type(evidence.reason_codes) is not tuple
        or evidence.reason_codes != ("CONTENT_CONTROVERSIAL",)
        or evidence.requires_human is not True
        or evidence.policy_version != GENERAL_EDUCATION_POLICY_VERSION
        or evidence.policy_hash != claim.policy_hash
        or evidence.policy_hash is None
    ):
        raise ResearchEducationInputReviewError("INPUT_REVIEW_NOT_ELIGIBLE")
    for name, value, limit in (
        ("decision_id", evidence.decision_id, 160),
        ("safety_review_ref", evidence.safety_review_ref, 160),
        ("safety_trace_id", evidence.safety_trace_id, 160),
        ("source_package_ref", evidence.source_package_ref, 128),
        ("source_study_ref", evidence.source_study_ref, 128),
        ("prompt_id", evidence.prompt_id, 128),
        ("prompt_version", evidence.prompt_version, 64),
        ("trace_id", evidence.trace_id, 128),
    ):
        _require_token(value, name, limit)
    for name, value in (
        ("canonical_input_sha256", evidence.canonical_input_sha256),
        ("policy_hash", evidence.policy_hash),
        ("source_manifest_sha256", evidence.source_manifest_sha256),
        ("prompt_sha256", evidence.prompt_sha256),
    ):
        _require_sha256(value, name)


def _same_evidence(
    row: SchoolResearchEducationInputReview,
    scope: ResearchEducationInputReviewScope,
    evidence: ResearchEducationInputReviewEvidence,
    expires: datetime,
) -> bool:
    if any(getattr(row, name) != getattr(scope, name) for name in _SCOPE_FIELDS):
        return False
    expected = {name: getattr(evidence, name) for name in _IMMUTABLE_FIELDS if name != "expires_at"}
    expected["safety_decision_id"] = evidence.decision_id
    expected["safety_reason_code"] = evidence.reason_codes[0]
    expected["safety_requires_human"] = evidence.requires_human
    expected["expires_at"] = expires
    return all(
        (_stored_utc_naive(getattr(row, name)) == value)
        if name == "expires_at"
        else getattr(row, name) == value
        for name, value in expected.items()
    )


def _scope_values(scope: ResearchEducationInputReviewScope) -> dict[str, object]:
    return {name: getattr(scope, name) for name in _SCOPE_FIELDS}


def _dto(
    row: SchoolResearchEducationInputReview,
    job_ref: str,
) -> ResearchEducationInputReviewDTO:
    return ResearchEducationInputReviewDTO(
        id=row.id,
        input_review_ref=row.input_review_ref,
        job_id=row.job_id,
        job_ref=job_ref,
        scope=ResearchEducationInputReviewScope(
            **{name: getattr(row, name) for name in _SCOPE_FIELDS}
        ),
        **{name: getattr(row, name) for name in _IMMUTABLE_FIELDS if name != "expires_at"},
        decision_id=row.safety_decision_id,
        safety_reason_code=row.safety_reason_code,
        safety_requires_human=row.safety_requires_human,
        status=row.status,
        state_version=row.state_version,
        expires_at=_required_utc_aware(row.expires_at),
        resolved_by_membership_role_id=row.resolved_by_membership_role_id,
        resolved_at=_utc_aware(row.resolved_at),
        retention_due_at=_utc_aware(row.retention_due_at),
        created_at=_required_utc_aware(row.created_at),
        updated_at=_required_utc_aware(row.updated_at),
        original_job_generation_round=row.original_job_generation_round,
        grant_policy_version=row.grant_policy_version,
        grant_policy_hash=row.grant_policy_hash,
        authorized_by_membership_role_id=row.authorized_by_membership_role_id,
        authorized_at=_utc_aware(row.authorized_at),
        consumed_at=_utc_aware(row.consumed_at),
    )


def _event(
    row: SchoolResearchEducationInputReview,
    *,
    actor_membership_role_id: int | None,
    event_type: str,
    from_status: str | None,
    to_status: str,
    state_version: int,
    trace_id: str,
) -> SchoolResearchEducationInputReviewEvent:
    return SchoolResearchEducationInputReviewEvent(
        input_review_id=row.id,
        research_session_id=row.research_session_id,
        school_id=row.school_id,
        input_review_ref=row.input_review_ref,
        actor_membership_role_id=actor_membership_role_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        state_version=state_version,
        trace_id=trace_id,
        retention_due_at=row.retention_due_at,
    )


async def _job_ref(session: AsyncSession, job_id: int) -> str:
    value = await session.scalar(
        select(SchoolResearchEducationJob.job_ref).where(SchoolResearchEducationJob.id == job_id)
    )
    if value is None:
        raise ForeignKeyConflict("research job reference was not found")
    return value


def _require_id(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ResearchEducationInputReviewError("INVALID_INPUT")
    return value


def _require_token(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or not value.isascii()
        or _TOKEN.fullmatch(value) is None
    ):
        raise ResearchEducationInputReviewError("INVALID_INPUT")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ResearchEducationInputReviewError("INVALID_INPUT")
    return value


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        value = datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchEducationInputReviewError("INVALID_TIMESTAMP")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None else None


def _required_utc_aware(value: datetime | None) -> datetime:
    if value is None:
        raise ResearchEducationInputReviewError("PERSISTED_TIMESTAMP_INVALID")
    return value.replace(tzinfo=UTC)


def _stored_utc_naive(value: datetime) -> datetime:
    """SQL DATETIME values are timezone-naive by database convention and mean UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = [
    "ResearchEducationInputReviewDTO",
    "ResearchEducationInputReviewError",
    "ResearchEducationInputReviewEvidence",
    "ResearchEducationInputReviewScope",
    "SchoolResearchEducationInputReviewRepository",
]
