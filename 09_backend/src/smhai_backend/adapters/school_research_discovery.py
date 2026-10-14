"""Read-only, current-scope projections for a student's research tasks/history."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUseError,
    ResearchStudyUsePolicy,
)
from smhai_backend.domains.school_research_discovery.schemas import (
    ResearchDiscoverySessionDto,
    ResearchDiscoverySessionPage,
    ResearchDiscoveryTaskDto,
    ResearchDiscoveryTaskPage,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PUBLIC_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_PUBLICATION_NOT_APPROVED = "not_approved_for_publication_or_operational_use"
_RESEARCH_MODE = "RESEARCH_PROFILE"
_RESPONSE_ORIGIN = "PUBLIC_OBSERVED"


class SchoolResearchDiscoveryPersistenceAdapter:
    """Query currently eligible own-scope records without loading encrypted payloads."""

    def __init__(
        self, owner: Any, *, study_use_policy: ResearchStudyUsePolicy | None = None
    ) -> None:
        if not callable(getattr(owner, "_uow", None)):
            raise TypeError("owner must provide database units of work")
        if study_use_policy is not None and not callable(
            getattr(study_use_policy, "require_scope", None)
        ):
            raise TypeError("study-use policy must provide require_scope")
        self._owner = owner
        self._study_use_policy = study_use_policy

    async def list_tasks(
        self, actor: Actor, *, limit: int, offset: int, at: datetime
    ) -> ResearchDiscoveryTaskPage:
        _validate_page(limit, offset)
        actor = _require_student_actor(actor)
        at_utc = _utc_naive(at)
        from sqlalchemy import func

        owner = self._owner
        m = owner._db_models
        e = owner._db_enums
        async with owner._uow() as uow:
            account_id, _role_id = await _persisted_student_role(owner, uow, actor, at_utc)
            policy = self._require_policy()
            pins = _policy_pins(policy, school_id=actor.school_id, at=at_utc)
            if not pins:
                return ResearchDiscoveryTaskPage(
                    items=[],
                    total=0,
                    limit=limit,
                    offset=offset,
                    has_more=False,
                    next_offset=None,
                )

            statement, task, school_class, binding, profile, enrollment = _eligible_task_query(
                owner=owner,
                account_id=account_id,
                actor=actor,
                at=at_utc,
                policy=policy,
                pins=pins,
                func=func,
                enums=e,
            )
            session = m.SchoolResearchSession
            statement = statement.outerjoin(
                session,
                (session.school_id == task.school_id)
                & (session.task_id == task.id)
                & (session.class_id == school_class.id)
                & (session.task_enrollment_id == enrollment.id)
                & (session.subject_id == enrollment.subject_id)
                & (session.task_binding_id == binding.id)
                & (session.profile_version_id == profile.id)
                & (session.profile_ref == binding.profile_ref)
                & (session.profile_version_number == binding.profile_version_number)
                & (session.profile_sha256 == binding.profile_sha256)
                & (session.response_origin == _RESPONSE_ORIGIN)
                & (session.research_only.is_(True))
                & (session.purpose == "RESEARCH_SIMULATION")
                & (session.status.in_(("IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED")))
                & (session.items_answered >= 0),
            ).add_columns(session)
            statement = statement.options(
                *_metadata_load_options(task, school_class, enrollment, binding, profile),
                _session_metadata_load_option(session),
            )
            count_source = (
                statement.with_only_columns(task.id, maintain_column_froms=True)
                .distinct()
                .order_by(None)
                .subquery()
            )
            total = int(
                await uow.session.scalar(owner._select(func.count()).select_from(count_source)) or 0
            )
            rows = list(
                (
                    await uow.session.execute(
                        statement.order_by(task.published_at.desc(), task.id.desc())
                        .offset(offset)
                        .limit(limit + 1)
                    )
                ).all()
            )

            items: list[ResearchDiscoveryTaskDto] = []
            for row in rows[:limit]:
                task_row, class_row, _enrollment_row, binding_row, profile_row, session_row = row
                _require_current_pin(
                    policy, actor.school_id, binding_row, profile_row, task_row, at_utc
                )
                if (
                    not _valid_public_text(profile_row.source_population_scope, 64)
                    or not _valid_public_ref(profile_row.instrument_id)
                    or not _valid_public_ref(task_row.instrument_version)
                ):
                    raise _dependency_error()
                if session_row is not None and (
                    session_row.school_id != task_row.school_id
                    or session_row.task_id != task_row.id
                    or session_row.class_id != class_row.id
                    or session_row.task_enrollment_id != _enrollment_row.id
                    or session_row.subject_id != _enrollment_row.subject_id
                    or session_row.task_binding_id != binding_row.id
                    or session_row.profile_version_id != profile_row.id
                    or session_row.profile_ref != binding_row.profile_ref
                    or session_row.profile_version_number != binding_row.profile_version_number
                    or session_row.profile_sha256 != binding_row.profile_sha256
                    or session_row.response_origin != _RESPONSE_ORIGIN
                    or type(session_row.items_answered) is not int
                    or session_row.items_answered < 0
                    or session_row.status not in {"IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED"}
                    or not _valid_public_ref(session_row.session_ref)
                ):
                    raise _dependency_error()
                completions = int(session_row is not None and session_row.status == "COMPLETED")
                items.append(
                    ResearchDiscoveryTaskDto(
                        task_ref=task_row.task_ref,
                        class_ref=class_row.class_ref,
                        profile_ref=binding_row.profile_ref,
                        source_population_scope=profile_row.source_population_scope,
                        instrument_id=profile_row.instrument_id,
                        instrument_version=task_row.instrument_version,
                        publication_status=_PUBLICATION_NOT_APPROVED,
                        research_only=True,
                        opens_at=task_row.opens_at,
                        due_at=task_row.due_at,
                        status="PUBLISHED",
                        completion_count=completions,
                        session_ref=session_row.session_ref if session_row is not None else None,
                        session_status=session_row.status if session_row is not None else None,
                        items_answered=(
                            session_row.items_answered if session_row is not None else 0
                        ),
                    )
                )
            has_more = len(rows) > limit
            return ResearchDiscoveryTaskPage(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=has_more,
                next_offset=(offset + len(items) if has_more else None),
            )

    async def list_sessions(
        self, actor: Actor, *, limit: int, offset: int, at: datetime
    ) -> ResearchDiscoverySessionPage:
        _validate_page(limit, offset)
        actor = _require_student_actor(actor)
        at_utc = _utc_naive(at)
        from sqlalchemy import func

        owner = self._owner
        m = owner._db_models
        e = owner._db_enums
        async with owner._uow() as uow:
            account_id, _role_id = await _persisted_student_role(owner, uow, actor, at_utc)
            policy = self._require_policy()
            pins = _policy_pins(policy, school_id=actor.school_id, at=at_utc)
            if not pins:
                return ResearchDiscoverySessionPage(
                    items=[],
                    total=0,
                    limit=limit,
                    offset=offset,
                    has_more=False,
                    next_offset=None,
                )

            statement, task, school_class, binding, profile, enrollment = _eligible_task_query(
                owner=owner,
                account_id=account_id,
                actor=actor,
                at=at_utc,
                policy=policy,
                pins=pins,
                func=func,
                enums=e,
            )
            session = m.SchoolResearchSession
            statement = statement.join(
                session,
                (session.school_id == task.school_id)
                & (session.task_id == task.id)
                & (session.class_id == school_class.id)
                & (session.task_enrollment_id == enrollment.id)
                & (session.subject_id == enrollment.subject_id)
                & (session.task_binding_id == binding.id)
                & (session.profile_version_id == profile.id)
                & (session.profile_ref == binding.profile_ref)
                & (session.profile_version_number == binding.profile_version_number)
                & (session.profile_sha256 == binding.profile_sha256)
                & (session.response_origin == _RESPONSE_ORIGIN),
            ).add_columns(session)
            statement = statement.options(
                *_metadata_load_options(task, school_class, enrollment, binding, profile),
                _session_metadata_load_option(session),
            )
            statement = statement.where(
                session.research_only.is_(True),
                session.purpose == "RESEARCH_SIMULATION",
                session.status.in_(("IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED")),
                session.items_answered >= 0,
            )
            count_source = (
                statement.with_only_columns(session.id, maintain_column_froms=True)
                .distinct()
                .order_by(None)
                .subquery()
            )
            total = int(
                await uow.session.scalar(owner._select(func.count()).select_from(count_source)) or 0
            )
            rows = list(
                (
                    await uow.session.execute(
                        statement.order_by(session.started_at.desc(), session.id.desc())
                        .offset(offset)
                        .limit(limit + 1)
                    )
                ).all()
            )
            items: list[ResearchDiscoverySessionDto] = []
            for row in rows[:limit]:
                task_row, _class_row, _enrollment_row, binding_row, profile_row, session_row = row
                _require_current_pin(
                    policy, actor.school_id, binding_row, profile_row, task_row, at_utc
                )
                if (
                    type(session_row.items_answered) is not int
                    or session_row.items_answered < 0
                    or session_row.status not in {"IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED"}
                ):
                    raise _dependency_error()
                items.append(
                    ResearchDiscoverySessionDto(
                        session_ref=session_row.session_ref,
                        task_ref=task_row.task_ref,
                        status=session_row.status,
                        items_answered=session_row.items_answered,
                        completed_at=session_row.completed_at,
                        research_only=True,
                    )
                )
            has_more = len(rows) > limit
            return ResearchDiscoverySessionPage(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=has_more,
                next_offset=(offset + len(items) if has_more else None),
            )

    def _require_policy(self) -> ResearchStudyUsePolicy:
        policy = self._study_use_policy
        if (
            type(policy) is not ResearchStudyUsePolicy
            or policy.source_rights_verified is not True
            or not callable(getattr(policy, "require_scope", None))
        ):
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="trusted research discovery policy is unavailable",
                retryable=True,
            )
        return policy


def _metadata_load_options(task, school_class, enrollment, binding, profile):
    from sqlalchemy.orm import load_only

    return (
        load_only(
            task.id,
            task.school_id,
            task.task_ref,
            task.instrument_id,
            task.instrument_version,
            task.opens_at,
            task.due_at,
            task.published_at,
            task.status,
            task.cat_binding_mode,
            task.config_version,
        ),
        load_only(school_class.id, school_class.school_id, school_class.class_ref),
        load_only(
            enrollment.id,
            enrollment.task_id,
            enrollment.school_id,
            enrollment.class_id,
            enrollment.class_student_id,
            enrollment.subject_id,
        ),
        load_only(
            binding.id,
            binding.school_id,
            binding.task_id,
            binding.class_id,
            binding.profile_version_id,
            binding.profile_ref,
            binding.profile_version_number,
            binding.profile_sha256,
            binding.response_origin,
            binding.status,
            binding.revoked_at,
            binding.research_only,
            binding.purpose,
            binding.config_version,
        ),
        load_only(
            profile.id,
            profile.school_id,
            profile.profile_ref,
            profile.version_number,
            profile.instrument_id,
            profile.source_population_scope,
            profile.profile_sha256,
            profile.manifest_sha256,
            profile.fit_sha256,
            profile.calibration_sha256,
            profile.parameter_origin,
            profile.published_parameter_crosswalk_sha256,
            profile.rights_status,
            profile.execution_status,
            profile.rights_revoked_at,
            profile.disabled_at,
            profile.simulation_enabled_at,
            profile.research_only,
            profile.human_curated,
            profile.psychological_interpretation_allowed,
            profile.publication_status,
            profile.purpose,
        ),
    )


def _session_metadata_load_option(session):
    from sqlalchemy.orm import load_only

    return load_only(
        session.id,
        session.session_ref,
        session.school_id,
        session.task_id,
        session.class_id,
        session.task_enrollment_id,
        session.subject_id,
        session.task_binding_id,
        session.profile_version_id,
        session.profile_ref,
        session.profile_version_number,
        session.profile_sha256,
        session.response_origin,
        session.research_only,
        session.purpose,
        session.status,
        session.items_answered,
        session.started_at,
        session.completed_at,
    )


def _eligible_task_query(
    *,
    owner: Any,
    account_id: int,
    actor: Actor,
    at: datetime,
    policy: ResearchStudyUsePolicy,
    pins: tuple[ResearchStudyProfilePin, ...],
    func: Any,
    enums: Any,
):
    from sqlalchemy import String, cast, literal

    m = owner._db_models
    task = m.MeasurementTask
    school_class = m.SchoolClass
    enrollment = m.TaskEnrollment
    roster = m.SchoolClassStudent
    subject = m.Subject
    grant = m.SubjectAccessGrant
    school = m.School
    binding = m.SchoolResearchTaskBinding
    profile = m.SchoolResearchProfileVersion

    eligible_enrollments = (
        owner._select(func.count(func.distinct(enrollment.id)))
        .select_from(enrollment)
        .join(
            roster,
            (roster.id == enrollment.class_student_id)
            & (roster.school_id == enrollment.school_id)
            & (roster.class_id == enrollment.class_id)
            & (roster.subject_id == enrollment.subject_id),
        )
        .join(
            subject,
            (subject.id == enrollment.subject_id) & (subject.school_id == enrollment.school_id),
        )
        .join(
            grant,
            (grant.subject_id == subject.id)
            & (grant.school_id == subject.school_id)
            & (grant.principal_account_id == account_id),
        )
        .where(
            enrollment.task_id == task.id,
            enrollment.school_id == task.school_id,
            enrollment.class_id == task.class_id,
            enrollment.status == "ACTIVE",
            enrollment.revoked_at.is_(None),
            roster.status == "ACTIVE",
            roster.revoked_at.is_(None),
            roster.valid_from <= at,
            (roster.valid_until.is_(None)) | (roster.valid_until >= at),
            subject.status == enums.SubjectStatus.ACTIVE.value,
            subject.data_origin == enums.DataOrigin.SYNTHETIC.value,
            grant.relationship_type == enums.RelationshipType.SELF.value,
            grant.status == enums.GrantStatus.ACTIVE.value,
            grant.revoked_at.is_(None),
            grant.valid_from <= at,
            (grant.valid_until.is_(None)) | (grant.valid_until >= at),
        )
        .correlate(task)
        .scalar_subquery()
    )
    eligible_grants = (
        owner._select(func.count(grant.id))
        .where(
            grant.subject_id == subject.id,
            grant.school_id == subject.school_id,
            grant.principal_account_id == account_id,
            grant.relationship_type == enums.RelationshipType.SELF.value,
            grant.status == enums.GrantStatus.ACTIVE.value,
            grant.revoked_at.is_(None),
            grant.valid_from <= at,
            (grant.valid_until.is_(None)) | (grant.valid_until >= at),
        )
        .correlate(subject)
        .scalar_subquery()
    )
    pin_clauses = [
        (profile.profile_ref == pin.profile_ref)
        & (profile.profile_sha256 == pin.profile_sha256)
        & (profile.manifest_sha256 == pin.manifest_sha256)
        & (profile.published_parameter_crosswalk_sha256 == pin.published_crosswalk_sha256)
        for pin in pins
    ]
    statement = (
        owner._select(task, school_class, enrollment, binding, profile)
        .join(
            school_class,
            (school_class.id == task.class_id) & (school_class.school_id == task.school_id),
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
            (subject.id == enrollment.subject_id) & (subject.school_id == enrollment.school_id),
        )
        .join(
            grant,
            (grant.subject_id == subject.id)
            & (grant.school_id == subject.school_id)
            & (grant.principal_account_id == account_id),
        )
        .join(school, school.id == task.school_id)
        .join(
            binding,
            (binding.school_id == task.school_id)
            & (binding.task_id == task.id)
            & (binding.class_id == task.class_id),
        )
        .join(
            profile,
            (profile.id == binding.profile_version_id)
            & (profile.school_id == binding.school_id)
            & (profile.profile_ref == binding.profile_ref)
            & (profile.version_number == binding.profile_version_number)
            & (profile.profile_sha256 == binding.profile_sha256),
        )
        .where(
            task.school_id == actor.school_id,
            task.status == "PUBLISHED",
            task.cat_binding_mode == _RESEARCH_MODE,
            task.opens_at <= at,
            task.due_at.is_not(None),
            task.due_at >= at,
            task.opens_at >= policy.starts_at.replace(tzinfo=None),
            task.due_at <= policy.ends_at.replace(tzinfo=None),
            school.school_ref == actor.school_ref,
            school.status == "ACTIVE",
            school.data_origin == enums.DataOrigin.SYNTHETIC.value,
            school_class.status == "ACTIVE",
            enrollment.status == "ACTIVE",
            enrollment.revoked_at.is_(None),
            roster.status == "ACTIVE",
            roster.revoked_at.is_(None),
            roster.valid_from <= at,
            (roster.valid_until.is_(None)) | (roster.valid_until >= at),
            subject.status == enums.SubjectStatus.ACTIVE.value,
            subject.data_origin == enums.DataOrigin.SYNTHETIC.value,
            grant.relationship_type == enums.RelationshipType.SELF.value,
            grant.status == enums.GrantStatus.ACTIVE.value,
            grant.revoked_at.is_(None),
            grant.valid_from <= at,
            (grant.valid_until.is_(None)) | (grant.valid_until >= at),
            eligible_enrollments == 1,
            eligible_grants == 1,
            binding.status == "ACTIVE",
            binding.revoked_at.is_(None),
            binding.response_origin == _RESPONSE_ORIGIN,
            binding.research_only.is_(True),
            binding.purpose == "RESEARCH_SIMULATION",
            profile.rights_status == "VERIFIED",
            profile.execution_status == "SIMULATION_ENABLED",
            profile.rights_revoked_at.is_(None),
            profile.disabled_at.is_(None),
            profile.simulation_enabled_at.is_not(None),
            profile.research_only.is_(True),
            profile.human_curated.is_(False),
            profile.psychological_interpretation_allowed.is_(False),
            profile.publication_status == _PUBLICATION_NOT_APPROVED,
            profile.purpose == "RESEARCH_SIMULATION",
            task.instrument_id == profile.instrument_id,
            task.instrument_version
            == (literal("research-v") + cast(profile.version_number, String)),
            task.config_version == binding.config_version,
            (pin_clauses[0] if len(pin_clauses) == 1 else _or(pin_clauses)),
        )
    )
    return statement, task, school_class, binding, profile, enrollment


def _or(clauses):
    from sqlalchemy import or_

    return or_(*clauses)


def _policy_pins(
    policy: ResearchStudyUsePolicy, *, school_id: int, at: datetime
) -> tuple[ResearchStudyProfilePin, ...]:
    try:
        now = _utc_aware(at)
        if not policy.starts_at <= now <= policy.ends_at:
            raise ResearchStudyUseError("scope_denied")
        return policy.profiles if policy.school_id == school_id else ()
    except Exception:
        raise _study_denied() from None


def _require_current_pin(policy, school_id, binding, profile, task, at) -> None:
    if (
        binding.response_origin != _RESPONSE_ORIGIN
        or binding.profile_ref != profile.profile_ref
        or binding.profile_sha256 != profile.profile_sha256
        or binding.profile_version_number != profile.version_number
        or profile.publication_status != _PUBLICATION_NOT_APPROVED
        or profile.parameter_origin != "PUBLISHED_ROUNDED_REFERENCE"
        or profile.fit_sha256 is not None
        or profile.calibration_sha256 is not None
        or type(profile.manifest_sha256) is not str
        or _SHA256.fullmatch(profile.manifest_sha256) is None
        or type(profile.published_parameter_crosswalk_sha256) is not str
        or _SHA256.fullmatch(profile.published_parameter_crosswalk_sha256) is None
    ):
        raise _not_found()
    try:
        pin = policy.require_scope(
            school_id=school_id,
            profile_ref=binding.profile_ref,
            profile_sha256=binding.profile_sha256,
            manifest_sha256=profile.manifest_sha256,
            at=_utc_aware(at),
            task_opens_at=_utc_aware(task.opens_at),
            task_due_at=_utc_aware(task.due_at),
        )
    except ResearchStudyUseError:
        raise _not_found() from None
    if (
        type(pin) is not ResearchStudyProfilePin
        or pin.profile_ref != binding.profile_ref
        or pin.profile_sha256 != binding.profile_sha256
        or pin.manifest_sha256 != profile.manifest_sha256
        or pin.published_crosswalk_sha256 != profile.published_parameter_crosswalk_sha256
    ):
        raise _not_found()


async def _persisted_student_role(owner, uow, actor, at):
    try:
        return await owner._school_actor_role(uow, actor, "student", at)
    except Exception as exc:
        from smhai_backend.core.errors import BackendError

        if isinstance(exc, BackendError) and exc.code is ErrorCode.FORBIDDEN:
            raise
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="student research discovery is unavailable",
            retryable=True,
        ) from None


def _require_student_actor(actor: Any) -> Actor:
    if (
        type(actor) is not Actor
        or actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.STUDENT
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or _PUBLIC_REF.fullmatch(actor.school_ref) is None
        or type(actor.school_contexts) is not tuple
        or sum(
            context.role is BackendRole.STUDENT
            and context.school_id == actor.school_id
            and context.school_ref == actor.school_ref
            for context in actor.school_contexts
        )
        != 1
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    return actor


def _validate_page(limit: int, offset: int) -> None:
    if (
        type(limit) is not int
        or not 1 <= limit <= 30
        or type(offset) is not int
        or not 0 <= offset <= 10_000
    ):
        raise error(
            ErrorCode.VALIDATION_FAILED,
            detail="research discovery pagination is invalid",
        )


def _valid_public_ref(value: object) -> bool:
    return type(value) is str and _PUBLIC_REF.fullmatch(value) is not None


def _valid_public_text(value: object, maximum: int) -> bool:
    return type(value) is str and 1 <= len(value.strip()) <= maximum and value == value.strip()


def _utc_naive(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research discovery time is invalid")
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone(UTC).replace(tzinfo=None)
    except (OverflowError, ValueError):
        raise error(
            ErrorCode.VALIDATION_FAILED,
            detail="research discovery time is invalid",
        ) from None


def _utc_aware(value: datetime | None) -> datetime:
    if not isinstance(value, datetime):
        raise ResearchStudyUseError("task_window_invalid")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _study_denied():
    return error(ErrorCode.FORBIDDEN, detail="research discovery is unavailable")


def _not_found():
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="research discovery is unavailable")


def _dependency_error():
    return error(
        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
        detail="research discovery data is unavailable",
    )
