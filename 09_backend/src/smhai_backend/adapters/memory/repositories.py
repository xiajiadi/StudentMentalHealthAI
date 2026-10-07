"""In-memory ports for Backend Round 1.

No adapter in this file is durable or suitable for multiple workers.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import replace
from typing import Any

from pwdlib import PasswordHash

from smhai_backend.domains.models import (
    AssessmentRecord,
    AuditEvent,
    BackendRole,
    IdempotencyRecord,
    ReportRecord,
    ReviewProjection,
    SessionRecord,
    SyntheticUser,
)


class InMemoryUserRepository:
    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        hasher = password_hash or PasswordHash.recommended()
        self._users: dict[str, SyntheticUser] = {}
        self._by_username: dict[str, SyntheticUser] = {}
        self._add(
            SyntheticUser(
                user_id="USER_student_a",
                username="student_a",
                role=BackendRole.STUDENT,
                subject_id="SUBJ_demo_a",
                password_hash=hasher.hash("synthetic-student-a"),
            )
        )
        self._add(
            SyntheticUser(
                user_id="USER_student_b",
                username="student_b",
                role=BackendRole.STUDENT,
                subject_id="SUBJ_demo_b",
                password_hash=hasher.hash("synthetic-student-b"),
            )
        )
        subjects = frozenset({"SUBJ_demo_a", "SUBJ_demo_b"})
        self._add(
            SyntheticUser(
                user_id="USER_teacher",
                username="teacher",
                role=BackendRole.TEACHER,
                subject_id=None,
                password_hash=hasher.hash("synthetic-teacher"),
                accessible_subject_ids=subjects,
            )
        )
        self._add(
            SyntheticUser(
                user_id="USER_reviewer",
                username="reviewer",
                role=BackendRole.REVIEWER,
                subject_id=None,
                password_hash=hasher.hash("synthetic-reviewer"),
                accessible_subject_ids=subjects,
            )
        )

    def _add(self, user: SyntheticUser) -> None:
        self._users[user.user_id] = user
        self._by_username[user.username] = user

    def get_by_username(self, username: str) -> SyntheticUser | None:
        return self._by_username.get(username)

    def get(self, user_id: str) -> SyntheticUser | None:
        return self._users.get(user_id)


class InMemorySessionStore:
    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._sessions: dict[str, SessionRecord] = {}
        self._revoked: set[str] = set()

    def create(self, user_id: str, ttl_seconds: int) -> SessionRecord:
        now = self._clock()
        session = SessionRecord(
            session_id=secrets.token_urlsafe(32),
            user_id=user_id,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + ttl_seconds,
            last_seen_at=now,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> SessionRecord | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expires_at <= self._clock():
            self._sessions.pop(session_id, None)
            self._revoked.add(session_id)
            return None
        return session

    def rotate(self, session_id: str, user_id: str, ttl_seconds: int) -> SessionRecord:
        self.revoke(session_id)
        return self.create(user_id, ttl_seconds)

    def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._revoked.add(session_id)

    def is_revoked(self, session_id: str) -> bool:
        return session_id in self._revoked

    def touch(self, session_id: str, ttl_seconds: int) -> SessionRecord | None:
        session = self.get(session_id)
        if session is None:
            return None
        now = self._clock()
        session.last_seen_at = now
        session.expires_at = now + ttl_seconds
        return session


class InMemoryAssessmentRepository:
    def __init__(self) -> None:
        self._records: dict[str, AssessmentRecord] = {}

    def save(self, record: AssessmentRecord) -> None:
        self._records[record.assessment_id] = record

    def get(self, assessment_id: str) -> AssessmentRecord | None:
        return self._records.get(assessment_id)

    def list_assessments_for_subjects(self, subject_ids: set[str]) -> list[AssessmentRecord]:
        return sorted(
            (record for record in self._records.values() if record.subject_id in subject_ids),
            key=lambda record: str(record.assessment.get("timestamps", {}).get("started_at", "")),
            reverse=True,
        )


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def save_metadata(self, *, request_id: str, trace_id: str, metadata: dict[str, Any]) -> None:
        self.records.append(
            {
                "request_id": request_id,
                "trace_id": trace_id,
                "metadata": dict(metadata),
            }
        )

    def begin_workflow(self, **metadata: Any) -> None:
        self.records.append({"workflow": "REQUESTED", "metadata": dict(metadata)})

    def complete_workflow(self, result: Any) -> None:
        self.records.append(
            {"workflow": "COMPLETED", "report_id": getattr(result, "report_id", None)}
        )

    def fail_workflow(self, report_id: str, *, reason_code: str, trace_id: str) -> None:
        self.records.append(
            {
                "workflow": "FAILED",
                "report_id": report_id,
                "reason_code": reason_code,
                "trace_id": trace_id,
            }
        )


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._records: dict[str, ReportRecord] = {}

    def save(self, record: ReportRecord) -> None:
        self._records[record.report_id] = record

    def get(self, report_id: str) -> ReportRecord | None:
        return self._records.get(report_id)

    def list_for_subjects(
        self,
        subject_ids: set[str],
        assessment_id: str | None = None,
        limit: int = 100,
    ) -> list[ReportRecord]:
        limit = max(1, min(limit, 100))
        records = (
            record
            for record in self._records.values()
            if record.subject_id in subject_ids
            and (assessment_id is None or record.assessment_id == assessment_id)
        )
        return sorted(
            records,
            key=lambda record: str(record.generation.get("created_at", "")),
            reverse=True,
        )[:limit]

    def delete(self, report_id: str) -> None:
        self._records.pop(report_id, None)


class InMemoryReviewProjectionRepository:
    def __init__(self) -> None:
        self._records: dict[str, ReviewProjection] = {}

    def save(self, projection: ReviewProjection) -> None:
        self._records[projection.review_id] = projection

    def get(self, review_id: str) -> ReviewProjection | None:
        return self._records.get(review_id)

    def list_pending(self) -> list[ReviewProjection]:
        return [
            record for record in self._records.values() if record.status in {"pending", "in_review"}
        ]


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list(self) -> list[AuditEvent]:
        return list(self._events)


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], IdempotencyRecord] = {}

    def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        return self._records.get((scope, key))

    def put(self, scope: str, key: str, record: IdempotencyRecord) -> None:
        existing = self._records.get((scope, key))
        if existing is None or existing.fingerprint == record.fingerprint:
            self._records[(scope, key)] = replace(record)

    def claim(self, scope: str, key: str, request_fingerprint: str) -> bool:
        """Atomically reserve a key before a potentially slow workflow."""

        identity = (scope, key)
        if identity in self._records:
            return False
        self._records[identity] = IdempotencyRecord(
            fingerprint=request_fingerprint,
            status_code=0,
            body={},
            created_at=time.time(),
        )
        return True


class InMemoryUnitOfWork:
    def __enter__(self) -> InMemoryUnitOfWork:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None
