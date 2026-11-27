"""Transactional school support persistence with role-specific projections."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from smhai_backend.adapters.school_feedback import SchoolFeedbackPersistenceAdapter
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.school_support.service import (
    validate_action_outcome,
    validate_case_transition,
)

_CASE_RESOURCE = "school_support_case"
_ACTION_RESOURCE = "school_support_action"
_USER_REF = re.compile(r"^USER_([A-Za-z0-9][A-Za-z0-9_.-]{0,122})$")
_LEGACY_FEEDBACK_QUESTION = re.compile(
    r"^请说明测评反馈第 [1-9][0-9]{0,9} 版\n反馈编号 FEED_[A-Za-z0-9_.-]{1,123}\n\n"
)
_SOURCE_LABELS = {"TEACHER": "TEACHER_REFERRAL", "STUDENT": "STUDENT_REQUEST"}


def _not_found():
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="support resource was not found")


def _conflict():
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="support workflow state changed")


def _positive_version(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid support version")
    return value


def _source_label(value: str) -> str:
    label = _SOURCE_LABELS.get(value)
    if label is None:
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            detail="school support data is unavailable",
        )
    return label


def _role_value(actor: Any) -> str:
    return str(getattr(getattr(actor, "role", None), "value", getattr(actor, "role", ""))).lower()


def _repo_error(exc: Exception) -> None:
    name = type(exc).__name__
    if name == "OptimisticConcurrencyConflict":
        raise _conflict() from None
    if name in {"ForeignKeyConflict", "NotFound"}:
        raise _not_found() from None
    if name in {"SchoolSupportError", "PersistenceError"}:
        raise _conflict() from None
    raise exc


def _content_error(exc: Exception) -> None:
    if type(exc).__name__ in {"SchoolSupportError", "InvalidTag", "ValueError"}:
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            detail="school support content is unavailable",
        ) from None
    _repo_error(exc)


class SchoolSupportPersistenceAdapter:
    """Compose the shared tenant/idempotency port with support workflow reads."""

    def __init__(self, persistence: Any) -> None:
        self._reviews = SchoolFeedbackPersistenceAdapter(persistence)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._reviews, name)

    async def _require_actor(
        self,
        uow: Any,
        actor: Any,
        role_code: str,
        now: datetime,
        *,
        lock: bool = False,
    ) -> tuple[int, int]:
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or _role_value(actor) != role_code
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or not isinstance(actor.school_ref, str)
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return await self._school_actor_role(uow, actor, role_code, now, lock=lock)

    async def _teacher_class_ids(self, uow: Any, role_id: int, now: datetime) -> set[int]:
        m = self._db_models
        rows = (
            await uow.session.execute(
                self._select(m.SchoolClassTeacher.class_id).where(
                    m.SchoolClassTeacher.membership_role_id == role_id,
                    m.SchoolClassTeacher.status == "ACTIVE",
                    m.SchoolClassTeacher.revoked_at.is_(None),
                    m.SchoolClassTeacher.valid_from <= now,
                    (m.SchoolClassTeacher.valid_until.is_(None))
                    | (m.SchoolClassTeacher.valid_until >= now),
                )
            )
        ).scalars()
        return {int(value) for value in rows.all()}

    async def _teacher_class_student(
        self,
        uow: Any,
        *,
        school_id: int,
        role_id: int,
        class_ref: str,
        student_ref: str,
        now: datetime,
    ) -> Any:
        m = self._db_models
        rows = list(
            (
                await uow.session.execute(
                    self._select(
                        m.Subject.id,
                        m.Subject.subject_ref,
                        m.SchoolClassStudent.class_id,
                        m.SchoolClassStudent.id,
                        m.SchoolClass.class_ref,
                    )
                    .join(
                        m.SchoolClassStudent,
                        (m.SchoolClassStudent.subject_id == m.Subject.id)
                        & (m.SchoolClassStudent.school_id == m.Subject.school_id),
                    )
                    .join(
                        m.SchoolClass,
                        (m.SchoolClass.id == m.SchoolClassStudent.class_id)
                        & (m.SchoolClass.school_id == m.SchoolClassStudent.school_id),
                    )
                    .join(
                        m.SchoolClassTeacher,
                        (m.SchoolClassTeacher.class_id == m.SchoolClass.id)
                        & (m.SchoolClassTeacher.school_id == m.SchoolClass.school_id),
                    )
                    .join(
                        m.SubjectAccessGrant,
                        (m.SubjectAccessGrant.subject_id == m.Subject.id)
                        & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
                    )
                    .where(
                        m.Subject.subject_ref == student_ref,
                        m.Subject.school_id == school_id,
                        m.SchoolClass.school_id == school_id,
                        m.SchoolClass.class_ref == class_ref,
                        m.SchoolClass.status == "ACTIVE",
                        m.SchoolClassStudent.status == "ACTIVE",
                        m.SchoolClassStudent.revoked_at.is_(None),
                        m.SchoolClassStudent.valid_from <= now,
                        (m.SchoolClassStudent.valid_until.is_(None))
                        | (m.SchoolClassStudent.valid_until >= now),
                        m.SchoolClassTeacher.membership_role_id == role_id,
                        m.SchoolClassTeacher.status == "ACTIVE",
                        m.SchoolClassTeacher.revoked_at.is_(None),
                        m.SchoolClassTeacher.valid_from <= now,
                        (m.SchoolClassTeacher.valid_until.is_(None))
                        | (m.SchoolClassTeacher.valid_until >= now),
                        m.SubjectAccessGrant.relationship_type == "SELF",
                        m.SubjectAccessGrant.status == "ACTIVE",
                        m.SubjectAccessGrant.revoked_at.is_(None),
                        m.SubjectAccessGrant.valid_from <= now,
                        (m.SubjectAccessGrant.valid_until.is_(None))
                        | (m.SubjectAccessGrant.valid_until >= now),
                    )
                    .limit(2)
                )
            ).all()
        )
        if len(rows) != 1:
            raise _not_found()
        return rows[0]

    async def _student_scope(
        self, uow: Any, actor: Any, now: datetime
    ) -> tuple[int, str, int, int, str]:
        m = self._db_models
        if not isinstance(actor.subject_id, str):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        rows = list(
            (
                await uow.session.execute(
                    self._select(
                        m.Subject.id,
                        m.Subject.subject_ref,
                        m.SchoolClassStudent.class_id,
                        m.SchoolClassStudent.id,
                        m.SchoolClass.class_ref,
                    )
                    .join(
                        m.SubjectAccessGrant,
                        (m.SubjectAccessGrant.subject_id == m.Subject.id)
                        & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
                    )
                    .join(
                        m.SchoolClassStudent,
                        (m.SchoolClassStudent.subject_id == m.Subject.id)
                        & (m.SchoolClassStudent.school_id == m.Subject.school_id),
                    )
                    .join(
                        m.SchoolClass,
                        (m.SchoolClass.id == m.SchoolClassStudent.class_id)
                        & (m.SchoolClass.school_id == m.SchoolClassStudent.school_id),
                    )
                    .where(
                        m.Subject.subject_ref == actor.subject_id,
                        m.Subject.school_id == actor.school_id,
                        m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                        m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                        m.SchoolClass.status == "ACTIVE",
                        m.SchoolClassStudent.status == "ACTIVE",
                        m.SchoolClassStudent.revoked_at.is_(None),
                        m.SchoolClassStudent.valid_from <= now,
                        (m.SchoolClassStudent.valid_until.is_(None))
                        | (m.SchoolClassStudent.valid_until >= now),
                        m.SubjectAccessGrant.relationship_type == "SELF",
                        m.SubjectAccessGrant.status == "ACTIVE",
                        m.SubjectAccessGrant.revoked_at.is_(None),
                        m.SubjectAccessGrant.valid_from <= now,
                        (m.SubjectAccessGrant.valid_until.is_(None))
                        | (m.SubjectAccessGrant.valid_until >= now),
                    )
                    .limit(2)
                )
            ).all()
        )
        if len(rows) != 1:
            raise _not_found()
        row = rows[0]
        return int(row[0]), str(row[1]), int(row[2]), int(row[3]), str(row[4])

    async def _student_subject(
        self, uow: Any, actor: Any, now: datetime
    ) -> tuple[int, int, str]:
        m = self._db_models
        if not isinstance(actor.subject_id, str):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        rows = list(
            (
                await uow.session.execute(
                    self._select(m.Subject.id, m.Subject.subject_ref)
                    .join(
                        m.SubjectAccessGrant,
                        (m.SubjectAccessGrant.subject_id == m.Subject.id)
                        & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
                    )
                    .where(
                        m.Subject.subject_ref == actor.subject_id,
                        m.Subject.school_id == actor.school_id,
                        m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                        m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                        m.SubjectAccessGrant.relationship_type == "SELF",
                        m.SubjectAccessGrant.status == "ACTIVE",
                        m.SubjectAccessGrant.revoked_at.is_(None),
                        m.SubjectAccessGrant.valid_from <= now,
                        (m.SubjectAccessGrant.valid_until.is_(None))
                        | (m.SubjectAccessGrant.valid_until >= now),
                    )
                    .limit(2)
                )
            ).all()
        )
        if len(rows) != 1:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return int(rows[0][0]), int(actor.school_id), str(rows[0][1])

    async def _student_class_current(
        self, uow: Any, *, subject_id: int, class_id: int, now: datetime
    ) -> bool:
        m = self._db_models
        row = await uow.session.scalar(
            self._select(m.SchoolClassStudent.id)
            .where(
                m.SchoolClassStudent.subject_id == subject_id,
                m.SchoolClassStudent.class_id == class_id,
                m.SchoolClassStudent.status == "ACTIVE",
                m.SchoolClassStudent.revoked_at.is_(None),
                m.SchoolClassStudent.valid_from <= now,
                (m.SchoolClassStudent.valid_until.is_(None))
                | (m.SchoolClassStudent.valid_until >= now),
            )
            .limit(1)
        )
        return row is not None

    async def _teacher_assignment_for_user(
        self,
        uow: Any,
        *,
        school_id: int,
        class_id: int,
        teacher_user_id: str,
        now: datetime,
    ) -> tuple[int, int]:
        match = _USER_REF.fullmatch(teacher_user_id)
        if match is None:
            raise _not_found()
        m = self._db_models
        rows = list(
            (
                await uow.session.execute(
                    self._select(m.MembershipRole.id, m.SchoolClassTeacher.id)
                    .join(
                        m.AccountSchoolMembership,
                        (m.AccountSchoolMembership.id == m.MembershipRole.membership_id)
                        & (m.AccountSchoolMembership.school_id == m.MembershipRole.school_id),
                    )
                    .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                    .join(
                        m.SchoolClassTeacher,
                        (m.SchoolClassTeacher.membership_role_id == m.MembershipRole.id)
                        & (m.SchoolClassTeacher.school_id == m.MembershipRole.school_id),
                    )
                    .join(
                        m.SchoolClass,
                        (m.SchoolClass.id == m.SchoolClassTeacher.class_id)
                        & (m.SchoolClass.school_id == m.SchoolClassTeacher.school_id),
                    )
                    .join(m.School, m.School.id == m.MembershipRole.school_id)
                    .where(
                        m.Account.public_id == match.group(1),
                        m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                        m.AccountSchoolMembership.school_id == school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.MembershipRole.school_id == school_id,
                        m.MembershipRole.role_code == "teacher",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                        m.SchoolClassTeacher.class_id == class_id,
                        m.SchoolClassTeacher.status == "ACTIVE",
                        m.SchoolClassTeacher.revoked_at.is_(None),
                        m.SchoolClassTeacher.valid_from <= now,
                        (m.SchoolClassTeacher.valid_until.is_(None))
                        | (m.SchoolClassTeacher.valid_until >= now),
                        m.SchoolClass.status == "ACTIVE",
                        m.School.status == "ACTIVE",
                        m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    )
                    .limit(2)
                )
            ).all()
        )
        if len(rows) != 1:
            raise _not_found()
        if len(rows[0]) != 2:
            raise _not_found()
        return int(rows[0][0]), int(rows[0][1])

    async def _teacher_user_ref(
        self, uow: Any, *, school_id: int, role_id: int
    ) -> str | None:
        m = self._db_models
        value = await uow.session.scalar(
            self._select(m.Account.public_id)
            .join(
                m.AccountSchoolMembership,
                (m.AccountSchoolMembership.account_id == m.Account.id)
                & (m.AccountSchoolMembership.school_id == school_id),
            )
            .join(
                m.MembershipRole,
                (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
            )
            .where(
                m.MembershipRole.id == role_id,
                m.MembershipRole.school_id == school_id,
            )
            .limit(1)
        )
        return f"USER_{value}" if isinstance(value, str) else None

    async def _subject_ref(self, uow: Any, *, school_id: int, subject_id: int) -> str:
        m = self._db_models
        value = await uow.session.scalar(
            self._select(m.Subject.subject_ref).where(
                m.Subject.id == subject_id,
                m.Subject.school_id == school_id,
            )
        )
        if not isinstance(value, str):
            raise _not_found()
        return value

    async def _class_ref(self, uow: Any, *, school_id: int, class_id: int) -> str:
        m = self._db_models
        value = await uow.session.scalar(
            self._select(m.SchoolClass.class_ref).where(
                m.SchoolClass.id == class_id,
                m.SchoolClass.school_id == school_id,
            )
        )
        if not isinstance(value, str):
            raise _not_found()
        return value

    async def _case(self, uow: Any, actor: Any, case_ref: str, *, lock: bool = False):
        if not isinstance(case_ref, str) or not case_ref.startswith("SSC_"):
            raise _not_found()
        try:
            case = await uow.support_cases.get_case(
                school_id=actor.school_id, case_ref=case_ref, lock=lock
            )
        except Exception as exc:
            _repo_error(exc)
            raise
        if case is None:
            raise _not_found()
        return case

    async def _action(self, uow: Any, actor: Any, action_ref: str, *, lock: bool = False):
        if not isinstance(action_ref, str) or not action_ref.startswith("SSA_"):
            raise _not_found()
        try:
            action = await uow.support_cases.get_action(
                school_id=actor.school_id, action_ref=action_ref, lock=lock
            )
        except Exception as exc:
            _repo_error(exc)
            raise
        if action is None:
            raise _not_found()
        return action

    async def _case_content(self, uow: Any, actor: Any, case_ref: str):
        try:
            return await uow.support_cases.get_case_content(
                school_id=actor.school_id, case_ref=case_ref
            )
        except Exception as exc:
            _content_error(exc)
            raise

    async def _action_content(self, uow: Any, actor: Any, action_ref: str):
        try:
            return await uow.support_cases.get_action_content(
                school_id=actor.school_id, action_ref=action_ref
            )
        except Exception as exc:
            _content_error(exc)
            raise

    async def _case_actions(self, uow: Any, actor: Any, case_ref: str) -> list[Any]:
        try:
            return await uow.support_cases.list_actions_for_case(
                school_id=actor.school_id,
                case_ref=case_ref,
                limit=200,
                offset=0,
            )
        except Exception as exc:
            _repo_error(exc)
            raise

    def _student_action_schema_ready(self) -> bool:
        action_model = getattr(self._db_models, "SchoolSupportAction", None)
        return action_model is not None and hasattr(action_model, "recipient_subject_id")

    async def _student_case_actions(
        self, uow: Any, actor: Any, case_ref: str, subject_id: int
    ) -> list[Any]:
        if not self._student_action_schema_ready():
            return []
        return [
            action
            for action in await self._case_actions(uow, actor, case_ref)
            if getattr(action, "recipient_subject_id", None) == subject_id
        ]

    async def _audit(
        self,
        uow: Any,
        *,
        account_id: int,
        action: str,
        resource_type: str,
        resource_ref: str,
        trace_id: str,
        state: str,
    ) -> None:
        await uow.audit.append(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_ref,
            result=self._db_enums.AuditResult.SUCCESS,
            trace_id=trace_id,
            actor_account_id=account_id,
            safe_metadata={"source": "school_support", "state": state},
        )

    @staticmethod
    def _summary(case: Any) -> dict[str, Any]:
        return {
            "case_ref": case.case_ref,
            "source": _source_label(case.source_type),
            "category_code": case.category_code,
            "status": case.status,
            "state_version": case.version,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        }

    async def _action_projection(
        self,
        uow: Any,
        actor: Any,
        action: Any,
        *,
        case_ref: str,
        include_teacher: bool,
    ) -> dict[str, Any]:
        content = await self._action_content(uow, actor, action.action_ref)
        return {
            "action_ref": action.action_ref,
            "case_ref": case_ref,
            "status": action.status,
            "version": action.version,
            "teacher_user_id": (
                await self._teacher_user_ref(
                    uow,
                    school_id=actor.school_id,
                    role_id=action.assigned_teacher_membership_role_id,
                )
                if include_teacher
                else None
            ),
            "instructions": content.instruction,
            "feedback": content.feedback,
            "due_at": action.due_at,
            "created_at": action.created_at,
            "updated_at": action.updated_at,
        }

    async def _case_detail(
        self,
        uow: Any,
        actor: Any,
        case: Any,
        *,
        role_id: int,
        role: BackendRole,
        now: datetime,
    ) -> dict[str, Any]:
        result = self._summary(case)
        if role is BackendRole.PSYCHOLOGICAL_SPECIALIST and case.owner_membership_role_id is None:
            return result
        result.update(
            {
                "assigned_at": case.triaged_at,
                "closed_at": case.closed_at,
            }
        )
        if role is BackendRole.STUDENT:
            content = (
                await self._case_content(uow, actor, case.case_ref)
                if case.source_type == "STUDENT" else None
            )
            actions = [
                await self._action_projection(
                    uow,
                    actor,
                    action,
                    case_ref=case.case_ref,
                    include_teacher=False,
                )
                for action in await self._student_case_actions(
                    uow, actor, case.case_ref, case.subject_id
                )
            ]
            result.update(
                {
                    "student_ref": None,
                    "class_ref": None,
                    "content": content.source_text if content is not None else None,
                    "plan": None,
                    "actions": actions,
                }
            )
            return result
        result.update(
            {
                "student_ref": await self._subject_ref(
                    uow, school_id=actor.school_id, subject_id=case.subject_id
                ),
                "class_ref": await self._class_ref(
                    uow, school_id=actor.school_id, class_id=case.class_id
                ),
            }
        )
        creator = case.created_by_membership_role_id == role_id
        if role is BackendRole.TEACHER:
            content = (
                await self._case_content(uow, actor, case.case_ref) if creator else None
            )
            actions = [
                await self._action_projection(
                    uow,
                    actor,
                    action,
                    case_ref=case.case_ref,
                    include_teacher=False,
                )
                for action in await self._case_actions(uow, actor, case.case_ref)
                if action.assigned_teacher_membership_role_id == role_id
            ]
            result.update(
                {
                    "content": content.source_text if content is not None else None,
                    "plan": None,
                    "actions": actions,
                }
            )
            return result
        content = await self._case_content(uow, actor, case.case_ref)
        actions = [
            await self._action_projection(
                uow,
                actor,
                action,
                case_ref=case.case_ref,
                include_teacher=True,
            )
            for action in await self._case_actions(uow, actor, case.case_ref)
        ]
        result.update(
            {
                "content": content.source_text,
                "plan": content.professional_plan,
                "actions": actions,
            }
        )
        return result

    async def support_list_students(self, actor: Any) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            _account_id, role_id = await self._require_actor(uow, actor, "teacher", now)
            m = self._db_models
            rows = list(
                (
                    await uow.session.execute(
                        self._select(
                            m.Subject.subject_ref,
                            m.AccountSchoolMembership.display_name,
                            m.SchoolClass.class_ref,
                        )
                        .join(
                            m.SchoolClassStudent,
                            (m.SchoolClassStudent.subject_id == m.Subject.id)
                            & (m.SchoolClassStudent.school_id == m.Subject.school_id),
                        )
                        .join(
                            m.SchoolClass,
                            (m.SchoolClass.id == m.SchoolClassStudent.class_id)
                            & (m.SchoolClass.school_id == m.SchoolClassStudent.school_id),
                        )
                        .join(
                            m.SchoolClassTeacher,
                            (m.SchoolClassTeacher.class_id == m.SchoolClass.id)
                            & (m.SchoolClassTeacher.school_id == m.SchoolClass.school_id),
                        )
                        .join(
                            m.SubjectAccessGrant,
                            (m.SubjectAccessGrant.subject_id == m.Subject.id)
                            & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
                        )
                        .join(
                            m.AccountSchoolMembership,
                            (
                                m.AccountSchoolMembership.account_id
                                == m.SubjectAccessGrant.principal_account_id
                            )
                            & (
                                m.AccountSchoolMembership.school_id
                                == m.SubjectAccessGrant.school_id
                            ),
                        )
                        .where(
                            m.Subject.school_id == actor.school_id,
                            m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                            m.Subject.data_origin
                            == self._db_enums.DataOrigin.SYNTHETIC.value,
                            m.SchoolClass.status == "ACTIVE",
                            m.SchoolClassStudent.status == "ACTIVE",
                            m.SchoolClassStudent.revoked_at.is_(None),
                            m.SchoolClassStudent.valid_from <= now,
                            (m.SchoolClassStudent.valid_until.is_(None))
                            | (m.SchoolClassStudent.valid_until >= now),
                            m.SchoolClassTeacher.membership_role_id == role_id,
                            m.SchoolClassTeacher.status == "ACTIVE",
                            m.SchoolClassTeacher.revoked_at.is_(None),
                            m.SchoolClassTeacher.valid_from <= now,
                            (m.SchoolClassTeacher.valid_until.is_(None))
                            | (m.SchoolClassTeacher.valid_until >= now),
                            m.SubjectAccessGrant.relationship_type == "SELF",
                            m.SubjectAccessGrant.status == "ACTIVE",
                            m.SubjectAccessGrant.revoked_at.is_(None),
                            m.SubjectAccessGrant.valid_from <= now,
                            (m.SubjectAccessGrant.valid_until.is_(None))
                            | (m.SubjectAccessGrant.valid_until >= now),
                            m.AccountSchoolMembership.status == "ACTIVE",
                            m.AccountSchoolMembership.revoked_at.is_(None),
                            m.AccountSchoolMembership.display_name.is_not(None),
                        )
                        .distinct()
                        .order_by(m.SchoolClass.class_ref, m.AccountSchoolMembership.display_name)
                    )
                ).all()
            )
            items = [
                {
                    "student_ref": str(row[0]),
                    "display_name": str(row[1]),
                    "class_ref": str(row[2]),
                }
                for row in rows
            ]
            return {"items": items, "total": len(items)}

    async def support_list_assignees(self, actor: Any, case_ref: str) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            case = await self._case(uow, actor, case_ref)
            _account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            if case.owner_membership_role_id != role_id:
                raise _not_found()
            m = self._db_models
            rows = list(
                (
                    await uow.session.execute(
                        self._select(
                            m.Account.public_id,
                            m.AccountSchoolMembership.display_name,
                        )
                        .join(
                            m.AccountSchoolMembership,
                            (m.AccountSchoolMembership.account_id == m.Account.id)
                            & (m.AccountSchoolMembership.school_id == actor.school_id),
                        )
                        .join(
                            m.MembershipRole,
                            (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                            & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
                        )
                        .join(
                            m.SchoolClassTeacher,
                            (m.SchoolClassTeacher.membership_role_id == m.MembershipRole.id)
                            & (m.SchoolClassTeacher.school_id == m.MembershipRole.school_id),
                        )
                        .join(
                            m.SchoolClass,
                            (m.SchoolClass.id == m.SchoolClassTeacher.class_id)
                            & (m.SchoolClass.school_id == m.SchoolClassTeacher.school_id),
                        )
                        .join(m.School, m.School.id == m.MembershipRole.school_id)
                        .where(
                            m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                            m.AccountSchoolMembership.school_id == actor.school_id,
                            m.AccountSchoolMembership.status == "ACTIVE",
                            m.AccountSchoolMembership.revoked_at.is_(None),
                            m.AccountSchoolMembership.valid_from <= now,
                            (m.AccountSchoolMembership.valid_until.is_(None))
                            | (m.AccountSchoolMembership.valid_until >= now),
                            m.AccountSchoolMembership.display_name.is_not(None),
                            m.MembershipRole.school_id == actor.school_id,
                            m.MembershipRole.role_code == "teacher",
                            m.MembershipRole.status == "ACTIVE",
                            m.MembershipRole.revoked_at.is_(None),
                            m.MembershipRole.valid_from <= now,
                            (m.MembershipRole.valid_until.is_(None))
                            | (m.MembershipRole.valid_until >= now),
                            m.SchoolClassTeacher.class_id == case.class_id,
                            m.SchoolClassTeacher.status == "ACTIVE",
                            m.SchoolClassTeacher.revoked_at.is_(None),
                            m.SchoolClassTeacher.valid_from <= now,
                            (m.SchoolClassTeacher.valid_until.is_(None))
                            | (m.SchoolClassTeacher.valid_until >= now),
                            m.SchoolClass.status == "ACTIVE",
                            m.School.status == "ACTIVE",
                            m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                        )
                        .distinct()
                        .order_by(
                            m.AccountSchoolMembership.display_name,
                            m.Account.public_id,
                        )
                    )
                ).all()
            )
            items = [
                {
                    "teacher_user_id": f"USER_{row[0]}",
                    "display_name": str(row[1]),
                }
                for row in rows
            ]
            return {"items": items, "total": len(items)}

    async def support_create_case(
        self,
        actor: Any,
        *,
        student_ref: str | None,
        class_ref: str | None,
        category_code: str,
        content: str,
        idempotency,
        trace_id: str,
        feedback_source: tuple[str, int] | None = None,
    ) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            role = actor.role
            role_code = "teacher" if role is BackendRole.TEACHER else "student"
            account_id, role_id = await self._require_actor(
                uow, actor, role_code, now, lock=feedback_source is not None
            )
            if role is BackendRole.TEACHER:
                if feedback_source is not None:
                    raise error(ErrorCode.FORBIDDEN, detail="access denied")
                if student_ref is None or class_ref is None:
                    raise error(
                        ErrorCode.VALIDATION_FAILED,
                        detail="teacher referrals require a student and class",
                    )
                subject = await self._teacher_class_student(
                    uow,
                    school_id=actor.school_id,
                    role_id=role_id,
                    class_ref=class_ref,
                    student_ref=student_ref,
                    now=now,
                )
                subject_id = int(subject[0])
                class_id = int(subject[2])
                class_student_id = int(subject[3])
                source_type = "TEACHER"
            elif feedback_source is not None:
                feedback_ref, revision = feedback_source
                subject_id, class_id, class_student_id = (
                    await self._reviews.student_feedback_support_scope(
                        uow, actor, account_id, feedback_ref, revision, now
                    )
                )
                current_subject_id, _, _ = await self._student_subject(uow, actor, now)
                if subject_id != current_subject_id:
                    raise _not_found()
                source_type = "STUDENT"
                content = f"请说明测评反馈第 {revision} 版\n反馈编号 {feedback_ref}\n\n{content}"
            else:
                scope = await self._student_scope(uow, actor, now)
                subject_id = int(scope[0])
                class_id = int(scope[2])
                class_student_id = int(scope[3])
                source_type = "STUDENT"
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = self._receipt_ref(claim, _CASE_RESOURCE)
                case = await self._case(uow, actor, ref)
                return self._summary(case)
            try:
                case = await uow.support_cases.create_case(
                    school_id=actor.school_id,
                    subject_id=subject_id,
                    class_id=class_id,
                    class_student_id=class_student_id,
                    source_type=source_type,
                    source_text=content,
                    category_code=category_code,
                    created_by_membership_role_id=role_id,
                    trace_id=trace_id,
                    now=now,
                    feedback_source=feedback_source,
                )
            except Exception as exc:
                _repo_error(exc)
                raise
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=case.case_ref
            )
            await self._audit(
                uow,
                account_id=account_id,
                action="school_support.case_created",
                resource_type=_CASE_RESOURCE,
                resource_ref=case.case_ref,
                trace_id=trace_id,
                state="SUBMITTED",
            )
            return self._summary(case)

    async def support_list_cases(
        self, actor: Any, *, offset: int, limit: int
    ) -> dict[str, Any]:
        from sqlalchemy import and_, exists, func, or_, select

        now = self._utc_now()
        async with self._uow() as uow:
            m = self._db_models
            if actor.role is BackendRole.TEACHER:
                _account_id, role_id = await self._require_actor(uow, actor, "teacher", now)
                class_ids = await self._teacher_class_ids(uow, role_id, now)
                if not class_ids:
                    return {"items": [], "total": 0}
                condition = and_(
                    m.SchoolSupportCase.school_id == actor.school_id,
                    m.SchoolSupportCase.class_id.in_(tuple(class_ids)),
                    or_(
                        m.SchoolSupportCase.created_by_membership_role_id == role_id,
                        exists(
                            select(m.SchoolSupportAction.id).where(
                                m.SchoolSupportAction.case_id
                                == m.SchoolSupportCase.id,
                                m.SchoolSupportAction.school_id
                                == m.SchoolSupportCase.school_id,
                                m.SchoolSupportAction.assigned_teacher_membership_role_id
                                == role_id,
                            )
                        ),
                    ),
                )
            elif actor.role is BackendRole.STUDENT:
                await self._require_actor(uow, actor, "student", now)
                subject_id, _subject_school_id, _subject_ref = await self._student_subject(
                    uow, actor, now
                )
                condition = and_(
                    m.SchoolSupportCase.school_id == actor.school_id,
                    m.SchoolSupportCase.subject_id == subject_id,
                )
            else:
                _account_id, role_id = await self._require_actor(
                    uow, actor, "psychological_specialist", now
                )
                condition = and_(
                    m.SchoolSupportCase.school_id == actor.school_id,
                    or_(
                        and_(
                            m.SchoolSupportCase.status == "SUBMITTED",
                            m.SchoolSupportCase.owner_membership_role_id.is_(None),
                        ),
                        m.SchoolSupportCase.owner_membership_role_id == role_id,
                    ),
                )
            total = await uow.session.scalar(
                self._select(func.count()).select_from(m.SchoolSupportCase).where(condition)
            )
            rows = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolSupportCase)
                        .where(condition)
                        .order_by(
                            m.SchoolSupportCase.created_at.desc(),
                            m.SchoolSupportCase.id.desc(),
                        )
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
            )
            return {
                "items": [self._summary(case) for case in rows],
                "total": int(total or 0),
            }

    async def support_list_actions(
        self, actor: Any, *, offset: int, limit: int
    ) -> dict[str, Any]:
        from sqlalchemy import and_, func

        now = self._utc_now()
        async with self._uow() as uow:
            m = self._db_models
            if actor.role is BackendRole.TEACHER:
                _account_id, role_id = await self._require_actor(uow, actor, "teacher", now)
                class_ids = await self._teacher_class_ids(uow, role_id, now)
                if not class_ids:
                    return {"items": [], "total": 0}
                condition = and_(
                    m.SchoolSupportAction.school_id == actor.school_id,
                    m.SchoolSupportAction.assigned_teacher_membership_role_id == role_id,
                    m.SchoolSupportCase.class_id.in_(tuple(class_ids)),
                )
            elif actor.role is BackendRole.STUDENT:
                await self._require_actor(uow, actor, "student", now)
                subject_id, _subject_school_id, _subject_ref = await self._student_subject(
                    uow, actor, now
                )
                if not self._student_action_schema_ready():
                    return {"items": [], "total": 0}
                condition = and_(
                    m.SchoolSupportAction.school_id == actor.school_id,
                    m.SchoolSupportAction.subject_id == subject_id,
                    m.SchoolSupportAction.recipient_subject_id == subject_id,
                    m.SchoolSupportCase.subject_id == subject_id,
                )
            else:
                raise error(ErrorCode.FORBIDDEN, detail="access denied")
            join_condition = and_(
                m.SchoolSupportAction.case_id == m.SchoolSupportCase.id,
                m.SchoolSupportAction.school_id == m.SchoolSupportCase.school_id,
            )
            total = await uow.session.scalar(
                self._select(func.count())
                .select_from(m.SchoolSupportAction)
                .join(m.SchoolSupportCase, join_condition)
                .where(condition)
            )
            rows = list(
                (
                    await uow.session.execute(
                        self._select(
                            m.SchoolSupportAction,
                            m.SchoolSupportCase.case_ref,
                        )
                        .join(m.SchoolSupportCase, join_condition)
                        .where(condition)
                        .order_by(
                            m.SchoolSupportAction.due_at,
                            m.SchoolSupportAction.created_at,
                            m.SchoolSupportAction.id,
                        )
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
            )
            return {
                "items": [
                    await self._action_projection(
                        uow,
                        actor,
                        action,
                        case_ref=case_ref,
                        include_teacher=False,
                    )
                    for action, case_ref in rows
                ],
                "total": int(total or 0),
            }

    async def support_get_case(self, actor: Any, case_ref: str) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            role = actor.role
            role_code = {
                BackendRole.STUDENT: "student",
                BackendRole.TEACHER: "teacher",
                BackendRole.PSYCHOLOGICAL_SPECIALIST: "psychological_specialist",
            }.get(role)
            if role_code is None:
                raise error(ErrorCode.FORBIDDEN, detail="access denied")
            _account_id, role_id = await self._require_actor(uow, actor, role_code, now)
            case = await self._case(uow, actor, case_ref)
            if role is BackendRole.STUDENT:
                subject_id, _school_id, _subject_ref = await self._student_subject(
                    uow, actor, now
                )
                if case.subject_id != subject_id:
                    raise _not_found()
                if not await self._student_class_current(
                    uow,
                    subject_id=case.subject_id,
                    class_id=case.class_id,
                    now=now,
                ):
                    raise _not_found()
            elif role is BackendRole.TEACHER:
                if case.class_id not in await self._teacher_class_ids(uow, role_id, now):
                    raise _not_found()
                if case.created_by_membership_role_id != role_id:
                    actions = await self._case_actions(uow, actor, case.case_ref)
                    if not any(
                        action.assigned_teacher_membership_role_id == role_id
                        for action in actions
                    ):
                        raise _not_found()
            else:
                if case.owner_membership_role_id is None:
                    if case.status != "SUBMITTED":
                        raise _not_found()
                    return self._summary(case)
                if case.owner_membership_role_id != role_id:
                    raise _not_found()
            return await self._case_detail(
                uow, actor, case, role_id=role_id, role=role, now=now
            )

    async def support_plan_evidence(self, actor: Any, case_ref: str) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now, lock=True
            )
            case = await self._case(uow, actor, case_ref, lock=True)
            if case.owner_membership_role_id != role_id or case.status != "TRIAGED":
                raise _not_found()
            source = None
            if case.source_type == "STUDENT":
                content = await self._case_content(uow, actor, case.case_ref)
                source = content.feedback_source
                if source is None and _LEGACY_FEEDBACK_QUESTION.match(content.source_text):
                    # Old records kept the link in editable text. With no
                    # verified source, avoid showing an unrelated publication.
                    return {"feedback": None}
            feedback = await self._reviews.assigned_published_feedback_for_support(
                uow, actor, case, account_id, role_id, now, source=source
            )
            return {"feedback": feedback}

    async def support_transition_case(
        self,
        actor: Any,
        case_ref: str,
        *,
        expected_version: int,
        target_status: str,
        plan: str | None,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        expected_version = _positive_version(expected_version)
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            case = await self._case(uow, actor, case_ref)
            if case.status == "SUBMITTED":
                if case.owner_membership_role_id is not None:
                    raise _not_found()
            elif case.owner_membership_role_id != role_id:
                raise _not_found()
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = self._receipt_ref(claim, _CASE_RESOURCE)
                current = await self._case(uow, actor, ref)
                return await self._case_detail(
                    uow,
                    actor,
                    current,
                    role_id=role_id,
                    role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
                    now=now,
                )
            validate_case_transition(case.status, target_status)
            try:
                current = await uow.support_cases.transition_case(
                    school_id=actor.school_id,
                    case_ref=case_ref,
                    actor_membership_role_id=role_id,
                    expected_version=expected_version,
                    to_status=target_status,
                    owner_membership_role_id=role_id,
                    professional_plan=plan,
                    trace_id=trace_id,
                    now=now,
                )
            except Exception as exc:
                _repo_error(exc)
                raise
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=current.case_ref
            )
            await self._audit(
                uow,
                account_id=account_id,
                action="school_support.case_transitioned",
                resource_type=_CASE_RESOURCE,
                resource_ref=current.case_ref,
                trace_id=trace_id,
                state=current.status,
            )
            return await self._case_detail(
                uow,
                actor,
                current,
                role_id=role_id,
                role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
                now=now,
            )

    async def support_create_action(
        self,
        actor: Any,
        case_ref: str,
        *,
        expected_version: int,
        target: str = "TEACHER",
        teacher_user_id: str | None = None,
        instructions: str,
        due_at: datetime,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        expected_version = _positive_version(expected_version)
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            case = await self._case(uow, actor, case_ref)
            if case.owner_membership_role_id != role_id:
                raise _not_found()
            if target not in {"STUDENT", "TEACHER"}:
                raise error(ErrorCode.VALIDATION_FAILED, detail="invalid support action target")
            if target == "TEACHER" and teacher_user_id is None:
                raise error(
                    ErrorCode.VALIDATION_FAILED,
                    detail="teacher targets require a teacher_user_id",
                )
            if target == "STUDENT" and (
                not self._student_action_schema_ready()
                or not hasattr(uow.support_cases, "create_student_action")
            ):
                raise error(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    detail="student support actions require database revision 0027",
                    retryable=False,
                )
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = self._receipt_ref(claim, _CASE_RESOURCE)
                current = await self._case(uow, actor, ref)
                return await self._case_detail(
                    uow,
                    actor,
                    current,
                    role_id=role_id,
                    role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
                    now=now,
                )
            if case.status != "PLANNED":
                raise _not_found()
            try:
                if target == "STUDENT":
                    current, action = await uow.support_cases.create_student_action(
                        school_id=actor.school_id,
                        case_ref=case_ref,
                        actor_membership_role_id=role_id,
                        expected_case_version=expected_version,
                        recipient_subject_id=case.subject_id,
                        instruction=instructions,
                        due_at=due_at,
                        trace_id=trace_id,
                        now=now,
                    )
                else:
                    if teacher_user_id is None:
                        raise error(
                            ErrorCode.VALIDATION_FAILED,
                            detail="teacher targets require a teacher_user_id",
                        )
                    teacher_role_id, class_teacher_id = (
                        await self._teacher_assignment_for_user(
                            uow,
                            school_id=actor.school_id,
                            class_id=case.class_id,
                            teacher_user_id=teacher_user_id,
                            now=now,
                        )
                    )
                    current, action = await uow.support_cases.create_action(
                        school_id=actor.school_id,
                        case_ref=case_ref,
                        actor_membership_role_id=role_id,
                        expected_case_version=expected_version,
                        assigned_teacher_membership_role_id=teacher_role_id,
                        assigned_class_teacher_id=class_teacher_id,
                        instruction=instructions,
                        due_at=due_at,
                        trace_id=trace_id,
                        now=now,
                    )
            except Exception as exc:
                _repo_error(exc)
                raise
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=current.case_ref
            )
            await self._audit(
                uow,
                account_id=account_id,
                action="school_support.action_created",
                resource_type=_ACTION_RESOURCE,
                resource_ref=action.action_ref,
                trace_id=trace_id,
                state="PENDING",
            )
            return await self._case_detail(
                uow,
                actor,
                current,
                role_id=role_id,
                role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
                now=now,
            )

    async def support_action_feedback(
        self,
        actor: Any,
        action_ref: str,
        *,
        expected_version: int,
        outcome: str,
        feedback: str | None,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        expected_version = _positive_version(expected_version)
        now = self._utc_now()
        async with self._uow() as uow:
            role = actor.role
            if role is BackendRole.STUDENT:
                account_id, _role_id = await self._require_actor(
                    uow, actor, "student", now
                )
                if (
                    not self._student_action_schema_ready()
                    or not hasattr(uow.support_cases, "submit_student_action_feedback")
                ):
                    raise error(
                        ErrorCode.DEPENDENCY_UNAVAILABLE,
                        detail="student support actions require database revision 0027",
                        retryable=False,
                    )
                subject_id, _subject_school_id, _subject_ref = await self._student_subject(
                    uow, actor, now
                )
                action = await self._action(uow, actor, action_ref)
                if (
                    action.subject_id != subject_id
                    or getattr(action, "recipient_subject_id", None) != subject_id
                ):
                    raise _not_found()
                case = await self._case_for_id(uow, actor.school_id, action.case_id)
                if case.subject_id != subject_id or not await self._student_class_current(
                    uow,
                    subject_id=subject_id,
                    class_id=case.class_id,
                    now=now,
                ):
                    raise _not_found()
                claim = await self._school_idempotency_begin(uow, idempotency)
                if claim.replayed:
                    ref = self._receipt_ref(claim, _ACTION_RESOURCE)
                    current = await self._action(uow, actor, ref)
                    return await self._action_projection(
                        uow,
                        actor,
                        current,
                        case_ref=case.case_ref,
                        include_teacher=False,
                    )
                validate_action_outcome(role, action.status, outcome)
                if feedback is None:
                    raise error(
                        ErrorCode.VALIDATION_FAILED,
                        detail="student feedback is required",
                    )
                try:
                    current = await uow.support_cases.submit_student_action_feedback(
                        school_id=actor.school_id,
                        action_ref=action_ref,
                        recipient_subject_id=subject_id,
                        expected_version=expected_version,
                        feedback=feedback,
                        trace_id=trace_id,
                        now=now,
                    )
                except BackendError:
                    raise
                except Exception as exc:
                    _repo_error(exc)
                    raise
                await self._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type=_ACTION_RESOURCE,
                    result_ref=current.action_ref,
                )
                await self._audit(
                    uow,
                    account_id=account_id,
                    action="school_support.action_feedback",
                    resource_type=_ACTION_RESOURCE,
                    resource_ref=current.action_ref,
                    trace_id=trace_id,
                    state=current.status,
                )
                return await self._action_projection(
                    uow,
                    actor,
                    current,
                    case_ref=case.case_ref,
                    include_teacher=False,
                )
            role_code = "teacher" if role is BackendRole.TEACHER else "psychological_specialist"
            account_id, role_id = await self._require_actor(uow, actor, role_code, now)
            action = await self._action(uow, actor, action_ref)
            if role is BackendRole.TEACHER:
                if action.assigned_teacher_membership_role_id != role_id:
                    raise _not_found()
                if action.class_id not in await self._teacher_class_ids(uow, role_id, now):
                    raise _not_found()
            case = await self._case_for_id(uow, actor.school_id, action.case_id)
            if role is BackendRole.PSYCHOLOGICAL_SPECIALIST:
                if case.owner_membership_role_id != role_id:
                    raise _not_found()
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = self._receipt_ref(claim, _ACTION_RESOURCE)
                current = await self._action(uow, actor, ref)
                return await self._action_projection(
                    uow,
                    actor,
                    current,
                    case_ref=case.case_ref,
                    include_teacher=role is BackendRole.PSYCHOLOGICAL_SPECIALIST,
                )
            validate_action_outcome(role, action.status, outcome)
            try:
                if role is BackendRole.TEACHER:
                    if feedback is None:
                        raise error(
                            ErrorCode.VALIDATION_FAILED,
                            detail="teacher feedback is required",
                        )
                    current = await uow.support_cases.submit_action_feedback(
                        school_id=actor.school_id,
                        action_ref=action_ref,
                        teacher_membership_role_id=role_id,
                        expected_version=expected_version,
                        feedback=feedback,
                        trace_id=trace_id,
                        now=now,
                    )
                else:
                    if outcome == "ACCEPTED":
                        current = await uow.support_cases.accept_action(
                            school_id=actor.school_id,
                            action_ref=action_ref,
                            owner_membership_role_id=role_id,
                            expected_version=expected_version,
                            trace_id=trace_id,
                            now=now,
                        )
                    elif outcome == "RETURNED":
                        current = await uow.support_cases.return_action(
                            school_id=actor.school_id,
                            action_ref=action_ref,
                            owner_membership_role_id=role_id,
                            expected_version=expected_version,
                            trace_id=trace_id,
                            now=now,
                        )
                    else:
                        current = await uow.support_cases.cancel_action(
                            school_id=actor.school_id,
                            action_ref=action_ref,
                            owner_membership_role_id=role_id,
                            expected_version=expected_version,
                            trace_id=trace_id,
                            now=now,
                        )
            except BackendError:
                raise
            except Exception as exc:
                _repo_error(exc)
                raise
            await self._school_idempotency_complete(
                uow, claim, resource_type=_ACTION_RESOURCE, result_ref=current.action_ref
            )
            await self._audit(
                uow,
                account_id=account_id,
                action="school_support.action_feedback",
                resource_type=_ACTION_RESOURCE,
                resource_ref=current.action_ref,
                trace_id=trace_id,
                state=current.status,
            )
            return await self._action_projection(
                uow,
                actor,
                current,
                case_ref=case.case_ref,
                include_teacher=role is BackendRole.PSYCHOLOGICAL_SPECIALIST,
            )

    async def _case_for_id(self, uow: Any, school_id: int, case_id: int):
        case = await uow.support_cases.get_case(
            school_id=school_id, case_ref=await self._case_ref_for_id(uow, school_id, case_id)
        )
        if case is None:
            raise _not_found()
        return case

    async def _case_ref_for_id(self, uow: Any, school_id: int, case_id: int) -> str:
        m = self._db_models
        value = await uow.session.scalar(
            self._select(m.SchoolSupportCase.case_ref).where(
                m.SchoolSupportCase.id == case_id,
                m.SchoolSupportCase.school_id == school_id,
            )
        )
        if not isinstance(value, str):
            raise _not_found()
        return value

    @staticmethod
    def _receipt_ref(claim: Any, resource_type: str) -> str:
        record = claim.record
        if (
            record is None
            or record.result_resource_type != resource_type
            or not isinstance(record.result_public_id, str)
        ):
            raise _conflict()
        return record.result_public_id
