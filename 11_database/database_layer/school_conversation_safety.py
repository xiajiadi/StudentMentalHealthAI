"""Durable metadata-only review cases for independent school conversations."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    Account,
    AccountSchoolMembership,
    MembershipRole,
    SafetyDecision,
    SchoolClass,
    SchoolClassStudent,
    SchoolConversationSafetyCase,
    SchoolConversationSafetyEvent,
    Subject,
    SubjectAccessGrant,
    SupportRun,
    SupportSession,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ACTIONS = frozenset({"REVIEW_REQUIRED", "CRISIS_ROUTE"})
_EVENTS = frozenset(
    {"CREATED", "ASSIGNED", "REASSIGNED", "UNASSIGNED", "NOTE_DRAFTED", "TRANSITIONED", "REVOKED"}
)
_DECISION_CODE = "UNRESOLVED_NEEDS_CONTEXT"


class SchoolConversationSafetyError(ValueError):
    """Fixed persistence validation errors; never include stored content."""


@dataclass(frozen=True, slots=True, repr=False)
class ConversationSafetyCaseDTO:
    id: int = field(repr=False)
    case_ref: str
    school_id: int = field(repr=False)
    subject_id: int = field(repr=False)
    support_session_id: int = field(repr=False)
    support_run_id: int = field(repr=False)
    safety_decision_id: int = field(repr=False)
    class_id: int | None = field(repr=False)
    class_student_id: int | None = field(repr=False)
    class_ref: str | None
    action: str
    reason_codes: tuple[str, ...]
    safety_review_reference: str | None = field(repr=False)
    status: str
    state_version: int
    decision_code: str | None
    assigned_membership_role_id: int | None = field(repr=False)
    review_note_ciphertext: bytes | None = field(repr=False)
    review_note_cipher_format_version: str | None = field(repr=False)
    review_note_key_version: str | None = field(repr=False)
    review_note_payload_schema_version: str | None = field(repr=False)
    trace_id: str = field(repr=False)
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime | None
    reviewed_at: datetime | None
    closed_at: datetime | None
    revoked_at: datetime | None
    retention_due_at: datetime | None


@dataclass(frozen=True, slots=True, repr=False)
class ConversationSafetyEventDTO:
    id: int = field(repr=False)
    case_id: int = field(repr=False)
    actor_membership_role_id: int = field(repr=False)
    assigned_membership_role_id: int | None = field(repr=False)
    class_id: int | None = field(repr=False)
    class_student_id: int | None = field(repr=False)
    event_type: str
    from_status: str | None
    to_status: str
    state_version: int
    trace_id: str = field(repr=False)
    created_at: datetime


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if not isinstance(value, datetime):
        raise SchoolConversationSafetyError("invalid timestamp")
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).replace(
        tzinfo=None
    )


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SchoolConversationSafetyError(f"invalid {field_name}")
    return value


def _safe_token(value: object, field_name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise SchoolConversationSafetyError(f"invalid {field_name}")
    return value


def _reason_codes(values: object) -> list[str]:
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= 16:
        raise SchoolConversationSafetyError("invalid reason codes")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _REASON.fullmatch(value):
            raise SchoolConversationSafetyError("invalid reason codes")
        if value in result:
            raise SchoolConversationSafetyError("invalid reason codes")
        result.append(value)
    return result


def _case_dto(
    case: SchoolConversationSafetyCase, class_ref: str | None
) -> ConversationSafetyCaseDTO:
    reason_codes = case.reason_codes
    if not isinstance(reason_codes, list) or any(
        not isinstance(value, str) or not _REASON.fullmatch(value) for value in reason_codes
    ):
        raise SchoolConversationSafetyError("stored safety case metadata is invalid")
    return ConversationSafetyCaseDTO(
        id=case.id,
        case_ref=case.case_ref,
        school_id=case.school_id,
        subject_id=case.subject_id,
        support_session_id=case.support_session_id,
        support_run_id=case.support_run_id,
        safety_decision_id=case.safety_decision_id,
        class_id=case.class_id,
        class_student_id=case.class_student_id,
        class_ref=class_ref,
        action=case.action,
        reason_codes=tuple(reason_codes),
        safety_review_reference=case.safety_review_reference,
        status=case.status,
        state_version=case.state_version,
        decision_code=case.decision_code,
        assigned_membership_role_id=case.assigned_membership_role_id,
        review_note_ciphertext=case.review_note_ciphertext,
        review_note_cipher_format_version=case.review_note_cipher_format_version,
        review_note_key_version=case.review_note_key_version,
        review_note_payload_schema_version=case.review_note_payload_schema_version,
        trace_id=case.trace_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        assigned_at=case.assigned_at,
        reviewed_at=case.reviewed_at,
        closed_at=case.closed_at,
        revoked_at=case.revoked_at,
        retention_due_at=case.retention_due_at,
    )


class SchoolConversationSafetyRepository:
    """Same-UOW case creation and CAS metadata transitions for school conversations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_from_safety_decision(
        self,
        *,
        support_session_id: int,
        support_run_id: int,
        safety_decision_id: int,
        school_id: int,
        subject_id: int,
        action: str,
        reason_codes: tuple[str, ...] | list[str],
        safety_review_reference: str | None,
        actor_membership_role_id: int,
        trace_id: str,
        retention_due_at: datetime | None = None,
        now: datetime | None = None,
    ) -> ConversationSafetyCaseDTO:
        _positive_int(support_session_id, "support_session_id")
        _positive_int(support_run_id, "support_run_id")
        _positive_int(safety_decision_id, "safety_decision_id")
        _positive_int(school_id, "school_id")
        _positive_int(subject_id, "subject_id")
        _positive_int(actor_membership_role_id, "actor_membership_role_id")
        action = _safe_token(action, "action") or ""
        if action not in _ACTIONS:
            raise SchoolConversationSafetyError("invalid safety action")
        codes = _reason_codes(reason_codes)
        review_ref = _safe_token(safety_review_reference, "safety review reference", optional=True)
        trace = _safe_token(trace_id, "trace_id") or ""
        clock = _utc_naive(now)
        retention = _utc_naive(retention_due_at) if retention_due_at is not None else None
        await self._require_source_scope(
            support_session_id=support_session_id,
            support_run_id=support_run_id,
            safety_decision_id=safety_decision_id,
            school_id=school_id,
            subject_id=subject_id,
            action=action,
        )
        if (
            await self.session.scalar(
                select(SchoolConversationSafetyCase.id).where(
                    SchoolConversationSafetyCase.safety_decision_id == safety_decision_id
                )
            )
            is not None
        ):
            raise UniqueConflict("conversation safety case already exists")
        role = await self._require_school_actor(
            actor_membership_role_id, school_id, "student", clock
        )
        if not await self._has_self_grant(school_id, subject_id, role.membership_id, clock):
            raise SchoolConversationSafetyError("source actor role is unavailable")
        class_rows = await self._active_class_links(school_id, subject_id, clock, limit=2)
        class_row = class_rows[0] if len(class_rows) == 1 else None
        case = SchoolConversationSafetyCase(
            case_ref=f"SCS_{secrets.token_hex(24)}",
            school_id=school_id,
            subject_id=subject_id,
            support_session_id=support_session_id,
            support_run_id=support_run_id,
            safety_decision_id=safety_decision_id,
            class_id=class_row[0].class_id if class_row is not None else None,
            class_student_id=class_row[0].id if class_row is not None else None,
            action=action,
            reason_codes=codes,
            safety_review_reference=review_ref,
            status="UNASSIGNED_PENDING",
            state_version=1,
            trace_id=trace,
            retention_due_at=retention,
            created_at=clock,
            updated_at=clock,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(case)
                await self.session.flush()
                self.session.add(
                    SchoolConversationSafetyEvent(
                        case_id=case.id,
                        school_id=school_id,
                        actor_membership_role_id=actor_membership_role_id,
                        event_type="CREATED",
                        from_status=None,
                        to_status="UNASSIGNED_PENDING",
                        state_version=1,
                        trace_id=trace,
                        retention_due_at=retention,
                        created_at=clock,
                    )
                )
                await self.session.flush()
        except IntegrityError:
            raise ForeignKeyConflict("conversation safety scope was rejected") from None
        return _case_dto(case, class_row[1] if class_row is not None else None)

    async def get_student_status(
        self, *, school_id: int, subject_id: int, support_session_id: int
    ) -> ConversationSafetyCaseDTO | None:
        case = await self.session.scalar(
            select(SchoolConversationSafetyCase)
            .where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.subject_id == subject_id,
                SchoolConversationSafetyCase.support_session_id == support_session_id,
            )
            .order_by(
                SchoolConversationSafetyCase.created_at.desc(),
                SchoolConversationSafetyCase.id.desc(),
            )
            .limit(1)
        )
        if case is None:
            return None
        return _case_dto(case, await self._class_ref(case.class_id, school_id))

    async def get_case_for_school(
        self, *, school_id: int, case_ref: str
    ) -> ConversationSafetyCaseDTO | None:
        _positive_int(school_id, "school_id")
        _safe_token(case_ref, "case_ref")
        case = await self.session.scalar(
            select(SchoolConversationSafetyCase).where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.case_ref == case_ref,
            )
        )
        return _case_dto(case, await self._class_ref(case.class_id, school_id)) if case else None

    async def list_unassigned(
        self, *, school_id: int, limit: int = 50, offset: int = 0
    ) -> list[ConversationSafetyCaseDTO]:
        _positive_int(school_id, "school_id")
        _page(limit, offset)
        cases = await self.session.scalars(
            select(SchoolConversationSafetyCase)
            .where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.status == "UNASSIGNED_PENDING",
            )
            .order_by(SchoolConversationSafetyCase.created_at, SchoolConversationSafetyCase.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            _case_dto(case, await self._class_ref(case.class_id, school_id)) for case in cases.all()
        ]

    async def count_unassigned(self, *, school_id: int) -> int:
        _positive_int(school_id, "school_id")
        count = await self.session.scalar(
            select(func.count(SchoolConversationSafetyCase.id)).where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.status == "UNASSIGNED_PENDING",
            )
        )
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SchoolConversationSafetyError("unassigned case count is invalid")
        return count

    async def count_assigned(
        self,
        *,
        school_id: int,
        specialist_membership_role_id: int,
        now: datetime | None = None,
    ) -> int:
        _positive_int(school_id, "school_id")
        _positive_int(specialist_membership_role_id, "specialist_membership_role_id")
        clock = _utc_naive(now)
        count = await self.session.scalar(
            select(func.count(SchoolConversationSafetyCase.id))
            .join(Subject, Subject.id == SchoolConversationSafetyCase.subject_id)
            .join(
                SchoolClassStudent,
                (SchoolClassStudent.id == SchoolConversationSafetyCase.class_student_id)
                & (SchoolClassStudent.subject_id == SchoolConversationSafetyCase.subject_id)
                & (SchoolClassStudent.class_id == SchoolConversationSafetyCase.class_id)
                & (SchoolClassStudent.school_id == SchoolConversationSafetyCase.school_id),
            )
            .join(
                SchoolClass,
                (SchoolClass.id == SchoolClassStudent.class_id)
                & (SchoolClass.school_id == SchoolClassStudent.school_id),
            )
            .where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.assigned_membership_role_id
                == specialist_membership_role_id,
                SchoolConversationSafetyCase.status.in_(
                    ("ASSIGNED", "IN_REVIEW", "REVIEWED", "ESCALATION_NEEDED", "CLOSED")
                ),
                *_active_scope_predicates(clock),
            )
        )
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SchoolConversationSafetyError("assigned case count is invalid")
        return count

    async def list_assigned(
        self,
        *,
        school_id: int,
        specialist_membership_role_id: int,
        limit: int = 50,
        offset: int = 0,
        now: datetime | None = None,
    ) -> list[ConversationSafetyCaseDTO]:
        _positive_int(school_id, "school_id")
        _positive_int(specialist_membership_role_id, "specialist_membership_role_id")
        _page(limit, offset)
        clock = _utc_naive(now)
        stmt = (
            select(SchoolConversationSafetyCase)
            .join(Subject, Subject.id == SchoolConversationSafetyCase.subject_id)
            .join(
                SchoolClassStudent,
                (SchoolClassStudent.id == SchoolConversationSafetyCase.class_student_id)
                & (SchoolClassStudent.subject_id == SchoolConversationSafetyCase.subject_id)
                & (SchoolClassStudent.class_id == SchoolConversationSafetyCase.class_id)
                & (SchoolClassStudent.school_id == SchoolConversationSafetyCase.school_id),
            )
            .join(
                SchoolClass,
                (SchoolClass.id == SchoolClassStudent.class_id)
                & (SchoolClass.school_id == SchoolClassStudent.school_id),
            )
            .where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.assigned_membership_role_id
                == specialist_membership_role_id,
                SchoolConversationSafetyCase.status.in_(
                    ("ASSIGNED", "IN_REVIEW", "REVIEWED", "ESCALATION_NEEDED", "CLOSED")
                ),
                *_active_scope_predicates(clock),
            )
            .order_by(
                SchoolConversationSafetyCase.created_at.desc(),
                SchoolConversationSafetyCase.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        cases = await self.session.scalars(stmt)
        return [
            _case_dto(case, await self._class_ref(case.class_id, school_id)) for case in cases.all()
        ]

    async def get_assigned(
        self,
        *,
        school_id: int,
        case_ref: str,
        specialist_membership_role_id: int,
        now: datetime | None = None,
        lock: bool = False,
    ) -> ConversationSafetyCaseDTO | None:
        _safe_token(case_ref, "case_ref")
        _positive_int(specialist_membership_role_id, "specialist_membership_role_id")
        clock = _utc_naive(now)
        statement = (
            select(SchoolConversationSafetyCase)
            .join(Subject, Subject.id == SchoolConversationSafetyCase.subject_id)
            .join(
                SchoolClassStudent,
                (SchoolClassStudent.id == SchoolConversationSafetyCase.class_student_id)
                & (SchoolClassStudent.subject_id == SchoolConversationSafetyCase.subject_id)
                & (SchoolClassStudent.class_id == SchoolConversationSafetyCase.class_id)
                & (SchoolClassStudent.school_id == SchoolConversationSafetyCase.school_id),
            )
            .join(
                SchoolClass,
                (SchoolClass.id == SchoolClassStudent.class_id)
                & (SchoolClass.school_id == SchoolClassStudent.school_id),
            )
            .where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.case_ref == case_ref,
                SchoolConversationSafetyCase.assigned_membership_role_id
                == specialist_membership_role_id,
                SchoolConversationSafetyCase.status.in_(
                    ("ASSIGNED", "IN_REVIEW", "REVIEWED", "ESCALATION_NEEDED", "CLOSED")
                ),
                *_active_scope_predicates(clock),
            )
        )
        if lock:
            statement = statement.with_for_update()
        case = await self.session.scalar(statement)
        return _case_dto(case, await self._class_ref(case.class_id, school_id)) if case else None

    async def assign(
        self,
        *,
        school_id: int,
        case_ref: str,
        class_ref: str,
        specialist_membership_role_id: int,
        actor_membership_role_id: int,
        expected_version: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ConversationSafetyCaseDTO:
        clock = _utc_naive(now)
        case = await self._lock_case(school_id, case_ref)
        _expect_version(case, expected_version)
        if case.status != "UNASSIGNED_PENDING":
            raise OptimisticConcurrencyConflict("case is no longer unassigned")
        await self._require_school_actor(actor_membership_role_id, school_id, "admin", clock)
        specialist = await self._require_school_actor(
            specialist_membership_role_id, school_id, "psychological_specialist", clock
        )
        await self._require_current_student_subject(school_id, case.subject_id, clock)
        roster, selected_class_ref = await self._active_class_link_for_ref(
            school_id, case.subject_id, class_ref, clock
        )
        if case.class_id is not None and (
            case.class_id != roster.class_id or case.class_student_id != roster.id
        ):
            raise SchoolConversationSafetyError("case class binding requires explicit rebind")
        self._set_assignment(case, roster.class_id, roster.id, specialist.id, clock)
        case.decision_code = None
        case.state_version += 1
        case.updated_at = clock
        await self._append_event(
            case,
            actor_membership_role_id=actor_membership_role_id,
            event_type="ASSIGNED",
            from_status="UNASSIGNED_PENDING",
            to_status="ASSIGNED",
            trace_id=trace_id,
            now=clock,
        )
        return _case_dto(case, selected_class_ref)

    async def transfer(
        self,
        *,
        school_id: int,
        case_ref: str,
        class_ref: str,
        specialist_membership_role_id: int,
        actor_membership_role_id: int,
        expected_version: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ConversationSafetyCaseDTO:
        clock = _utc_naive(now)
        case = await self._lock_case(school_id, case_ref)
        _expect_version(case, expected_version)
        if case.status in {"CLOSED", "REVOKED"}:
            raise OptimisticConcurrencyConflict("case is closed")
        await self._require_school_actor(actor_membership_role_id, school_id, "admin", clock)
        specialist = await self._require_school_actor(
            specialist_membership_role_id, school_id, "psychological_specialist", clock
        )
        await self._require_current_student_subject(school_id, case.subject_id, clock)
        roster, selected_class_ref = await self._active_class_link_for_ref(
            school_id, case.subject_id, class_ref, clock
        )
        before = case.status
        previous_role = case.assigned_membership_role_id
        self._set_assignment(case, roster.class_id, roster.id, specialist.id, clock)
        case.status = "ASSIGNED"
        case.decision_code = None
        case.state_version += 1
        case.updated_at = clock
        await self._append_event(
            case,
            actor_membership_role_id=actor_membership_role_id,
            event_type="REASSIGNED" if previous_role else "ASSIGNED",
            from_status=before,
            to_status="ASSIGNED",
            trace_id=trace_id,
            now=clock,
        )
        return _case_dto(case, selected_class_ref)

    async def unassign(
        self,
        *,
        school_id: int,
        case_ref: str,
        actor_membership_role_id: int,
        expected_version: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ConversationSafetyCaseDTO:
        clock = _utc_naive(now)
        case = await self._lock_case(school_id, case_ref)
        _expect_version(case, expected_version)
        if case.status in {"CLOSED", "REVOKED"}:
            raise OptimisticConcurrencyConflict("case is closed")
        await self._require_school_actor(actor_membership_role_id, school_id, "admin", clock)
        before = case.status
        case.status = "UNASSIGNED_PENDING"
        case.assigned_membership_role_id = None
        case.assigned_at = None
        case.class_id = None
        case.class_student_id = None
        case.decision_code = None
        case.state_version += 1
        case.updated_at = clock
        await self._append_event(
            case,
            actor_membership_role_id=actor_membership_role_id,
            event_type="UNASSIGNED",
            from_status=before,
            to_status="UNASSIGNED_PENDING",
            trace_id=trace_id,
            now=clock,
        )
        return _case_dto(case, None)

    async def revoke_case(
        self,
        *,
        school_id: int,
        case_ref: str,
        actor_membership_role_id: int,
        expected_version: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> ConversationSafetyCaseDTO:
        clock = _utc_naive(now)
        case = await self._lock_case(school_id, case_ref)
        _expect_version(case, expected_version)
        if case.status in {"CLOSED", "REVOKED"}:
            raise OptimisticConcurrencyConflict("case is closed")
        await self._require_school_actor(actor_membership_role_id, school_id, "admin", clock)
        before = case.status
        case.status = "REVOKED"
        case.revoked_at = clock
        case.state_version += 1
        case.updated_at = clock
        await self._append_event(
            case,
            actor_membership_role_id=actor_membership_role_id,
            event_type="REVOKED",
            from_status=before,
            to_status="REVOKED",
            trace_id=trace_id,
            now=clock,
        )
        return _case_dto(case, await self._class_ref(case.class_id, school_id))

    async def save_draft_note(
        self,
        *,
        school_id: int,
        case_ref: str,
        specialist_membership_role_id: int,
        expected_version: int,
        ciphertext: bytes,
        cipher_format_version: str,
        key_version: str,
        payload_schema_version: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> ConversationSafetyCaseDTO:
        clock = _utc_naive(now)
        _require_cipher(ciphertext, cipher_format_version, key_version, payload_schema_version)
        case = await self._require_assigned_locked(
            school_id, case_ref, specialist_membership_role_id, clock
        )
        _expect_version(case, expected_version)
        if case.status not in {"ASSIGNED", "IN_REVIEW", "ESCALATION_NEEDED"}:
            raise OptimisticConcurrencyConflict("case does not accept a draft note")
        before = case.status
        case.status = "IN_REVIEW"
        case.review_note_ciphertext = ciphertext
        case.review_note_cipher_format_version = cipher_format_version
        case.review_note_key_version = key_version
        case.review_note_payload_schema_version = payload_schema_version
        case.state_version += 1
        case.updated_at = clock
        await self._append_event(
            case,
            actor_membership_role_id=specialist_membership_role_id,
            event_type="NOTE_DRAFTED",
            from_status=before,
            to_status="IN_REVIEW",
            trace_id=trace_id,
            now=clock,
        )
        return _case_dto(case, await self._class_ref(case.class_id, school_id))

    async def transition(
        self,
        *,
        school_id: int,
        case_ref: str,
        specialist_membership_role_id: int,
        expected_version: int,
        to_status: Literal["IN_REVIEW", "REVIEWED", "ESCALATION_NEEDED", "CLOSED"],
        decision_code: str | None,
        trace_id: str,
        now: datetime | None = None,
    ) -> ConversationSafetyCaseDTO:
        clock = _utc_naive(now)
        case = await self._require_assigned_locked(
            school_id, case_ref, specialist_membership_role_id, clock
        )
        _expect_version(case, expected_version)
        if to_status not in {"IN_REVIEW", "REVIEWED", "ESCALATION_NEEDED", "CLOSED"}:
            raise SchoolConversationSafetyError("invalid case transition")
        if to_status in {"REVIEWED", "ESCALATION_NEEDED", "CLOSED"}:
            if decision_code != _DECISION_CODE:
                raise SchoolConversationSafetyError(
                    "explicit unresolved-context decision is required"
                )
        elif decision_code is not None:
            raise SchoolConversationSafetyError("decision code is invalid for this transition")
        allowed = {
            "ASSIGNED": {"IN_REVIEW"},
            "IN_REVIEW": {"REVIEWED", "ESCALATION_NEEDED", "CLOSED"},
            "ESCALATION_NEEDED": {"IN_REVIEW", "CLOSED"},
        }
        before = case.status
        if to_status not in allowed.get(before, set()):
            raise OptimisticConcurrencyConflict("case transition is not allowed")
        case.status = to_status
        case.decision_code = decision_code
        if to_status == "REVIEWED":
            case.reviewed_at = clock
        elif to_status == "CLOSED":
            case.closed_at = clock
        case.state_version += 1
        case.updated_at = clock
        await self._append_event(
            case,
            actor_membership_role_id=specialist_membership_role_id,
            event_type="TRANSITIONED",
            from_status=before,
            to_status=to_status,
            trace_id=trace_id,
            now=clock,
            decision_code=decision_code,
        )
        return _case_dto(case, await self._class_ref(case.class_id, school_id))

    async def _require_assigned_locked(
        self, school_id: int, case_ref: str, specialist_role_id: int, now: datetime
    ) -> SchoolConversationSafetyCase:
        projected = await self.get_assigned(
            school_id=school_id,
            case_ref=case_ref,
            specialist_membership_role_id=specialist_role_id,
            now=now,
            lock=True,
        )
        if projected is None:
            raise SchoolConversationSafetyError("assigned case is unavailable")
        case = await self.session.scalar(
            select(SchoolConversationSafetyCase)
            .where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.case_ref == case_ref,
                SchoolConversationSafetyCase.assigned_membership_role_id == specialist_role_id,
            )
            .with_for_update()
        )
        if case is None:
            raise SchoolConversationSafetyError("assigned case is unavailable")
        await self._require_school_actor(
            specialist_role_id, school_id, "psychological_specialist", now
        )
        return case

    async def _lock_case(self, school_id: int, case_ref: str) -> SchoolConversationSafetyCase:
        _positive_int(school_id, "school_id")
        _safe_token(case_ref, "case_ref")
        case = await self.session.scalar(
            select(SchoolConversationSafetyCase)
            .where(
                SchoolConversationSafetyCase.school_id == school_id,
                SchoolConversationSafetyCase.case_ref == case_ref,
            )
            .with_for_update()
        )
        if case is None:
            raise SchoolConversationSafetyError("case is unavailable")
        return case

    async def _require_source_scope(
        self,
        *,
        support_session_id: int,
        support_run_id: int,
        safety_decision_id: int,
        school_id: int,
        subject_id: int,
        action: str,
    ) -> None:
        found = await self.session.scalar(
            select(SafetyDecision.id)
            .join(SupportRun, SupportRun.id == SafetyDecision.support_run_id)
            .join(SupportSession, SupportSession.id == SupportRun.support_session_id)
            .join(Subject, Subject.id == SupportSession.subject_id)
            .where(
                SafetyDecision.id == safety_decision_id,
                SafetyDecision.support_run_id == support_run_id,
                SafetyDecision.action == action,
                SupportRun.id == support_run_id,
                SupportRun.support_session_id == support_session_id,
                SupportRun.status == "BLOCKED",
                SupportRun.workflow_action == action,
                SupportRun.assessment_session_id.is_(None),
                SupportSession.id == support_session_id,
                SupportSession.subject_id == subject_id,
                SupportSession.assessment_session_id.is_(None),
                SupportSession.target_role.in_(("student", "student_research")),
                Subject.id == subject_id,
                Subject.school_id == school_id,
                Subject.status == "ACTIVE",
                Subject.data_origin == "SYNTHETIC",
            )
        )
        if found is None:
            raise SchoolConversationSafetyError("safety source scope is unavailable")

    async def _active_class_links(
        self, school_id: int, subject_id: int, now: datetime, *, limit: int
    ) -> list[tuple[SchoolClassStudent, str]]:
        return list(
            (
                await self.session.execute(
                    select(SchoolClassStudent, SchoolClass.class_ref)
                    .join(
                        SchoolClass,
                        (SchoolClass.id == SchoolClassStudent.class_id)
                        & (SchoolClass.school_id == SchoolClassStudent.school_id),
                    )
                    .where(
                        SchoolClassStudent.school_id == school_id,
                        SchoolClassStudent.subject_id == subject_id,
                        SchoolClassStudent.status == "ACTIVE",
                        SchoolClassStudent.revoked_at.is_(None),
                        SchoolClassStudent.valid_from <= now,
                        (SchoolClassStudent.valid_until.is_(None))
                        | (SchoolClassStudent.valid_until >= now),
                        SchoolClass.status == "ACTIVE",
                    )
                    .order_by(SchoolClassStudent.class_id, SchoolClassStudent.id)
                    .limit(limit)
                )
            ).all()
        )

    async def _active_class_link_for_ref(
        self, school_id: int, subject_id: int, class_ref: str, now: datetime
    ) -> tuple[SchoolClassStudent, str]:
        _safe_token(class_ref, "class_ref")
        rows = list(
            (
                await self.session.execute(
                    select(SchoolClassStudent, SchoolClass.class_ref)
                    .join(
                        SchoolClass,
                        (SchoolClass.id == SchoolClassStudent.class_id)
                        & (SchoolClass.school_id == SchoolClassStudent.school_id),
                    )
                    .where(
                        SchoolClassStudent.school_id == school_id,
                        SchoolClassStudent.subject_id == subject_id,
                        SchoolClass.class_ref == class_ref,
                        SchoolClass.status == "ACTIVE",
                        SchoolClassStudent.status == "ACTIVE",
                        SchoolClassStudent.revoked_at.is_(None),
                        SchoolClassStudent.valid_from <= now,
                        (SchoolClassStudent.valid_until.is_(None))
                        | (SchoolClassStudent.valid_until >= now),
                    )
                    .limit(2)
                )
            ).all()
        )
        if len(rows) != 1:
            raise SchoolConversationSafetyError("active class binding is unavailable")
        return rows[0][0], rows[0][1]

    async def _valid_membership_role(
        self, role_id: int, school_id: int, now: datetime
    ) -> MembershipRole | None:
        return await self.session.scalar(
            select(MembershipRole)
            .join(
                AccountSchoolMembership,
                (AccountSchoolMembership.id == MembershipRole.membership_id)
                & (AccountSchoolMembership.school_id == MembershipRole.school_id),
            )
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .where(
                MembershipRole.id == role_id,
                MembershipRole.school_id == school_id,
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= now,
                (MembershipRole.valid_until.is_(None) | (MembershipRole.valid_until >= now)),
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= now,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= now),
                Account.status == "ACTIVE",
            )
        )

    async def _require_school_actor(
        self, role_id: int, school_id: int, role_code: str, now: datetime
    ) -> MembershipRole:
        role = await self._valid_membership_role(role_id, school_id, now)
        if role is None or role.role_code != role_code:
            raise SchoolConversationSafetyError("actor role is unavailable")
        return role

    async def _has_self_grant(
        self, school_id: int, subject_id: int, membership_id: int, now: datetime
    ) -> bool:
        found = await self.session.scalar(
            select(SubjectAccessGrant.id)
            .join(
                AccountSchoolMembership,
                (AccountSchoolMembership.account_id == SubjectAccessGrant.principal_account_id)
                & (AccountSchoolMembership.school_id == SubjectAccessGrant.school_id),
            )
            .where(
                SubjectAccessGrant.subject_id == subject_id,
                SubjectAccessGrant.school_id == school_id,
                SubjectAccessGrant.relationship_type == "SELF",
                SubjectAccessGrant.status == "ACTIVE",
                SubjectAccessGrant.revoked_at.is_(None),
                SubjectAccessGrant.valid_from <= now,
                (SubjectAccessGrant.valid_until.is_(None))
                | (SubjectAccessGrant.valid_until >= now),
                AccountSchoolMembership.id == membership_id,
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= now,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= now),
            )
            .limit(1)
        )
        return found is not None

    async def _require_current_student_subject(
        self, school_id: int, subject_id: int, now: datetime
    ) -> None:
        active_self = exists(
            select(SubjectAccessGrant.id)
            .select_from(SubjectAccessGrant)
            .join(
                AccountSchoolMembership,
                (AccountSchoolMembership.account_id == SubjectAccessGrant.principal_account_id)
                & (AccountSchoolMembership.school_id == SubjectAccessGrant.school_id),
            )
            .join(
                MembershipRole,
                (MembershipRole.membership_id == AccountSchoolMembership.id)
                & (MembershipRole.school_id == AccountSchoolMembership.school_id),
            )
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .where(
                SubjectAccessGrant.subject_id == Subject.id,
                SubjectAccessGrant.school_id == school_id,
                SubjectAccessGrant.relationship_type == "SELF",
                SubjectAccessGrant.status == "ACTIVE",
                SubjectAccessGrant.revoked_at.is_(None),
                SubjectAccessGrant.valid_from <= now,
                (SubjectAccessGrant.valid_until.is_(None))
                | (SubjectAccessGrant.valid_until >= now),
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= now,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= now),
                MembershipRole.role_code == "student",
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= now,
                (MembershipRole.valid_until.is_(None) | (MembershipRole.valid_until >= now)),
                Account.status == "ACTIVE",
            )
        )
        found = await self.session.scalar(
            select(Subject.id).where(
                Subject.id == subject_id,
                Subject.school_id == school_id,
                Subject.status == "ACTIVE",
                Subject.data_origin == "SYNTHETIC",
                active_self,
            )
        )
        if found is None:
            raise SchoolConversationSafetyError("current student scope is unavailable")

    async def _class_ref(self, class_id: int | None, school_id: int) -> str | None:
        if class_id is None:
            return None
        return await self.session.scalar(
            select(SchoolClass.class_ref).where(
                SchoolClass.id == class_id, SchoolClass.school_id == school_id
            )
        )

    def _set_assignment(
        self,
        case: SchoolConversationSafetyCase,
        class_id: int,
        class_student_id: int,
        specialist_role_id: int,
        now: datetime,
    ) -> None:
        case.class_id = class_id
        case.class_student_id = class_student_id
        case.assigned_membership_role_id = specialist_role_id
        case.status = "ASSIGNED"
        case.assigned_at = now

    async def _append_event(
        self,
        case: SchoolConversationSafetyCase,
        *,
        actor_membership_role_id: int,
        event_type: str,
        from_status: str | None,
        to_status: str,
        trace_id: str,
        now: datetime,
        decision_code: str | None = None,
    ) -> None:
        if event_type not in _EVENTS:
            raise SchoolConversationSafetyError("invalid event type")
        self.session.add(
            SchoolConversationSafetyEvent(
                case_id=case.id,
                school_id=case.school_id,
                actor_membership_role_id=actor_membership_role_id,
                assigned_membership_role_id=case.assigned_membership_role_id,
                class_id=case.class_id,
                class_student_id=case.class_student_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                decision_code=decision_code,
                state_version=case.state_version,
                trace_id=trace_id,
                retention_due_at=case.retention_due_at,
                created_at=now,
            )
        )
        await self.session.flush()


def _page(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise SchoolConversationSafetyError("invalid pagination")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100_000:
        raise SchoolConversationSafetyError("invalid pagination")


def _expect_version(case: SchoolConversationSafetyCase, expected: int) -> None:
    if (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected != case.state_version
    ):
        raise OptimisticConcurrencyConflict("case version changed")


def _require_cipher(ciphertext: bytes, fmt: str, key: str, schema: str) -> None:
    if not isinstance(ciphertext, bytes) or not ciphertext or len(ciphertext) > 65_536:
        raise SchoolConversationSafetyError("invalid encrypted review note")
    if any(not isinstance(item, str) or not _TOKEN.fullmatch(item) for item in (fmt, key, schema)):
        raise SchoolConversationSafetyError("invalid encrypted review note")


def _active_scope_predicates(now: datetime) -> tuple[object, ...]:
    self_grant_active = exists(
        select(SubjectAccessGrant.id)
        .select_from(SubjectAccessGrant)
        .join(
            AccountSchoolMembership,
            (AccountSchoolMembership.account_id == SubjectAccessGrant.principal_account_id)
            & (AccountSchoolMembership.school_id == SubjectAccessGrant.school_id),
        )
        .join(
            MembershipRole,
            (MembershipRole.membership_id == AccountSchoolMembership.id)
            & (MembershipRole.school_id == AccountSchoolMembership.school_id),
        )
        .join(Account, Account.id == AccountSchoolMembership.account_id)
        .where(
            SubjectAccessGrant.subject_id == SchoolConversationSafetyCase.subject_id,
            SubjectAccessGrant.school_id == SchoolConversationSafetyCase.school_id,
            SubjectAccessGrant.relationship_type == "SELF",
            SubjectAccessGrant.status == "ACTIVE",
            SubjectAccessGrant.revoked_at.is_(None),
            SubjectAccessGrant.valid_from <= now,
            (SubjectAccessGrant.valid_until.is_(None) | (SubjectAccessGrant.valid_until >= now)),
            AccountSchoolMembership.status == "ACTIVE",
            AccountSchoolMembership.revoked_at.is_(None),
            AccountSchoolMembership.valid_from <= now,
            (AccountSchoolMembership.valid_until.is_(None))
            | (AccountSchoolMembership.valid_until >= now),
            MembershipRole.role_code == "student",
            MembershipRole.status == "ACTIVE",
            MembershipRole.revoked_at.is_(None),
            MembershipRole.valid_from <= now,
            (MembershipRole.valid_until.is_(None) | (MembershipRole.valid_until >= now)),
            Account.status == "ACTIVE",
        )
    )
    assigned_specialist_active = exists(
        select(MembershipRole.id)
        .select_from(MembershipRole)
        .join(
            AccountSchoolMembership,
            (AccountSchoolMembership.id == MembershipRole.membership_id)
            & (AccountSchoolMembership.school_id == MembershipRole.school_id),
        )
        .join(Account, Account.id == AccountSchoolMembership.account_id)
        .where(
            MembershipRole.id == SchoolConversationSafetyCase.assigned_membership_role_id,
            MembershipRole.school_id == SchoolConversationSafetyCase.school_id,
            MembershipRole.role_code == "psychological_specialist",
            MembershipRole.status == "ACTIVE",
            MembershipRole.revoked_at.is_(None),
            MembershipRole.valid_from <= now,
            (MembershipRole.valid_until.is_(None) | (MembershipRole.valid_until >= now)),
            AccountSchoolMembership.status == "ACTIVE",
            AccountSchoolMembership.revoked_at.is_(None),
            AccountSchoolMembership.valid_from <= now,
            (AccountSchoolMembership.valid_until.is_(None))
            | (AccountSchoolMembership.valid_until >= now),
            Account.status == "ACTIVE",
        )
    )
    source_is_current_independent = exists(
        select(SupportRun.id)
        .select_from(SupportRun)
        .join(SupportSession, SupportSession.id == SupportRun.support_session_id)
        .join(SafetyDecision, SafetyDecision.support_run_id == SupportRun.id)
        .where(
            SupportRun.id == SchoolConversationSafetyCase.support_run_id,
            SupportRun.support_session_id == SchoolConversationSafetyCase.support_session_id,
            SupportRun.status == "BLOCKED",
            SupportRun.workflow_action == SchoolConversationSafetyCase.action,
            SupportRun.assessment_session_id.is_(None),
            SupportSession.subject_id == SchoolConversationSafetyCase.subject_id,
            SupportSession.assessment_session_id.is_(None),
            SupportSession.target_role.in_(("student", "student_research")),
            SafetyDecision.id == SchoolConversationSafetyCase.safety_decision_id,
            SafetyDecision.action == SchoolConversationSafetyCase.action,
        )
    )
    return (
        Subject.school_id == SchoolConversationSafetyCase.school_id,
        Subject.status == "ACTIVE",
        Subject.data_origin == "SYNTHETIC",
        SchoolClass.status == "ACTIVE",
        SchoolClassStudent.status == "ACTIVE",
        SchoolClassStudent.revoked_at.is_(None),
        SchoolClassStudent.valid_from <= now,
        (SchoolClassStudent.valid_until.is_(None) | (SchoolClassStudent.valid_until >= now)),
        SchoolClassStudent.subject_id == SchoolConversationSafetyCase.subject_id,
        SchoolClassStudent.class_id == SchoolConversationSafetyCase.class_id,
        SchoolClassStudent.id == SchoolConversationSafetyCase.class_student_id,
        self_grant_active,
        assigned_specialist_active,
        source_is_current_independent,
    )
