"""Ciphertext-only persistence for exact-session education candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    SchoolResearchEducationCandidate,
    SchoolResearchEducationCandidateEvent,
    SchoolResearchEducationJob,
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


class SchoolResearchEducationCandidateRepository:
    """Store immutable encrypted candidates and append-only status events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        if any(action not in _SAFE_SAFETY_ACTIONS for action in (
            input_safety_action, retrieval_safety_action, output_safety_action
        )):
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
            ):
                raise UniqueConflict("research candidate replay does not match its held payload")
            return _dto(existing)

        row = SchoolResearchEducationCandidate(
            candidate_ref=candidate_ref,
            job_id=job.id,
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
            ):
                raise UniqueConflict(
                    "research candidate job already has a different payload"
                ) from None
            return _dto(existing)
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
        return [_dto(row) for row in rows.all()]

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
        resolved_at=row.resolved_at,
        trace_id=row.trace_id,
        retention_due_at=row.retention_due_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
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


__all__ = [
    "ResearchEducationCandidateDTO",
    "ResearchEducationCandidateError",
    "ResearchEducationCandidateScope",
    "SchoolResearchEducationCandidateRepository",
]
