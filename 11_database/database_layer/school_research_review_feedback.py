"""Research-only review and general education-feedback persistence.

The repository accepts ciphertext only. Backend remains responsible for live
actor authorization, encryption/decryption and request idempotency.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    SchoolResearchFeedbackEvent,
    SchoolResearchFeedbackRecord,
    SchoolResearchReviewCase,
    SchoolResearchReviewEvent,
    SchoolResearchSession,
    SchoolTaskSpecialistAssignment,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_STATUSES = frozenset({"OPEN", "IN_REVIEW", "APPROVED", "REJECTED"})
_FEEDBACK_STATUSES = frozenset({"DRAFT", "PUBLISHED", "REVOKED"})
_REVIEW_TRANSITIONS = {
    "OPEN": frozenset({"IN_REVIEW"}),
    "IN_REVIEW": frozenset({"APPROVED", "REJECTED"}),
    "APPROVED": frozenset(),
    "REJECTED": frozenset(),
}
_PURPOSE = "RESEARCH_SIMULATION"
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_FEEDBACK_KIND = "GENERAL_EDUCATIONAL_SUPPORT"
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


class ResearchReviewFeedbackError(ValueError):
    """Fixed persistence validation failure without row or payload values."""


@dataclass(frozen=True, slots=True, repr=False)
class ResearchSessionScope:
    research_session_id: int
    school_id: int
    task_id: int
    class_id: int
    task_enrollment_id: int
    subject_id: int
    task_binding_id: int
    profile_version_id: int
    profile_ref: str
    profile_version_number: int
    profile_sha256: str
    response_origin: str


@dataclass(frozen=True, slots=True, repr=False)
class ResearchReviewCaseDTO:
    id: int = field(repr=False)
    public_id: str = field(repr=False)
    review_ref: str
    scope: ResearchSessionScope = field(repr=False)
    specialist_membership_role_id: int = field(repr=False)
    status: str
    version: int
    purpose: str
    research_only: bool
    publication_status: str
    case_note_ciphertext: bytes | None = field(repr=False)
    case_note_cipher_format_version: str | None = field(repr=False)
    case_note_key_version: str | None = field(repr=False)
    case_note_payload_schema_version: str | None = field(repr=False)
    trace_id: str | None = field(repr=False)
    retention_due_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ResearchReviewEventDTO:
    id: int = field(repr=False)
    review_case_id: int = field(repr=False)
    scope: ResearchSessionScope = field(repr=False)
    actor_membership_role_id: int = field(repr=False)
    event_type: str
    from_status: str | None
    to_status: str
    version: int
    trace_id: str | None = field(repr=False)
    retention_due_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ResearchFeedbackRecordDTO:
    id: int = field(repr=False)
    public_id: str = field(repr=False)
    feedback_ref: str
    review_case_id: int = field(repr=False)
    scope: ResearchSessionScope = field(repr=False)
    content_revision: int
    case_version: int
    state_version: int
    status: str
    feedback_kind: str
    purpose: str
    research_only: bool
    psychological_interpretation_allowed: bool
    publication_status: str
    payload_ciphertext: bytes = field(repr=False)
    cipher_format_version: str = field(repr=False)
    key_version: str = field(repr=False)
    payload_schema_version: str = field(repr=False)
    created_by_membership_role_id: int = field(repr=False)
    published_by_membership_role_id: int | None = field(repr=False)
    revoked_by_membership_role_id: int | None = field(repr=False)
    published_at: datetime | None
    revoked_at: datetime | None
    trace_id: str | None = field(repr=False)
    retention_due_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ResearchFeedbackEventDTO:
    id: int = field(repr=False)
    feedback_id: int = field(repr=False)
    review_case_id: int = field(repr=False)
    scope: ResearchSessionScope = field(repr=False)
    content_revision: int
    actor_membership_role_id: int = field(repr=False)
    event_type: str
    from_status: str | None
    to_status: str
    state_version: int
    trace_id: str | None = field(repr=False)
    retention_due_at: datetime | None
    created_at: datetime


class SchoolResearchReviewRepository:
    """CAS review transitions and content-free event history for research sessions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_case(
        self,
        *,
        scope: ResearchSessionScope,
        specialist_membership_role_id: int,
        case_note_ciphertext: bytes | None = None,
        case_note_cipher_format_version: str | None = None,
        case_note_key_version: str | None = None,
        case_note_payload_schema_version: str | None = None,
        actor_membership_role_id: int,
        trace_id: str | None = None,
        retention_due_at: datetime | None = None,
        now: datetime | None = None,
    ) -> ResearchReviewCaseDTO:
        _validate_scope(scope)
        _require_id(specialist_membership_role_id, "specialist_membership_role_id")
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        if actor_membership_role_id != specialist_membership_role_id:
            raise ResearchReviewFeedbackError("review actor must match task specialist")
        _require_encrypted_payload(
            case_note_ciphertext,
            case_note_cipher_format_version,
            case_note_key_version,
            case_note_payload_schema_version,
            optional=True,
        )
        _require_optional_token(trace_id, "trace_id", 128)
        clock = _utc_naive(now)
        retention = _utc_naive(retention_due_at) if retention_due_at is not None else None
        await self._require_completed_session(scope)
        await _require_active_assignment(self.session, scope, specialist_membership_role_id)
        existing = await self.session.scalar(
            select(SchoolResearchReviewCase.id).where(
                SchoolResearchReviewCase.research_session_id == scope.research_session_id
            )
        )
        if existing is not None:
            raise UniqueConflict("research review case already exists for this session")

        case = SchoolResearchReviewCase(
            review_ref=_new_ref("SRV"),
            **_scope_values(scope),
            specialist_membership_role_id=specialist_membership_role_id,
            status="OPEN",
            version=1,
            purpose=_PURPOSE,
            research_only=True,
            publication_status=_PUBLICATION_STATUS,
            case_note_ciphertext=case_note_ciphertext,
            case_note_cipher_format_version=case_note_cipher_format_version,
            case_note_key_version=case_note_key_version,
            case_note_payload_schema_version=case_note_payload_schema_version,
            trace_id=trace_id,
            retention_due_at=retention,
            created_at=clock,
            updated_at=clock,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(case)
                await self.session.flush()
                event = SchoolResearchReviewEvent(
                    review_case_id=case.id,
                    **_scope_values(scope),
                    actor_membership_role_id=actor_membership_role_id,
                    event_type="CREATED",
                    from_status=None,
                    to_status="OPEN",
                    version=1,
                    trace_id=trace_id,
                    retention_due_at=retention,
                    created_at=clock,
                    updated_at=clock,
                )
                self.session.add(event)
                await self.session.flush()
        except IntegrityError:
            raise ForeignKeyConflict(
                "research review scope or specialist assignment was rejected"
            ) from None
        return _review_case_dto(case)

    async def get_case(
        self, *, school_id: int, research_session_id: int
    ) -> ResearchReviewCaseDTO | None:
        _require_id(school_id, "school_id")
        _require_id(research_session_id, "research_session_id")
        case = await self.session.scalar(
            select(SchoolResearchReviewCase).where(
                SchoolResearchReviewCase.school_id == school_id,
                SchoolResearchReviewCase.research_session_id == research_session_id,
            )
        )
        return _review_case_dto(case) if case is not None else None

    async def list_cases(
        self,
        *,
        school_id: int,
        task_id: int,
        specialist_membership_role_id: int,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ResearchReviewCaseDTO]:
        _require_id(school_id, "school_id")
        _require_id(task_id, "task_id")
        _require_id(specialist_membership_role_id, "specialist_membership_role_id")
        _bounded_int(limit, "limit", 1, 100)
        _bounded_int(offset, "offset", 0, 100_000)
        if status is not None and (not isinstance(status, str) or status not in _REVIEW_STATUSES):
            raise ResearchReviewFeedbackError("invalid review status")
        stmt = select(SchoolResearchReviewCase).where(
            SchoolResearchReviewCase.school_id == school_id,
            SchoolResearchReviewCase.task_id == task_id,
            SchoolResearchReviewCase.specialist_membership_role_id == specialist_membership_role_id,
        )
        if status is not None:
            stmt = stmt.where(SchoolResearchReviewCase.status == status)
        rows = await self.session.scalars(
            stmt.order_by(SchoolResearchReviewCase.created_at, SchoolResearchReviewCase.id)
            .limit(limit)
            .offset(offset)
        )
        return [_review_case_dto(row) for row in rows.all()]

    async def list_events(
        self, *, school_id: int, research_session_id: int
    ) -> list[ResearchReviewEventDTO]:
        _require_id(school_id, "school_id")
        _require_id(research_session_id, "research_session_id")
        rows = await self.session.scalars(
            select(SchoolResearchReviewEvent)
            .where(
                SchoolResearchReviewEvent.school_id == school_id,
                SchoolResearchReviewEvent.research_session_id == research_session_id,
            )
            .order_by(SchoolResearchReviewEvent.version, SchoolResearchReviewEvent.id)
        )
        return [_review_event_dto(row) for row in rows.all()]

    async def transition_case(
        self,
        *,
        school_id: int,
        research_session_id: int,
        expected_version: int,
        to_status: Literal["OPEN", "IN_REVIEW", "APPROVED", "REJECTED"],
        actor_membership_role_id: int,
        case_note_ciphertext: bytes | None = None,
        case_note_cipher_format_version: str | None = None,
        case_note_key_version: str | None = None,
        case_note_payload_schema_version: str | None = None,
        trace_id: str | None = None,
        now: datetime | None = None,
    ) -> ResearchReviewCaseDTO:
        _require_id(school_id, "school_id")
        _require_id(research_session_id, "research_session_id")
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        _require_positive_int(expected_version, "expected_version")
        if not isinstance(to_status, str) or to_status not in _REVIEW_STATUSES:
            raise ResearchReviewFeedbackError("invalid review status")
        _require_encrypted_payload(
            case_note_ciphertext,
            case_note_cipher_format_version,
            case_note_key_version,
            case_note_payload_schema_version,
            optional=True,
        )
        _require_optional_token(trace_id, "trace_id", 128)
        clock = _utc_naive(now)
        case = await self.session.scalar(
            select(SchoolResearchReviewCase)
            .where(
                SchoolResearchReviewCase.school_id == school_id,
                SchoolResearchReviewCase.research_session_id == research_session_id,
            )
            .with_for_update()
        )
        if case is None:
            raise ForeignKeyConflict("research review case was not found")
        if (
            case.version != expected_version
            or case.specialist_membership_role_id != actor_membership_role_id
            or to_status not in _REVIEW_TRANSITIONS[case.status]
        ):
            raise OptimisticConcurrencyConflict(
                "research review case version or transition is stale"
            )
        scope = _scope_from_model(case)
        await _require_active_assignment(self.session, scope, actor_membership_role_id)
        previous = case.status
        case.status = to_status
        case.version += 1
        case.trace_id = trace_id
        case.updated_at = clock
        if case_note_ciphertext is not None:
            case.case_note_ciphertext = case_note_ciphertext
            case.case_note_cipher_format_version = case_note_cipher_format_version
            case.case_note_key_version = case_note_key_version
            case.case_note_payload_schema_version = case_note_payload_schema_version
        event = SchoolResearchReviewEvent(
            review_case_id=case.id,
            **_scope_values(scope),
            actor_membership_role_id=actor_membership_role_id,
            event_type="TRANSITION",
            from_status=previous,
            to_status=to_status,
            version=case.version,
            trace_id=trace_id,
            retention_due_at=case.retention_due_at,
            created_at=clock,
            updated_at=clock,
        )
        self.session.add(event)
        await self.session.flush()
        return _review_case_dto(case)

    async def _require_completed_session(self, scope: ResearchSessionScope) -> None:
        session = await self.session.scalar(
            select(SchoolResearchSession)
            .where(
                SchoolResearchSession.id == scope.research_session_id,
                SchoolResearchSession.school_id == scope.school_id,
                SchoolResearchSession.task_id == scope.task_id,
                SchoolResearchSession.class_id == scope.class_id,
                SchoolResearchSession.task_enrollment_id == scope.task_enrollment_id,
                SchoolResearchSession.subject_id == scope.subject_id,
                SchoolResearchSession.task_binding_id == scope.task_binding_id,
                SchoolResearchSession.profile_version_id == scope.profile_version_id,
                SchoolResearchSession.profile_ref == scope.profile_ref,
                SchoolResearchSession.profile_version_number == scope.profile_version_number,
                SchoolResearchSession.profile_sha256 == scope.profile_sha256,
                SchoolResearchSession.response_origin == scope.response_origin,
                SchoolResearchSession.status == "COMPLETED",
                SchoolResearchSession.purpose == _PURPOSE,
                SchoolResearchSession.research_only.is_(True),
            )
            .with_for_update()
        )
        if session is None:
            raise ForeignKeyConflict("completed research session scope was not found")


class SchoolResearchFeedbackRepository:
    """Encrypted draft, explicit publication/revocation and metadata events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_draft(
        self,
        *,
        school_id: int,
        research_session_id: int,
        expected_case_version: int,
        feedback_ref: str,
        content_revision: int,
        payload_ciphertext: bytes,
        cipher_format_version: str,
        key_version: str,
        payload_schema_version: str,
        actor_membership_role_id: int,
        trace_id: str | None = None,
        retention_due_at: datetime | None = None,
        now: datetime | None = None,
    ) -> ResearchFeedbackRecordDTO:
        _require_id(school_id, "school_id")
        _require_id(research_session_id, "research_session_id")
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        _require_positive_int(expected_case_version, "expected_case_version")
        _require_positive_int(content_revision, "content_revision")
        _require_token(feedback_ref, "feedback_ref", 128)
        _require_encrypted_payload(
            payload_ciphertext,
            cipher_format_version,
            key_version,
            payload_schema_version,
            optional=False,
        )
        _require_optional_token(trace_id, "trace_id", 128)
        clock = _utc_naive(now)
        retention = _utc_naive(retention_due_at) if retention_due_at is not None else None
        case = await self.session.scalar(
            select(SchoolResearchReviewCase)
            .where(
                SchoolResearchReviewCase.school_id == school_id,
                SchoolResearchReviewCase.research_session_id == research_session_id,
            )
            .with_for_update()
        )
        if case is None:
            raise ForeignKeyConflict("research review case was not found")
        if (
            case.status != "APPROVED"
            or case.version != expected_case_version
            or case.specialist_membership_role_id != actor_membership_role_id
        ):
            raise OptimisticConcurrencyConflict("approved research review version is stale")
        scope = _scope_from_model(case)
        await _require_active_assignment(self.session, scope, actor_membership_role_id)
        row = SchoolResearchFeedbackRecord(
            feedback_ref=feedback_ref,
            review_case_id=case.id,
            **_scope_values(scope),
            content_revision=content_revision,
            case_version=case.version,
            state_version=1,
            status="DRAFT",
            feedback_kind=_FEEDBACK_KIND,
            purpose=_PURPOSE,
            research_only=True,
            psychological_interpretation_allowed=False,
            publication_status=_PUBLICATION_STATUS,
            payload_ciphertext=payload_ciphertext,
            cipher_format_version=cipher_format_version,
            key_version=key_version,
            payload_schema_version=payload_schema_version,
            created_by_membership_role_id=actor_membership_role_id,
            published_by_membership_role_id=None,
            revoked_by_membership_role_id=None,
            published_at=None,
            revoked_at=None,
            trace_id=trace_id,
            retention_due_at=retention,
            created_at=clock,
            updated_at=clock,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                event = _feedback_event(
                    row,
                    actor_membership_role_id=actor_membership_role_id,
                    event_type="CREATED",
                    from_status=None,
                    to_status="DRAFT",
                    trace_id=trace_id,
                    now=clock,
                )
                self.session.add(event)
                await self.session.flush()
        except IntegrityError:
            raise ForeignKeyConflict(
                "research feedback scope or content revision was rejected"
            ) from None
        return _feedback_record_dto(row)

    async def get_feedback(
        self, *, school_id: int, feedback_id: int
    ) -> ResearchFeedbackRecordDTO | None:
        _require_id(school_id, "school_id")
        _require_id(feedback_id, "feedback_id")
        row = await self.session.scalar(
            select(SchoolResearchFeedbackRecord).where(
                SchoolResearchFeedbackRecord.school_id == school_id,
                SchoolResearchFeedbackRecord.id == feedback_id,
            )
        )
        return _feedback_record_dto(row) if row is not None else None

    async def list_feedback(
        self,
        *,
        school_id: int,
        research_session_id: int,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ResearchFeedbackRecordDTO]:
        _require_id(school_id, "school_id")
        _require_id(research_session_id, "research_session_id")
        _bounded_int(limit, "limit", 1, 100)
        _bounded_int(offset, "offset", 0, 100_000)
        if status is not None and (not isinstance(status, str) or status not in _FEEDBACK_STATUSES):
            raise ResearchReviewFeedbackError("invalid feedback status")
        stmt = select(SchoolResearchFeedbackRecord).where(
            SchoolResearchFeedbackRecord.school_id == school_id,
            SchoolResearchFeedbackRecord.research_session_id == research_session_id,
        )
        if status is not None:
            stmt = stmt.where(SchoolResearchFeedbackRecord.status == status)
        rows = await self.session.scalars(
            stmt.order_by(
                SchoolResearchFeedbackRecord.content_revision,
                SchoolResearchFeedbackRecord.id,
            )
            .limit(limit)
            .offset(offset)
        )
        return [_feedback_record_dto(row) for row in rows.all()]

    async def list_events(
        self, *, school_id: int, feedback_id: int
    ) -> list[ResearchFeedbackEventDTO]:
        _require_id(school_id, "school_id")
        _require_id(feedback_id, "feedback_id")
        rows = await self.session.scalars(
            select(SchoolResearchFeedbackEvent)
            .where(
                SchoolResearchFeedbackEvent.school_id == school_id,
                SchoolResearchFeedbackEvent.feedback_id == feedback_id,
            )
            .order_by(
                SchoolResearchFeedbackEvent.state_version,
                SchoolResearchFeedbackEvent.id,
            )
        )
        return [_feedback_event_dto(row) for row in rows.all()]

    async def publish(
        self,
        *,
        school_id: int,
        feedback_id: int,
        expected_state_version: int,
        expected_case_version: int,
        actor_membership_role_id: int,
        trace_id: str | None = None,
        now: datetime | None = None,
    ) -> ResearchFeedbackRecordDTO:
        return await self._transition(
            school_id=school_id,
            feedback_id=feedback_id,
            expected_state_version=expected_state_version,
            expected_case_version=expected_case_version,
            actor_membership_role_id=actor_membership_role_id,
            target="PUBLISHED",
            trace_id=trace_id,
            now=now,
        )

    async def revoke(
        self,
        *,
        school_id: int,
        feedback_id: int,
        expected_state_version: int,
        actor_membership_role_id: int,
        trace_id: str | None = None,
        now: datetime | None = None,
    ) -> ResearchFeedbackRecordDTO:
        return await self._transition(
            school_id=school_id,
            feedback_id=feedback_id,
            expected_state_version=expected_state_version,
            expected_case_version=None,
            actor_membership_role_id=actor_membership_role_id,
            target="REVOKED",
            trace_id=trace_id,
            now=now,
        )

    async def _transition(
        self,
        *,
        school_id: int,
        feedback_id: int,
        expected_state_version: int,
        expected_case_version: int | None,
        actor_membership_role_id: int,
        target: Literal["PUBLISHED", "REVOKED"],
        trace_id: str | None,
        now: datetime | None,
    ) -> ResearchFeedbackRecordDTO:
        _require_id(school_id, "school_id")
        _require_id(feedback_id, "feedback_id")
        _require_id(actor_membership_role_id, "actor_membership_role_id")
        _require_positive_int(expected_state_version, "expected_state_version")
        if expected_case_version is not None:
            _require_positive_int(expected_case_version, "expected_case_version")
        _require_optional_token(trace_id, "trace_id", 128)
        clock = _utc_naive(now)
        row = await self.session.scalar(
            select(SchoolResearchFeedbackRecord)
            .where(
                SchoolResearchFeedbackRecord.school_id == school_id,
                SchoolResearchFeedbackRecord.id == feedback_id,
            )
            .with_for_update()
        )
        if row is None:
            raise ForeignKeyConflict("research feedback record was not found")
        allowed_source_statuses = {"DRAFT"} if target == "PUBLISHED" else {"DRAFT", "PUBLISHED"}
        if (
            row.state_version != expected_state_version
            or row.created_by_membership_role_id != actor_membership_role_id
            or row.status not in allowed_source_statuses
        ):
            raise OptimisticConcurrencyConflict("research feedback state version is stale")
        case = await self.session.scalar(
            select(SchoolResearchReviewCase)
            .where(
                SchoolResearchReviewCase.school_id == row.school_id,
                SchoolResearchReviewCase.research_session_id == row.research_session_id,
            )
            .with_for_update()
        )
        if (
            case is None
            or case.id != row.review_case_id
            or case.specialist_membership_role_id != actor_membership_role_id
        ):
            raise OptimisticConcurrencyConflict("research feedback review scope is stale")
        scope = _scope_from_model(case)
        await _require_active_assignment(self.session, scope, actor_membership_role_id)
        if target == "PUBLISHED" and (
            case.status != "APPROVED"
            or case.version != expected_case_version
            or case.version != row.case_version
        ):
            raise OptimisticConcurrencyConflict("approved research review version is stale")
        previous = row.status
        row.status = target
        row.state_version += 1
        row.trace_id = trace_id
        row.updated_at = clock
        if target == "PUBLISHED":
            row.published_at = clock
            row.published_by_membership_role_id = actor_membership_role_id
        else:
            row.revoked_at = clock
            row.revoked_by_membership_role_id = actor_membership_role_id
        event = _feedback_event(
            row,
            actor_membership_role_id=actor_membership_role_id,
            event_type=target,
            from_status=previous,
            to_status=target,
            trace_id=trace_id,
            now=clock,
        )
        self.session.add(event)
        await self.session.flush()
        return _feedback_record_dto(row)


def _scope_values(scope: ResearchSessionScope) -> dict[str, object]:
    return {name: getattr(scope, name) for name in _SCOPE_FIELDS}


def _validate_scope(scope: ResearchSessionScope) -> None:
    if type(scope) is not ResearchSessionScope:
        raise ResearchReviewFeedbackError("research session scope is required")
    for name in _SCOPE_FIELDS[:8]:
        _require_id(getattr(scope, name), name)
    _require_token(scope.profile_ref, "profile_ref", 128)
    _require_positive_int(scope.profile_version_number, "profile_version_number")
    if not isinstance(scope.profile_sha256, str) or _SHA256.fullmatch(scope.profile_sha256) is None:
        raise ResearchReviewFeedbackError("profile_sha256 must be lowercase SHA-256")
    if not isinstance(scope.response_origin, str) or scope.response_origin not in {
        "PUBLIC_OBSERVED",
        "MODEL_GENERATED",
    }:
        raise ResearchReviewFeedbackError("unsupported research response origin")


async def _require_active_assignment(
    session: AsyncSession, scope: ResearchSessionScope, specialist_membership_role_id: int
) -> None:
    row = await session.scalar(
        select(SchoolTaskSpecialistAssignment.id)
        .where(
            SchoolTaskSpecialistAssignment.task_id == scope.task_id,
            SchoolTaskSpecialistAssignment.school_id == scope.school_id,
            SchoolTaskSpecialistAssignment.class_id == scope.class_id,
            SchoolTaskSpecialistAssignment.specialist_membership_role_id
            == specialist_membership_role_id,
            SchoolTaskSpecialistAssignment.status == "ACTIVE",
            SchoolTaskSpecialistAssignment.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise ForeignKeyConflict("active task specialist assignment was not found")


def _scope_from_model(row: object) -> ResearchSessionScope:
    return ResearchSessionScope(**{name: getattr(row, name) for name in _SCOPE_FIELDS})


def _review_case_dto(row: SchoolResearchReviewCase) -> ResearchReviewCaseDTO:
    return ResearchReviewCaseDTO(
        id=row.id,
        public_id=row.public_id,
        review_ref=row.review_ref,
        scope=_scope_from_model(row),
        specialist_membership_role_id=row.specialist_membership_role_id,
        status=row.status,
        version=row.version,
        purpose=row.purpose,
        research_only=row.research_only,
        publication_status=row.publication_status,
        case_note_ciphertext=row.case_note_ciphertext,
        case_note_cipher_format_version=row.case_note_cipher_format_version,
        case_note_key_version=row.case_note_key_version,
        case_note_payload_schema_version=row.case_note_payload_schema_version,
        trace_id=row.trace_id,
        retention_due_at=_utc_aware(row.retention_due_at),
        created_at=_utc_aware(row.created_at),
        updated_at=_utc_aware(row.updated_at),
    )


def _review_event_dto(row: SchoolResearchReviewEvent) -> ResearchReviewEventDTO:
    return ResearchReviewEventDTO(
        id=row.id,
        review_case_id=row.review_case_id,
        scope=_scope_from_model(row),
        actor_membership_role_id=row.actor_membership_role_id,
        event_type=row.event_type,
        from_status=row.from_status,
        to_status=row.to_status,
        version=row.version,
        trace_id=row.trace_id,
        retention_due_at=_utc_aware(row.retention_due_at),
        created_at=_utc_aware(row.created_at),
    )


def _feedback_record_dto(row: SchoolResearchFeedbackRecord) -> ResearchFeedbackRecordDTO:
    return ResearchFeedbackRecordDTO(
        id=row.id,
        public_id=row.public_id,
        feedback_ref=row.feedback_ref,
        review_case_id=row.review_case_id,
        scope=_scope_from_model(row),
        content_revision=row.content_revision,
        case_version=row.case_version,
        state_version=row.state_version,
        status=row.status,
        feedback_kind=row.feedback_kind,
        purpose=row.purpose,
        research_only=row.research_only,
        psychological_interpretation_allowed=row.psychological_interpretation_allowed,
        publication_status=row.publication_status,
        payload_ciphertext=row.payload_ciphertext,
        cipher_format_version=row.cipher_format_version,
        key_version=row.key_version,
        payload_schema_version=row.payload_schema_version,
        created_by_membership_role_id=row.created_by_membership_role_id,
        published_by_membership_role_id=row.published_by_membership_role_id,
        revoked_by_membership_role_id=row.revoked_by_membership_role_id,
        published_at=_utc_aware(row.published_at),
        revoked_at=_utc_aware(row.revoked_at),
        trace_id=row.trace_id,
        retention_due_at=_utc_aware(row.retention_due_at),
        created_at=_utc_aware(row.created_at),
        updated_at=_utc_aware(row.updated_at),
    )


def _feedback_event(
    row: SchoolResearchFeedbackRecord,
    *,
    actor_membership_role_id: int,
    event_type: str,
    from_status: str | None,
    to_status: str,
    trace_id: str | None,
    now: datetime,
) -> SchoolResearchFeedbackEvent:
    return SchoolResearchFeedbackEvent(
        feedback_id=row.id,
        review_case_id=row.review_case_id,
        **{name: getattr(row, name) for name in _SCOPE_FIELDS},
        content_revision=row.content_revision,
        actor_membership_role_id=actor_membership_role_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        state_version=row.state_version,
        trace_id=trace_id,
        retention_due_at=row.retention_due_at,
        created_at=now,
        updated_at=now,
    )


def _feedback_event_dto(row: SchoolResearchFeedbackEvent) -> ResearchFeedbackEventDTO:
    return ResearchFeedbackEventDTO(
        id=row.id,
        feedback_id=row.feedback_id,
        review_case_id=row.review_case_id,
        scope=_scope_from_model(row),
        content_revision=row.content_revision,
        actor_membership_role_id=row.actor_membership_role_id,
        event_type=row.event_type,
        from_status=row.from_status,
        to_status=row.to_status,
        state_version=row.state_version,
        trace_id=row.trace_id,
        retention_due_at=_utc_aware(row.retention_due_at),
        created_at=_utc_aware(row.created_at),
    )


def _require_id(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ResearchReviewFeedbackError(f"{name} must be a positive integer")
    return value


def _require_positive_int(value: object, name: str) -> int:
    return _require_id(value, name)


def _require_token(value: object, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or not value.isascii()
        or _TOKEN.fullmatch(value) is None
    ):
        raise ResearchReviewFeedbackError(f"{name} must be a bounded ASCII token")
    return value


def _require_optional_token(value: object | None, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _require_token(value, name, maximum)


def _require_encrypted_payload(
    ciphertext: object,
    cipher_format_version: object,
    key_version: object,
    payload_schema_version: object,
    *,
    optional: bool,
) -> None:
    if ciphertext is None and optional:
        if any(
            item is not None
            for item in (cipher_format_version, key_version, payload_schema_version)
        ):
            raise ResearchReviewFeedbackError("cipher metadata requires ciphertext")
        return
    if not isinstance(ciphertext, bytes) or not 1 <= len(ciphertext) <= 16_777_215:
        raise ResearchReviewFeedbackError("ciphertext must be bounded nonempty bytes")
    _require_token(cipher_format_version, "cipher_format_version", 32)
    _require_token(key_version, "key_version", 64)
    _require_token(payload_schema_version, "payload_schema_version", 64)


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ResearchReviewFeedbackError(f"{name} is outside its allowed range")
    return value


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        value = datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchReviewFeedbackError("timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None else None


def _new_ref(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(24)}"
