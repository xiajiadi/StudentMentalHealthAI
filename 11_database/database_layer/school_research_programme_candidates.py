"""Encrypted task-level programme candidates awaiting specialist adoption."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import SchoolResearchProgrammeCandidate, SchoolResearchTaskBinding

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SAFETY_ACTIONS = frozenset({"PROCEED", "PROCEED_WITH_BOUNDARY"})
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"


class ResearchProgrammeCandidateError(ValueError):
    """Fixed-code error; messages never contain source text or ciphertext."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchProgrammeCandidateScope:
    school_id: int = field(repr=False)
    task_id: int = field(repr=False)
    class_id: int = field(repr=False)
    task_binding_id: int = field(repr=False)
    profile_version_id: int = field(repr=False)
    profile_ref: str = field(repr=False)
    profile_version_number: int = field(repr=False)
    profile_sha256: str = field(repr=False)
    response_origin: str = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchProgrammeCandidateDTO:
    id: int = field(repr=False)
    public_id: str = field(repr=False)
    candidate_ref: str
    scope: ResearchProgrammeCandidateScope = field(repr=False)
    study_ref: str
    study_policy_sha256: str = field(repr=False)
    processor_policy_sha256: str = field(repr=False)
    programme_ref: str
    source_manifest_sha256: str = field(repr=False)
    source_set_sha256: str = field(repr=False)
    retrieval_id: str = field(repr=False)
    retrieval_bundle_sha256: str = field(repr=False)
    chunk_set_sha256: str = field(repr=False)
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
    claim_boundary_version: str
    claim_boundary_status: str
    purpose: str
    research_only: bool
    psychological_interpretation_allowed: bool
    publication_status: str
    output_boundary: str
    status: str
    state_version: int
    payload_ciphertext: bytes = field(repr=False)
    cipher_format_version: str = field(repr=False)
    key_version: str = field(repr=False)
    payload_schema_version: str = field(repr=False)
    resolved_by_membership_role_id: int | None = field(default=None, repr=False)
    resolved_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SchoolResearchProgrammeCandidateRepository:
    """Ciphertext-only repository participating in the caller transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_held(
        self,
        *,
        scope: ResearchProgrammeCandidateScope,
        candidate_ref: str,
        study_ref: str,
        study_policy_sha256: str,
        processor_policy_sha256: str,
        programme_ref: str,
        source_manifest_sha256: str,
        source_set_sha256: str,
        retrieval_id: str,
        retrieval_bundle_sha256: str,
        chunk_set_sha256: str,
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
        claim_boundary_version: str,
        claim_boundary_status: str,
        payload_ciphertext: bytes,
        cipher_format_version: str,
        key_version: str,
        payload_schema_version: str,
        now: datetime | None = None,
    ) -> ResearchProgrammeCandidateDTO:
        _validate_scope(scope)
        for name, value in (
            ("candidate_ref", candidate_ref),
            ("study_ref", study_ref),
            ("programme_ref", programme_ref),
            ("retrieval_id", retrieval_id),
            ("prompt_ref", prompt_ref),
            ("prompt_version", prompt_version),
            ("model_ref", model_ref),
            ("runtime_version", runtime_version),
            ("safety_policy_version", safety_policy_version),
            ("claim_boundary_version", claim_boundary_version),
        ):
            _require_token(value, name)
        for name, value in (
            ("study_policy_sha256", study_policy_sha256),
            ("processor_policy_sha256", processor_policy_sha256),
            ("source_manifest_sha256", source_manifest_sha256),
            ("source_set_sha256", source_set_sha256),
            ("retrieval_bundle_sha256", retrieval_bundle_sha256),
            ("chunk_set_sha256", chunk_set_sha256),
            ("prompt_sha256", prompt_sha256),
            ("model_digest_sha256", model_digest_sha256),
        ):
            _require_sha256(value, name)
        if any(action not in _SAFE_SAFETY_ACTIONS for action in (
            input_safety_action, retrieval_safety_action, output_safety_action
        )):
            raise ResearchProgrammeCandidateError("INVALID_SAFETY_DISPOSITION")
        if claim_boundary_status != "ACCEPTED":
            raise ResearchProgrammeCandidateError("CLAIM_BOUNDARY_REJECTED")
        _require_ciphertext(
            payload_ciphertext,
            cipher_format_version,
            key_version,
            payload_schema_version,
        )
        clock = _utc_naive(now)

        binding = await self.session.scalar(
            select(SchoolResearchTaskBinding)
            .where(
                SchoolResearchTaskBinding.id == scope.task_binding_id,
                SchoolResearchTaskBinding.school_id == scope.school_id,
                SchoolResearchTaskBinding.task_id == scope.task_id,
                SchoolResearchTaskBinding.class_id == scope.class_id,
                SchoolResearchTaskBinding.profile_version_id == scope.profile_version_id,
                SchoolResearchTaskBinding.profile_ref == scope.profile_ref,
                SchoolResearchTaskBinding.profile_version_number == scope.profile_version_number,
                SchoolResearchTaskBinding.profile_sha256 == scope.profile_sha256,
                SchoolResearchTaskBinding.response_origin == scope.response_origin,
                SchoolResearchTaskBinding.status == "ACTIVE",
                SchoolResearchTaskBinding.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if binding is None:
            raise ForeignKeyConflict("research programme task binding is unavailable")

        pins = _candidate_pins(
            scope=scope,
            study_ref=study_ref,
            study_policy_sha256=study_policy_sha256,
            processor_policy_sha256=processor_policy_sha256,
            programme_ref=programme_ref,
            source_manifest_sha256=source_manifest_sha256,
            source_set_sha256=source_set_sha256,
            retrieval_id=retrieval_id,
            retrieval_bundle_sha256=retrieval_bundle_sha256,
            chunk_set_sha256=chunk_set_sha256,
            prompt_ref=prompt_ref,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            model_ref=model_ref,
            model_digest_sha256=model_digest_sha256,
            runtime_version=runtime_version,
            safety_policy_version=safety_policy_version,
            claim_boundary_version=claim_boundary_version,
        )
        existing = await self.session.scalar(
            select(SchoolResearchProgrammeCandidate)
            .where(*_pin_predicates(SchoolResearchProgrammeCandidate, pins))
            .with_for_update()
        )
        if existing is not None:
            return _dto(existing)

        row = SchoolResearchProgrammeCandidate(
            candidate_ref=candidate_ref,
            **_scope_values(scope),
            study_ref=study_ref,
            study_policy_sha256=study_policy_sha256,
            processor_policy_sha256=processor_policy_sha256,
            programme_ref=programme_ref,
            source_manifest_sha256=source_manifest_sha256,
            source_set_sha256=source_set_sha256,
            retrieval_id=retrieval_id,
            retrieval_bundle_sha256=retrieval_bundle_sha256,
            chunk_set_sha256=chunk_set_sha256,
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
            claim_boundary_version=claim_boundary_version,
            claim_boundary_status=claim_boundary_status,
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            psychological_interpretation_allowed=False,
            publication_status=_PUBLICATION_STATUS,
            output_boundary="STAFF_REFERENCE_ONLY",
            status="HELD",
            state_version=1,
            payload_ciphertext=payload_ciphertext,
            cipher_format_version=cipher_format_version,
            key_version=key_version,
            payload_schema_version=payload_schema_version,
            resolved_by_membership_role_id=None,
            resolved_at=None,
            created_at=clock,
            updated_at=clock,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(SchoolResearchProgrammeCandidate).where(
                    *_pin_predicates(SchoolResearchProgrammeCandidate, pins)
                )
            )
            if existing is None:
                raise UniqueConflict("research programme candidate pin conflicts") from None
            return _dto(existing)
        return _dto(row)

    async def get(
        self, *, school_id: int, task_id: int, candidate_ref: str, lock: bool = False
    ) -> ResearchProgrammeCandidateDTO | None:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        _require_token(candidate_ref, "candidate_ref")
        stmt = select(SchoolResearchProgrammeCandidate).where(
            SchoolResearchProgrammeCandidate.school_id == school_id,
            SchoolResearchProgrammeCandidate.task_id == task_id,
            SchoolResearchProgrammeCandidate.candidate_ref == candidate_ref,
        )
        if lock:
            stmt = stmt.with_for_update()
        row = await self.session.scalar(stmt)
        return _dto(row) if row is not None else None

    async def list_for_task(
        self,
        *,
        school_id: int,
        task_id: int,
        status: str = "HELD",
        limit: int = 20,
        offset: int = 0,
    ) -> list[ResearchProgrammeCandidateDTO]:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        if status not in {"HELD", "ADOPTED", "DISCARDED"}:
            raise ResearchProgrammeCandidateError("INVALID_STATUS")
        _require_bounded_int(limit, 1, 50, "limit")
        _require_bounded_int(offset, 0, 100_000, "offset")
        rows = await self.session.scalars(
            select(SchoolResearchProgrammeCandidate)
            .where(
                SchoolResearchProgrammeCandidate.school_id == school_id,
                SchoolResearchProgrammeCandidate.task_id == task_id,
                SchoolResearchProgrammeCandidate.status == status,
            )
            .order_by(
                SchoolResearchProgrammeCandidate.created_at.desc(),
                SchoolResearchProgrammeCandidate.candidate_ref,
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
        now: datetime | None = None,
    ) -> ResearchProgrammeCandidateDTO:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        _require_token(candidate_ref, "candidate_ref")
        _require_bounded_int(expected_state_version, 1, 2_147_483_647, "expected_state_version")
        if target not in {"ADOPTED", "DISCARDED"}:
            raise ResearchProgrammeCandidateError("INVALID_TRANSITION")
        row = await self.session.scalar(
            select(SchoolResearchProgrammeCandidate)
            .where(
                SchoolResearchProgrammeCandidate.school_id == school_id,
                SchoolResearchProgrammeCandidate.task_id == task_id,
                SchoolResearchProgrammeCandidate.candidate_ref == candidate_ref,
            )
            .with_for_update()
        )
        if row is None:
            raise ForeignKeyConflict("research programme candidate was not found")
        if row.status != "HELD" or row.state_version != expected_state_version:
            raise OptimisticConcurrencyConflict("research programme candidate version is stale")
        row.status = target
        row.state_version = 2
        row.resolved_by_membership_role_id = actor_membership_role_id
        row.resolved_at = _utc_naive(now)
        row.updated_at = row.resolved_at
        await self.session.flush()
        return _dto(row)


def _dto(row: SchoolResearchProgrammeCandidate) -> ResearchProgrammeCandidateDTO:
    return ResearchProgrammeCandidateDTO(
        id=row.id,
        public_id=row.public_id,
        candidate_ref=row.candidate_ref,
        scope=ResearchProgrammeCandidateScope(
            school_id=row.school_id,
            task_id=row.task_id,
            class_id=row.class_id,
            task_binding_id=row.task_binding_id,
            profile_version_id=row.profile_version_id,
            profile_ref=row.profile_ref,
            profile_version_number=row.profile_version_number,
            profile_sha256=row.profile_sha256,
            response_origin=row.response_origin,
        ),
        study_ref=row.study_ref,
        study_policy_sha256=row.study_policy_sha256,
        processor_policy_sha256=row.processor_policy_sha256,
        programme_ref=row.programme_ref,
        source_manifest_sha256=row.source_manifest_sha256,
        source_set_sha256=row.source_set_sha256,
        retrieval_id=row.retrieval_id,
        retrieval_bundle_sha256=row.retrieval_bundle_sha256,
        chunk_set_sha256=row.chunk_set_sha256,
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
        claim_boundary_version=row.claim_boundary_version,
        claim_boundary_status=row.claim_boundary_status,
        purpose=row.purpose,
        research_only=row.research_only,
        psychological_interpretation_allowed=row.psychological_interpretation_allowed,
        publication_status=row.publication_status,
        output_boundary=row.output_boundary,
        status=row.status,
        state_version=row.state_version,
        payload_ciphertext=row.payload_ciphertext,
        cipher_format_version=row.cipher_format_version,
        key_version=row.key_version,
        payload_schema_version=row.payload_schema_version,
        resolved_by_membership_role_id=row.resolved_by_membership_role_id,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _scope_values(scope: ResearchProgrammeCandidateScope) -> dict[str, object]:
    return {
        "school_id": scope.school_id,
        "task_id": scope.task_id,
        "class_id": scope.class_id,
        "task_binding_id": scope.task_binding_id,
        "profile_version_id": scope.profile_version_id,
        "profile_ref": scope.profile_ref,
        "profile_version_number": scope.profile_version_number,
        "profile_sha256": scope.profile_sha256,
        "response_origin": scope.response_origin,
    }


def _candidate_pins(**values) -> dict[str, object]:
    scope = values.pop("scope")
    return {
        "school_id": scope.school_id,
        "task_id": scope.task_id,
        "task_binding_id": scope.task_binding_id,
        "study_ref": values["study_ref"],
        "study_policy_sha256": values["study_policy_sha256"],
        "processor_policy_sha256": values["processor_policy_sha256"],
        "programme_ref": values["programme_ref"],
        "source_manifest_sha256": values["source_manifest_sha256"],
        "prompt_ref": values["prompt_ref"],
        "prompt_version": values["prompt_version"],
        "prompt_sha256": values["prompt_sha256"],
        "model_ref": values["model_ref"],
        "model_digest_sha256": values["model_digest_sha256"],
        "runtime_version": values["runtime_version"],
        "safety_policy_version": values["safety_policy_version"],
        "claim_boundary_version": values["claim_boundary_version"],
    }


def _pin_predicates(model, values: dict[str, object]):
    return [getattr(model, key) == value for key, value in values.items()]


def _validate_scope(scope: ResearchProgrammeCandidateScope) -> None:
    if type(scope) is not ResearchProgrammeCandidateScope:
        raise ResearchProgrammeCandidateError("INVALID_SCOPE")
    for name in (
        "school_id", "task_id", "class_id", "task_binding_id", "profile_version_id"
    ):
        _require_id(getattr(scope, name), name)
    _require_token(scope.profile_ref, "profile_ref")
    _require_bounded_int(scope.profile_version_number, 1, 2_147_483_647, "profile_version_number")
    _require_sha256(scope.profile_sha256, "profile_sha256")
    if scope.response_origin not in {"PUBLIC_OBSERVED", "MODEL_GENERATED"}:
        raise ResearchProgrammeCandidateError("INVALID_SCOPE")


def _require_id(value: object, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ResearchProgrammeCandidateError("INVALID_INPUT")


def _require_token(value: object, name: str) -> None:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ResearchProgrammeCandidateError("INVALID_INPUT")


def _require_sha256(value: object, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ResearchProgrammeCandidateError("INVALID_INPUT")


def _require_ciphertext(ciphertext, cipher_format_version, key_version, payload_schema_version):
    if (
        not isinstance(ciphertext, bytes)
        or not ciphertext
        or len(ciphertext) > 1_000_000
        or any(not isinstance(value, str) or _TOKEN.fullmatch(value) is None for value in (
            cipher_format_version, key_version, payload_schema_version
        ))
    ):
        raise ResearchProgrammeCandidateError("INVALID_ENCRYPTED_PAYLOAD")


def _require_bounded_int(value: object, lower: int, upper: int, name: str) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise ResearchProgrammeCandidateError("INVALID_INPUT")


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if not isinstance(value, datetime):
        raise ResearchProgrammeCandidateError("INVALID_INPUT")
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
