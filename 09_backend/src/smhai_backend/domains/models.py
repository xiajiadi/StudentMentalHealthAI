"""Backend-owned records and actor types.

These records are persistence-neutral. A later Database module can implement
the ports without changing the orchestration contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class BackendRole(StrEnum):
    STUDENT = "STUDENT"
    TEACHER = "TEACHER"
    REVIEWER = "REVIEWER"
    PARENT = "PARENT"
    ADMIN = "ADMIN"


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    username: str
    role: BackendRole
    subject_id: str | None
    accessible_subject_ids: frozenset[str] = frozenset()


@dataclass(slots=True)
class SyntheticUser:
    user_id: str
    username: str
    role: BackendRole
    subject_id: str | None
    password_hash: str = field(repr=False)
    accessible_subject_ids: frozenset[str] = frozenset()

    def actor(self) -> Actor:
        return Actor(
            user_id=self.user_id,
            username=self.username,
            role=self.role,
            subject_id=self.subject_id,
            accessible_subject_ids=self.accessible_subject_ids,
        )


@dataclass(slots=True)
class SessionRecord:
    session_id: str = field(repr=False)
    user_id: str
    csrf_token: str = field(repr=False)
    created_at: float
    expires_at: float
    last_seen_at: float


@dataclass(slots=True)
class AssessmentRecord:
    assessment_id: str
    subject_id: str
    assessment: dict[str, Any]
    responses: dict[str, Any] = field(default_factory=dict, repr=False)
    selected_item_id: str | None = None
    current_item: dict[str, Any] | None = None
    current_index: int = 0
    answered_count: int = 0
    administered_count: int = 0
    can_complete: bool = False
    max_items: int | None = None
    cat_provider_version: str | None = None
    cat_item_bank_version: str | None = None
    cat_config_version: str | None = None


@dataclass(slots=True)
class ReportRecord:
    report_id: str
    assessment_id: str
    subject_id: str
    generation_id: str
    status: str
    generation: dict[str, Any]
    review_id: str | None = None
    review_status: str = "not_required"
    safety_action: str = "PROCEED"


@dataclass(slots=True)
class ReviewProjection:
    review_id: str
    report_id: str
    assessment_id: str
    subject_id: str
    generation_id: str
    status: str
    reason_codes: list[str]
    safety_action: str
    safety_review_case_id: str | None = None
    created_at: str = field(
        default_factory=lambda: (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    )
    updated_at: str = field(
        default_factory=lambda: (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event: str
    actor_id: str | None
    request_id: str
    trace_id: str
    occurred_at: str
    outcome: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class IdempotencyRecord:
    fingerprint: str
    status_code: int
    body: dict[str, Any]
    created_at: float
