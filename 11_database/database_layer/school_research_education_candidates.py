"""Ciphertext-only persistence for exact-session education candidates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    SchoolResearchEducationCandidate,
    SchoolResearchEducationCandidateEvent,
    SchoolResearchEducationInputReview,
    SchoolResearchEducationJob,
    SchoolResearchEducationOutputReview,
    SchoolResearchSession,
)
from .school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    ResearchEducationJobClaim,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SAFETY_ACTIONS = frozenset({"PROCEED", "PROCEED_WITH_BOUNDARY"})
_SESSION_SCOPE_FIELDS = (
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


def _continuation_trace_id(job_ref: str, attempt_count: int) -> str:
    token = hashlib.sha256(f"{job_ref}:{attempt_count}".encode("ascii")).hexdigest()[:32]
    return f"TRACE_{token}"

if TYPE_CHECKING:
    from .school_research_education_input_reviews import ResearchEducationInputReviewDTO


class ResearchEducationCandidateError(ValueError):
    """Fixed-code error without candidate text, ciphertext, or session content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchEducationCandidateScope:
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
class ResearchEducationCandidateDTO:
    id: int = field(repr=False)
    public_id: str = field(repr=False)
    candidate_ref: str
    job_id: int = field(repr=False)
    scope: ResearchEducationCandidateScope = field(repr=False)
    study_ref: str
    policy_version: str
    policy_hash: str = field(repr=False)
    source_manifest_sha256: str = field(repr=False)
    retrieval_id: str = field(repr=False)
    retrieval_bundle_sha256: str = field(repr=False)
    prompt_ref: str
    prompt_version: str
    prompt_sha256: str = field(repr=False)
    model_ref: str
    model_digest_sha256: str = field(repr=False)
    runtime_version: str
    safety_policy_version: str
    input_safety_action: str
    retrieval_safety_action: str
    output_safety_action: str
    purpose: str
    research_only: bool
    psychological_interpretation_allowed: bool
    publication_status: str
    content_revision: int
    content_sha256: str = field(repr=False)
    status: str
    state_version: int
    payload_ciphertext: bytes = field(repr=False)
    cipher_format_version: str = field(repr=False)
    key_version: str = field(repr=False)
    payload_schema_version: str = field(repr=False)
    resolved_by_membership_role_id: int | None = field(repr=False)
    resolved_at: datetime | None
    trace_id: str = field(repr=False)
    retention_due_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    generation_round: int = field(default=0, kw_only=True)
    input_review_id: int | None = field(default=None, kw_only=True, repr=False)
    input_review_state: str | None = field(default=None, kw_only=True)
    output_review_id: int | None = field(default=None, kw_only=True, repr=False)
    output_review_state: str | None = field(default=None, kw_only=True)


class SchoolResearchEducationCandidateRepository:
    """Store immutable encrypted candidates and append-only status events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _validate_consumed_review(
        self,
        job: SchoolResearchEducationJob,
        receipt: ResearchEducationInputReviewDTO,
        scope: ResearchEducationCandidateScope,
    ) -> None:
        from .school_research_education_input_reviews import ResearchEducationInputReviewDTO

        if type(receipt) is not ResearchEducationInputReviewDTO:
            raise ResearchEducationCandidateError("INPUT_REVIEW_RECEIPT_INVALID")
        review = await self.session.scalar(
            select(SchoolResearchEducationInputReview)
            .where(
                SchoolResearchEducationInputReview.id == job.input_review_id,
                SchoolResearchEducationInputReview.research_session_id
                == scope.research_session_id,
                SchoolResearchEducationInputReview.school_id == scope.school_id,
            )
            .with_for_update()
        )
        if (
            review is None
            or review.status != "CONSUMED"
            or review.state_version != 3
            or review.consumed_at is None
            or review.original_job_generation_round != 0
            or review.job_id == job.id
            or job.generation_round != 1
            or job.input_review_id != review.id
            or any(getattr(review, name) != getattr(scope, name) for name in _SESSION_SCOPE_FIELDS)
            or review.policy_version != job.policy_version
            or review.policy_hash != job.policy_hash
            or receipt.id != review.id
            or receipt.job_id != review.job_id
            or receipt.input_review_ref != review.input_review_ref
            or receipt.status != review.status
            or receipt.state_version != review.state_version
            or receipt.consumed_at is None
            or _stored_utc_naive(receipt.consumed_at)
            != _stored_utc_naive(review.consumed_at)
            or receipt.grant_policy_version != review.grant_policy_version
            or receipt.grant_policy_hash != review.grant_policy_hash
            or receipt.authorized_by_membership_role_id
            != review.authorized_by_membership_role_id
            or receipt.policy_version != review.policy_version
            or receipt.policy_hash != review.policy_hash
            or receipt.source_package_ref != review.source_package_ref
            or receipt.source_study_ref != review.source_study_ref
            or receipt.source_manifest_sha256 != review.source_manifest_sha256
            or receipt.prompt_id != review.prompt_id
            or receipt.prompt_version != review.prompt_version
            or receipt.prompt_sha256 != review.prompt_sha256
            or receipt.canonical_input_sha256 != review.canonical_input_sha256
            or receipt.safety_action != review.safety_action
            or receipt.safety_reason_code != review.safety_reason_code
            or receipt.safety_requires_human is not review.safety_requires_human
            or receipt.original_job_generation_round != 0
            or any(
                getattr(receipt.scope, name) != getattr(scope, name)
                for name in _SESSION_SCOPE_FIELDS
            )
        ):
            raise ResearchEducationCandidateError("INPUT_REVIEW_LINEAGE_INVALID")
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
            or any(
                getattr(source_job, name) != getattr(scope, name)
                for name in _SESSION_SCOPE_FIELDS
            )
            or source_job.policy_version != review.policy_version
            or source_job.policy_hash != review.policy_hash
        ):
            raise ResearchEducationCandidateError("INPUT_REVIEW_SOURCE_INVALID")

    async def _validate_persisted_lineage(
        self, row: SchoolResearchEducationCandidate
    ) -> None:
        job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == row.job_id,
                SchoolResearchEducationJob.research_session_id == row.research_session_id,
                SchoolResearchEducationJob.school_id == row.school_id,
            )
            .with_for_update()
        )
        if job is None:
            raise ResearchEducationCandidateError("CANDIDATE_JOB_LINEAGE_INVALID")
        if row.output_review_id is None:
            if row.output_review_state is not None or row.output_safety_action not in _SAFE_SAFETY_ACTIONS:
                raise ResearchEducationCandidateError("CANDIDATE_OUTPUT_REVIEW_LINEAGE_INVALID")
        else:
            await self._validate_consumed_output_review(row, job)
        if row.generation_round == 0:
            if (
                row.input_review_id is not None
                or row.input_review_state is not None
                or row.input_safety_action not in _SAFE_SAFETY_ACTIONS
                or job.generation_round != 0
                or job.input_review_id is not None
            ):
                raise ResearchEducationCandidateError("CANDIDATE_ROUND_ZERO_LINEAGE_INVALID")
            return
        if (
            row.generation_round != 1
            or row.input_review_id is None
            or row.input_review_state != "CONSUMED"
            or row.input_safety_action != "REVIEW_REQUIRED"
            or row.retrieval_safety_action not in _SAFE_SAFETY_ACTIONS
            or job.generation_round != 1
            or job.input_review_id != row.input_review_id
            or job.attempt_count != 1
            or (
                row.output_review_id is None
                and row.trace_id != _continuation_trace_id(job.job_ref, job.attempt_count)
            )
        ):
            raise ResearchEducationCandidateError("CANDIDATE_CONTINUATION_LINEAGE_INVALID")
        review = await self.session.scalar(
            select(SchoolResearchEducationInputReview).where(
                SchoolResearchEducationInputReview.id == row.input_review_id,
                SchoolResearchEducationInputReview.status == "CONSUMED",
                SchoolResearchEducationInputReview.state_version == 3,
                SchoolResearchEducationInputReview.research_session_id
                == row.research_session_id,
                SchoolResearchEducationInputReview.school_id == row.school_id,
            )
        )
        if (
            review is None
            or review.consumed_at is None
            or review.original_job_generation_round != 0
            or review.authorized_at is None
            or review.authorized_by_membership_role_id is None
            or review.grant_policy_version is None
            or review.grant_policy_hash is None
            or any(getattr(review, name) != getattr(row, name) for name in _SESSION_SCOPE_FIELDS)
            or review.policy_version != row.policy_version
            or review.policy_hash != row.policy_hash
            or review.source_manifest_sha256 != row.source_manifest_sha256
            or review.prompt_id != row.prompt_ref
            or review.prompt_version != row.prompt_version
            or review.prompt_sha256 != row.prompt_sha256
            or review.safety_operation != "INPUT"
            or review.safety_action != "REVIEW_REQUIRED"
            or review.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or review.safety_requires_human is not True
        ):
            raise ResearchEducationCandidateError("CANDIDATE_CONSUMED_REVIEW_INVALID")
        source_job = await self.session.scalar(
            select(SchoolResearchEducationJob).where(
                SchoolResearchEducationJob.id == review.job_id,
                SchoolResearchEducationJob.generation_round == 0,
                SchoolResearchEducationJob.input_review_id.is_(None),
                SchoolResearchEducationJob.status == "REVIEW_REQUIRED",
                SchoolResearchEducationJob.research_session_id == row.research_session_id,
                SchoolResearchEducationJob.school_id == row.school_id,
            )
        )
        if (
            source_job is None
            or any(
                getattr(source_job, name) != getattr(row, name)
                for name in _SESSION_SCOPE_FIELDS
            )
            or source_job.policy_version != review.policy_version
            or source_job.policy_hash != review.policy_hash
        ):
            raise ResearchEducationCandidateError("CANDIDATE_SOURCE_JOB_INVALID")

    async def _validate_consumed_output_review(
        self,
        candidate: SchoolResearchEducationCandidate,
        job: SchoolResearchEducationJob,
    ) -> None:
        review = await self.session.scalar(
            select(SchoolResearchEducationOutputReview).where(
                SchoolResearchEducationOutputReview.id == candidate.output_review_id,
                SchoolResearchEducationOutputReview.status == "CONSUMED",
                SchoolResearchEducationOutputReview.state_version == 2,
                SchoolResearchEducationOutputReview.research_session_id
                == candidate.research_session_id,
                SchoolResearchEducationOutputReview.school_id == candidate.school_id,
                SchoolResearchEducationOutputReview.job_id == candidate.job_id,
                SchoolResearchEducationOutputReview.generation_round
                == candidate.generation_round,
            )
        )
        if (
            review is None
            or candidate.output_review_state != "CONSUMED"
            or candidate.output_safety_action != "REVIEW_REQUIRED"
            or review.consumed_at is None
            or review.resolved_at is None
            or review.resolved_by_membership_role_id is None
            or review.output_review_ref is None
            or review.status != "CONSUMED"
            or review.safety_operation != "OUTPUT"
            or review.safety_action != "REVIEW_REQUIRED"
            or review.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or review.safety_requires_human is not True
            or review.content_sha256 is None
            or review.candidate_content_sha256 != candidate.content_sha256
            or review.candidate_payload_schema_version != candidate.payload_schema_version
            or review.input_safety_action != candidate.input_safety_action
            or review.retrieval_safety_action != candidate.retrieval_safety_action
            or review.policy_version != candidate.policy_version
            or review.policy_hash != candidate.policy_hash
            or review.source_study_ref != candidate.study_ref
            or review.source_manifest_sha256 != candidate.source_manifest_sha256
            or review.retrieval_id != candidate.retrieval_id
            or review.retrieval_bundle_sha256 != candidate.retrieval_bundle_sha256
            or review.prompt_id != candidate.prompt_ref
            or review.prompt_version != candidate.prompt_version
            or review.prompt_sha256 != candidate.prompt_sha256
            or review.model_ref != candidate.model_ref
            or review.model_digest_sha256 != candidate.model_digest_sha256
            or review.runtime_version != candidate.runtime_version
            or review.safety_policy_version != candidate.safety_policy_version
            or review.trace_id != _continuation_trace_id(job.job_ref, job.attempt_count)
            or any(getattr(review, name) != getattr(candidate, name) for name in _SESSION_SCOPE_FIELDS)
            or any(getattr(job, name) != getattr(candidate, name) for name in _SESSION_SCOPE_FIELDS)
            or job.status != "REVIEW_REQUIRED"
            or job.last_error_code != "SAFETY_BLOCKED"
            or job.attempt_count != 1
            or job.lease_owner is not None
            or job.lease_token is not None
            or job.lease_expires_at is not None
            or job.policy_version != review.policy_version
            or job.policy_hash != review.policy_hash
            or not _TOKEN.fullmatch(candidate.trace_id)
        ):
            raise ResearchEducationCandidateError("CANDIDATE_CONSUMED_OUTPUT_REVIEW_INVALID")

    async def create_held(
        self,
        *,
        claim: ResearchEducationJobClaim,
        scope: ResearchEducationCandidateScope,
        candidate_ref: str,
        study_ref: str,
        policy_version: str,
        policy_hash: str,
        source_manifest_sha256: str,
        retrieval_id: str,
        retrieval_bundle_sha256: str,
        prompt_ref: str,
        prompt_version: str,
        prompt_sha256: str,
        model_ref: str,
        model_digest_sha256: str,
        runtime_version: str,
        safety_policy_version: str,
        input_safety_action: str,
        retrieval_safety_action: str,
        output_safety_action: str,
        content_sha256: str,
        payload_ciphertext: bytes,
        cipher_format_version: str,
        key_version: str,
        payload_schema_version: str,
        trace_id: str,
        input_review: ResearchEducationInputReviewDTO | None = None,
        now: datetime | None = None,
    ) -> ResearchEducationCandidateDTO:
        _validate_scope(scope)
        _require_claim_scope(claim, scope)
        for name, value in (
            ("candidate_ref", candidate_ref),
            ("study_ref", study_ref),
            ("retrieval_id", retrieval_id),
            ("prompt_ref", prompt_ref),
            ("prompt_version", prompt_version),
            ("model_ref", model_ref),
            ("runtime_version", runtime_version),
            ("safety_policy_version", safety_policy_version),
            ("trace_id", trace_id),
        ):
            _require_token(value, name)
        if policy_version != GENERAL_EDUCATION_POLICY_VERSION:
            raise ResearchEducationCandidateError("POLICY_VERSION_INVALID")
        for name, value in (
            ("policy_hash", policy_hash),
            ("source_manifest_sha256", source_manifest_sha256),
            ("retrieval_bundle_sha256", retrieval_bundle_sha256),
            ("prompt_sha256", prompt_sha256),
            ("model_digest_sha256", model_digest_sha256),
            ("content_sha256", content_sha256),
        ):
            _require_sha256(value, name)
        if claim.policy_version != policy_version or claim.policy_hash != policy_hash:
            raise ResearchEducationCandidateError("POLICY_PIN_MISMATCH")
        is_continuation = claim.generation_round == 1
        if (
            retrieval_safety_action not in _SAFE_SAFETY_ACTIONS
            or output_safety_action not in _SAFE_SAFETY_ACTIONS
            or (
                not is_continuation
                and (
                    claim.generation_round != 0
                    or claim.input_review_id is not None
                    or input_review is not None
                    or input_safety_action not in _SAFE_SAFETY_ACTIONS
                )
            )
            or (
                is_continuation
                and (
                    input_safety_action != "REVIEW_REQUIRED"
                    or input_review is None
                    or claim.input_review_id != input_review.id
                    or input_review.status != "CONSUMED"
                    or input_review.state_version != 3
                    or input_review.consumed_at is None
                    or input_review.original_job_generation_round != 0
                    or any(
                        getattr(input_review.scope, name) != getattr(scope, name)
                        for name in _SESSION_SCOPE_FIELDS
                    )
                    or input_review.policy_version != policy_version
                    or input_review.policy_hash != policy_hash
                    or input_review.source_manifest_sha256 != source_manifest_sha256
                    or input_review.prompt_id != prompt_ref
                    or input_review.prompt_version != prompt_version
                    or input_review.prompt_sha256 != prompt_sha256
                )
            )
        ):
            raise ResearchEducationCandidateError("INVALID_SAFETY_DISPOSITION")
        _require_ciphertext(
            payload_ciphertext,
            cipher_format_version,
            key_version,
            payload_schema_version,
        )
        clock = _utc_naive(now)

        job = await self.session.scalar(
            select(SchoolResearchEducationJob)
            .where(
                SchoolResearchEducationJob.id == claim.id,
                SchoolResearchEducationJob.job_ref == claim.job_ref,
                SchoolResearchEducationJob.research_session_id == claim.research_session_id,
                SchoolResearchEducationJob.school_id == claim.school_id,
                SchoolResearchEducationJob.policy_version == policy_version,
                SchoolResearchEducationJob.policy_hash == policy_hash,
                SchoolResearchEducationJob.response_origin == "PUBLIC_OBSERVED",
                SchoolResearchEducationJob.generation_round == claim.generation_round,
                SchoolResearchEducationJob.input_review_id == claim.input_review_id,
                SchoolResearchEducationJob.status == "LEASED",
                SchoolResearchEducationJob.lease_owner == claim.lease_owner,
                SchoolResearchEducationJob.lease_token == claim.lease_token,
                SchoolResearchEducationJob.lease_expires_at > clock,
            )
            .with_for_update()
        )
        if job is None:
            raise OptimisticConcurrencyConflict("research education job lease is stale")
        if any(getattr(job, name) != getattr(scope, name) for name in _SESSION_SCOPE_FIELDS):
            raise ForeignKeyConflict("research candidate session scope was not found")
        if is_continuation:
            if trace_id != _continuation_trace_id(job.job_ref, job.attempt_count):
                raise ResearchEducationCandidateError("INPUT_REVIEW_TRACE_INVALID")
            await self._validate_consumed_review(job, input_review, scope)
        elif job.input_review_id is not None:
            raise ResearchEducationCandidateError("ROUND_ZERO_JOB_HAS_REVIEW_LINEAGE")

        # Select metadata columns only: never materialize the encrypted CAT snapshot.
        completed_session = await self.session.execute(
            select(SchoolResearchSession.id, SchoolResearchSession.retention_due_at)
            .where(
                SchoolResearchSession.id == scope.research_session_id,
                *[
                    getattr(SchoolResearchSession, name) == getattr(scope, name)
                    for name in _SESSION_SCOPE_FIELDS[1:]
                ],
                SchoolResearchSession.status == "COMPLETED",
                SchoolResearchSession.completed_at.is_not(None),
            )
            .with_for_update()
        )
        session_metadata = completed_session.first()
        if session_metadata is None:
            raise ForeignKeyConflict("completed research session scope was not found")

        existing = await self.session.scalar(
            select(SchoolResearchEducationCandidate)
            .where(SchoolResearchEducationCandidate.job_id == job.id)
            .with_for_update()
        )
        if existing is not None:
            await self._validate_persisted_lineage(existing)
            if not _same_candidate(
                existing,
                scope=scope,
                candidate_ref=candidate_ref,
                study_ref=study_ref,
                policy_version=policy_version,
                policy_hash=policy_hash,
                source_manifest_sha256=source_manifest_sha256,
                retrieval_id=retrieval_id,
                retrieval_bundle_sha256=retrieval_bundle_sha256,
                prompt_ref=prompt_ref,
                prompt_version=prompt_version,
                prompt_sha256=prompt_sha256,
                model_ref=model_ref,
                model_digest_sha256=model_digest_sha256,
                runtime_version=runtime_version,
                safety_policy_version=safety_policy_version,
                input_safety_action=input_safety_action,
                retrieval_safety_action=retrieval_safety_action,
                output_safety_action=output_safety_action,
                content_sha256=content_sha256,
                payload_schema_version=payload_schema_version,
                generation_round=claim.generation_round,
                input_review_id=claim.input_review_id,
                input_review_state="CONSUMED" if is_continuation else None,
            ):
                raise UniqueConflict("research candidate replay does not match its held payload")
            return _dto(existing)

        row = SchoolResearchEducationCandidate(
            candidate_ref=candidate_ref,
            job_id=job.id,
            generation_round=claim.generation_round,
            input_review_id=claim.input_review_id,
            input_review_state="CONSUMED" if is_continuation else None,
            **_scope_values(scope),
            study_ref=study_ref,
            policy_version=policy_version,
            policy_hash=policy_hash,
            source_manifest_sha256=source_manifest_sha256,
            retrieval_id=retrieval_id,
            retrieval_bundle_sha256=retrieval_bundle_sha256,
            prompt_ref=prompt_ref,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            model_ref=model_ref,
            model_digest_sha256=model_digest_sha256,
            runtime_version=runtime_version,
            safety_policy_version=safety_policy_version,
            input_safety_action=input_safety_action,
            retrieval_safety_action=retrieval_safety_action,
            output_safety_action=output_safety_action,
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            psychological_interpretation_allowed=False,
            publication_status="not_approved_for_publication_or_operational_use",
            content_revision=1,
            content_sha256=content_sha256,
            status="HELD",
            state_version=1,
            payload_ciphertext=payload_ciphertext,
            cipher_format_version=cipher_format_version,
            key_version=key_version,
            payload_schema_version=payload_schema_version,
            resolved_by_membership_role_id=None,
            resolved_at=None,
            trace_id=trace_id,
            retention_due_at=session_metadata.retention_due_at,
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
                        event_type="HELD",
                        from_status=None,
                        to_status="HELD",
                        state_version=1,
                        trace_id=trace_id,
                        retention_due_at=session_metadata.retention_due_at,
                    )
                )
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(SchoolResearchEducationCandidate).where(
                    SchoolResearchEducationCandidate.job_id == job.id
                )
            )
            if existing is None or not _same_candidate(
                existing,
                scope=scope,
                candidate_ref=candidate_ref,
                study_ref=study_ref,
                policy_version=policy_version,
                policy_hash=policy_hash,
                source_manifest_sha256=source_manifest_sha256,
                retrieval_id=retrieval_id,
                retrieval_bundle_sha256=retrieval_bundle_sha256,
                prompt_ref=prompt_ref,
                prompt_version=prompt_version,
                prompt_sha256=prompt_sha256,
                model_ref=model_ref,
                model_digest_sha256=model_digest_sha256,
                runtime_version=runtime_version,
                safety_policy_version=safety_policy_version,
                input_safety_action=input_safety_action,
                retrieval_safety_action=retrieval_safety_action,
                output_safety_action=output_safety_action,
                content_sha256=content_sha256,
                payload_schema_version=payload_schema_version,
                generation_round=claim.generation_round,
                input_review_id=claim.input_review_id,
                input_review_state="CONSUMED" if is_continuation else None,
            ):
                raise UniqueConflict(
                    "research candidate job already has a different payload"
                ) from None
            await self._validate_persisted_lineage(existing)
            return _dto(existing)
        return _dto(row)

    async def create_held_from_output_review(
        self,
        *,
        scope: ResearchEducationCandidateScope,
        output_review_ref: str,
        candidate_ref: str,
        content_sha256: str,
        payload_ciphertext: bytes,
        cipher_format_version: str,
        key_version: str,
        payload_schema_version: str = "school-research-general-education-candidate.v1",
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationCandidateDTO:
        """Atomically consume review sidecars and insert a candidate in one savepoint."""
        async with self.session.begin_nested():
            return await self._create_held_from_output_review_unchecked(
                scope=scope,
                output_review_ref=output_review_ref,
                candidate_ref=candidate_ref,
                content_sha256=content_sha256,
                payload_ciphertext=payload_ciphertext,
                cipher_format_version=cipher_format_version,
                key_version=key_version,
                payload_schema_version=payload_schema_version,
                actor_membership_role_id=actor_membership_role_id,
                trace_id=trace_id,
                now=now,
            )

    async def _create_held_from_output_review_unchecked(
        self,
        *,
        scope: ResearchEducationCandidateScope,
        output_review_ref: str,
        candidate_ref: str,
        content_sha256: str,
        payload_ciphertext: bytes,
        cipher_format_version: str,
        key_version: str,
        payload_schema_version: str = "school-research-general-education-candidate.v1",
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationCandidateDTO:
        """Consume a reviewed safety stop and persist one immutable HELD candidate."""
        _validate_scope(scope)
        _require_token(output_review_ref, "output_review_ref")
        _require_token(candidate_ref, "candidate_ref")
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        _require_token(trace_id, "trace_id")
        _require_sha256(content_sha256, "content_sha256")
        _require_ciphertext(
            payload_ciphertext, cipher_format_version, key_version, payload_schema_version
        )
        if payload_schema_version != "school-research-general-education-candidate.v1":
            raise ResearchEducationCandidateError("INVALID_OUTPUT_REVIEW_CANDIDATE_SCHEMA")
        from .school_research_education_output_reviews import (
            OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
            ResearchEducationOutputReviewScope,
            ResearchEducationOutputReviewStatus,
            SchoolResearchEducationOutputReviewRepository,
        )
        from .school_research_education_input_reviews import (
            ResearchEducationInputReviewScope,
            SchoolResearchEducationInputReviewRepository,
        )

        review_scope = ResearchEducationOutputReviewScope(**_scope_values(scope))
        output_reviews = SchoolResearchEducationOutputReviewRepository(self.session)
        review_dto = await output_reviews.get_for_task(
            scope=review_scope, output_review_ref=output_review_ref
        )
        if review_dto is None:
            raise ForeignKeyConflict("output review was not found in this task scope")
        if (
            review_dto.payload_schema_version != OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION
            or (
                review_dto.status == "PENDING"
                and (
                    review_dto.candidate_payload_schema_version is not None
                    or review_dto.candidate_content_sha256 is not None
                )
            )
            or (
                review_dto.status == "CONSUMED"
                and (
                    review_dto.candidate_payload_schema_version != payload_schema_version
                    or review_dto.candidate_content_sha256 != content_sha256
                )
            )
            or review_dto.policy_version != GENERAL_EDUCATION_POLICY_VERSION
            or review_dto.status not in {"PENDING", "CONSUMED"}
        ):
            raise ResearchEducationCandidateError("OUTPUT_REVIEW_CANDIDATE_PINS_INVALID")

        job_stmt = select(SchoolResearchEducationJob).where(
                SchoolResearchEducationJob.id == review_dto.job_id,
                SchoolResearchEducationJob.job_ref == review_dto.job_ref,
                SchoolResearchEducationJob.generation_round == review_dto.generation_round,
                SchoolResearchEducationJob.input_review_id == review_dto.input_review_id,
                SchoolResearchEducationJob.research_session_id == scope.research_session_id,
                SchoolResearchEducationJob.school_id == scope.school_id,
            )
        if review_dto.generation_round == 0:
            job_stmt = job_stmt.with_for_update()
        job = await self.session.scalar(job_stmt)
        if (
            job is None
            or job.status != "REVIEW_REQUIRED"
            or job.last_error_code != "SAFETY_BLOCKED"
            or job.attempt_count != 1
            or job.lease_owner is not None
            or job.lease_token is not None
            or job.lease_expires_at is not None
            or job.generation_round not in {0, 1}
            or any(getattr(job, name) != getattr(scope, name) for name in _SESSION_SCOPE_FIELDS)
            or job.policy_version != review_dto.policy_version
            or job.policy_hash != review_dto.policy_hash
            or review_dto.trace_id != _continuation_trace_id(job.job_ref, job.attempt_count)
            or review_dto.safety_trace_id != review_dto.trace_id
            or review_dto.safety_operation != "OUTPUT"
            or review_dto.safety_action != "REVIEW_REQUIRED"
            or review_dto.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or review_dto.safety_requires_human is not True
            or review_dto.input_safety_action != (
                "REVIEW_REQUIRED" if job.generation_round == 1 else review_dto.input_safety_action
            )
            or (job.generation_round == 0 and review_dto.input_safety_action not in _SAFE_SAFETY_ACTIONS)
            or review_dto.retrieval_safety_action not in _SAFE_SAFETY_ACTIONS
            or review_dto.policy_version != GENERAL_EDUCATION_POLICY_VERSION
            or review_dto.expires_at.replace(tzinfo=None) <= _utc_naive(now)
            or review_dto.retention_due_at is not None
            and review_dto.retention_due_at.replace(tzinfo=None) <= _utc_naive(now)
        ):
            raise ResearchEducationCandidateError("OUTPUT_REVIEW_JOB_NOT_CURRENT")

        existing = await self.session.scalar(
            select(SchoolResearchEducationCandidate)
            .where(SchoolResearchEducationCandidate.job_id == job.id)
            .with_for_update()
        )
        if existing is not None:
            await self._validate_persisted_lineage(existing)
            if not _same_candidate(
                existing,
                scope=scope,
                candidate_ref=candidate_ref,
                study_ref=review_dto.source_study_ref,
                policy_version=review_dto.policy_version,
                policy_hash=review_dto.policy_hash,
                source_manifest_sha256=review_dto.source_manifest_sha256,
                retrieval_id=review_dto.retrieval_id,
                retrieval_bundle_sha256=review_dto.retrieval_bundle_sha256,
                prompt_ref=review_dto.prompt_id,
                prompt_version=review_dto.prompt_version,
                prompt_sha256=review_dto.prompt_sha256,
                model_ref=review_dto.model_ref,
                model_digest_sha256=review_dto.model_digest_sha256,
                runtime_version=review_dto.runtime_version,
                safety_policy_version=review_dto.safety_policy_version,
                input_safety_action=review_dto.input_safety_action,
                retrieval_safety_action=review_dto.retrieval_safety_action,
                output_safety_action="REVIEW_REQUIRED",
                content_sha256=content_sha256,
                payload_schema_version=payload_schema_version,
                generation_round=job.generation_round,
                input_review_id=job.input_review_id,
                input_review_state="CONSUMED" if job.generation_round == 1 else None,
                output_review_id=review_dto.id,
                output_review_state="CONSUMED",
            ):
                raise UniqueConflict("job already has a different output-review candidate")
            return _dto(existing)

        input_review = None
        clock = _utc_naive(now)
        if job.generation_round == 1:
            if job.input_review_id is None or review_dto.canonical_input_sha256 is None:
                raise ResearchEducationCandidateError("OUTPUT_REVIEW_INPUT_LINEAGE_INVALID")
            persisted_input = await self.session.scalar(
                select(SchoolResearchEducationInputReview)
                .where(SchoolResearchEducationInputReview.id == job.input_review_id)
                .with_for_update()
            )
            if (
                persisted_input is None
                or persisted_input.grant_policy_version is None
                or persisted_input.grant_policy_hash is None
            ):
                raise ResearchEducationCandidateError("OUTPUT_REVIEW_INPUT_LINEAGE_INVALID")
            input_reviews = SchoolResearchEducationInputReviewRepository(self.session)
            input_review = await input_reviews.consume_authorized_input_for_output_review_candidate(
                output_review_ref=output_review_ref,
                scope=ResearchEducationInputReviewScope(**_scope_values(scope)),
                grant_policy_version=persisted_input.grant_policy_version,
                grant_policy_hash=persisted_input.grant_policy_hash,
                source_package_ref=review_dto.source_package_ref,
                source_study_ref=review_dto.source_study_ref,
                source_manifest_sha256=review_dto.source_manifest_sha256,
                prompt_id=review_dto.prompt_id,
                prompt_version=review_dto.prompt_version,
                prompt_sha256=review_dto.prompt_sha256,
                canonical_input_sha256=review_dto.canonical_input_sha256,
                trace_id=trace_id,
                now=now,
            )

        async with self.session.begin_nested():
            consumed_review = await output_reviews.consume_for_candidate(
                scope=review_scope,
                output_review_ref=output_review_ref,
                actor_membership_role_id=actor_membership_role_id,
                trace_id=trace_id,
                candidate_content_sha256=content_sha256,
                candidate_payload_schema_version=payload_schema_version,
                now=now,
            )
            session_result = await self.session.execute(
                select(SchoolResearchSession.id, SchoolResearchSession.retention_due_at)
                .where(
                    SchoolResearchSession.id == scope.research_session_id,
                    *[
                        getattr(SchoolResearchSession, name) == getattr(scope, name)
                        for name in _SESSION_SCOPE_FIELDS[1:]
                    ],
                    SchoolResearchSession.status == "COMPLETED",
                    SchoolResearchSession.completed_at.is_not(None),
                )
                .with_for_update()
            )
            session_row = session_result.first()
            if session_row is None:
                raise ForeignKeyConflict("completed research session scope was not found")
            retention_due_at = session_row.retention_due_at
            if (
                retention_due_at is not None
                and _stored_utc_naive(retention_due_at) <= clock
            ):
                raise ResearchEducationCandidateError("CANDIDATE_RETENTION_EXPIRED")
            row = SchoolResearchEducationCandidate(
                candidate_ref=candidate_ref,
                job_id=job.id,
                generation_round=job.generation_round,
                input_review_id=input_review.id if input_review is not None else None,
                input_review_state="CONSUMED" if input_review is not None else None,
                output_review_id=consumed_review.id,
                output_review_state="CONSUMED",
                **_scope_values(scope),
                study_ref=consumed_review.source_study_ref,
                policy_version=consumed_review.policy_version,
                policy_hash=consumed_review.policy_hash,
                source_manifest_sha256=consumed_review.source_manifest_sha256,
                retrieval_id=consumed_review.retrieval_id,
                retrieval_bundle_sha256=consumed_review.retrieval_bundle_sha256,
                prompt_ref=consumed_review.prompt_id,
                prompt_version=consumed_review.prompt_version,
                prompt_sha256=consumed_review.prompt_sha256,
                model_ref=consumed_review.model_ref,
                model_digest_sha256=consumed_review.model_digest_sha256,
                runtime_version=consumed_review.runtime_version,
                safety_policy_version=consumed_review.safety_policy_version,
                input_safety_action=consumed_review.input_safety_action,
                retrieval_safety_action=consumed_review.retrieval_safety_action,
                output_safety_action="REVIEW_REQUIRED",
                purpose="RESEARCH_SIMULATION",
                research_only=True,
                psychological_interpretation_allowed=False,
                publication_status="not_approved_for_publication_or_operational_use",
                content_revision=1,
                content_sha256=content_sha256,
                status="HELD",
                state_version=1,
                payload_ciphertext=payload_ciphertext,
                cipher_format_version=cipher_format_version,
                key_version=key_version,
                payload_schema_version=payload_schema_version,
                resolved_by_membership_role_id=None,
                resolved_at=None,
                trace_id=trace_id,
                retention_due_at=retention_due_at,
                created_at=clock,
                updated_at=clock,
            )
            try:
                self.session.add(row)
                await self.session.flush()
                self.session.add(
                    _event(
                        row,
                        actor_membership_role_id=None,
                        event_type="HELD",
                        from_status=None,
                        to_status="HELD",
                        state_version=1,
                        trace_id=trace_id,
                        retention_due_at=retention_due_at,
                    )
                )
                await self.session.flush()
            except IntegrityError as exc:
                raise UniqueConflict("output-review candidate conflicts with an existing row") from exc
        return _dto(row)

    async def get_for_task(
        self, *, school_id: int, task_id: int, candidate_ref: str
    ) -> ResearchEducationCandidateDTO | None:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        _require_token(candidate_ref, "candidate_ref")
        row = await self.session.scalar(
            select(SchoolResearchEducationCandidate).where(
                SchoolResearchEducationCandidate.school_id == school_id,
                SchoolResearchEducationCandidate.task_id == task_id,
                SchoolResearchEducationCandidate.candidate_ref == candidate_ref,
            )
        )
        if row is not None:
            await self._validate_persisted_lineage(row)
        return _dto(row) if row is not None else None

    async def list_for_task(
        self,
        *,
        school_id: int,
        task_id: int,
        status: str = "HELD",
        limit: int = 20,
        offset: int = 0,
    ) -> list[ResearchEducationCandidateDTO]:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        if status not in {"HELD", "ADOPTED", "DISCARDED"}:
            raise ResearchEducationCandidateError("INVALID_STATUS")
        _require_bounded_int(limit, "limit", 1, 50)
        _require_bounded_int(offset, "offset", 0, 100_000)
        rows = await self.session.scalars(
            select(SchoolResearchEducationCandidate)
            .where(
                SchoolResearchEducationCandidate.school_id == school_id,
                SchoolResearchEducationCandidate.task_id == task_id,
                SchoolResearchEducationCandidate.status == status,
            )
            .order_by(
                SchoolResearchEducationCandidate.created_at.desc(),
                SchoolResearchEducationCandidate.candidate_ref,
            )
            .limit(limit)
            .offset(offset)
        )
        result = list(rows.all())
        for row in result:
            await self._validate_persisted_lineage(row)
        return [_dto(row) for row in result]

    async def resolve(
        self,
        *,
        school_id: int,
        task_id: int,
        candidate_ref: str,
        expected_state_version: int,
        target: Literal["ADOPTED", "DISCARDED"],
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ResearchEducationCandidateDTO:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        _require_token(candidate_ref, "candidate_ref")
        _require_token(trace_id, "trace_id")
        _require_bounded_int(expected_state_version, "expected_state_version", 1, 2_147_483_647)
        if target not in {"ADOPTED", "DISCARDED"}:
            raise ResearchEducationCandidateError("INVALID_TRANSITION")
        row = await self.session.scalar(
            select(SchoolResearchEducationCandidate)
            .where(
                SchoolResearchEducationCandidate.school_id == school_id,
                SchoolResearchEducationCandidate.task_id == task_id,
                SchoolResearchEducationCandidate.candidate_ref == candidate_ref,
            )
            .with_for_update()
        )
        if row is None:
            raise ForeignKeyConflict("research education candidate was not found")
        await self._validate_persisted_lineage(row)
        if row.status != "HELD" or row.state_version != expected_state_version:
            raise OptimisticConcurrencyConflict("research education candidate version is stale")
        previous = row.status
        row.status = target
        row.state_version += 1
        row.resolved_by_membership_role_id = actor_membership_role_id
        row.resolved_at = _utc_naive(now)
        row.updated_at = row.resolved_at
        self.session.add(
            _event(
                row,
                actor_membership_role_id=actor_membership_role_id,
                event_type=target,
                from_status=previous,
                to_status=target,
                state_version=row.state_version,
                trace_id=trace_id,
                retention_due_at=row.retention_due_at,
            )
        )
        await self.session.flush()
        return _dto(row)


def _event(
    row: SchoolResearchEducationCandidate,
    *,
    actor_membership_role_id: int | None,
    event_type: str,
    from_status: str | None,
    to_status: str,
    state_version: int,
    trace_id: str,
    retention_due_at: datetime | None,
) -> SchoolResearchEducationCandidateEvent:
    return SchoolResearchEducationCandidateEvent(
        candidate_id=row.id,
        research_session_id=row.research_session_id,
        school_id=row.school_id,
        candidate_ref=row.candidate_ref,
        candidate_revision=row.content_revision,
        actor_membership_role_id=actor_membership_role_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        state_version=state_version,
        trace_id=trace_id,
        retention_due_at=retention_due_at,
    )


def _dto(row: SchoolResearchEducationCandidate) -> ResearchEducationCandidateDTO:
    return ResearchEducationCandidateDTO(
        id=row.id,
        public_id=row.public_id,
        candidate_ref=row.candidate_ref,
        job_id=row.job_id,
        scope=ResearchEducationCandidateScope(
            **{name: getattr(row, name) for name in _SESSION_SCOPE_FIELDS}
        ),
        study_ref=row.study_ref,
        policy_version=row.policy_version,
        policy_hash=row.policy_hash,
        source_manifest_sha256=row.source_manifest_sha256,
        retrieval_id=row.retrieval_id,
        retrieval_bundle_sha256=row.retrieval_bundle_sha256,
        prompt_ref=row.prompt_ref,
        prompt_version=row.prompt_version,
        prompt_sha256=row.prompt_sha256,
        model_ref=row.model_ref,
        model_digest_sha256=row.model_digest_sha256,
        runtime_version=row.runtime_version,
        safety_policy_version=row.safety_policy_version,
        input_safety_action=row.input_safety_action,
        retrieval_safety_action=row.retrieval_safety_action,
        output_safety_action=row.output_safety_action,
        purpose=row.purpose,
        research_only=row.research_only,
        psychological_interpretation_allowed=row.psychological_interpretation_allowed,
        publication_status=row.publication_status,
        content_revision=row.content_revision,
        content_sha256=row.content_sha256,
        status=row.status,
        state_version=row.state_version,
        payload_ciphertext=row.payload_ciphertext,
        cipher_format_version=row.cipher_format_version,
        key_version=row.key_version,
        payload_schema_version=row.payload_schema_version,
        resolved_by_membership_role_id=row.resolved_by_membership_role_id,
        resolved_at=_utc_aware(row.resolved_at),
        trace_id=row.trace_id,
        retention_due_at=_utc_aware(row.retention_due_at),
        created_at=_required_utc_aware(row.created_at),
        updated_at=_required_utc_aware(row.updated_at),
        generation_round=row.generation_round,
        input_review_id=row.input_review_id,
        input_review_state=row.input_review_state,
        output_review_id=row.output_review_id,
        output_review_state=row.output_review_state,
    )


def _same_candidate(row, **expected) -> bool:
    scope = expected.pop("scope")
    return (
        all(getattr(row, name) == getattr(scope, name) for name in _SESSION_SCOPE_FIELDS)
        and all(getattr(row, name) == value for name, value in expected.items())
    )


def _scope_values(scope: ResearchEducationCandidateScope) -> dict[str, object]:
    return {name: getattr(scope, name) for name in _SESSION_SCOPE_FIELDS}


def _validate_scope(scope: ResearchEducationCandidateScope) -> None:
    if type(scope) is not ResearchEducationCandidateScope:
        raise ResearchEducationCandidateError("INVALID_SCOPE")
    for name in (
        "research_session_id", "school_id", "task_id", "class_id", "task_enrollment_id",
        "subject_id", "task_binding_id", "profile_version_id",
    ):
        _require_id(getattr(scope, name), name)
    _require_token(scope.profile_ref, "profile_ref")
    _require_bounded_int(scope.profile_version_number, "profile_version_number", 1, 2_147_483_647)
    _require_sha256(scope.profile_sha256, "profile_sha256")
    if scope.response_origin != "PUBLIC_OBSERVED":
        raise ResearchEducationCandidateError("RESPONSE_ORIGIN_NOT_AUTHORIZED")


def _require_claim_scope(
    claim: ResearchEducationJobClaim, scope: ResearchEducationCandidateScope
) -> None:
    if (
        type(claim) is not ResearchEducationJobClaim
        or claim.status != "LEASED"
        or claim.policy_version != GENERAL_EDUCATION_POLICY_VERSION
        or claim.response_origin != "PUBLIC_OBSERVED"
        or claim.generation_round not in {0, 1}
        or (claim.generation_round == 0 and claim.input_review_id is not None)
        or (claim.generation_round == 1 and claim.input_review_id is None)
        or (claim.generation_round == 1 and claim.attempt_count != 1)
        or any(getattr(claim, name) != getattr(scope, name) for name in _SESSION_SCOPE_FIELDS)
    ):
        raise ResearchEducationCandidateError("JOB_CLAIM_SCOPE_INVALID")
    _require_id(claim.id, "job_id")
    _require_token(claim.job_ref, "job_ref")
    _require_token(claim.lease_owner, "lease_owner")
    _require_token(claim.lease_token, "lease_token")


def _require_id(value: object, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ResearchEducationCandidateError("INVALID_INPUT")


def _require_token(value: object, name: str) -> None:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ResearchEducationCandidateError("INVALID_INPUT")


def _require_sha256(value: object, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ResearchEducationCandidateError("INVALID_INPUT")


def _require_bounded_int(value: object, name: str, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise ResearchEducationCandidateError("INVALID_INPUT")


def _require_ciphertext(
    ciphertext: object,
    cipher_format_version: object,
    key_version: object,
    payload_schema_version: object,
) -> None:
    if (
        not isinstance(ciphertext, bytes)
        or not ciphertext
        or len(ciphertext) > 1_000_000
        or any(
            not isinstance(value, str) or _TOKEN.fullmatch(value) is None
            for value in (cipher_format_version, key_version, payload_schema_version)
        )
    ):
        raise ResearchEducationCandidateError("INVALID_ENCRYPTED_PAYLOAD")


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchEducationCandidateError("INVALID_TIMESTAMP")
    return value.astimezone(UTC).replace(tzinfo=None)


def _stored_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_utc_aware(value: datetime | None) -> datetime:
    result = _utc_aware(value)
    if result is None:
        raise ResearchEducationCandidateError("PERSISTED_TIMESTAMP_INVALID")
    return result


__all__ = [
    "ResearchEducationCandidateDTO",
    "ResearchEducationCandidateError",
    "ResearchEducationCandidateScope",
    "SchoolResearchEducationCandidateRepository",
]
