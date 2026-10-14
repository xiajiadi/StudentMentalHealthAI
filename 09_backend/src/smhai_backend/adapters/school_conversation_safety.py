"""Tenant-scoped adapter for durable metadata-only conversation safety cases."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from smhai_backend.adapters.school_conversations import SchoolConversationsPersistenceAdapter
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import get_request_context

_CASE_RESOURCE = "school_conversation_safety_case"
_NOTE_SCHEMA = "school_conversation_safety_review_note.v1"
_SAFE_CASE_REF = re.compile(r"^SCS_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$")
_SAFE_CONVERSATION_REF = re.compile(r"^CONV_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$")
_SAFE_USER_REF = re.compile(r"^USER_([A-Za-z0-9][A-Za-z0-9_.-]{0,122})$")
_MAX_NOTE_LENGTH = 4000


def _not_found():
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="conversation safety case was not found")


def _conflict():
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="conversation safety case state changed")


def _ref(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_CASE_REF.fullmatch(value):
        raise _not_found()
    return value


def _conversation_ref(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_CONVERSATION_REF.fullmatch(value):
        raise _not_found()
    return value


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SchoolConversationSafetyPersistenceAdapter:
    """Authorize every projection before it reaches a route or decrypt operation."""

    def __init__(self, persistence: Any) -> None:
        self._conversations = SchoolConversationsPersistenceAdapter(persistence)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conversations, name)

    @staticmethod
    def _project_admin(case) -> dict[str, Any]:
        return {
            "case_ref": case.case_ref,
            "status": case.status,
            "state_version": case.state_version,
            "class_ref": case.class_ref,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
            "assigned_at": case.assigned_at,
        }

    @staticmethod
    def _project_unassigned(case) -> dict[str, Any]:
        return {
            "case_ref": case.case_ref,
            "status": case.status,
            "state_version": case.state_version,
            "class_ref": case.class_ref,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        }

    @staticmethod
    def _project_student(case) -> dict[str, Any]:
        return {
            "case_ref": case.case_ref,
            "action": case.action,
            "status": case.status,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        }

    def _project_specialist(
        self, case, *, note: str | None = None, include_note: bool = False
    ) -> dict[str, Any]:
        result = {
            "case_ref": case.case_ref,
            "class_ref": case.class_ref,
            "action": case.action,
            "reason_codes": list(case.reason_codes),
            "status": case.status,
            "state_version": case.state_version,
            "decision_code": case.decision_code,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
            "assigned_at": case.assigned_at,
            "reviewed_at": case.reviewed_at,
            "closed_at": case.closed_at,
        }
        if include_note:
            result["review_note"] = note
        return result

    @staticmethod
    def _project_assignment(case) -> dict[str, Any]:
        return {
            "case_ref": case.case_ref,
            "status": case.status,
            "state_version": case.state_version,
            "class_ref": case.class_ref,
            "assigned_at": case.assigned_at,
            "updated_at": case.updated_at,
        }

    async def _actor_role(self, uow: Any, actor: Any, role_code: str, now: datetime):
        return await self._conversations._school_actor_role(uow, actor, role_code, now)

    async def _specialist_role_for_user(
        self, uow: Any, *, school_id: int, specialist_user_id: str, now: datetime
    ) -> int:
        match = _SAFE_USER_REF.fullmatch(specialist_user_id)
        if match is None:
            raise _not_found()
        m = self._db_models
        rows = list(
            (
                await uow.session.execute(
                    self._select(m.MembershipRole.id)
                    .join(
                        m.AccountSchoolMembership,
                        (m.AccountSchoolMembership.id == m.MembershipRole.membership_id)
                        & (m.AccountSchoolMembership.school_id == m.MembershipRole.school_id),
                    )
                    .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                    .join(m.School, m.School.id == m.MembershipRole.school_id)
                    .where(
                        m.Account.public_id == match.group(1),
                        m.Account.status == "ACTIVE",
                        m.AccountSchoolMembership.school_id == school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.MembershipRole.school_id == school_id,
                        m.MembershipRole.role_code == "psychological_specialist",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                        m.School.status == "ACTIVE",
                        m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    )
                    .limit(2)
                )
            ).scalars()
        )
        if len(rows) != 1:
            raise _not_found()
        return int(rows[0])

    async def _current_case(self, uow: Any, *, school_id: int, case_ref: str):
        row = await uow.conversation_safety.get_case_for_school(
            school_id=school_id, case_ref=case_ref
        )
        if row is None:
            raise _not_found()
        return row

    async def _audit_case(
        self, uow: Any, *, account_id: int, action: str, case_ref: str, trace_id: str
    ) -> None:
        await self._conversations._audit(
            uow,
            account_id=account_id,
            action=action,
            resource_type=_CASE_RESOURCE,
            resource_ref=case_ref,
            trace_id=trace_id,
        )

    async def student_status(
        self, actor: Any, conversation_ref: str, *, target_role: str = "student"
    ) -> dict[str, Any]:
        if target_role not in {"student", "student_research"}:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid conversation lane")
        conversation_ref = _conversation_ref(conversation_ref)
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, subject = await self._conversations._student_subject(uow, actor, now)
            m = self._db_models
            session = await uow.session.scalar(
                self._select(m.SupportSession)
                .join(m.Subject, m.Subject.id == m.SupportSession.subject_id)
                .where(
                    m.SupportSession.support_ref == conversation_ref,
                    m.SupportSession.subject_id == subject.id,
                    m.SupportSession.assessment_session_id.is_(None),
                    m.SupportSession.target_role == target_role,
                    m.Subject.school_id == actor.school_id,
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
            )
            if session is None:
                raise _not_found()
            case = await uow.conversation_safety.get_student_status(
                school_id=actor.school_id,
                subject_id=subject.id,
                support_session_id=session.id,
            )
            if case is None:
                raise _not_found()
            await self._conversations._audit(
                uow,
                account_id=account_id,
                action="student_conversation_safety.status_read",
                resource_type=_CASE_RESOURCE,
                resource_ref=case.case_ref,
                trace_id=get_request_context().trace_id,
            )
            return self._project_student(case)

    async def admin_list_unassigned(self, actor: Any, *, offset: int, limit: int) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            await self._actor_role(uow, actor, "admin", now)
            rows = await uow.conversation_safety.list_unassigned(
                school_id=actor.school_id, limit=limit, offset=offset
            )
            total = await uow.conversation_safety.count_unassigned(school_id=actor.school_id)
            return {"items": [self._project_unassigned(row) for row in rows], "total": total}

    async def admin_assign(
        self,
        actor: Any,
        case_ref: str,
        *,
        class_ref: str,
        specialist_user_id: str,
        expected_version: int,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        case_ref = _ref(case_ref)
        now = self._utc_now()
        payload = {
            "operation": "conversation_safety.assign",
            "case_ref": case_ref,
            "class_ref": class_ref,
            "specialist_user_id": specialist_user_id,
            "expected_version": expected_version,
        }
        async with self._uow() as uow:
            account_id, _admin_role_id = await self._actor_role(uow, actor, "admin", now)
            specialist_role_id = await self._specialist_role_for_user(
                uow,
                school_id=actor.school_id,
                specialist_user_id=specialist_user_id,
                now=now,
            )
            claim = await self._school_idempotency_begin(
                uow,
                (
                    idempotency[0],
                    fingerprint(payload),
                    f"{account_id}:school:conversation-safety:assign:{actor.school_id}",
                ),
            )
            if claim.replayed:
                receipt = await self._conversations._lookup_receipt_resource(
                    uow, receipt=claim.record, resource_type=_CASE_RESOURCE
                )
                row = await self._current_case(uow, school_id=actor.school_id, case_ref=receipt)
                if (
                    row.assigned_membership_role_id != specialist_role_id
                    or row.class_ref != class_ref
                ):
                    raise _conflict()
                return self._project_assignment(row)
            try:
                row = await uow.conversation_safety.assign(
                    school_id=actor.school_id,
                    case_ref=case_ref,
                    class_ref=class_ref,
                    specialist_membership_role_id=specialist_role_id,
                    actor_membership_role_id=_admin_role_id,
                    expected_version=expected_version,
                    trace_id=trace_id,
                    now=now,
                )
            except Exception as exc:
                self._translate_repo_error(exc)
            await self._audit_case(
                uow,
                account_id=account_id,
                action="school.conversation_safety.assigned",
                case_ref=case_ref,
                trace_id=trace_id,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=case_ref
            )
            return self._project_assignment(row)

    async def admin_transfer(
        self,
        actor: Any,
        case_ref: str,
        *,
        class_ref: str,
        specialist_user_id: str,
        expected_version: int,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        case_ref = _ref(case_ref)
        now = self._utc_now()
        payload = {
            "operation": "conversation_safety.transfer",
            "case_ref": case_ref,
            "class_ref": class_ref,
            "specialist_user_id": specialist_user_id,
            "expected_version": expected_version,
        }
        async with self._uow() as uow:
            account_id, admin_role_id = await self._actor_role(uow, actor, "admin", now)
            specialist_role_id = await self._specialist_role_for_user(
                uow,
                school_id=actor.school_id,
                specialist_user_id=specialist_user_id,
                now=now,
            )
            claim = await self._school_idempotency_begin(
                uow,
                (
                    idempotency[0],
                    fingerprint(payload),
                    f"{account_id}:school:conversation-safety:transfer:{actor.school_id}",
                ),
            )
            if claim.replayed:
                receipt = await self._conversations._lookup_receipt_resource(
                    uow, receipt=claim.record, resource_type=_CASE_RESOURCE
                )
                replayed = await self._current_case(
                    uow, school_id=actor.school_id, case_ref=receipt
                )
                if (
                    replayed.assigned_membership_role_id != specialist_role_id
                    or replayed.class_ref != class_ref
                ):
                    raise _conflict()
                return self._project_assignment(replayed)
            try:
                row = await uow.conversation_safety.transfer(
                    school_id=actor.school_id,
                    case_ref=case_ref,
                    class_ref=class_ref,
                    specialist_membership_role_id=specialist_role_id,
                    actor_membership_role_id=admin_role_id,
                    expected_version=expected_version,
                    trace_id=trace_id,
                    now=now,
                )
            except Exception as exc:
                self._translate_repo_error(exc)
            await self._audit_case(
                uow,
                account_id=account_id,
                action="school.conversation_safety.transferred",
                case_ref=case_ref,
                trace_id=trace_id,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=case_ref
            )
            return self._project_assignment(row)

    async def admin_unassign(
        self, actor, case_ref: str, *, expected_version: int, idempotency, trace_id: str
    ) -> dict[str, Any]:
        return await self._admin_case_transition(
            actor,
            case_ref,
            operation="unassign",
            expected_version=expected_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def admin_revoke(
        self, actor, case_ref: str, *, expected_version: int, idempotency, trace_id: str
    ) -> dict[str, Any]:
        return await self._admin_case_transition(
            actor,
            case_ref,
            operation="revoke",
            expected_version=expected_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def _admin_case_transition(
        self,
        actor,
        case_ref: str,
        *,
        operation: str,
        expected_version: int,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        case_ref = _ref(case_ref)
        now = self._utc_now()
        payload = {
            "operation": f"conversation_safety.{operation}",
            "case_ref": case_ref,
            "expected_version": expected_version,
        }
        async with self._uow() as uow:
            account_id, admin_role_id = await self._actor_role(uow, actor, "admin", now)
            claim = await self._school_idempotency_begin(
                uow,
                (
                    idempotency[0],
                    fingerprint(payload),
                    f"{account_id}:school:conversation-safety:{operation}:{actor.school_id}",
                ),
            )
            if claim.replayed:
                receipt = await self._conversations._lookup_receipt_resource(
                    uow, receipt=claim.record, resource_type=_CASE_RESOURCE
                )
                return self._project_admin(
                    await self._current_case(uow, school_id=actor.school_id, case_ref=receipt)
                )
            try:
                if operation == "unassign":
                    row = await uow.conversation_safety.unassign(
                        school_id=actor.school_id,
                        case_ref=case_ref,
                        actor_membership_role_id=admin_role_id,
                        expected_version=expected_version,
                        trace_id=trace_id,
                        now=now,
                    )
                else:
                    row = await uow.conversation_safety.revoke_case(
                        school_id=actor.school_id,
                        case_ref=case_ref,
                        actor_membership_role_id=admin_role_id,
                        expected_version=expected_version,
                        trace_id=trace_id,
                        now=now,
                    )
            except Exception as exc:
                self._translate_repo_error(exc)
            await self._audit_case(
                uow,
                account_id=account_id,
                action=f"school.conversation_safety.{operation}",
                case_ref=case_ref,
                trace_id=trace_id,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=case_ref
            )
            return self._project_admin(row)

    async def specialist_list_assigned(
        self, actor: Any, *, offset: int, limit: int
    ) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            _account_id, role_id = await self._actor_role(
                uow, actor, "psychological_specialist", now
            )
            rows = await uow.conversation_safety.list_assigned(
                school_id=actor.school_id,
                specialist_membership_role_id=role_id,
                limit=limit,
                offset=offset,
                now=now,
            )
            total = await uow.conversation_safety.count_assigned(
                school_id=actor.school_id,
                specialist_membership_role_id=role_id,
                now=now,
            )
            return {"items": [self._project_specialist(row) for row in rows], "total": total}

    async def specialist_get(
        self, actor: Any, case_ref: str, *, include_note: bool = True
    ) -> dict[str, Any]:
        case_ref = _ref(case_ref)
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, role_id = await self._actor_role(
                uow, actor, "psychological_specialist", now
            )
            row = await uow.conversation_safety.get_assigned(
                school_id=actor.school_id,
                case_ref=case_ref,
                specialist_membership_role_id=role_id,
                now=now,
            )
            if row is None:
                raise _not_found()
            note = self._decrypt_note(uow, row) if include_note else None
            await self._audit_case(
                uow,
                account_id=account_id,
                action="school.conversation_safety.detail_read",
                case_ref=case_ref,
                trace_id=get_request_context().trace_id,
            )
            return self._project_specialist(row, note=note, include_note=include_note)

    async def specialist_save_note(
        self,
        actor: Any,
        case_ref: str,
        *,
        expected_version: int,
        note: str,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        case_ref = _ref(case_ref)
        note = self._validate_note(note)
        now = self._utc_now()
        payload = {
            "operation": "conversation_safety.save_note",
            "case_ref": case_ref,
            "expected_version": expected_version,
            "note": note,
        }
        async with self._uow() as uow:
            account_id, role_id = await self._actor_role(
                uow, actor, "psychological_specialist", now
            )
            claim = await self._school_idempotency_begin(
                uow,
                (
                    idempotency[0],
                    fingerprint(payload),
                    f"{account_id}:school:conversation-safety:note:{actor.school_id}",
                ),
            )
            if claim.replayed:
                receipt = await self._conversations._lookup_receipt_resource(
                    uow, receipt=claim.record, resource_type=_CASE_RESOURCE
                )
                if receipt != case_ref:
                    raise _conflict()
                return await self._specialist_projection_in_uow(uow, actor, role_id, case_ref, now)
            protected = uow.protection.encrypt_json(
                {"case_ref": case_ref, "note": note},
                payload_schema_version=_NOTE_SCHEMA,
            )
            try:
                row = await uow.conversation_safety.save_draft_note(
                    school_id=actor.school_id,
                    case_ref=case_ref,
                    specialist_membership_role_id=role_id,
                    expected_version=expected_version,
                    ciphertext=protected.ciphertext,
                    cipher_format_version=protected.cipher_format_version,
                    key_version=protected.key_version,
                    payload_schema_version=protected.payload_schema_version,
                    trace_id=trace_id,
                    now=now,
                )
            except Exception as exc:
                self._translate_repo_error(exc)
            await self._audit_case(
                uow,
                account_id=account_id,
                action="school.conversation_safety.note_drafted",
                case_ref=case_ref,
                trace_id=trace_id,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=case_ref
            )
            return self._project_specialist(row, note=note, include_note=True)

    async def _specialist_projection_in_uow(self, uow, actor, role_id, case_ref, now):
        row = await uow.conversation_safety.get_assigned(
            school_id=actor.school_id,
            case_ref=case_ref,
            specialist_membership_role_id=role_id,
            now=now,
        )
        if row is None:
            raise _not_found()
        return self._project_specialist(row, note=self._decrypt_note(uow, row), include_note=True)

    async def specialist_transition(
        self,
        actor: Any,
        case_ref: str,
        *,
        expected_version: int,
        status: str,
        decision_code: str | None,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        case_ref = _ref(case_ref)
        now = self._utc_now()
        payload = {
            "operation": "conversation_safety.transition",
            "case_ref": case_ref,
            "expected_version": expected_version,
            "status": status,
            "decision_code": decision_code,
        }
        async with self._uow() as uow:
            account_id, role_id = await self._actor_role(
                uow, actor, "psychological_specialist", now
            )
            claim = await self._school_idempotency_begin(
                uow,
                (
                    idempotency[0],
                    fingerprint(payload),
                    f"{account_id}:school:conversation-safety:transition:{actor.school_id}",
                ),
            )
            if claim.replayed:
                receipt = await self._conversations._lookup_receipt_resource(
                    uow, receipt=claim.record, resource_type=_CASE_RESOURCE
                )
                if receipt != case_ref:
                    raise _conflict()
                return await self._specialist_projection_in_uow(uow, actor, role_id, case_ref, now)
            try:
                row = await uow.conversation_safety.transition(
                    school_id=actor.school_id,
                    case_ref=case_ref,
                    specialist_membership_role_id=role_id,
                    expected_version=expected_version,
                    to_status=status,
                    decision_code=decision_code,
                    trace_id=trace_id,
                    now=now,
                )
            except Exception as exc:
                self._translate_repo_error(exc)
            await self._audit_case(
                uow,
                account_id=account_id,
                action="school.conversation_safety.transitioned",
                case_ref=case_ref,
                trace_id=trace_id,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=case_ref
            )
            return self._project_specialist(
                row, note=self._decrypt_note(uow, row), include_note=True
            )

    def _decrypt_note(self, uow: Any, row) -> str | None:
        if row.review_note_ciphertext is None:
            return None
        if (
            row.review_note_payload_schema_version != _NOTE_SCHEMA
            or not row.review_note_cipher_format_version
            or not row.review_note_key_version
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review note is unavailable")
        from database_layer.crypto import EncryptedPayload

        try:
            value = uow.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=row.review_note_ciphertext,
                    key_version=row.review_note_key_version,
                    cipher_format_version=row.review_note_cipher_format_version,
                    payload_schema_version=row.review_note_payload_schema_version,
                )
            )
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review note is unavailable"
            ) from None
        if (
            not isinstance(value, dict)
            or set(value) != {"case_ref", "note"}
            or value["case_ref"] != row.case_ref
            or not isinstance(value["note"], str)
            or len(value["note"]) > _MAX_NOTE_LENGTH
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review note is unavailable")
        return value["note"]

    @staticmethod
    def _validate_note(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > _MAX_NOTE_LENGTH:
            raise error(ErrorCode.VALIDATION_FAILED, detail="review note is invalid")
        return value

    @staticmethod
    def _translate_repo_error(exc: Exception) -> None:
        from database_layer.errors import (
            ForeignKeyConflict,
            OptimisticConcurrencyConflict,
            UniqueConflict,
        )
        from database_layer.school_conversation_safety import SchoolConversationSafetyError

        if isinstance(exc, OptimisticConcurrencyConflict):
            raise _conflict() from None
        if isinstance(exc, (ForeignKeyConflict, UniqueConflict)):
            raise _not_found() from None
        if isinstance(exc, SchoolConversationSafetyError):
            raise _not_found() from None
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="conversation safety persistence is unavailable",
            retryable=True,
        ) from None
