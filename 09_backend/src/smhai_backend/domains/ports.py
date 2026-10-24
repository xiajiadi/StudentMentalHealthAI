"""Repository and policy ports owned by Backend Round 1."""

from __future__ import annotations

from typing import Any, Protocol

from .models import (
    Actor,
    AssessmentRecord,
    AuditEvent,
    IdempotencyRecord,
    ReportRecord,
    ReviewProjection,
    SessionRecord,
    SyntheticUser,
)


class UserRepository(Protocol):
    def get_by_username(self, username: str) -> SyntheticUser | None: ...
    def get(self, user_id: str) -> SyntheticUser | None: ...
    def record_login_failure(
        self, username: str, *, threshold: int, lock_seconds: int
    ) -> None: ...
    def record_login_success(self, user_id: str) -> None: ...


class SessionStore(Protocol):
    def create(
        self, user_id: str, ttl_seconds: int, *, active_context_id: str | None = None
    ) -> SessionRecord: ...
    def get(self, session_id: str) -> SessionRecord | None: ...
    def rotate(self, session_id: str, user_id: str, ttl_seconds: int) -> SessionRecord: ...
    def revoke(self, session_id: str) -> None: ...
    def is_revoked(self, session_id: str) -> bool: ...
    def touch(self, session_id: str, ttl_seconds: int) -> SessionRecord | None: ...
    def set_active_context(self, session_id: str, context_id: str) -> SessionRecord | None: ...
    def mark_reauthenticated(self, session_id: str, at: float) -> SessionRecord | None: ...


class AssessmentRepository(Protocol):
    def save(self, record: AssessmentRecord) -> None: ...
    def get(self, assessment_id: str) -> AssessmentRecord | None: ...
    def list_assessments_for_subjects(
        self,
        subject_ids: set[str],
        *,
        limit: int | None = None,
        skip: int = 0,
        status: str | None = None,
    ) -> list[AssessmentRecord]: ...


class ConversationRepository(Protocol):
    def save_metadata(
        self, *, request_id: str, trace_id: str, metadata: dict[str, Any]
    ) -> None: ...

    def begin_workflow(
        self,
        *,
        report_id: str,
        assessment_id: str,
        subject_id: str,
        target_role: str,
        message: str,
        generation_id: str,
        trace_id: str,
        request_id: str,
    ) -> None: ...

    def complete_workflow(self, result: Any) -> None: ...

    def fail_workflow(
        self,
        report_id: str,
        *,
        reason_code: str,
        trace_id: str,
        stage_diagnostics: dict[str, Any] | None = None,
    ) -> None: ...


class ReportRepository(Protocol):
    def save(self, record: ReportRecord) -> None: ...
    def get(self, report_id: str) -> ReportRecord | None: ...
    def list_for_subjects(
        self,
        subject_ids: set[str],
        assessment_id: str | None = None,
        limit: int = 100,
    ) -> list[ReportRecord]: ...


class ReviewProjectionRepository(Protocol):
    def save(self, projection: ReviewProjection) -> None: ...
    def get(self, review_id: str) -> ReviewProjection | None: ...
    def list_pending(self) -> list[ReviewProjection]: ...


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def list(self) -> list[AuditEvent]: ...


class IdempotencyStore(Protocol):
    def get(self, scope: str, key: str) -> IdempotencyRecord | None: ...
    def put(self, scope: str, key: str, record: IdempotencyRecord) -> None: ...

    def claim(self, scope: str, key: str, request_fingerprint: str) -> bool: ...


class AuthorizationProvider(Protocol):
    def can(self, actor: Actor, action: str, *, resource: dict[str, Any] | None = None) -> bool: ...
    def require(
        self, actor: Actor, action: str, *, resource: dict[str, Any] | None = None
    ) -> None: ...


class OPAAuthorizationProvider(AuthorizationProvider, Protocol):
    """Future adapter shape; OPA is not used for generic auth in Round 1."""


class UnitOfWork(Protocol):
    def __enter__(self) -> UnitOfWork: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
