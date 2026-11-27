"""School-scoped manual support workflow persistence.

The repository participates in the caller's unit of work and never commits.
Role authorization remains in Backend; this module enforces structural school,
class, student, ownership, and assigned-teacher scope.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import EncryptedPayload, FernetDataProtectionProvider
from .errors import (
    ForeignKeyConflict,
    NotFound,
    OptimisticConcurrencyConflict,
    PersistenceError,
)
from .models import (
    AccountSchoolMembership,
    MembershipRole,
    SchoolClassTeacher,
    SchoolSupportAction,
    SchoolSupportCase,
    SchoolSupportEvent,
    SubjectAccessGrant,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FEEDBACK_REF = re.compile(r"FEED_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}")
_CATEGORY = re.compile(r"^[A-Z][A-Z0-9_]{0,47}$")
_MAX_CONTENT_CHARS = 65_536
_MAX_CIPHERTEXT_BYTES = 1_048_576
_CASE_CONTENT_SCHEMA = "school-support-case-source.v1"
_PLAN_SCHEMA = "school-support-professional-plan.v1"
_INSTRUCTION_SCHEMA = "school-support-action-instruction.v1"
_FEEDBACK_SCHEMA = "school-support-action-feedback.v1"

SourceType = Literal["TEACHER", "STUDENT"]
CASE_STATUSES = frozenset({"SUBMITTED", "TRIAGED", "PLANNED", "FOLLOWING", "REVIEW", "CLOSED"})
ACTION_STATUSES = frozenset({"PENDING", "SUBMITTED", "ACCEPTED", "RETURNED", "CANCELLED"})
_SOURCE_TYPES = frozenset({"TEACHER", "STUDENT"})
_CASE_TRANSITIONS = {
    "SUBMITTED": frozenset({"TRIAGED"}),
    "TRIAGED": frozenset({"PLANNED"}),
    "PLANNED": frozenset({"FOLLOWING"}),
    "FOLLOWING": frozenset({"REVIEW"}),
    "REVIEW": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
}
_OPEN_ACTION_STATUSES = frozenset({"PENDING", "SUBMITTED", "RETURNED"})


class SchoolSupportError(PersistenceError):
    """Fixed support persistence error that never contains user content."""


@dataclass(frozen=True, slots=True, repr=False)
class SchoolSupportCaseDTO:
    id: int = field(repr=False)
    case_ref: str
    school_id: int = field(repr=False)
    subject_id: int = field(repr=False)
    class_id: int = field(repr=False)
    class_student_id: int = field(repr=False)
    source_type: str
    category_code: str
    status: str
    version: int
    created_by_membership_role_id: int = field(repr=False)
    owner_membership_role_id: int | None = field(repr=False)
    trace_id: str = field(repr=False)
    created_at: datetime
    updated_at: datetime
    triaged_at: datetime | None
    planned_at: datetime | None
    following_at: datetime | None
    review_requested_at: datetime | None
    closed_at: datetime | None


@dataclass(frozen=True, slots=True, repr=False)
class SchoolSupportCaseContentDTO:
    source_type: str
    source_text: str = field(repr=False)
    professional_plan: str | None = field(repr=False)
    feedback_source: tuple[str, int] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class SchoolSupportActionDTO:
    id: int = field(repr=False)
    action_ref: str
    case_id: int = field(repr=False)
    school_id: int = field(repr=False)
    subject_id: int = field(repr=False)
    class_id: int = field(repr=False)
    class_student_id: int = field(repr=False)
    created_by_membership_role_id: int = field(repr=False)
    assigned_teacher_membership_role_id: int | None = field(repr=False)
    assigned_class_teacher_id: int | None = field(repr=False)
    recipient_subject_id: int | None = field(repr=False)
    status: str
    version: int
    due_at: datetime
    trace_id: str = field(repr=False)
    feedback_submitted_at: datetime | None
    accepted_at: datetime | None
    returned_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class SchoolSupportActionContentDTO:
    instruction: str = field(repr=False)
    feedback: str | None = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class SchoolSupportEventDTO:
    id: int = field(repr=False)
    case_id: int = field(repr=False)
    action_id: int | None = field(repr=False)
    actor_membership_role_id: int = field(repr=False)
    event_type: str
    from_status: str | None
    to_status: str
    version: int
    trace_id: str = field(repr=False)
    created_at: datetime


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SchoolSupportError(f"invalid {name}")
    return value


def _token(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise SchoolSupportError(f"invalid {name}")
    return value


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if not isinstance(value, datetime):
        raise SchoolSupportError("invalid timestamp")
    if value.tzinfo is None:
        return value
    if value.utcoffset() is None:
        raise SchoolSupportError("invalid timestamp")
    return value.astimezone(UTC).replace(tzinfo=None)


def _content(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_CONTENT_CHARS:
        raise SchoolSupportError(f"invalid {name}")
    return value


def _category(value: object) -> str:
    if not isinstance(value, str) or _CATEGORY.fullmatch(value) is None:
        raise SchoolSupportError("invalid category_code")
    return value


def _source_type(value: object) -> str:
    if not isinstance(value, str) or value not in _SOURCE_TYPES:
        raise SchoolSupportError("invalid source_type")
    return value


def _feedback_source(reference: object, revision: object) -> tuple[str, int]:
    if (
        not isinstance(reference, str)
        or _FEEDBACK_REF.fullmatch(reference) is None
        or type(revision) is not int
        or not 1 <= revision <= 2_147_483_647
    ):
        raise SchoolSupportError("stored feedback source is invalid")
    return reference, revision


def _new_ref(prefix: Literal["SSC", "SSA"]) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def _case_dto(case: SchoolSupportCase) -> SchoolSupportCaseDTO:
    return SchoolSupportCaseDTO(
        id=case.id,
        case_ref=case.case_ref,
        school_id=case.school_id,
        subject_id=case.subject_id,
        class_id=case.class_id,
        class_student_id=case.class_student_id,
        source_type=case.source_type,
        category_code=case.category_code,
        status=case.status,
        version=case.version,
        created_by_membership_role_id=case.created_by_membership_role_id,
        owner_membership_role_id=case.owner_membership_role_id,
        trace_id=case.trace_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        triaged_at=case.triaged_at,
        planned_at=case.planned_at,
        following_at=case.following_at,
        review_requested_at=case.review_requested_at,
        closed_at=case.closed_at,
    )


def _action_dto(action: SchoolSupportAction) -> SchoolSupportActionDTO:
    return SchoolSupportActionDTO(
        id=action.id,
        action_ref=action.action_ref,
        case_id=action.case_id,
        school_id=action.school_id,
        subject_id=action.subject_id,
        class_id=action.class_id,
        class_student_id=action.class_student_id,
        created_by_membership_role_id=action.created_by_membership_role_id,
        assigned_teacher_membership_role_id=action.assigned_teacher_membership_role_id,
        assigned_class_teacher_id=action.assigned_class_teacher_id,
        recipient_subject_id=action.recipient_subject_id,
        status=action.status,
        version=action.version,
        due_at=action.due_at,
        trace_id=action.trace_id,
        feedback_submitted_at=action.feedback_submitted_at,
        accepted_at=action.accepted_at,
        returned_at=action.returned_at,
        cancelled_at=action.cancelled_at,
        created_at=action.created_at,
        updated_at=action.updated_at,
    )


def _event_dto(event: SchoolSupportEvent) -> SchoolSupportEventDTO:
    return SchoolSupportEventDTO(
        id=event.id,
        case_id=event.case_id,
        action_id=event.action_id,
        actor_membership_role_id=event.actor_membership_role_id,
        event_type=event.event_type,
        from_status=event.from_status,
        to_status=event.to_status,
        version=event.version,
        trace_id=event.trace_id,
        created_at=event.created_at,
    )


def _expect_version(row: SchoolSupportCase | SchoolSupportAction, expected: int) -> None:
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != row.version:
        raise OptimisticConcurrencyConflict("support workflow version changed")


def _page(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise SchoolSupportError("invalid pagination")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100_000:
        raise SchoolSupportError("invalid pagination")


def _envelope(
    ciphertext: bytes | None,
    cipher_format_version: str | None,
    key_version: str | None,
    payload_schema_version: str | None,
    *,
    name: str,
) -> EncryptedPayload:
    if (
        not isinstance(ciphertext, bytes)
        or not ciphertext
        or len(ciphertext) > _MAX_CIPHERTEXT_BYTES
    ):
        raise SchoolSupportError(f"invalid {name}")
    cipher_format = cipher_format_version
    key = key_version
    schema = payload_schema_version
    if (
        not isinstance(cipher_format, str)
        or not cipher_format
        or not isinstance(key, str)
        or not key
        or not isinstance(schema, str)
        or not schema
    ):
        raise SchoolSupportError(f"invalid {name}")
    return EncryptedPayload(
        ciphertext=ciphertext,
        cipher_format_version=cipher_format,
        key_version=key,
        payload_schema_version=schema,
    )


class SchoolSupportRepository:
    """Same-UOW support case, action, and append-only event operations."""

    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_case(
        self,
        *,
        school_id: int,
        subject_id: int,
        class_id: int,
        class_student_id: int,
        source_type: str,
        source_text: str,
        category_code: str,
        created_by_membership_role_id: int,
        trace_id: str,
        retention_due_at: datetime | None = None,
        now: datetime | None = None,
        feedback_source: tuple[str, int] | None = None,
    ) -> SchoolSupportCaseDTO:
        school_id = _positive_int(school_id, "school_id")
        subject_id = _positive_int(subject_id, "subject_id")
        class_id = _positive_int(class_id, "class_id")
        class_student_id = _positive_int(class_student_id, "class_student_id")
        creator_id = _positive_int(created_by_membership_role_id, "created_by_membership_role_id")
        source_type = _source_type(source_type)
        category_code = _category(category_code)
        source = _content(source_text, "source_text")
        trace = _token(trace_id, "trace_id") or ""
        clock = _utc_naive(now)
        retention = _utc_naive(retention_due_at) if retention_due_at is not None else None
        source_payload: dict[str, str | int] = {
            "schema_version": _CASE_CONTENT_SCHEMA,
            "source_text": source,
        }
        if feedback_source is not None:
            if source_type != "STUDENT":
                raise SchoolSupportError("only student requests can link a feedback source")
            reference, revision = _feedback_source(*feedback_source)
            source_payload["feedback_ref"] = reference
            source_payload["feedback_revision"] = revision
        protected = self._encrypt_payload(source_payload, _CASE_CONTENT_SCHEMA)
        case = SchoolSupportCase(
            case_ref=_new_ref("SSC"),
            school_id=school_id,
            subject_id=subject_id,
            class_id=class_id,
            class_student_id=class_student_id,
            source_type=source_type,
            category_code=category_code,
            status="SUBMITTED",
            version=1,
            created_by_membership_role_id=creator_id,
            owner_membership_role_id=None,
            source_ciphertext=protected.ciphertext,
            source_cipher_format_version=protected.cipher_format_version,
            source_key_version=protected.key_version,
            source_payload_schema_version=protected.payload_schema_version,
            professional_plan_ciphertext=None,
            professional_plan_cipher_format_version=None,
            professional_plan_key_version=None,
            professional_plan_payload_schema_version=None,
            trace_id=trace,
            triaged_at=None,
            planned_at=None,
            following_at=None,
            review_requested_at=None,
            closed_at=None,
            retention_due_at=retention,
            created_at=clock,
            updated_at=clock,
        )
        try:
            self.session.add(case)
            await self.session.flush()
            self._append_event(
                case=case,
                action=None,
                actor_membership_role_id=creator_id,
                event_type="CASE_SUBMITTED",
                from_status=None,
                to_status="SUBMITTED",
                version=1,
                trace_id=trace,
                now=clock,
            )
            await self.session.flush()
        except IntegrityError:
            raise ForeignKeyConflict("support case scope was rejected") from None
        return _case_dto(case)

    async def get_case(
        self, *, school_id: int, case_ref: str, lock: bool = False
    ) -> SchoolSupportCaseDTO | None:
        school_id = _positive_int(school_id, "school_id")
        case_ref = _token(case_ref, "case_ref") or ""
        statement = select(SchoolSupportCase).where(
            SchoolSupportCase.school_id == school_id,
            SchoolSupportCase.case_ref == case_ref,
        )
        if lock:
            statement = statement.with_for_update()
        case = await self.session.scalar(statement)
        return _case_dto(case) if case is not None else None

    async def get_case_content(
        self, *, school_id: int, case_ref: str
    ) -> SchoolSupportCaseContentDTO:
        case = await self._locked_case(
            _positive_int(school_id, "school_id"),
            _token(case_ref, "case_ref") or "",
            lock=False,
        )
        source_text, source_payload = self._decrypt_content(
            _envelope(
                case.source_ciphertext,
                case.source_cipher_format_version,
                case.source_key_version,
                case.source_payload_schema_version,
                name="source ciphertext",
            ),
            _CASE_CONTENT_SCHEMA,
            "source_text",
        )
        feedback_source = None
        if "feedback_ref" in source_payload or "feedback_revision" in source_payload:
            if case.source_type != "STUDENT":
                raise SchoolSupportError("stored feedback source is invalid")
            feedback_source = _feedback_source(
                source_payload.get("feedback_ref"), source_payload.get("feedback_revision")
            )
        plan = (
            self._decrypt(
                _envelope(
                    case.professional_plan_ciphertext,
                    case.professional_plan_cipher_format_version,
                    case.professional_plan_key_version,
                    case.professional_plan_payload_schema_version,
                    name="professional plan ciphertext",
                ),
                _PLAN_SCHEMA,
                "plan_text",
            )
            if case.professional_plan_ciphertext is not None
            else None
        )
        return SchoolSupportCaseContentDTO(
            source_type=case.source_type,
            source_text=source_text,
            professional_plan=plan,
            feedback_source=feedback_source,
        )

    async def list_cases(
        self,
        *,
        school_id: int,
        subject_id: int | None = None,
        owner_membership_role_id: int | None = None,
        created_by_membership_role_id: int | None = None,
        assigned_teacher_membership_role_id: int | None = None,
        statuses: tuple[str, ...] | list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SchoolSupportCaseDTO]:
        school_id = _positive_int(school_id, "school_id")
        _page(limit, offset)
        statement = select(SchoolSupportCase).where(SchoolSupportCase.school_id == school_id)
        if subject_id is not None:
            statement = statement.where(
                SchoolSupportCase.subject_id == _positive_int(subject_id, "subject_id")
            )
        if owner_membership_role_id is not None:
            statement = statement.where(
                SchoolSupportCase.owner_membership_role_id
                == _positive_int(owner_membership_role_id, "owner_membership_role_id")
            )
        if created_by_membership_role_id is not None:
            statement = statement.where(
                SchoolSupportCase.created_by_membership_role_id
                == _positive_int(created_by_membership_role_id, "created_by_membership_role_id")
            )
        if assigned_teacher_membership_role_id is not None:
            teacher_id = _positive_int(
                assigned_teacher_membership_role_id,
                "assigned_teacher_membership_role_id",
            )
            statement = statement.where(
                exists(
                    select(SchoolSupportAction.id).where(
                        SchoolSupportAction.case_id == SchoolSupportCase.id,
                        SchoolSupportAction.school_id == SchoolSupportCase.school_id,
                        SchoolSupportAction.assigned_teacher_membership_role_id == teacher_id,
                    )
                )
            )
        if statuses is not None:
            if (
                not isinstance(statuses, (tuple, list))
                or not statuses
                or any(
                    not isinstance(status, str) or status not in CASE_STATUSES
                    for status in statuses
                )
            ):
                raise SchoolSupportError("invalid statuses")
            statement = statement.where(SchoolSupportCase.status.in_(statuses))
        cases = await self.session.scalars(
            statement.order_by(SchoolSupportCase.created_at.desc(), SchoolSupportCase.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_case_dto(case) for case in cases.all()]

    async def transition_case(
        self,
        *,
        school_id: int,
        case_ref: str,
        actor_membership_role_id: int,
        expected_version: int,
        to_status: str,
        owner_membership_role_id: int | None = None,
        professional_plan: str | None = None,
        trace_id: str,
        now: datetime | None = None,
    ) -> SchoolSupportCaseDTO:
        school_id = _positive_int(school_id, "school_id")
        actor_id = _positive_int(actor_membership_role_id, "actor_membership_role_id")
        case_ref = _token(case_ref, "case_ref") or ""
        trace = _token(trace_id, "trace_id") or ""
        if not isinstance(to_status, str) or to_status not in CASE_STATUSES:
            raise SchoolSupportError("invalid to_status")
        clock = _utc_naive(now)
        case = await self._locked_case(school_id, case_ref, lock=True)
        _expect_version(case, expected_version)
        if to_status not in _CASE_TRANSITIONS[case.status]:
            raise SchoolSupportError("invalid support case transition")
        if to_status == "TRIAGED":
            owner_id = _positive_int(owner_membership_role_id, "owner_membership_role_id")
            case.owner_membership_role_id = owner_id
            case.triaged_at = clock
        else:
            if owner_membership_role_id is None or owner_membership_role_id != (
                case.owner_membership_role_id
            ):
                raise SchoolSupportError("support case owner scope changed")
        if to_status == "PLANNED":
            if professional_plan is None:
                raise SchoolSupportError("professional plan is required")
            plan = _content(professional_plan, "professional_plan")
            protected = self._encrypt(plan, _PLAN_SCHEMA, "plan_text")
            case.professional_plan_ciphertext = protected.ciphertext
            case.professional_plan_cipher_format_version = protected.cipher_format_version
            case.professional_plan_key_version = protected.key_version
            case.professional_plan_payload_schema_version = protected.payload_schema_version
            case.planned_at = clock
        elif professional_plan is not None:
            raise SchoolSupportError("professional plan is only accepted for PLANNED")
        if to_status == "FOLLOWING":
            action_exists = await self.session.scalar(
                select(
                    exists(
                        select(SchoolSupportAction.id).where(
                            SchoolSupportAction.case_id == case.id,
                            SchoolSupportAction.school_id == case.school_id,
                            SchoolSupportAction.status != "CANCELLED",
                        )
                    )
                )
            )
            if not action_exists:
                raise SchoolSupportError("a support action is required before FOLLOWING")
            case.following_at = clock
        if to_status == "REVIEW":
            case.review_requested_at = clock
        if to_status == "CLOSED":
            open_action = await self.session.scalar(
                select(
                    exists(
                        select(SchoolSupportAction.id).where(
                            SchoolSupportAction.case_id == case.id,
                            SchoolSupportAction.school_id == case.school_id,
                            SchoolSupportAction.status.in_(tuple(_OPEN_ACTION_STATUSES)),
                        )
                    )
                )
            )
            if open_action:
                raise SchoolSupportError("open support actions must be resolved before closing")
            case.closed_at = clock
        from_status = case.status
        case.status = to_status
        case.version += 1
        case.updated_at = clock
        event_type = {
            "TRIAGED": "CASE_TRIAGED",
            "PLANNED": "CASE_PLANNED",
            "FOLLOWING": "CASE_FOLLOWING",
            "REVIEW": "CASE_REVIEW_REQUESTED",
            "CLOSED": "CASE_CLOSED",
        }[to_status]
        try:
            self._append_event(
                case=case,
                action=None,
                actor_membership_role_id=actor_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                version=case.version,
                trace_id=trace,
                now=clock,
            )
            await self.session.flush()
        except IntegrityError:
            raise ForeignKeyConflict("support case transition scope was rejected") from None
        return _case_dto(case)

    async def create_action(
        self,
        *,
        school_id: int,
        case_ref: str,
        actor_membership_role_id: int,
        expected_case_version: int,
        assigned_class_teacher_id: int,
        assigned_teacher_membership_role_id: int,
        instruction: str,
        due_at: datetime,
        trace_id: str,
        now: datetime | None = None,
    ) -> tuple[SchoolSupportCaseDTO, SchoolSupportActionDTO]:
        return await self._create_action(
            school_id=school_id,
            case_ref=case_ref,
            actor_membership_role_id=actor_membership_role_id,
            expected_case_version=expected_case_version,
            assigned_teacher_membership_role_id=assigned_teacher_membership_role_id,
            assigned_class_teacher_id=assigned_class_teacher_id,
            recipient_subject_id=None,
            instruction=instruction,
            due_at=due_at,
            trace_id=trace_id,
            now=now,
        )

    async def create_student_action(
        self,
        *,
        school_id: int,
        case_ref: str,
        actor_membership_role_id: int,
        expected_case_version: int,
        recipient_subject_id: int,
        instruction: str,
        due_at: datetime,
        trace_id: str,
        now: datetime | None = None,
    ) -> tuple[SchoolSupportCaseDTO, SchoolSupportActionDTO]:
        return await self._create_action(
            school_id=school_id,
            case_ref=case_ref,
            actor_membership_role_id=actor_membership_role_id,
            expected_case_version=expected_case_version,
            assigned_teacher_membership_role_id=None,
            assigned_class_teacher_id=None,
            recipient_subject_id=recipient_subject_id,
            instruction=instruction,
            due_at=due_at,
            trace_id=trace_id,
            now=now,
        )

    async def _create_action(
        self,
        *,
        school_id: int,
        case_ref: str,
        actor_membership_role_id: int,
        expected_case_version: int,
        assigned_teacher_membership_role_id: int | None,
        assigned_class_teacher_id: int | None,
        recipient_subject_id: int | None,
        instruction: str,
        due_at: datetime,
        trace_id: str,
        now: datetime | None,
    ) -> tuple[SchoolSupportCaseDTO, SchoolSupportActionDTO]:
        school_id = _positive_int(school_id, "school_id")
        actor_id = _positive_int(actor_membership_role_id, "actor_membership_role_id")
        teacher_id = (
            _positive_int(
                assigned_teacher_membership_role_id,
                "assigned_teacher_membership_role_id",
            )
            if assigned_teacher_membership_role_id is not None
            else None
        )
        class_teacher_id = (
            _positive_int(assigned_class_teacher_id, "assigned_class_teacher_id")
            if assigned_class_teacher_id is not None
            else None
        )
        recipient_id = (
            _positive_int(recipient_subject_id, "recipient_subject_id")
            if recipient_subject_id is not None
            else None
        )
        if (teacher_id is None) == (recipient_id is None):
            raise SchoolSupportError("support action target is invalid")
        case_ref = _token(case_ref, "case_ref") or ""
        trace = _token(trace_id, "trace_id") or ""
        text = _content(instruction, "instruction")
        clock = _utc_naive(now)
        due = _utc_naive(due_at)
        if due <= clock:
            raise SchoolSupportError("due_at must be in the future")
        case = await self._locked_case(school_id, case_ref, lock=True)
        _expect_version(case, expected_case_version)
        if case.status != "PLANNED":
            raise SchoolSupportError("support case must be PLANNED before action creation")
        if case.owner_membership_role_id != actor_id:
            raise SchoolSupportError("support case owner scope changed")
        if recipient_id is not None:
            if recipient_id != case.subject_id:
                raise SchoolSupportError("student action recipient scope changed")
        else:
            class_teacher = await self.session.scalar(
                select(SchoolClassTeacher).where(
                    SchoolClassTeacher.id == class_teacher_id,
                    SchoolClassTeacher.school_id == school_id,
                    SchoolClassTeacher.class_id == case.class_id,
                )
            )
            if class_teacher is None or class_teacher.membership_role_id != teacher_id:
                raise SchoolSupportError("assigned teacher scope changed")
        protected = self._encrypt(text, _INSTRUCTION_SCHEMA, "instruction_text")
        action = SchoolSupportAction(
            action_ref=_new_ref("SSA"),
            case_id=case.id,
            school_id=case.school_id,
            subject_id=case.subject_id,
            class_id=case.class_id,
            class_student_id=case.class_student_id,
            created_by_membership_role_id=actor_id,
            assigned_teacher_membership_role_id=teacher_id,
            assigned_class_teacher_id=class_teacher_id,
            recipient_subject_id=recipient_id,
            status="PENDING",
            version=1,
            due_at=due,
            instruction_ciphertext=protected.ciphertext,
            instruction_cipher_format_version=protected.cipher_format_version,
            instruction_key_version=protected.key_version,
            instruction_payload_schema_version=protected.payload_schema_version,
            feedback_ciphertext=None,
            feedback_cipher_format_version=None,
            feedback_key_version=None,
            feedback_payload_schema_version=None,
            feedback_submitted_at=None,
            accepted_at=None,
            returned_at=None,
            cancelled_at=None,
            trace_id=trace,
            retention_due_at=case.retention_due_at,
            created_at=clock,
            updated_at=clock,
        )
        from_status = case.status
        case.status = "FOLLOWING"
        case.following_at = clock
        case.version += 1
        case.updated_at = clock
        try:
            self.session.add(action)
            await self.session.flush()
            self._append_event(
                case=case,
                action=None,
                actor_membership_role_id=actor_id,
                event_type="CASE_FOLLOWING",
                from_status=from_status,
                to_status="FOLLOWING",
                version=case.version,
                trace_id=trace,
                now=clock,
            )
            self._append_event(
                case=case,
                action=action,
                actor_membership_role_id=actor_id,
                event_type="ACTION_CREATED",
                from_status=None,
                to_status="PENDING",
                version=case.version,
                trace_id=trace,
                now=clock,
            )
            await self.session.flush()
        except IntegrityError:
            raise ForeignKeyConflict("support action scope was rejected") from None
        return _case_dto(case), _action_dto(action)

    async def get_action(
        self, *, school_id: int, action_ref: str, lock: bool = False
    ) -> SchoolSupportActionDTO | None:
        school_id = _positive_int(school_id, "school_id")
        action_ref = _token(action_ref, "action_ref") or ""
        statement = select(SchoolSupportAction).where(
            SchoolSupportAction.school_id == school_id,
            SchoolSupportAction.action_ref == action_ref,
        )
        if lock:
            statement = statement.with_for_update()
        action = await self.session.scalar(statement)
        return _action_dto(action) if action is not None else None

    async def get_action_content(
        self, *, school_id: int, action_ref: str
    ) -> SchoolSupportActionContentDTO:
        action = await self._locked_action(
            _positive_int(school_id, "school_id"),
            _token(action_ref, "action_ref") or "",
            lock=False,
        )
        instruction = self._decrypt(
            _envelope(
                action.instruction_ciphertext,
                action.instruction_cipher_format_version,
                action.instruction_key_version,
                action.instruction_payload_schema_version,
                name="instruction ciphertext",
            ),
            _INSTRUCTION_SCHEMA,
            "instruction_text",
        )
        feedback = (
            self._decrypt(
                _envelope(
                    action.feedback_ciphertext,
                    action.feedback_cipher_format_version,
                    action.feedback_key_version,
                    action.feedback_payload_schema_version,
                    name="feedback ciphertext",
                ),
                _FEEDBACK_SCHEMA,
                "feedback_text",
            )
            if action.feedback_ciphertext is not None
            else None
        )
        return SchoolSupportActionContentDTO(instruction=instruction, feedback=feedback)

    async def list_actions_for_case(
        self,
        *,
        school_id: int,
        case_ref: str,
        statuses: tuple[str, ...] | list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SchoolSupportActionDTO]:
        school_id = _positive_int(school_id, "school_id")
        case_ref = _token(case_ref, "case_ref") or ""
        _page(limit, offset)
        case = await self._locked_case(school_id, case_ref, lock=False)
        statement = select(SchoolSupportAction).where(
            SchoolSupportAction.case_id == case.id,
            SchoolSupportAction.school_id == school_id,
        )
        if statuses is not None:
            if (
                not isinstance(statuses, (tuple, list))
                or not statuses
                or any(
                    not isinstance(status, str) or status not in ACTION_STATUSES
                    for status in statuses
                )
            ):
                raise SchoolSupportError("invalid statuses")
            statement = statement.where(SchoolSupportAction.status.in_(statuses))
        actions = await self.session.scalars(
            statement.order_by(SchoolSupportAction.created_at.desc(), SchoolSupportAction.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_action_dto(action) for action in actions.all()]

    async def submit_action_feedback(
        self,
        *,
        school_id: int,
        action_ref: str,
        teacher_membership_role_id: int,
        expected_version: int,
        feedback: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> SchoolSupportActionDTO:
        school_id = _positive_int(school_id, "school_id")
        teacher_id = _positive_int(teacher_membership_role_id, "teacher_membership_role_id")
        action_ref = _token(action_ref, "action_ref") or ""
        trace = _token(trace_id, "trace_id") or ""
        text = _content(feedback, "feedback")
        clock = _utc_naive(now)
        action = await self._locked_action(school_id, action_ref, lock=True)
        _expect_version(action, expected_version)
        if action.status not in {"PENDING", "RETURNED"}:
            raise SchoolSupportError("support action does not accept feedback")
        if action.assigned_teacher_membership_role_id != teacher_id:
            raise SchoolSupportError("support action teacher scope changed")
        case = await self._locked_case_by_id(action.case_id, school_id)
        if case.status not in {"FOLLOWING", "REVIEW"}:
            raise SchoolSupportError("support case does not accept action feedback")
        protected = self._encrypt(text, _FEEDBACK_SCHEMA, "feedback_text")
        from_status = action.status
        action.status = "SUBMITTED"
        action.version += 1
        action.feedback_ciphertext = protected.ciphertext
        action.feedback_cipher_format_version = protected.cipher_format_version
        action.feedback_key_version = protected.key_version
        action.feedback_payload_schema_version = protected.payload_schema_version
        action.feedback_submitted_at = clock
        action.accepted_at = None
        action.returned_at = None
        action.cancelled_at = None
        action.updated_at = clock
        await self.session.flush()
        self._append_event(
            case=case,
            action=action,
            actor_membership_role_id=teacher_id,
            event_type="ACTION_FEEDBACK_SUBMITTED",
            from_status=from_status,
            to_status="SUBMITTED",
            version=case.version,
            trace_id=trace,
            now=clock,
        )
        await self.session.flush()
        return _action_dto(action)

    async def submit_student_action_feedback(
        self,
        *,
        school_id: int,
        action_ref: str,
        recipient_subject_id: int,
        expected_version: int,
        feedback: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> SchoolSupportActionDTO:
        school_id = _positive_int(school_id, "school_id")
        recipient_id = _positive_int(recipient_subject_id, "recipient_subject_id")
        action_ref = _token(action_ref, "action_ref") or ""
        trace = _token(trace_id, "trace_id") or ""
        text = _content(feedback, "feedback")
        clock = _utc_naive(now)
        action = await self._locked_action(school_id, action_ref, lock=True)
        _expect_version(action, expected_version)
        if action.status not in {"PENDING", "RETURNED"}:
            raise SchoolSupportError("support action does not accept feedback")
        if (
            action.recipient_subject_id != recipient_id
            or action.subject_id != recipient_id
            or action.assigned_teacher_membership_role_id is not None
            or action.assigned_class_teacher_id is not None
        ):
            raise SchoolSupportError("student action recipient scope changed")
        case = await self._locked_case_by_id(action.case_id, school_id)
        if case.subject_id != recipient_id:
            raise SchoolSupportError("student action recipient scope changed")
        if case.status not in {"FOLLOWING", "REVIEW"}:
            raise SchoolSupportError("support case does not accept action feedback")
        student_role_id = await self._student_membership_role_id(
            school_id=school_id,
            subject_id=recipient_id,
            now=clock,
        )
        protected = self._encrypt(text, _FEEDBACK_SCHEMA, "feedback_text")
        from_status = action.status
        action.status = "SUBMITTED"
        action.version += 1
        action.feedback_ciphertext = protected.ciphertext
        action.feedback_cipher_format_version = protected.cipher_format_version
        action.feedback_key_version = protected.key_version
        action.feedback_payload_schema_version = protected.payload_schema_version
        action.feedback_submitted_at = clock
        action.accepted_at = None
        action.returned_at = None
        action.cancelled_at = None
        action.updated_at = clock
        await self.session.flush()
        self._append_event(
            case=case,
            action=action,
            actor_membership_role_id=student_role_id,
            event_type="ACTION_FEEDBACK_SUBMITTED",
            from_status=from_status,
            to_status="SUBMITTED",
            version=case.version,
            trace_id=trace,
            now=clock,
        )
        await self.session.flush()
        return _action_dto(action)

    async def accept_action(
        self,
        *,
        school_id: int,
        action_ref: str,
        owner_membership_role_id: int,
        expected_version: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> SchoolSupportActionDTO:
        return await self._owner_action_transition(
            school_id=school_id,
            action_ref=action_ref,
            owner_membership_role_id=owner_membership_role_id,
            expected_version=expected_version,
            allowed_from=frozenset({"SUBMITTED"}),
            to_status="ACCEPTED",
            event_type="ACTION_ACCEPTED",
            trace_id=trace_id,
            now=now,
        )

    async def return_action(
        self,
        *,
        school_id: int,
        action_ref: str,
        owner_membership_role_id: int,
        expected_version: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> SchoolSupportActionDTO:
        return await self._owner_action_transition(
            school_id=school_id,
            action_ref=action_ref,
            owner_membership_role_id=owner_membership_role_id,
            expected_version=expected_version,
            allowed_from=frozenset({"SUBMITTED"}),
            to_status="RETURNED",
            event_type="ACTION_RETURNED",
            trace_id=trace_id,
            now=now,
        )

    async def cancel_action(
        self,
        *,
        school_id: int,
        action_ref: str,
        owner_membership_role_id: int,
        expected_version: int,
        trace_id: str,
        now: datetime | None = None,
    ) -> SchoolSupportActionDTO:
        return await self._owner_action_transition(
            school_id=school_id,
            action_ref=action_ref,
            owner_membership_role_id=owner_membership_role_id,
            expected_version=expected_version,
            allowed_from=frozenset({"PENDING", "SUBMITTED", "RETURNED"}),
            to_status="CANCELLED",
            event_type="ACTION_CANCELLED",
            trace_id=trace_id,
            now=now,
        )

    async def list_events_for_case(
        self,
        *,
        school_id: int,
        case_ref: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[SchoolSupportEventDTO]:
        school_id = _positive_int(school_id, "school_id")
        case_ref = _token(case_ref, "case_ref") or ""
        _page(limit, offset)
        case = await self._locked_case(school_id, case_ref, lock=False)
        events = await self.session.scalars(
            select(SchoolSupportEvent)
            .where(
                SchoolSupportEvent.school_id == school_id,
                SchoolSupportEvent.case_id == case.id,
            )
            .order_by(SchoolSupportEvent.created_at, SchoolSupportEvent.id)
            .limit(limit)
            .offset(offset)
        )
        return [_event_dto(event) for event in events.all()]

    async def _owner_action_transition(
        self,
        *,
        school_id: int,
        action_ref: str,
        owner_membership_role_id: int,
        expected_version: int,
        allowed_from: frozenset[str],
        to_status: Literal["ACCEPTED", "RETURNED", "CANCELLED"],
        event_type: Literal["ACTION_ACCEPTED", "ACTION_RETURNED", "ACTION_CANCELLED"],
        trace_id: str,
        now: datetime | None,
    ) -> SchoolSupportActionDTO:
        school_id = _positive_int(school_id, "school_id")
        owner_id = _positive_int(owner_membership_role_id, "owner_membership_role_id")
        action_ref = _token(action_ref, "action_ref") or ""
        trace = _token(trace_id, "trace_id") or ""
        clock = _utc_naive(now)
        action = await self._locked_action(school_id, action_ref, lock=True)
        _expect_version(action, expected_version)
        if action.status not in allowed_from:
            raise SchoolSupportError("invalid support action transition")
        case = await self._locked_case_by_id(action.case_id, school_id)
        if case.owner_membership_role_id != owner_id:
            raise SchoolSupportError("support case owner scope changed")
        if case.status not in {"FOLLOWING", "REVIEW"}:
            raise SchoolSupportError("support case does not accept action changes")
        from_status = action.status
        action.status = to_status
        action.version += 1
        action.updated_at = clock
        if to_status == "ACCEPTED":
            action.accepted_at = clock
        elif to_status == "RETURNED":
            action.returned_at = clock
        else:
            action.cancelled_at = clock
        await self.session.flush()
        self._append_event(
            case=case,
            action=action,
            actor_membership_role_id=owner_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            version=case.version,
            trace_id=trace,
            now=clock,
        )
        await self.session.flush()
        return _action_dto(action)

    async def _locked_case(self, school_id: int, case_ref: str, *, lock: bool) -> SchoolSupportCase:
        statement = select(SchoolSupportCase).where(
            SchoolSupportCase.school_id == school_id,
            SchoolSupportCase.case_ref == case_ref,
        )
        if lock:
            statement = statement.with_for_update()
        case = await self.session.scalar(statement)
        if case is None:
            raise NotFound("support case is unavailable")
        return case

    async def _student_membership_role_id(
        self, *, school_id: int, subject_id: int, now: datetime
    ) -> int:
        rows = await self.session.scalars(
            select(MembershipRole.id)
            .join(
                AccountSchoolMembership,
                and_(
                    AccountSchoolMembership.id == MembershipRole.membership_id,
                    AccountSchoolMembership.school_id == MembershipRole.school_id,
                ),
            )
            .join(
                SubjectAccessGrant,
                and_(
                    SubjectAccessGrant.principal_account_id
                    == AccountSchoolMembership.account_id,
                    SubjectAccessGrant.school_id == AccountSchoolMembership.school_id,
                ),
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
                AccountSchoolMembership.school_id == school_id,
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= now,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= now),
                MembershipRole.school_id == school_id,
                MembershipRole.role_code == "student",
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= now,
                (MembershipRole.valid_until.is_(None))
                | (MembershipRole.valid_until >= now),
            )
            .distinct()
        )
        role_ids = rows.all()
        if len(role_ids) != 1:
            raise SchoolSupportError("student action recipient scope changed")
        return role_ids[0]

    async def _locked_case_by_id(self, case_id: int, school_id: int) -> SchoolSupportCase:
        case = await self.session.scalar(
            select(SchoolSupportCase)
            .where(
                SchoolSupportCase.id == case_id,
                SchoolSupportCase.school_id == school_id,
            )
            .with_for_update()
        )
        if case is None:
            raise NotFound("support case is unavailable")
        return case

    async def _locked_action(
        self, school_id: int, action_ref: str, *, lock: bool
    ) -> SchoolSupportAction:
        statement = select(SchoolSupportAction).where(
            SchoolSupportAction.school_id == school_id,
            SchoolSupportAction.action_ref == action_ref,
        )
        if lock:
            statement = statement.with_for_update()
        action = await self.session.scalar(statement)
        if action is None:
            raise NotFound("support action is unavailable")
        return action

    def _encrypt(self, text: str, schema: str, field_name: str) -> EncryptedPayload:
        return self._encrypt_payload({"schema_version": schema, field_name: text}, schema)

    def _encrypt_payload(self, payload: dict[str, str | int], schema: str) -> EncryptedPayload:
        protected = self.protection.encrypt_json(payload, payload_schema_version=schema)
        if not protected.ciphertext or len(protected.ciphertext) > _MAX_CIPHERTEXT_BYTES:
            raise SchoolSupportError("encrypted support content is too large")
        return protected

    def _decrypt(self, encrypted: EncryptedPayload, schema: str, field_name: str) -> str:
        text, _ = self._decrypt_content(encrypted, schema, field_name)
        return text

    def _decrypt_content(
        self, encrypted: EncryptedPayload, schema: str, field_name: str
    ) -> tuple[str, dict[str, object]]:
        payload = self.protection.decrypt_json(encrypted)
        value = payload.get(field_name)
        if payload.get("schema_version") != schema or not isinstance(value, str):
            raise SchoolSupportError("stored support content is invalid")
        return value, payload

    def _append_event(
        self,
        *,
        case: SchoolSupportCase,
        action: SchoolSupportAction | None,
        actor_membership_role_id: int,
        event_type: str,
        from_status: str | None,
        to_status: str,
        version: int,
        trace_id: str,
        now: datetime,
    ) -> None:
        self.session.add(
            SchoolSupportEvent(
                case_id=case.id,
                action_id=action.id if action is not None else None,
                school_id=case.school_id,
                actor_membership_role_id=actor_membership_role_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                version=version,
                trace_id=trace_id,
                retention_due_at=case.retention_due_at,
                created_at=now,
            )
        )


__all__ = [
    "ACTION_STATUSES",
    "CASE_STATUSES",
    "SchoolSupportActionContentDTO",
    "SchoolSupportActionDTO",
    "SchoolSupportCaseContentDTO",
    "SchoolSupportCaseDTO",
    "SchoolSupportError",
    "SchoolSupportEventDTO",
    "SchoolSupportRepository",
    "SourceType",
]
