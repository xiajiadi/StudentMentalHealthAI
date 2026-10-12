"""Transactional persistence for school task professional-review records.

Every operation opens one shared SQLAlchemy UOW and repeats the active school,
role, task and assignment checks there. This adapter returns only the review
workflow projection; it never loads assessment responses or report content.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from smhai_backend.adapters.school_directory import SchoolDirectoryPersistenceAdapter
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import get_request_context

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")
_NOTE_SCHEMA = "school_professional_review_note.v1"
_ASSIGNMENT_RESOURCE = "school_task_specialist_assignment"
_CASE_RESOURCE = "school_professional_review_case"


def _public_id(value: Any, prefix: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(f"{prefix}_")
        or len(value) > 128
        or not _SAFE_REF.fullmatch(value[len(prefix) + 1 :])
    ):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review resource was not found")
    return value[len(prefix) + 1 :]


def _role_value(actor: Any) -> str:
    return str(getattr(getattr(actor, "role", None), "value", getattr(actor, "role", ""))).lower()


def _positive_version(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid review version")
    return value


class SchoolProfessionalReviewPersistenceAdapter:
    """Composition wrapper over the shared tenant/UOW/idempotency implementation."""

    def __init__(self, persistence: Any) -> None:
        self._directory = SchoolDirectoryPersistenceAdapter(persistence)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._directory, name)

    async def _require_actor(self, uow: Any, actor: Any, role_code: str, at: datetime):
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or _role_value(actor) != role_code
            or actor.school_id is None
            or actor.school_ref is None
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return await self._school_actor_role(uow, actor, role_code, at)

    async def _task(self, uow: Any, actor: Any, task_ref: str, *, lock: bool):
        m = self._db_models
        statement = (
            self._select(m.MeasurementTask)
            .join(m.School, m.School.id == m.MeasurementTask.school_id)
            .where(
                m.MeasurementTask.task_ref == task_ref,
                m.MeasurementTask.school_id == actor.school_id,
                m.School.school_ref == actor.school_ref,
                m.School.status == "ACTIVE",
                m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
            )
        )
        if lock:
            statement = statement.with_for_update()
        task = await uow.session.scalar(statement)
        if task is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="task was not found")
        return task

    async def _active_assignment(
        self, uow: Any, actor: Any, task: Any, *, at: datetime, lock: bool
    ) -> Any:
        m = self._db_models
        statement = (
            self._select(m.SchoolTaskSpecialistAssignment)
            .join(
                m.MembershipRole,
                m.MembershipRole.id
                == m.SchoolTaskSpecialistAssignment.specialist_membership_role_id,
            )
            .join(
                m.AccountSchoolMembership,
                m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
            )
            .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
            .where(
                m.SchoolTaskSpecialistAssignment.task_id == task.id,
                m.SchoolTaskSpecialistAssignment.school_id == actor.school_id,
                m.SchoolTaskSpecialistAssignment.class_id == task.class_id,
                m.SchoolTaskSpecialistAssignment.status == "ACTIVE",
                m.SchoolTaskSpecialistAssignment.revoked_at.is_(None),
                m.MembershipRole.school_id == actor.school_id,
                m.MembershipRole.role_code == "psychological_specialist",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= at,
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= at),
                m.AccountSchoolMembership.school_id == actor.school_id,
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= at,
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= at),
                m.Account.public_id == _public_id(actor.user_id, "USER"),
                m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
            )
            .limit(2)
        )
        if lock:
            statement = statement.with_for_update()
        rows = list((await uow.session.scalars(statement)).all())
        if len(rows) != 1:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return rows[0]

    async def _case(
        self,
        uow: Any,
        actor: Any,
        task: Any,
        case_ref: str,
        *,
        lock: bool,
    ) -> Any:
        m = self._db_models
        try:
            public_id = _public_id(case_ref, "PCR")
        except BackendError as exc:
            if exc.code is ErrorCode.RESOURCE_NOT_FOUND:
                raise
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review case was not found") from None
        statement = (
            self._select(m.SchoolProfessionalReviewCase)
            .join(
                m.TaskEnrollment,
                (m.TaskEnrollment.id == m.SchoolProfessionalReviewCase.task_enrollment_id)
                & (m.TaskEnrollment.task_id == m.SchoolProfessionalReviewCase.task_id)
                & (m.TaskEnrollment.school_id == m.SchoolProfessionalReviewCase.school_id)
                & (m.TaskEnrollment.subject_id == m.SchoolProfessionalReviewCase.subject_id),
            )
            .join(
                m.AssessmentSession,
                (m.AssessmentSession.id == m.SchoolProfessionalReviewCase.assessment_session_id)
                & (
                    m.AssessmentSession.task_enrollment_id
                    == m.SchoolProfessionalReviewCase.task_enrollment_id
                )
                & (m.AssessmentSession.subject_id == m.SchoolProfessionalReviewCase.subject_id),
            )
            .join(
                m.Subject,
                (m.Subject.id == m.SchoolProfessionalReviewCase.subject_id)
                & (m.Subject.school_id == m.SchoolProfessionalReviewCase.school_id),
            )
            .where(
                m.SchoolProfessionalReviewCase.review_ref == public_id,
                m.SchoolProfessionalReviewCase.task_id == task.id,
                m.SchoolProfessionalReviewCase.school_id == actor.school_id,
                m.SchoolProfessionalReviewCase.class_id == task.class_id,
                m.TaskEnrollment.status == "ACTIVE",
                m.TaskEnrollment.revoked_at.is_(None),
                m.AssessmentSession.status == self._db_enums.AssessmentStatus.COMPLETED.value,
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
            )
            .limit(2)
        )
        if lock:
            statement = statement.with_for_update()
        rows = list((await uow.session.scalars(statement)).all())
        if len(rows) != 1:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review case was not found")
        return rows[0]

    async def _enrollment_for_case(
        self, uow: Any, actor: Any, task: Any, enrollment_ref: str
    ) -> tuple[Any, Any]:
        try:
            public_id = _public_id(enrollment_ref, "ENROLL")
        except BackendError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="enrollment was not found") from None
        m = self._db_models
        rows = list(
            (
                await uow.session.execute(
                    self._select(m.TaskEnrollment, m.AssessmentSession)
                    .join(
                        m.AssessmentSession,
                        (m.AssessmentSession.task_enrollment_id == m.TaskEnrollment.id)
                        & (m.AssessmentSession.subject_id == m.TaskEnrollment.subject_id),
                    )
                    .join(
                        m.Subject,
                        (m.Subject.id == m.TaskEnrollment.subject_id)
                        & (m.Subject.school_id == m.TaskEnrollment.school_id),
                    )
                    .where(
                        m.TaskEnrollment.public_id == public_id,
                        m.TaskEnrollment.task_id == task.id,
                        m.TaskEnrollment.school_id == actor.school_id,
                        m.TaskEnrollment.class_id == task.class_id,
                        m.TaskEnrollment.status == "ACTIVE",
                        m.TaskEnrollment.revoked_at.is_(None),
                        m.AssessmentSession.status
                        == self._db_enums.AssessmentStatus.COMPLETED.value,
                        m.Subject.school_id == actor.school_id,
                        m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                        m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    )
                    .with_for_update()
                )
            ).all()
        )
        if len(rows) != 1:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="enrollment was not found")
        return rows[0][0], rows[0][1]

    def _assignment_projection(self, row: Any, task_ref: str, specialist_user_id: str):
        return {
            "assignment_ref": f"ASSIGN_{row.public_id}",
            "task_ref": task_ref,
            "specialist_user_id": specialist_user_id,
            "status": row.status,
            "assigned_at": row.created_at,
            "revoked_at": row.revoked_at,
        }

    def _decrypt_note(self, row: Any) -> str | None:
        if row.case_note_ciphertext is None:
            if any(
                value is not None
                for value in (
                    row.cipher_format_version,
                    row.key_version,
                    row.payload_schema_version,
                )
            ):
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="review note is unavailable",
                )
            return None
        if (
            not isinstance(row.case_note_ciphertext, bytes)
            or not row.key_version
            or row.cipher_format_version != self.protection.cipher_format_version
            or row.payload_schema_version != _NOTE_SCHEMA
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="review note is unavailable",
            )
        try:
            from database_layer.crypto import EncryptedPayload

            payload = self.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=row.case_note_ciphertext,
                    key_version=row.key_version,
                    cipher_format_version=row.cipher_format_version,
                    payload_schema_version=row.payload_schema_version,
                )
            )
        except Exception as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="review note is unavailable",
            ) from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"note", "review_ref"}
            or payload.get("review_ref") != row.review_ref
            or not isinstance(payload["note"], str)
            or not payload["note"].strip()
            or len(payload["note"]) > 2000
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="review note is unavailable",
            )
        return payload["note"]

    def _case_projection(
        self,
        row: Any,
        task_ref: str,
        enrollment_ref: str,
        assessment_ref: str,
        review_note: str | None,
    ):
        return {
            "case_ref": f"PCR_{row.review_ref}",
            "task_ref": task_ref,
            "enrollment_ref": enrollment_ref,
            "assessment_ref": assessment_ref,
            "status": row.status,
            "publication_status": "NOT_PUBLISHED",
            "version": row.version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "decision": row.status if row.status in {"APPROVED", "REJECTED"} else None,
            "review_note": review_note,
        }

    async def _case_projection_from_row(
        self, uow: Any, actor: Any, task: Any, row: Any, *, include_note: bool = True
    ) -> dict[str, Any]:
        m = self._db_models
        values = (
            await uow.session.execute(
                self._select(m.TaskEnrollment.public_id, m.AssessmentSession.assessment_ref)
                .join(
                    m.AssessmentSession,
                    (m.AssessmentSession.task_enrollment_id == m.TaskEnrollment.id)
                    & (m.AssessmentSession.subject_id == m.TaskEnrollment.subject_id),
                )
                .join(
                    m.Subject,
                    (m.Subject.id == m.TaskEnrollment.subject_id)
                    & (m.Subject.school_id == m.TaskEnrollment.school_id),
                )
                .where(
                    m.TaskEnrollment.id == row.task_enrollment_id,
                    m.TaskEnrollment.task_id == task.id,
                    m.TaskEnrollment.school_id == actor.school_id,
                    m.TaskEnrollment.class_id == task.class_id,
                    m.TaskEnrollment.status == "ACTIVE",
                    m.TaskEnrollment.revoked_at.is_(None),
                    m.AssessmentSession.id == row.assessment_session_id,
                    m.AssessmentSession.status == self._db_enums.AssessmentStatus.COMPLETED.value,
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .limit(2)
            )
        ).all()
        if len(values) != 1:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review case was not found")
        return self._case_projection(
            row,
            task.task_ref,
            f"ENROLL_{values[0][0]}",
            values[0][1],
            self._decrypt_note(row) if include_note else None,
        )

    async def _audit(
        self,
        uow: Any,
        *,
        actor_account_id: int,
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
            actor_account_id=actor_account_id,
            safe_metadata={"source": "school_professional_reviews", "state": state},
        )

    async def _event(
        self,
        uow: Any,
        *,
        row: Any,
        actor_role_id: int,
        event_type: str,
        from_status: str | None,
        to_status: str,
        version: int,
        trace_id: str,
        at: datetime,
    ) -> None:
        event = self._db_models.SchoolProfessionalReviewEvent(
            review_case_id=row.id,
            school_id=row.school_id,
            actor_membership_role_id=actor_role_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            version=version,
            trace_id=trace_id,
            retention_due_at=row.retention_due_at,
            created_at=at,
        )
        uow.session.add(event)
        await uow.session.flush()

    async def _receipt_resource(self, claim: Any, expected_type: str) -> str:
        receipt = claim.record
        if (
            receipt is None
            or receipt.result_resource_type != expected_type
            or not isinstance(receipt.result_public_id, str)
            or not receipt.result_public_id
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable")
        return receipt.result_public_id

    async def school_professional_review_list_assignments(
        self, actor: Any, *, task_ref: str | None = None
    ) -> list[dict[str, Any]]:
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            await self._require_actor(uow, actor, "admin", now)
            if task_ref is not None:
                await self._task(uow, actor, task_ref, lock=False)
            statement = (
                self._select(
                    m.SchoolTaskSpecialistAssignment,
                    m.MeasurementTask.task_ref,
                    m.Account.public_id,
                )
                .join(
                    m.MeasurementTask,
                    m.MeasurementTask.id == m.SchoolTaskSpecialistAssignment.task_id,
                )
                .join(
                    m.MembershipRole,
                    m.MembershipRole.id
                    == m.SchoolTaskSpecialistAssignment.specialist_membership_role_id,
                )
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
                )
                .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                .where(
                    m.SchoolTaskSpecialistAssignment.school_id == actor.school_id,
                    m.MeasurementTask.school_id == actor.school_id,
                )
                .order_by(m.MeasurementTask.task_ref, m.SchoolTaskSpecialistAssignment.created_at)
            )
            if task_ref is not None:
                statement = statement.where(m.MeasurementTask.task_ref == task_ref)
            rows = (await uow.session.execute(statement)).all()
            return [
                self._assignment_projection(row[0], row[1], f"USER_{row[2]}") for row in rows
            ]

    async def school_professional_review_assign(
        self,
        actor: Any,
        task_ref: str,
        specialist_user_id: str,
        *,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        now = self._utc_now()
        m = self._db_models
        try:
            specialist_public_id = _public_id(specialist_user_id, "USER")
        except BackendError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="specialist was not found") from None
        async with self._uow() as uow:
            actor_account_id, admin_role_id = await self._require_actor(uow, actor, "admin", now)
            task = await self._task(uow, actor, task_ref, lock=True)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                receipt_ref = await self._receipt_resource(claim, _ASSIGNMENT_RESOURCE)
                row = await uow.session.scalar(
                    self._select(m.SchoolTaskSpecialistAssignment)
                    .join(
                        m.MeasurementTask,
                        m.MeasurementTask.id == m.SchoolTaskSpecialistAssignment.task_id,
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.id
                        == m.SchoolTaskSpecialistAssignment.specialist_membership_role_id,
                    )
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
                    )
                    .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                    .where(
                        m.SchoolTaskSpecialistAssignment.public_id == receipt_ref,
                        m.SchoolTaskSpecialistAssignment.school_id == actor.school_id,
                        m.MeasurementTask.task_ref == task_ref,
                        m.MeasurementTask.school_id == actor.school_id,
                        m.Account.public_id == specialist_public_id,
                    )
                )
                if row is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable"
                    )
                return self._assignment_projection(row, task_ref, specialist_user_id)

            target_rows = list(
                (
                    await uow.session.execute(
                        self._select(m.MembershipRole.id)
                        .join(
                            m.AccountSchoolMembership,
                            m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
                        )
                        .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                        .where(
                            m.Account.public_id == specialist_public_id,
                            m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                            m.AccountSchoolMembership.school_id == actor.school_id,
                            m.AccountSchoolMembership.status == "ACTIVE",
                            m.AccountSchoolMembership.revoked_at.is_(None),
                            m.AccountSchoolMembership.valid_from <= now,
                            (m.AccountSchoolMembership.valid_until.is_(None))
                            | (m.AccountSchoolMembership.valid_until >= now),
                            m.MembershipRole.school_id == actor.school_id,
                            m.MembershipRole.role_code == "psychological_specialist",
                            m.MembershipRole.status == "ACTIVE",
                            m.MembershipRole.revoked_at.is_(None),
                            m.MembershipRole.valid_from <= now,
                            (m.MembershipRole.valid_until.is_(None))
                            | (m.MembershipRole.valid_until >= now),
                        )
                        .with_for_update()
                    )
                ).all()
            )
            if len(target_rows) != 1:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="specialist was not found")
            role_id = int(target_rows[0][0])
            row = await uow.session.scalar(
                self._select(m.SchoolTaskSpecialistAssignment)
                .where(
                    m.SchoolTaskSpecialistAssignment.task_id == task.id,
                    m.SchoolTaskSpecialistAssignment.school_id == actor.school_id,
                    m.SchoolTaskSpecialistAssignment.specialist_membership_role_id == role_id,
                )
                .with_for_update()
            )
            changed = row is None or row.status != "ACTIVE"
            if row is None:
                row = m.SchoolTaskSpecialistAssignment(
                    school_id=actor.school_id,
                    task_id=task.id,
                    class_id=task.class_id,
                    specialist_membership_role_id=role_id,
                    assigned_by_membership_role_id=admin_role_id,
                    status="ACTIVE",
                )
                uow.session.add(row)
            else:
                row.status = "ACTIVE"
                row.revoked_at = None
                row.assigned_by_membership_role_id = admin_role_id
            await uow.session.flush()
            await self._school_idempotency_complete(
                uow,
                claim,
                resource_type=_ASSIGNMENT_RESOURCE,
                result_ref=row.public_id,
            )
            if changed:
                await self._audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_professional_review.assignment_assigned",
                    resource_type=_ASSIGNMENT_RESOURCE,
                    resource_ref=row.public_id,
                    trace_id=trace_id,
                    state="ACTIVE",
                )
            return self._assignment_projection(row, task_ref, specialist_user_id)

    async def school_professional_review_revoke(
        self,
        actor: Any,
        task_ref: str,
        assignment_ref: str,
        *,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        now = self._utc_now()
        m = self._db_models
        public_id = _public_id(assignment_ref, "ASSIGN")
        async with self._uow() as uow:
            actor_account_id, _admin_role_id = await self._require_actor(uow, actor, "admin", now)
            await self._task(uow, actor, task_ref, lock=True)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _ASSIGNMENT_RESOURCE)
            else:
                ref = public_id
            if claim.replayed and ref != public_id:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable")
            row = await uow.session.scalar(
                self._select(m.SchoolTaskSpecialistAssignment)
                .join(
                    m.MeasurementTask,
                    m.MeasurementTask.id == m.SchoolTaskSpecialistAssignment.task_id,
                )
                .join(
                    m.MembershipRole,
                    m.MembershipRole.id
                    == m.SchoolTaskSpecialistAssignment.specialist_membership_role_id,
                )
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
                )
                .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                .where(
                    m.SchoolTaskSpecialistAssignment.public_id == ref,
                    m.SchoolTaskSpecialistAssignment.school_id == actor.school_id,
                    m.MeasurementTask.task_ref == task_ref,
                    m.MeasurementTask.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if row is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assignment was not found")
            if claim.replayed:
                specialist_ref = await uow.session.scalar(
                    self._select(m.Account.public_id)
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .where(m.MembershipRole.id == row.specialist_membership_role_id)
                )
                if not isinstance(specialist_ref, str):
                    raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assignment was not found")
                return self._assignment_projection(row, task_ref, f"USER_{specialist_ref}")
            if row.status == "ACTIVE":
                row.status = "REVOKED"
                row.revoked_at = now
                await uow.session.flush()
                await self._audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_professional_review.assignment_revoked",
                    resource_type=_ASSIGNMENT_RESOURCE,
                    resource_ref=row.public_id,
                    trace_id=trace_id,
                    state="REVOKED",
                )
            await self._school_idempotency_complete(
                uow,
                claim,
                resource_type=_ASSIGNMENT_RESOURCE,
                result_ref=row.public_id,
            )
            specialist_ref = await uow.session.scalar(
                self._select(m.Account.public_id)
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.account_id == m.Account.id,
                )
                .join(
                    m.MembershipRole,
                    m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                )
                .where(m.MembershipRole.id == row.specialist_membership_role_id)
            )
            if not isinstance(specialist_ref, str):
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assignment was not found")
            return self._assignment_projection(row, task_ref, f"USER_{specialist_ref}")

    async def school_professional_review_ensure_case(
        self,
        actor: Any,
        task_ref: str,
        enrollment_ref: str,
        *,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            actor_account_id, specialist_role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            task = await self._task(uow, actor, task_ref, lock=True)
            await self._active_assignment(uow, actor, task, at=now, lock=True)
            enrollment, assessment = await self._enrollment_for_case(
                uow, actor, task, enrollment_ref
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _CASE_RESOURCE)
                row = await self._case(uow, actor, task, f"PCR_{ref}", lock=True)
                if row.task_enrollment_id != enrollment.id:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency result is unavailable",
                    )
                return await self._case_projection_from_row(uow, actor, task, row)
            row = await uow.session.scalar(
                self._select(m.SchoolProfessionalReviewCase)
                .where(
                    m.SchoolProfessionalReviewCase.task_enrollment_id == enrollment.id,
                    m.SchoolProfessionalReviewCase.task_id == task.id,
                    m.SchoolProfessionalReviewCase.school_id == actor.school_id,
                )
                .with_for_update()
            )
            created = row is None
            if row is not None and row.assessment_session_id != assessment.id:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="review case scope changed")
            if row is None:
                row = m.SchoolProfessionalReviewCase(
                    review_ref=uuid4().hex,
                    school_id=actor.school_id,
                    task_id=task.id,
                    class_id=task.class_id,
                    task_enrollment_id=enrollment.id,
                    subject_id=enrollment.subject_id,
                    assessment_session_id=assessment.id,
                    status="OPEN",
                    version=1,
                )
                # Retention is copied from the persisted synthetic subject, not a
                # client value. The query deliberately selects no psych payload.
                subject = await uow.session.scalar(
                    self._select(m.Subject).where(
                        m.Subject.id == enrollment.subject_id,
                        m.Subject.school_id == actor.school_id,
                        m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                        m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    )
                )
                if subject is None:
                    raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="enrollment was not found")
                row.retention_due_at = subject.retention_due_at
                uow.session.add(row)
                await uow.session.flush()
                await self._event(
                    uow,
                    row=row,
                    actor_role_id=specialist_role_id,
                    event_type="CREATED",
                    from_status=None,
                    to_status="OPEN",
                    version=1,
                    trace_id=trace_id,
                    at=now,
                )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=row.review_ref
            )
            if created:
                await self._audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_professional_review.case_created",
                    resource_type=_CASE_RESOURCE,
                    resource_ref=row.review_ref,
                    trace_id=trace_id,
                    state="OPEN",
                )
            return await self._case_projection_from_row(uow, actor, task, row)

    async def school_professional_review_list_cases(
        self, actor: Any, task_ref: str, *, offset: int, limit: int
    ) -> dict[str, Any]:
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or offset > 100_000
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid pagination")
        from sqlalchemy import func

        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            await self._require_actor(uow, actor, "psychological_specialist", now)
            task = await self._task(uow, actor, task_ref, lock=False)
            await self._active_assignment(uow, actor, task, at=now, lock=False)
            base = (
                self._select(m.SchoolProfessionalReviewCase)
                .join(
                    m.TaskEnrollment,
                    (m.TaskEnrollment.id == m.SchoolProfessionalReviewCase.task_enrollment_id)
                    & (m.TaskEnrollment.task_id == m.SchoolProfessionalReviewCase.task_id)
                    & (m.TaskEnrollment.school_id == m.SchoolProfessionalReviewCase.school_id)
                    & (m.TaskEnrollment.subject_id == m.SchoolProfessionalReviewCase.subject_id),
                )
                .join(
                    m.AssessmentSession,
                    (m.AssessmentSession.id == m.SchoolProfessionalReviewCase.assessment_session_id)
                    & (m.AssessmentSession.task_enrollment_id == m.TaskEnrollment.id)
                    & (m.AssessmentSession.subject_id == m.TaskEnrollment.subject_id),
                )
                .join(
                    m.Subject,
                    (m.Subject.id == m.TaskEnrollment.subject_id)
                    & (m.Subject.school_id == m.TaskEnrollment.school_id),
                )
                .where(
                    m.SchoolProfessionalReviewCase.school_id == actor.school_id,
                    m.SchoolProfessionalReviewCase.task_id == task.id,
                    m.TaskEnrollment.status == "ACTIVE",
                    m.TaskEnrollment.revoked_at.is_(None),
                    m.AssessmentSession.status == self._db_enums.AssessmentStatus.COMPLETED.value,
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
            )
            total = int(
                await uow.session.scalar(
                    self._select(func.count()).select_from(base.order_by(None).subquery())
                )
                or 0
            )
            rows = list(
                (
                    await uow.session.scalars(
                        base.order_by(
                            m.SchoolProfessionalReviewCase.created_at,
                            m.SchoolProfessionalReviewCase.id,
                        )
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return {
                "items": [
                    await self._case_projection_from_row(
                        uow, actor, task, row, include_note=False
                    )
                    for row in rows
                ],
                "total": total,
            }

    async def school_professional_review_get_case(
        self, actor: Any, task_ref: str, case_ref: str
    ) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            actor_account_id, _ = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            task = await self._task(uow, actor, task_ref, lock=False)
            await self._active_assignment(uow, actor, task, at=now, lock=False)
            row = await self._case(uow, actor, task, case_ref, lock=False)
            projection = await self._case_projection_from_row(uow, actor, task, row)
            await uow.audit.append(
                action="school_professional_review.case_detail_read",
                resource_type=_CASE_RESOURCE,
                resource_public_id=row.review_ref,
                result=self._db_enums.AuditResult.SUCCESS,
                trace_id=get_request_context().trace_id,
                actor_account_id=actor_account_id,
            )
            return projection

    async def school_professional_review_list_specialists(
        self, actor: Any
    ) -> list[dict[str, str | None]]:
        """List active synthetic same-school specialists for admin assignment pickers."""
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            await self._require_actor(uow, actor, "admin", now)
            rows = (
                await uow.session.execute(
                    self._select(
                        m.Account.public_id,
                        m.AccountSchoolMembership.display_name,
                    )
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .join(m.School, m.School.id == m.MembershipRole.school_id)
                    .where(
                        m.School.id == actor.school_id,
                        m.School.school_ref == actor.school_ref,
                        m.School.status == "ACTIVE",
                        m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                        m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.MembershipRole.school_id == actor.school_id,
                        m.MembershipRole.role_code == "psychological_specialist",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                    )
                    .distinct()
                    .order_by(m.Account.public_id)
                )
            ).all()
            return [
                {"user_id": f"USER_{public_id}", "display_name": display_name}
                for public_id, display_name in rows
                if isinstance(public_id, str) and public_id
            ]

    async def school_professional_review_list_tasks(self, actor: Any) -> list[dict[str, Any]]:
        """List task and class labels for tasks actively assigned to this specialist."""
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            _, specialist_role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            rows = (
                await uow.session.execute(
                    self._select(
                        m.MeasurementTask.task_ref,
                        m.SchoolClass.class_ref,
                        m.SchoolClass.display_name,
                        m.MeasurementTask.published_at,
                    )
                    .join(
                        m.SchoolClass,
                        (m.SchoolClass.id == m.MeasurementTask.class_id)
                        & (m.SchoolClass.school_id == m.MeasurementTask.school_id),
                    )
                    .join(
                        m.School,
                        m.School.id == m.MeasurementTask.school_id,
                    )
                    .join(
                        m.SchoolTaskSpecialistAssignment,
                        (m.SchoolTaskSpecialistAssignment.task_id == m.MeasurementTask.id)
                        & (
                            m.SchoolTaskSpecialistAssignment.school_id
                            == m.MeasurementTask.school_id
                        )
                        & (m.SchoolTaskSpecialistAssignment.class_id == m.MeasurementTask.class_id),
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.id
                        == m.SchoolTaskSpecialistAssignment.specialist_membership_role_id,
                    )
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
                    )
                    .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                    .where(
                        m.MeasurementTask.school_id == actor.school_id,
                        m.School.school_ref == actor.school_ref,
                        m.School.status == "ACTIVE",
                        m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                        m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
                        m.SchoolTaskSpecialistAssignment.status == "ACTIVE",
                        m.SchoolTaskSpecialistAssignment.revoked_at.is_(None),
                        m.SchoolTaskSpecialistAssignment.specialist_membership_role_id
                        == specialist_role_id,
                        m.MembershipRole.school_id == actor.school_id,
                        m.MembershipRole.role_code == "psychological_specialist",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.Account.public_id == _public_id(actor.user_id, "USER"),
                        m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                    )
                    .distinct()
                    .order_by(m.MeasurementTask.published_at, m.MeasurementTask.task_ref)
                )
            ).all()
            return [
                {
                    "task_ref": task_ref,
                    "class_ref": class_ref,
                    "class_display_name": class_display_name,
                    "published_at": published_at,
                }
                for task_ref, class_ref, class_display_name, published_at in rows
            ]

    async def school_professional_review_list_eligible_enrollments(
        self,
        actor: Any,
        task_ref: str,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        """List only active synthetic enrollments with a completed task assessment."""
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid pagination")
        from sqlalchemy import func

        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            await self._require_actor(uow, actor, "psychological_specialist", now)
            task = await self._task(uow, actor, task_ref, lock=False)
            await self._active_assignment(uow, actor, task, at=now, lock=False)
            base = (
                self._select(
                    m.TaskEnrollment.public_id,
                    m.AssessmentSession.assessment_ref,
                    m.AssessmentSession.completed_at,
                    m.SchoolProfessionalReviewCase.review_ref,
                )
                .join(
                    m.AssessmentSession,
                    (m.AssessmentSession.task_enrollment_id == m.TaskEnrollment.id)
                    & (m.AssessmentSession.subject_id == m.TaskEnrollment.subject_id),
                )
                .join(
                    m.Subject,
                    (m.Subject.id == m.TaskEnrollment.subject_id)
                    & (m.Subject.school_id == m.TaskEnrollment.school_id),
                )
                .outerjoin(
                    m.SchoolProfessionalReviewCase,
                    (m.SchoolProfessionalReviewCase.task_enrollment_id == m.TaskEnrollment.id)
                    & (m.SchoolProfessionalReviewCase.task_id == m.TaskEnrollment.task_id)
                    & (m.SchoolProfessionalReviewCase.school_id == m.TaskEnrollment.school_id)
                    & (m.SchoolProfessionalReviewCase.class_id == m.TaskEnrollment.class_id)
                    & (m.SchoolProfessionalReviewCase.subject_id == m.TaskEnrollment.subject_id)
                    & (
                        m.SchoolProfessionalReviewCase.assessment_session_id
                        == m.AssessmentSession.id
                    ),
                )
                .where(
                    m.TaskEnrollment.task_id == task.id,
                    m.TaskEnrollment.school_id == actor.school_id,
                    m.TaskEnrollment.class_id == task.class_id,
                    m.TaskEnrollment.status == "ACTIVE",
                    m.TaskEnrollment.revoked_at.is_(None),
                    m.AssessmentSession.status == self._db_enums.AssessmentStatus.COMPLETED.value,
                    m.AssessmentSession.completed_at.is_not(None),
                    m.Subject.school_id == actor.school_id,
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
            )
            total = int(
                await uow.session.scalar(
                    self._select(func.count()).select_from(base.order_by(None).subquery())
                )
                or 0
            )
            rows = (
                await uow.session.execute(
                    base.order_by(
                        m.AssessmentSession.completed_at,
                        m.TaskEnrollment.public_id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return {
                "items": [
                    {
                        "enrollment_ref": f"ENROLL_{enrollment_public_id}",
                        "assessment_ref": assessment_ref,
                        "completed_at": completed_at,
                        "case_ref": f"PCR_{review_ref}" if review_ref is not None else None,
                    }
                    for enrollment_public_id, assessment_ref, completed_at, review_ref in rows
                ],
                "total": total,
            }

    async def school_professional_review_open_case(
        self,
        actor: Any,
        task_ref: str,
        case_ref: str,
        *,
        expected_version: int,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        expected_version = _positive_version(expected_version)
        now = self._utc_now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            task = await self._task(uow, actor, task_ref, lock=True)
            await self._active_assignment(uow, actor, task, at=now, lock=True)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _CASE_RESOURCE)
                if ref != _public_id(case_ref, "PCR"):
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency result is unavailable",
                    )
                row = await self._case(uow, actor, task, f"PCR_{ref}", lock=True)
                return await self._case_projection_from_row(uow, actor, task, row)
            row = await self._case(uow, actor, task, case_ref, lock=True)
            if row.version != expected_version:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="review version changed")
            if row.status != "OPEN":
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="review case cannot be opened")
            row.status = "IN_REVIEW"
            row.version += 1
            row.updated_at = now
            await uow.session.flush()
            await self._event(
                uow,
                row=row,
                actor_role_id=role_id,
                event_type="TRANSITION",
                from_status="OPEN",
                to_status="IN_REVIEW",
                version=row.version,
                trace_id=trace_id,
                at=now,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=row.review_ref
            )
            await self._audit(
                uow,
                actor_account_id=actor_account_id,
                action="school_professional_review.case_opened",
                resource_type=_CASE_RESOURCE,
                resource_ref=row.review_ref,
                trace_id=trace_id,
                state="IN_REVIEW",
            )
            return await self._case_projection_from_row(uow, actor, task, row)

    async def school_professional_review_process_case(
        self,
        actor: Any,
        task_ref: str,
        case_ref: str,
        *,
        expected_version: int,
        decision: Literal["APPROVED", "REJECTED"],
        note: str,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        expected_version = _positive_version(expected_version)
        if decision not in {"APPROVED", "REJECTED"}:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid review decision")
        if not isinstance(note, str) or not 1 <= len(note) <= 2000 or not note.strip():
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid review note")
        now = self._utc_now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", now
            )
            task = await self._task(uow, actor, task_ref, lock=True)
            await self._active_assignment(uow, actor, task, at=now, lock=True)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _CASE_RESOURCE)
                if ref != _public_id(case_ref, "PCR"):
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency result is unavailable",
                    )
                row = await self._case(uow, actor, task, f"PCR_{ref}", lock=True)
                return await self._case_projection_from_row(uow, actor, task, row)
            row = await self._case(uow, actor, task, case_ref, lock=True)
            if row.version != expected_version:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="review version changed")
            if row.status != "IN_REVIEW":
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="review case cannot be decided")
            encrypted = self.protection.encrypt_json(
                {"note": note, "review_ref": row.review_ref},
                payload_schema_version=_NOTE_SCHEMA,
            )
            previous_status = row.status
            row.status = decision
            row.version += 1
            row.updated_at = now
            row.closed_at = now
            row.case_note_ciphertext = encrypted.ciphertext
            row.cipher_format_version = encrypted.cipher_format_version
            row.key_version = encrypted.key_version
            row.payload_schema_version = encrypted.payload_schema_version
            await uow.session.flush()
            await self._event(
                uow,
                row=row,
                actor_role_id=role_id,
                event_type="TRANSITION",
                from_status=previous_status,
                to_status=decision,
                version=row.version,
                trace_id=trace_id,
                at=now,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=row.review_ref
            )
            await self._audit(
                uow,
                actor_account_id=actor_account_id,
                action="school_professional_review.case_decided",
                resource_type=_CASE_RESOURCE,
                resource_ref=row.review_ref,
                trace_id=trace_id,
                state=decision,
            )
            return await self._case_projection_from_row(uow, actor, task, row)
