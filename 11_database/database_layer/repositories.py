"""Domain-specific persistence adapters.

Repositories add, flush and query only.  Commit/rollback is owned by
``SqlAlchemyUnitOfWork``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import EncryptedPayload, FernetDataProtectionProvider
from .enums import (
    AccountStatus,
    AssessmentStatus,
    AuditResult,
    ConsentStatus,
    DataOrigin,
    IdempotencyState,
    MessageKind,
    ReviewEventType,
    ReviewPriority,
    ReviewStatus,
    SafetyAction,
    SupportRunStatus,
    SupportStatus,
)
from .errors import NotFound, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    Account,
    AssessmentResponse,
    AssessmentResult,
    AssessmentSession,
    AuditEvent,
    AuthSession,
    ConsentRecord,
    IdempotencyRecord,
    ReviewCase,
    ReviewEvent,
    SafetyDecision,
    Subject,
    SupportEvidence,
    SupportMessage,
    SupportRun,
    SupportSession,
)


def _hash_opaque_token(token: str) -> bytes:
    if not token:
        raise ValueError("opaque token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).digest()


def _hash_request(request_bytes: bytes) -> bytes:
    return hashlib.sha256(request_bytes).digest()


def _map_integrity_error(exc: IntegrityError) -> UniqueConflict:
    del exc
    return UniqueConflict("persistence uniqueness constraint was violated")


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        login_name: str,
        password_hash: str,
        status: AccountStatus = AccountStatus.ACTIVE,
    ) -> Account:
        account = Account(login_name=login_name, password_hash=password_hash, status=status.value)
        self.session.add(account)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return account

    async def get_by_login_name(self, login_name: str) -> Account | None:
        result = await self.session.execute(select(Account).where(Account.login_name == login_name))
        return result.scalar_one_or_none()


class SubjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        subject_ref: str,
        data_origin: DataOrigin = DataOrigin.SYNTHETIC,
        retention_due_at: datetime | None = None,
    ) -> Subject:
        subject = Subject(
            subject_ref=subject_ref,
            data_origin=data_origin.value,
            retention_due_at=retention_due_at,
        )
        self.session.add(subject)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return subject

    async def get_by_ref(self, subject_ref: str) -> Subject | None:
        result = await self.session.execute(
            select(Subject).where(Subject.subject_ref == subject_ref)
        )
        return result.scalar_one_or_none()


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        subject_id: int,
        consent_type: str,
        policy_version: str,
        scope_identifier: str,
        status: ConsentStatus,
        granted_at: datetime,
        granted_by_account_id: int | None = None,
        granted_by_relationship: str | None = None,
        withdrawn_at: datetime | None = None,
        trace_id: str | None = None,
        retention_due_at: datetime | None = None,
    ) -> ConsentRecord:
        record = ConsentRecord(
            subject_id=subject_id,
            consent_type=consent_type,
            policy_version=policy_version,
            scope_identifier=scope_identifier,
            granted_by_account_id=granted_by_account_id,
            granted_by_relationship=granted_by_relationship,
            granted_at=granted_at,
            withdrawn_at=withdrawn_at,
            status=status.value,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def history(self, subject_id: int, consent_type: str) -> list[ConsentRecord]:
        result = await self.session.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.subject_id == subject_id,
                ConsentRecord.consent_type == consent_type,
            )
            .order_by(ConsentRecord.created_at, ConsentRecord.id)
        )
        return list(result.scalars())


class AuthSessionStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        account_id: int,
        raw_session_token: str,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        raw_csrf_token: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        record = AuthSession(
            account_id=account_id,
            session_token_hash=_hash_opaque_token(raw_session_token),
            csrf_token_hash=_hash_opaque_token(raw_csrf_token) if raw_csrf_token else None,
            user_agent_hash=_hash_opaque_token(user_agent) if user_agent else None,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        )
        self.session.add(record)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return record

    async def find_by_token(self, raw_session_token: str) -> AuthSession | None:
        token_hash = _hash_opaque_token(raw_session_token)
        result = await self.session.execute(
            select(AuthSession).where(
                AuthSession.session_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, raw_session_token: str, *, reason: str, at: datetime) -> None:
        record = await self.find_by_token(raw_session_token)
        if record is not None:
            record.revoked_at = at
            record.revocation_reason = reason
            await self.session.flush()


class AssessmentRepository:
    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_session(
        self,
        *,
        assessment_ref: str,
        subject_id: int,
        instrument_id: str,
        instrument_version: str,
        item_bank_version: str | None,
        config_version: str | None,
        trace_id: str | None,
    ) -> AssessmentSession:
        record = AssessmentSession(
            assessment_ref=assessment_ref,
            subject_id=subject_id,
            instrument_id=instrument_id,
            instrument_version=instrument_version,
            item_bank_version=item_bank_version,
            config_version=config_version,
            trace_id=trace_id,
            status=AssessmentStatus.CREATED.value,
        )
        self.session.add(record)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return record

    async def append_response(
        self,
        *,
        assessment_session_id: int,
        sequence_no: int,
        item_ref: str,
        response_payload: Mapping[str, object],
        trace_id: str | None,
        payload_schema_version: str = "assessment-response.v1",
        retention_due_at: datetime | None = None,
    ) -> AssessmentResponse:
        protected = self.protection.encrypt_json(
            response_payload, payload_schema_version=payload_schema_version
        )
        record = AssessmentResponse(
            assessment_session_id=assessment_session_id,
            sequence_no=sequence_no,
            item_ref=item_ref,
            response_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def save_result(
        self,
        *,
        assessment_session_id: int,
        result_payload: Mapping[str, object],
        completed_at: datetime | None,
        retention_due_at: datetime | None,
        payload_schema_version: str = "assessment-result.v1",
    ) -> AssessmentResult:
        protected = self.protection.encrypt_json(
            result_payload, payload_schema_version=payload_schema_version
        )
        record = AssessmentResult(
            assessment_session_id=assessment_session_id,
            payload_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            completed_at=completed_at,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_session(self, assessment_ref: str) -> AssessmentSession:
        result = await self.session.execute(
            select(AssessmentSession).where(AssessmentSession.assessment_ref == assessment_ref)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFound("assessment session was not found")
        return record


class SupportRepository:
    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_session(
        self,
        *,
        support_ref: str,
        subject_id: int,
        target_role: str,
        assessment_session_id: int | None,
        trace_id: str | None,
        retention_due_at: datetime | None,
    ) -> SupportSession:
        record = SupportSession(
            support_ref=support_ref,
            subject_id=subject_id,
            target_role=target_role,
            assessment_session_id=assessment_session_id,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
            status=SupportStatus.OPEN.value,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_run(
        self,
        *,
        run_ref: str,
        support_session_id: int,
        trace_id: str,
        status: SupportRunStatus = SupportRunStatus.REQUESTED,
        workflow_action: str | None = None,
        assessment_session_id: int | None = None,
        generation_ref: str | None = None,
        retrieval_ref: str | None = None,
        component_versions: Mapping[str, object] | None = None,
    ) -> SupportRun:
        record = SupportRun(
            run_ref=run_ref,
            support_session_id=support_session_id,
            assessment_session_id=assessment_session_id,
            generation_ref=generation_ref,
            retrieval_ref=retrieval_ref,
            trace_id=trace_id,
            status=status.value,
            workflow_action=workflow_action,
            component_versions=dict(component_versions) if component_versions else None,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def persist_message(
        self,
        *,
        support_session_id: int,
        sequence_no: int,
        message_kind: MessageKind,
        payload: Mapping[str, object],
        safety_decision_id: int | None = None,
        retention_due_at: datetime | None = None,
    ) -> SupportMessage:
        if message_kind not in {MessageKind.USER_INPUT, MessageKind.APPROVED_OUTPUT}:
            raise ValueError("only user input or safety-approved output may be persisted")
        protected = self.protection.encrypt_json(
            payload, payload_schema_version="support-message.v1"
        )
        record = SupportMessage(
            support_session_id=support_session_id,
            sequence_no=sequence_no,
            message_kind=message_kind.value,
            payload_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            safety_decision_id=safety_decision_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def add_evidence(
        self,
        *,
        support_run_id: int,
        citation_id: str,
        source_id: str,
        source_version: str | None,
        source_hash: str | None,
        locator: str | None,
        rank_order: int,
    ) -> SupportEvidence:
        record = SupportEvidence(
            support_run_id=support_run_id,
            citation_id=citation_id,
            source_id=source_id,
            source_version=source_version,
            source_hash=source_hash,
            locator=locator,
            rank_order=rank_order,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_safety_decision(
        self,
        *,
        decision_ref: str,
        support_run_id: int,
        action: SafetyAction,
        policy_version: str,
        guard_model_revision: str | None,
        trace_id: str,
        detail: Mapping[str, object] | None,
        retention_due_at: datetime | None,
    ) -> SafetyDecision:
        protected: EncryptedPayload | None = None
        if detail is not None:
            protected = self.protection.encrypt_json(
                detail, payload_schema_version="safety-detail.v1"
            )
        record = SafetyDecision(
            decision_ref=decision_ref,
            support_run_id=support_run_id,
            action=action.value,
            policy_version=policy_version,
            guard_model_revision=guard_model_revision,
            trace_id=trace_id,
            detail_ciphertext=protected.ciphertext if protected else None,
            cipher_format_version=protected.cipher_format_version if protected else None,
            key_version=protected.key_version if protected else None,
            payload_schema_version=protected.payload_schema_version if protected else None,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record


class ReviewRepository:
    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_case(
        self,
        *,
        review_ref: str,
        subject_id: int,
        safety_decision_id: int,
        priority: ReviewPriority,
        case_note: Mapping[str, object] | None,
        retention_due_at: datetime | None,
    ) -> ReviewCase:
        protected = (
            self.protection.encrypt_json(case_note, payload_schema_version="review-note.v1")
            if case_note is not None
            else None
        )
        record = ReviewCase(
            review_ref=review_ref,
            subject_id=subject_id,
            safety_decision_id=safety_decision_id,
            priority=priority.value,
            status=ReviewStatus.OPEN.value,
            case_note_ciphertext=protected.ciphertext if protected else None,
            cipher_format_version=protected.cipher_format_version if protected else None,
            key_version=protected.key_version if protected else None,
            payload_schema_version=protected.payload_schema_version if protected else None,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        await self.add_event(
            review_case_id=record.id,
            event_type=ReviewEventType.CREATED,
            actor_account_id=None,
            to_status=ReviewStatus.OPEN.value,
            note=None,
            trace_id=None,
            retention_due_at=retention_due_at,
        )
        return record

    async def update_case(
        self,
        *,
        review_case_id: int,
        expected_version: int,
        status: ReviewStatus,
        assigned_account_id: int | None = None,
        closed_at: datetime | None = None,
    ) -> ReviewCase:
        values: dict[str, Any] = {
            "status": status.value,
            "assigned_account_id": assigned_account_id,
            "closed_at": closed_at,
            "version": expected_version + 1,
        }
        result = await self.session.execute(
            update(ReviewCase)
            .where(ReviewCase.id == review_case_id, ReviewCase.version == expected_version)
            .values(**values)
        )
        if result.rowcount != 1:  # type: ignore[reportAttributeAccessIssue]
            raise OptimisticConcurrencyConflict("review case version is stale")
        await self.session.flush()
        refreshed = await self.session.get(ReviewCase, review_case_id)
        if refreshed is None:
            raise NotFound("review case was not found")
        return refreshed

    async def add_event(
        self,
        *,
        review_case_id: int,
        event_type: ReviewEventType,
        actor_account_id: int | None,
        to_status: str | None,
        note: Mapping[str, object] | None,
        trace_id: str | None,
        retention_due_at: datetime | None,
    ) -> ReviewEvent:
        protected = (
            self.protection.encrypt_json(note, payload_schema_version="review-event-note.v1")
            if note is not None
            else None
        )
        record = ReviewEvent(
            review_case_id=review_case_id,
            event_type=event_type.value,
            actor_account_id=actor_account_id,
            to_status=to_status,
            note_ciphertext=protected.ciphertext if protected else None,
            cipher_format_version=protected.cipher_format_version if protected else None,
            key_version=protected.key_version if protected else None,
            payload_schema_version=protected.payload_schema_version if protected else None,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record


class IdempotencyStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self,
        *,
        scope: str,
        key: str,
        request_bytes: bytes,
        expires_at: datetime,
    ) -> tuple[IdempotencyRecord, bool]:
        record = IdempotencyRecord(
            scope=scope,
            key_hash=_hash_opaque_token(key),
            request_hash=_hash_request(request_bytes),
            state=IdempotencyState.IN_PROGRESS.value,
            expires_at=expires_at,
        )
        created = True
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except IntegrityError:
            created = False
        if created:
            return record, True
        result = await self.session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.key_hash == _hash_opaque_token(key),
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise UniqueConflict("idempotency record was concurrently removed")
        if existing.request_hash != _hash_request(request_bytes):
            raise UniqueConflict("idempotency key was reused for a different request")
        return existing, False

    async def complete(
        self,
        record_id: int,
        *,
        result_resource_type: str,
        result_public_id: str,
    ) -> None:
        record = await self.session.get(IdempotencyRecord, record_id)
        if record is None:
            raise NotFound("idempotency record was not found")
        record.state = IdempotencyState.COMPLETED.value
        record.result_resource_type = result_resource_type
        record.result_public_id = result_public_id
        await self.session.flush()


_SAFE_AUDIT_KEYS = frozenset(
    {"schema_version", "component_version", "reason_code", "count", "source", "state"}
)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        action: str,
        resource_type: str,
        resource_public_id: str | None,
        result: AuditResult,
        trace_id: str,
        actor_account_id: int | None = None,
        safe_metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        metadata = dict(safe_metadata or {})
        unknown = set(metadata) - _SAFE_AUDIT_KEYS
        if unknown:
            raise ValueError("audit metadata contains a non-whitelisted field")
        record = AuditEvent(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_public_id,
            result=result.value,
            trace_id=trace_id,
            actor_account_id=actor_account_id,
            safe_metadata=metadata,
        )
        self.session.add(record)
        await self.session.flush()
        return record


# Names aligned with the future Backend port vocabulary without importing its
# unfinished module.  Structural compatibility is documented separately.
SqlAlchemyUserRepository = AccountRepository
SqlAlchemySessionStore = AuthSessionStore
SqlAlchemyAssessmentRepository = AssessmentRepository
SqlAlchemyConversationRepository = SupportRepository
SqlAlchemyReviewRepository = ReviewRepository
SqlAlchemyAuditRepository = AuditRepository
SqlAlchemyIdempotencyStore = IdempotencyStore


__all__ = [
    "AccountRepository",
    "AssessmentRepository",
    "AuditRepository",
    "AuthSessionStore",
    "ConsentRepository",
    "IdempotencyStore",
    "ReviewRepository",
    "SqlAlchemyAssessmentRepository",
    "SqlAlchemyAuditRepository",
    "SqlAlchemyConversationRepository",
    "SqlAlchemyIdempotencyStore",
    "SqlAlchemyReviewRepository",
    "SqlAlchemySessionStore",
    "SqlAlchemyUserRepository",
    "SubjectRepository",
    "SupportRepository",
]
