"""Ciphertext-only persistence for future exact-scope research output review."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import ResearchEducationOutputReviewStatus
from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    SchoolResearchEducationJob,
    SchoolResearchEducationInputReview,
    SchoolResearchEducationOutputReview,
    SchoolResearchEducationOutputReviewEvent,
    SchoolResearchSession,
)
from .school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    ResearchEducationJobClaim,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
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
_SAFE_ACTIONS = frozenset({"PROCEED", "PROCEED_WITH_BOUNDARY"})
OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION = "school-research-general-education-output-review.v1"
CANDIDATE_PAYLOAD_SCHEMA_VERSION = "school-research-general-education-candidate.v1"


class ResearchEducationOutputReviewError(ValueError):
    """Closed, content-free output-review persistence failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationOutputReviewScope:
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
class ResearchEducationOutputReviewEvidence:
    safety_decision_id: str = field(repr=False)
    safety_review_ref: str = field(repr=False)
    safety_trace_id: str = field(repr=False)
    safety_operation: str
    safety_action: str
    safety_reason_codes: tuple[str, ...]
    safety_requires_human: bool
    input_safety_action: str
    retrieval_safety_action: str
    canonical_input_sha256: str | None = field(repr=False)
    policy_version: str
    policy_hash: str = field(repr=False)
    source_package_ref: str
    source_study_ref: str
    source_manifest_sha256: str = field(repr=False)
    retrieval_id: str = field(repr=False)
    retrieval_bundle_sha256: str = field(repr=False)
    prompt_id: str
    prompt_version: str
    prompt_sha256: str = field(repr=False)
    model_ref: str
    model_digest_sha256: str = field(repr=False)
    runtime_version: str
    safety_policy_version: str
    candidate_content_sha256: str | None = field(repr=False)
    candidate_payload_schema_version: str | None
    expires_at: datetime
    trace_id: str = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationOutputReviewSummaryDTO:
    id: int = field(repr=False)
    output_review_ref: str
    job_id: int = field(repr=False)
    job_ref: str
    generation_round: int
    input_review_id: int | None = field(repr=False)
    scope: ResearchEducationOutputReviewScope = field(repr=False)
    safety_decision_id: str = field(repr=False)
    safety_review_ref: str = field(repr=False)
    safety_trace_id: str = field(repr=False)
    safety_operation: str
    safety_action: str
    safety_reason_code: str
    safety_requires_human: bool
    input_safety_action: str
    retrieval_safety_action: str
    canonical_input_sha256: str | None = field(repr=False)
    policy_version: str
    policy_hash: str = field(repr=False)
    source_package_ref: str
    source_study_ref: str
    source_manifest_sha256: str = field(repr=False)
    retrieval_id: str = field(repr=False)
    retrieval_bundle_sha256: str = field(repr=False)
    prompt_id: str
    prompt_version: str
    prompt_sha256: str = field(repr=False)
    model_ref: str
    model_digest_sha256: str = field(repr=False)
    runtime_version: str
    safety_policy_version: str
    content_sha256: str = field(repr=False)
    candidate_content_sha256: str | None = field(repr=False)
    candidate_payload_schema_version: str | None
    status: str
    state_version: int
    expires_at: datetime
    resolved_by_membership_role_id: int | None = field(repr=False)
    resolved_at: datetime | None
    consumed_at: datetime | None
    trace_id: str = field(repr=False)
    retention_due_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationOutputReviewDTO(ResearchEducationOutputReviewSummaryDTO):
    payload_ciphertext: bytes = field(repr=False)
    cipher_format_version: str = field(repr=False)
    key_version: str = field(repr=False)
    payload_schema_version: str = field(repr=False)


class SchoolResearchEducationOutputReviewRepository:
    """Caller-owned transaction repository; plaintext never enters persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(
        self,
        *,
        claim: ResearchEducationJobClaim,
        scope: ResearchEducationOutputReviewScope,
        evidence: ResearchEducationOutputReviewEvidence,
        content_sha256: str,
        payload_ciphertext: bytes,
        cipher_format_version: str,
        key_version: str,
        payload_schema_version: str = OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
        now: datetime | None = None,
    ) -> ResearchEducationOutputReviewDTO:
        _validate_scope(scope)
        _validate_evidence(claim, evidence, content_sha256, payload_ciphertext, cipher_format_version, key_version, payload_schema_version)
        clock = _utc_naive(now)
        expires = _utc_naive(evidence.expires_at)
        if expires <= clock or expires > clock + timedelta(hours=24):
            raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_NOT_ELIGIBLE")

        job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == claim.id,
                SchoolResearchEducationJob.job_ref == claim.job_ref,
                SchoolResearchEducationJob.generation_round == claim.generation_round,
                SchoolResearchEducationJob.input_review_id == claim.input_review_id,
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
                SchoolResearchEducationJob.policy_version == claim.policy_version,
                SchoolResearchEducationJob.policy_hash == claim.policy_hash,
                SchoolResearchEducationJob.response_origin == "PUBLIC_OBSERVED",
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
            raise OptimisticConcurrencyConflict("research job lease is stale")

        if claim.generation_round == 1:
            await self._validate_authorized_input_grant(job, scope, evidence, now)
        elif claim.generation_round != 0 or claim.input_review_id is not None:
            raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_JOB_LINEAGE_INVALID")

        session_result = await self.session.execute(
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
        session_row = session_result.first()
        if session_row is None:
            raise ForeignKeyConflict("research session scope was not found")
        retention_due_at = session_row.retention_due_at
        if retention_due_at is not None and expires > _stored_utc_naive(retention_due_at):
            raise ResearchEducationOutputReviewError("EXPIRY_EXCEEDS_RETENTION")

        existing = await self.session.scalar(
            select(SchoolResearchEducationOutputReview)
            .where(SchoolResearchEducationOutputReview.job_id == job.id)
            .with_for_update()
        )
        if existing is not None:
            if not _same_evidence(existing, scope, evidence, content_sha256, expires):
                raise UniqueConflict("output review replay conflicts with immutable evidence")
            return await self._dto(existing, job.job_ref)

        row = SchoolResearchEducationOutputReview(
            output_review_ref=f"REOR_{uuid4().hex}",
            job_id=job.id,
            generation_round=job.generation_round,
            input_review_id=job.input_review_id,
            **_scope_values(scope),
            safety_decision_id=evidence.safety_decision_id,
            safety_review_ref=evidence.safety_review_ref,
            safety_trace_id=evidence.safety_trace_id,
            safety_operation=evidence.safety_operation,
            safety_action=evidence.safety_action,
            safety_reason_code=evidence.safety_reason_codes[0],
            safety_requires_human=evidence.safety_requires_human,
            input_safety_action=evidence.input_safety_action,
            retrieval_safety_action=evidence.retrieval_safety_action,
            canonical_input_sha256=evidence.canonical_input_sha256,
            policy_version=evidence.policy_version,
            policy_hash=evidence.policy_hash,
            source_package_ref=evidence.source_package_ref,
            source_study_ref=evidence.source_study_ref,
            source_manifest_sha256=evidence.source_manifest_sha256,
            retrieval_id=evidence.retrieval_id,
            retrieval_bundle_sha256=evidence.retrieval_bundle_sha256,
            prompt_id=evidence.prompt_id,
            prompt_version=evidence.prompt_version,
            prompt_sha256=evidence.prompt_sha256,
            model_ref=evidence.model_ref,
            model_digest_sha256=evidence.model_digest_sha256,
            runtime_version=evidence.runtime_version,
            safety_policy_version=evidence.safety_policy_version,
            content_sha256=content_sha256,
            candidate_content_sha256=evidence.candidate_content_sha256,
            candidate_payload_schema_version=evidence.candidate_payload_schema_version,
            payload_ciphertext=payload_ciphertext,
            cipher_format_version=cipher_format_version,
            key_version=key_version,
            payload_schema_version=payload_schema_version,
            status=ResearchEducationOutputReviewStatus.PENDING.value,
            state_version=1,
            expires_at=expires,
            resolved_by_membership_role_id=None,
            resolved_at=None,
            consumed_at=None,
            trace_id=evidence.trace_id,
            retention_due_at=retention_due_at,
            created_at=clock,
            updated_at=clock,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                self.session.add(_event(row, None, "PENDING", None, "PENDING", 1, evidence.trace_id))
                await self.session.flush()
        except IntegrityError as exc:
            raise UniqueConflict("output review evidence conflicts with an existing row") from exc
        return await self._dto(row, job.job_ref)

    async def get_for_task(
        self,
        *,
        scope: ResearchEducationOutputReviewScope,
        output_review_ref: str,
    ) -> ResearchEducationOutputReviewDTO | None:
        _validate_scope(scope)
        output_review_ref = _require_token(output_review_ref, "output_review_ref", 128)
        row = await self.session.scalar(
            select(SchoolResearchEducationOutputReview).where(
                SchoolResearchEducationOutputReview.output_review_ref == output_review_ref,
                *[
                    getattr(SchoolResearchEducationOutputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
        )
        if row is None:
            return None
        _require_terminal_review_job(
            await _load_job(self.session, row.job_id), row
        )
        return await self._dto(row, await _job_ref(self.session, row.job_id))

    async def find_scope_for_task(
        self,
        *,
        school_id: int,
        task_id: int,
        output_review_ref: str,
    ) -> ResearchEducationOutputReviewScope | None:
        """Resolve one public reference to exact scope without loading ciphertext."""
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        output_review_ref = _require_token(output_review_ref, "output_review_ref", 128)
        result = await self.session.execute(
            select(*[
                getattr(SchoolResearchEducationOutputReview, name)
                for name in _SCOPE_FIELDS
            ]).where(
                SchoolResearchEducationOutputReview.school_id == school_id,
                SchoolResearchEducationOutputReview.task_id == task_id,
                SchoolResearchEducationOutputReview.output_review_ref == output_review_ref,
            )
        )
        row = result.first()
        return None if row is None else ResearchEducationOutputReviewScope(**dict(row._mapping))

    async def list_for_task(
        self,
        *,
        school_id: int,
        task_id: int,
        offset: int = 0,
        limit: int = 21,
    ) -> tuple[ResearchEducationOutputReviewSummaryDTO, ...]:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        if type(offset) is not int or offset < 0 or offset > 100_000:
            raise ResearchEducationOutputReviewError("INVALID_PAGINATION")
        if type(limit) is not int or not 1 <= limit <= 21:
            raise ResearchEducationOutputReviewError("INVALID_PAGINATION")
        result = await self.session.execute(
            select(SchoolResearchEducationOutputReview, SchoolResearchEducationJob.job_ref)
            .join(
                SchoolResearchEducationJob,
                SchoolResearchEducationJob.id == SchoolResearchEducationOutputReview.job_id,
            )
            .where(
                SchoolResearchEducationOutputReview.school_id == school_id,
                SchoolResearchEducationOutputReview.task_id == task_id,
            )
            .order_by(SchoolResearchEducationOutputReview.created_at, SchoolResearchEducationOutputReview.id)
            .offset(offset)
            .limit(limit)
        )
        values = []
        for row, job_ref in result.all():
            job = await _load_job(self.session, row.job_id)
            _require_terminal_review_job(job, row)
            values.append(_summary(row, job_ref))
        return tuple(values)

    async def resolve(
        self,
        *,
        scope: ResearchEducationOutputReviewScope,
        output_review_ref: str,
        expected_state_version: int,
        status: str,
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationOutputReviewSummaryDTO:
        _validate_scope(scope)
        output_review_ref = _require_token(output_review_ref, "output_review_ref", 128)
        actor_membership_role_id = _require_id(actor_membership_role_id, "actor_membership_role_id")
        trace_id = _require_token(trace_id, "trace_id", 128)
        if status not in {
            ResearchEducationOutputReviewStatus.REJECTED.value,
            ResearchEducationOutputReviewStatus.REVOKED.value,
        }:
            raise ResearchEducationOutputReviewError("INVALID_DISPOSITION")
        if type(expected_state_version) is not int or expected_state_version != 1:
            raise OptimisticConcurrencyConflict("output review version is stale")
        clock = _utc_naive(now)
        row = await self.session.scalar(
            select(SchoolResearchEducationOutputReview)
            .where(
                SchoolResearchEducationOutputReview.output_review_ref == output_review_ref,
                *[
                    getattr(SchoolResearchEducationOutputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
            .with_for_update()
        )
        if row is None:
            raise ForeignKeyConflict("output review was not found in this task scope")
        if row.status != ResearchEducationOutputReviewStatus.PENDING.value or row.state_version != 1:
            raise OptimisticConcurrencyConflict("output review state changed")
        _require_terminal_review_job(await _load_job(self.session, row.job_id), row)
        if _stored_utc_naive(row.expires_at) <= clock or (
            row.retention_due_at is not None and _stored_utc_naive(row.retention_due_at) <= clock
        ):
            raise OptimisticConcurrencyConflict("output review has expired")
        previous = row.status
        async with self.session.begin_nested():
            row.status = status
            row.state_version = 2
            row.resolved_by_membership_role_id = actor_membership_role_id
            row.resolved_at = clock
            row.updated_at = clock
            await self.session.flush()
            self.session.add(_event(row, actor_membership_role_id, status, previous, status, 2, trace_id))
            await self.session.flush()
        return _summary(row, await _job_ref(self.session, row.job_id))

    async def consume_for_candidate(
        self,
        *,
        scope: ResearchEducationOutputReviewScope,
        output_review_ref: str,
        actor_membership_role_id: int,
        trace_id: str,
        candidate_content_sha256: str,
        candidate_payload_schema_version: str = CANDIDATE_PAYLOAD_SCHEMA_VERSION,
        now: datetime | None = None,
    ) -> ResearchEducationOutputReviewDTO:
        """Consume a pending review inside the candidate-creation UoW."""
        _validate_scope(scope)
        output_review_ref = _require_token(output_review_ref, "output_review_ref", 128)
        actor_membership_role_id = _require_id(actor_membership_role_id, "actor_membership_role_id")
        trace_id = _require_token(trace_id, "trace_id", 128)
        _require_sha256(candidate_content_sha256, "candidate_content_sha256")
        if candidate_payload_schema_version != CANDIDATE_PAYLOAD_SCHEMA_VERSION:
            raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_CANDIDATE_SCHEMA_INVALID")
        clock = _utc_naive(now)
        row = await self.session.scalar(
            select(SchoolResearchEducationOutputReview)
            .where(
                SchoolResearchEducationOutputReview.output_review_ref == output_review_ref,
                *[
                    getattr(SchoolResearchEducationOutputReview, name) == getattr(scope, name)
                    for name in _SCOPE_FIELDS
                ],
            )
            .with_for_update()
        )
        if row is None:
            raise ForeignKeyConflict("output review was not found in this task scope")
        if row.status != ResearchEducationOutputReviewStatus.PENDING.value or row.state_version != 1:
            raise OptimisticConcurrencyConflict("output review state changed")
        _require_terminal_review_job(await _load_job(self.session, row.job_id), row)
        if _stored_utc_naive(row.expires_at) <= clock or (
            row.retention_due_at is not None and _stored_utc_naive(row.retention_due_at) <= clock
        ):
            raise OptimisticConcurrencyConflict("output review has expired")
        previous = row.status
        async with self.session.begin_nested():
            row.status = ResearchEducationOutputReviewStatus.CONSUMED.value
            row.state_version = 2
            row.candidate_content_sha256 = candidate_content_sha256
            row.candidate_payload_schema_version = candidate_payload_schema_version
            row.resolved_by_membership_role_id = actor_membership_role_id
            row.resolved_at = clock
            row.consumed_at = clock
            row.updated_at = clock
            await self.session.flush()
            self.session.add(_event(
                row,
                actor_membership_role_id,
                ResearchEducationOutputReviewStatus.CONSUMED.value,
                previous,
                ResearchEducationOutputReviewStatus.CONSUMED.value,
                2,
                trace_id,
            ))
            await self.session.flush()
        return await self._dto(row, await _job_ref(self.session, row.job_id))

    async def _validate_authorized_input_grant(
        self,
        job: SchoolResearchEducationJob,
        scope: ResearchEducationOutputReviewScope,
        evidence: ResearchEducationOutputReviewEvidence,
        now: datetime | None,
    ) -> None:
        if job.input_review_id is None or evidence.canonical_input_sha256 is None:
            raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_INPUT_LINEAGE_INVALID")
        from .school_research_education_input_reviews import (
            ResearchEducationInputReviewScope,
            SchoolResearchEducationInputReviewRepository,
        )

        review = await self.session.scalar(
            select(SchoolResearchEducationInputReview)
            .where(
                SchoolResearchEducationInputReview.id == job.input_review_id
            )
            .with_for_update()
        )
        if review is None or review.grant_policy_version is None or review.grant_policy_hash is None:
            raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_INPUT_LINEAGE_INVALID")
        input_scope = ResearchEducationInputReviewScope(**_scope_values(scope))
        validator = SchoolResearchEducationInputReviewRepository(self.session)
        await validator.require_authorized_continuation(
            claim=await _job_claim(self.session, job),
            scope=input_scope,
            grant_policy_version=review.grant_policy_version,
            grant_policy_hash=review.grant_policy_hash,
            source_package_ref=evidence.source_package_ref,
            source_study_ref=evidence.source_study_ref,
            source_manifest_sha256=evidence.source_manifest_sha256,
            prompt_id=evidence.prompt_id,
            prompt_version=evidence.prompt_version,
            prompt_sha256=evidence.prompt_sha256,
            canonical_input_sha256=evidence.canonical_input_sha256,
            now=now,
        )

    async def _dto(
        self, row: SchoolResearchEducationOutputReview, job_ref: str
    ) -> ResearchEducationOutputReviewDTO:
        return ResearchEducationOutputReviewDTO(
            **_summary_kwargs(row, job_ref),
            payload_ciphertext=bytes(row.payload_ciphertext),
            cipher_format_version=row.cipher_format_version,
            key_version=row.key_version,
            payload_schema_version=row.payload_schema_version,
        )


def _validate_scope(scope: ResearchEducationOutputReviewScope) -> None:
    if type(scope) is not ResearchEducationOutputReviewScope:
        raise ResearchEducationOutputReviewError("INVALID_SCOPE")
    for name in ("research_session_id", "school_id", "task_id", "class_id", "task_enrollment_id", "subject_id", "task_binding_id", "profile_version_id", "profile_version_number"):
        _require_id(getattr(scope, name), name)
    _require_token(scope.profile_ref, "profile_ref", 128)
    _require_sha256(scope.profile_sha256, "profile_sha256")
    if scope.response_origin != "PUBLIC_OBSERVED":
        raise ResearchEducationOutputReviewError("INVALID_SCOPE")


def _validate_evidence(
    claim: ResearchEducationJobClaim,
    evidence: ResearchEducationOutputReviewEvidence,
    content_sha256: str,
    payload_ciphertext: bytes,
    cipher_format_version: str,
    key_version: str,
    payload_schema_version: str,
) -> None:
    if type(evidence) is not ResearchEducationOutputReviewEvidence:
        raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_EVIDENCE_INVALID")
    if (
        evidence.safety_operation != "OUTPUT"
        or evidence.safety_action != "REVIEW_REQUIRED"
        or evidence.safety_reason_codes != ("CONTENT_CONTROVERSIAL",)
        or evidence.safety_requires_human is not True
        or evidence.policy_version != GENERAL_EDUCATION_POLICY_VERSION
        or evidence.policy_hash != claim.policy_hash
        or (
            claim.generation_round == 0
            and evidence.input_safety_action not in _SAFE_ACTIONS
        )
        or (
            claim.generation_round == 1
            and evidence.input_safety_action != "REVIEW_REQUIRED"
        )
        or evidence.retrieval_safety_action not in _SAFE_ACTIONS
        or type(claim.attempt_count) is not int
        or claim.attempt_count != 1
        or (claim.generation_round == 0 and evidence.canonical_input_sha256 is not None)
        or (claim.generation_round == 1 and evidence.canonical_input_sha256 is None)
        or evidence.candidate_content_sha256 is not None
        or evidence.candidate_payload_schema_version is not None
        or payload_schema_version != OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION
        or type(payload_ciphertext) is not bytes
        or not payload_ciphertext
        or len(payload_ciphertext) > 1_000_000
        or not _SHA256.fullmatch(content_sha256 if isinstance(content_sha256, str) else "")
    ):
        raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_EVIDENCE_INVALID")
    for name, value, limit in (
        ("safety_decision_id", evidence.safety_decision_id, 160),
        ("safety_review_ref", evidence.safety_review_ref, 160),
        ("safety_trace_id", evidence.safety_trace_id, 160),
        ("source_package_ref", evidence.source_package_ref, 128),
        ("source_study_ref", evidence.source_study_ref, 128),
        ("retrieval_id", evidence.retrieval_id, 128),
        ("prompt_id", evidence.prompt_id, 128),
        ("prompt_version", evidence.prompt_version, 64),
        ("model_ref", evidence.model_ref, 128),
        ("runtime_version", evidence.runtime_version, 64),
        ("safety_policy_version", evidence.safety_policy_version, 64),
        ("trace_id", evidence.trace_id, 128),
        ("cipher_format_version", cipher_format_version, 32),
        ("key_version", key_version, 64),
    ):
        _require_token(value, name, limit)
    for name, value in (
        ("policy_hash", evidence.policy_hash),
        ("source_manifest_sha256", evidence.source_manifest_sha256),
        ("retrieval_bundle_sha256", evidence.retrieval_bundle_sha256),
        ("prompt_sha256", evidence.prompt_sha256),
        ("model_digest_sha256", evidence.model_digest_sha256),
    ):
        _require_sha256(value, name)
    if evidence.canonical_input_sha256 is not None:
        _require_sha256(evidence.canonical_input_sha256, "canonical_input_sha256")
    expected_trace = f"TRACE_{hashlib.sha256(f'{claim.job_ref}:{claim.attempt_count}'.encode('ascii')).hexdigest()[:32]}"
    if evidence.trace_id != expected_trace or evidence.safety_trace_id != expected_trace:
        raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_TRACE_INVALID")


def _require_terminal_review_job(
    job: SchoolResearchEducationJob | None,
    review: SchoolResearchEducationOutputReview,
) -> None:
    if (
        job is None
        or job.id != review.job_id
        or job.generation_round != review.generation_round
        or job.input_review_id != review.input_review_id
        or job.research_session_id != review.research_session_id
        or job.school_id != review.school_id
        or job.status != "REVIEW_REQUIRED"
        or job.last_error_code != "SAFETY_BLOCKED"
        or job.attempt_count != 1
        or job.lease_owner is not None
        or job.lease_token is not None
        or job.lease_expires_at is not None
        or job.policy_version != review.policy_version
        or job.policy_hash != review.policy_hash
        or any(getattr(job, name) != getattr(review, name) for name in _SCOPE_FIELDS)
    ):
        raise ResearchEducationOutputReviewError("OUTPUT_REVIEW_JOB_NOT_CURRENT")


def _same_evidence(
    row: SchoolResearchEducationOutputReview,
    scope: ResearchEducationOutputReviewScope,
    evidence: ResearchEducationOutputReviewEvidence,
    content_sha256: str,
    expires: datetime,
) -> bool:
    if any(getattr(row, name) != getattr(scope, name) for name in _SCOPE_FIELDS):
        return False
    expected = {
        "safety_decision_id": evidence.safety_decision_id,
        "safety_review_ref": evidence.safety_review_ref,
        "safety_trace_id": evidence.safety_trace_id,
        "safety_operation": evidence.safety_operation,
        "safety_action": evidence.safety_action,
        "safety_reason_code": evidence.safety_reason_codes[0],
        "safety_requires_human": evidence.safety_requires_human,
        "input_safety_action": evidence.input_safety_action,
        "retrieval_safety_action": evidence.retrieval_safety_action,
        "canonical_input_sha256": evidence.canonical_input_sha256,
        "policy_version": evidence.policy_version,
        "policy_hash": evidence.policy_hash,
        "source_package_ref": evidence.source_package_ref,
        "source_study_ref": evidence.source_study_ref,
        "source_manifest_sha256": evidence.source_manifest_sha256,
        "retrieval_id": evidence.retrieval_id,
        "retrieval_bundle_sha256": evidence.retrieval_bundle_sha256,
        "prompt_id": evidence.prompt_id,
        "prompt_version": evidence.prompt_version,
        "prompt_sha256": evidence.prompt_sha256,
        "model_ref": evidence.model_ref,
        "model_digest_sha256": evidence.model_digest_sha256,
        "runtime_version": evidence.runtime_version,
        "safety_policy_version": evidence.safety_policy_version,
        "candidate_content_sha256": evidence.candidate_content_sha256,
        "candidate_payload_schema_version": evidence.candidate_payload_schema_version,
        "content_sha256": content_sha256,
        "expires_at": expires,
    }
    return all(
        _stored_utc_naive(getattr(row, name)) == value
        if name == "expires_at"
        else getattr(row, name) == value
        for name, value in expected.items()
    )


def _summary_kwargs(row: SchoolResearchEducationOutputReview, job_ref: str) -> dict[str, object]:
    return {
        "id": row.id,
        "output_review_ref": row.output_review_ref,
        "job_id": row.job_id,
        "job_ref": job_ref,
        "generation_round": row.generation_round,
        "input_review_id": row.input_review_id,
        "scope": ResearchEducationOutputReviewScope(
            **{name: getattr(row, name) for name in _SCOPE_FIELDS}
        ),
        "safety_decision_id": row.safety_decision_id,
        "safety_review_ref": row.safety_review_ref,
        "safety_trace_id": row.safety_trace_id,
        "safety_operation": row.safety_operation,
        "safety_action": row.safety_action,
        "safety_reason_code": row.safety_reason_code,
        "safety_requires_human": row.safety_requires_human,
        "input_safety_action": row.input_safety_action,
        "retrieval_safety_action": row.retrieval_safety_action,
        "canonical_input_sha256": row.canonical_input_sha256,
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "source_package_ref": row.source_package_ref,
        "source_study_ref": row.source_study_ref,
        "source_manifest_sha256": row.source_manifest_sha256,
        "retrieval_id": row.retrieval_id,
        "retrieval_bundle_sha256": row.retrieval_bundle_sha256,
        "prompt_id": row.prompt_id,
        "prompt_version": row.prompt_version,
        "prompt_sha256": row.prompt_sha256,
        "model_ref": row.model_ref,
        "model_digest_sha256": row.model_digest_sha256,
        "runtime_version": row.runtime_version,
        "safety_policy_version": row.safety_policy_version,
        "content_sha256": row.content_sha256,
        "candidate_content_sha256": row.candidate_content_sha256,
        "candidate_payload_schema_version": row.candidate_payload_schema_version,
        "status": row.status,
        "state_version": row.state_version,
        "expires_at": _utc_aware(row.expires_at),
        "resolved_by_membership_role_id": row.resolved_by_membership_role_id,
        "resolved_at": _utc_aware(row.resolved_at),
        "consumed_at": _utc_aware(row.consumed_at),
        "trace_id": row.trace_id,
        "retention_due_at": _utc_aware(row.retention_due_at),
        "created_at": _utc_aware(row.created_at),
        "updated_at": _utc_aware(row.updated_at),
    }


def _summary(
    row: SchoolResearchEducationOutputReview, job_ref: str
) -> ResearchEducationOutputReviewSummaryDTO:
    return ResearchEducationOutputReviewSummaryDTO(**_summary_kwargs(row, job_ref))


def _event(
    row: SchoolResearchEducationOutputReview,
    actor_membership_role_id: int | None,
    event_type: str,
    from_status: str | None,
    to_status: str,
    state_version: int,
    trace_id: str,
) -> SchoolResearchEducationOutputReviewEvent:
    return SchoolResearchEducationOutputReviewEvent(
        output_review_id=row.id,
        research_session_id=row.research_session_id,
        school_id=row.school_id,
        output_review_ref=row.output_review_ref,
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


async def _load_job(session: AsyncSession, job_id: int) -> SchoolResearchEducationJob | None:
    return await session.scalar(
        select(SchoolResearchEducationJob).where(SchoolResearchEducationJob.id == job_id)
    )


def _scope_values(scope: ResearchEducationOutputReviewScope) -> dict[str, object]:
    return {name: getattr(scope, name) for name in _SCOPE_FIELDS}


def _require_id(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ResearchEducationOutputReviewError("INVALID_INPUT")
    return value


def _require_token(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or not value.isascii()
        or _TOKEN.fullmatch(value) is None
    ):
        raise ResearchEducationOutputReviewError("INVALID_INPUT")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ResearchEducationOutputReviewError("INVALID_INPUT")
    return value


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        value = datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchEducationOutputReviewError("INVALID_TIMESTAMP")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None else None


def _stored_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


async def _job_claim(session: AsyncSession, job: SchoolResearchEducationJob) -> ResearchEducationJobClaim:
    from .school_research_education_jobs import _dto as _job_dto

    dto = _job_dto(job)
    return ResearchEducationJobClaim(
        **{name: getattr(dto, name) for name in dto.__dataclass_fields__},
        lease_owner=job.lease_owner,
        lease_token=job.lease_token,
    )
