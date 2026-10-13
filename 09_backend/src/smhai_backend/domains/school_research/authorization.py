"""Read-only student scope resolution for school research CAT workflows.

The caller supplies the SQLAlchemy model/enum namespace, select constructor,
session and a hook that resolves the persisted student account and role. This
keeps the Backend importable without eagerly importing the optional Database
runtime and leaves transaction locks/fresh write-time rechecks to the caller.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from smhai_backend.domains.models import Actor, BackendRole

_PUBLIC_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class ResearchScopeResolutionError(Exception):
    """Content-free failure to resolve exactly one eligible student scope."""

    def __init__(self, code: str = "research_scope_unavailable") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResearchStudentScope:
    """Content-free server-derived scope; contains no answers or CAT snapshot."""

    account_id: int
    membership_role_id: int
    school_id: int
    school_ref: str
    task_id: int
    task_ref: str
    class_id: int
    class_ref: str
    task_enrollment_id: int
    task_enrollment_ref: str
    subject_id: int
    subject_ref: str
    research_session_id: int | None = None
    session_ref: str | None = None


RoleResolver = Callable[[Actor, datetime], Awaitable[tuple[int, int]]]
SelectFactory = Callable[..., Any]


async def resolve_research_student_scope(
    *,
    session: Any,
    actor: Actor,
    db_models: Any,
    db_enums: Any,
    select: SelectFactory,
    resolve_student_role: RoleResolver,
    at: datetime,
    task_ref: str | None = None,
    session_ref: str | None = None,
) -> ResearchStudentScope:
    """Resolve one active self-enrolled research task/session without locking.

    Exactly one of ``task_ref`` or ``session_ref`` is required. The role hook
    should close over the caller's UOW and delegate to the existing
    ``_school_actor_role(uow, actor, "student", at)``. This function performs
    only a read-only candidate resolution: a write/resume caller must repeat
    the predicates under its chosen lock order in the same UOW.
    """

    if not _valid_actor(actor):
        raise ResearchScopeResolutionError("research_actor_invalid")
    if (task_ref is None) == (session_ref is None):
        raise ResearchScopeResolutionError("research_scope_reference_invalid")
    if not callable(resolve_student_role) or not callable(select):
        raise ResearchScopeResolutionError("research_resolver_invalid")
    requested_ref = task_ref if task_ref is not None else session_ref
    if type(requested_ref) is not str or _PUBLIC_REF.fullmatch(requested_ref) is None:
        raise ResearchScopeResolutionError("research_scope_reference_invalid")
    if not isinstance(at, datetime):
        raise ResearchScopeResolutionError("research_scope_time_invalid")
    try:
        at_utc = _utc_naive(at)
    except (OverflowError, ValueError):
        raise ResearchScopeResolutionError("research_scope_time_invalid") from None

    try:
        resolved_ids = await resolve_student_role(actor, at_utc)
    except ResearchScopeResolutionError:
        raise
    if (
        type(resolved_ids) is not tuple
        or len(resolved_ids) != 2
        or not _positive_int(resolved_ids[0])
        or not _positive_int(resolved_ids[1])
    ):
        raise ResearchScopeResolutionError("research_actor_invalid")
    account_id, membership_role_id = resolved_ids

    m = db_models
    e = db_enums
    task = m.MeasurementTask
    school_class = m.SchoolClass
    enrollment = m.TaskEnrollment
    roster = m.SchoolClassStudent
    subject = m.Subject
    grant = m.SubjectAccessGrant
    school = m.School

    statement = (
        select(task, school_class, enrollment, roster, subject, grant, school)
        .join(
            school_class,
            (school_class.id == task.class_id)
            & (school_class.school_id == task.school_id),
        )
        .join(
            enrollment,
            (enrollment.task_id == task.id)
            & (enrollment.school_id == task.school_id)
            & (enrollment.class_id == task.class_id),
        )
        .join(
            roster,
            (roster.id == enrollment.class_student_id)
            & (roster.school_id == enrollment.school_id)
            & (roster.class_id == enrollment.class_id)
            & (roster.subject_id == enrollment.subject_id),
        )
        .join(
            subject,
            (subject.id == enrollment.subject_id)
            & (subject.school_id == enrollment.school_id),
        )
        .join(
            grant,
            (grant.subject_id == subject.id)
            & (grant.school_id == subject.school_id)
            & (grant.principal_account_id == account_id),
        )
        .join(school, school.id == task.school_id)
        .where(
            task.school_id == actor.school_id,
            task.status == "PUBLISHED",
            task.cat_binding_mode == "RESEARCH_PROFILE",
            task.opens_at <= at_utc,
            (task.due_at.is_(None)) | (task.due_at >= at_utc),
            school.school_ref == actor.school_ref,
            school.status == "ACTIVE",
            school.data_origin == e.DataOrigin.SYNTHETIC.value,
            school_class.status == "ACTIVE",
            enrollment.status == "ACTIVE",
            enrollment.revoked_at.is_(None),
            roster.status == "ACTIVE",
            roster.revoked_at.is_(None),
            roster.valid_from <= at_utc,
            (roster.valid_until.is_(None)) | (roster.valid_until >= at_utc),
            subject.status == e.SubjectStatus.ACTIVE.value,
            subject.data_origin == e.DataOrigin.SYNTHETIC.value,
            grant.relationship_type == e.RelationshipType.SELF.value,
            grant.status == e.GrantStatus.ACTIVE.value,
            grant.revoked_at.is_(None),
            grant.valid_from <= at_utc,
            (grant.valid_until.is_(None)) | (grant.valid_until >= at_utc),
        )
    )

    research_session = None
    if task_ref is not None:
        statement = statement.where(task.task_ref == task_ref)
    else:
        research_session = m.SchoolResearchSession
        statement = statement.add_columns(research_session)
        statement = statement.join(
            research_session,
            (research_session.task_enrollment_id == enrollment.id)
            & (research_session.task_id == task.id)
            & (research_session.school_id == task.school_id)
            & (research_session.class_id == task.class_id)
            & (research_session.subject_id == enrollment.subject_id),
        ).where(
            research_session.session_ref == session_ref,
            research_session.status == "IN_PROGRESS",
        )

    # This is a read-only candidate lookup, but it may share an AsyncSession
    # with earlier reads. Refresh mapped entities so the caller receives the
    # database's current row values before doing its transactional recheck.
    result = await session.execute(
        statement.limit(2).execution_options(populate_existing=True)
    )
    rows = result.all()
    if len(rows) != 1:
        raise ResearchScopeResolutionError()
    try:
        row = tuple(rows[0])
    except TypeError:
        raise ResearchScopeResolutionError() from None
    if len(row) != (8 if research_session else 7):
        raise ResearchScopeResolutionError()
    (
        task_row,
        class_row,
        enrollment_row,
        roster_row,
        subject_row,
        grant_row,
        school_row,
    ) = row[:7]
    session_row = row[7] if research_session is not None else None

    # SQL predicates are authoritative; these checks also fail closed for
    # adapters that return malformed result rows or stale identity-map state.
    if not _valid_scope_rows(
        actor=actor,
        task=task_row,
        school_class=class_row,
        enrollment=enrollment_row,
        roster=roster_row,
        subject=subject_row,
        grant=grant_row,
        school=school_row,
        session_row=session_row,
        account_id=account_id,
        task_ref=task_ref,
        session_ref=session_ref,
        at=at_utc,
    ):
        raise ResearchScopeResolutionError()

    return ResearchStudentScope(
        account_id=account_id,
        membership_role_id=membership_role_id,
        school_id=task_row.school_id,
        school_ref=actor.school_ref,
        task_id=task_row.id,
        task_ref=task_row.task_ref,
        class_id=class_row.id,
        class_ref=class_row.class_ref,
        task_enrollment_id=enrollment_row.id,
        task_enrollment_ref=enrollment_row.public_id,
        subject_id=subject_row.id,
        subject_ref=subject_row.subject_ref,
        research_session_id=(session_row.id if session_row is not None else None),
        session_ref=(session_row.session_ref if session_row is not None else None),
    )


def _valid_actor(actor: object) -> bool:
    if (
        type(actor) is not Actor
        or actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.STUDENT
        or not _positive_int(actor.school_id)
        or type(actor.school_ref) is not str
        or _PUBLIC_REF.fullmatch(actor.school_ref) is None
        or type(actor.school_contexts) is not tuple
    ):
        return False
    contexts = [
        context
        for context in actor.school_contexts
        if context.role is BackendRole.STUDENT
        and context.school_id == actor.school_id
        and context.school_ref == actor.school_ref
    ]
    return len(contexts) == 1 and type(contexts[0].context_id) is str


def _valid_scope_rows(
    *,
    actor: Actor,
    task: Any,
    school_class: Any,
    enrollment: Any,
    roster: Any,
    subject: Any,
    grant: Any,
    school: Any,
    session_row: Any,
    account_id: int,
    task_ref: str | None,
    session_ref: str | None,
    at: datetime,
) -> bool:
    if (
        task.school_id != actor.school_id
        or (task_ref is not None and task.task_ref != task_ref)
        or task.status != "PUBLISHED"
        or task.cat_binding_mode != "RESEARCH_PROFILE"
        or task.opens_at > at
        or (task.due_at is not None and task.due_at < at)
        or school.school_ref != actor.school_ref
        or school.id != actor.school_id
        or school.status != "ACTIVE"
        or school.data_origin != "SYNTHETIC"
        or school_class.id != task.class_id
        or school_class.school_id != task.school_id
        or school_class.status != "ACTIVE"
        or enrollment.task_id != task.id
        or enrollment.school_id != task.school_id
        or enrollment.class_id != task.class_id
        or enrollment.status != "ACTIVE"
        or enrollment.revoked_at is not None
        or roster.id != enrollment.class_student_id
        or roster.school_id != enrollment.school_id
        or roster.class_id != enrollment.class_id
        or roster.subject_id != enrollment.subject_id
        or roster.status != "ACTIVE"
        or roster.revoked_at is not None
        or roster.valid_from > at
        or (roster.valid_until is not None and roster.valid_until < at)
        or subject.id != enrollment.subject_id
        or subject.school_id != enrollment.school_id
        or subject.status != "ACTIVE"
        or subject.data_origin != "SYNTHETIC"
        or grant.subject_id != subject.id
        or grant.school_id != subject.school_id
        or grant.principal_account_id != account_id
        or grant.relationship_type != "SELF"
        or grant.status != "ACTIVE"
        or grant.revoked_at is not None
        or grant.valid_from > at
        or (grant.valid_until is not None and grant.valid_until < at)
        or not _positive_int(task.id)
        or not _positive_int(school_class.id)
        or not _positive_int(enrollment.id)
        or not _positive_int(roster.id)
        or not _positive_int(subject.id)
        or not _public_ref(task.task_ref)
        or not _public_ref(school_class.class_ref)
        or not _public_ref(enrollment.public_id)
        or not _public_ref(subject.subject_ref)
    ):
        return False
    if session_row is None:
        return session_ref is None
    return (
        session_row.session_ref == session_ref
        and session_row.status == "IN_PROGRESS"
        and session_row.task_enrollment_id == enrollment.id
        and session_row.task_id == task.id
        and session_row.school_id == task.school_id
        and session_row.class_id == task.class_id
        and session_row.subject_id == subject.id
        and _positive_int(session_row.id)
        and _public_ref(session_row.session_ref)
    )


def _public_ref(value: object) -> bool:
    return type(value) is str and _PUBLIC_REF.fullmatch(value) is not None


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
