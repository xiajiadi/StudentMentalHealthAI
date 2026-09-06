"""Application-level state vocabularies.

These are Python enums backed by VARCHAR columns and explicit database CHECK
constraints.  MySQL native ENUM is intentionally not used.
"""

from enum import StrEnum


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class GrantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    REVOKED = "REVOKED"


class RelationshipType(StrEnum):
    SELF = "SELF"
    TEACHER_OF = "TEACHER_OF"
    GUARDIAN_OF = "GUARDIAN_OF"
    REVIEW_ASSIGNMENT = "REVIEW_ASSIGNMENT"


class ConsentStatus(StrEnum):
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SubjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    ERASED = "ERASED"


class DataOrigin(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    PRODUCTION_PENDING = "PRODUCTION_PENDING"


class AssessmentStatus(StrEnum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"
    INVALID = "INVALID"


class SupportStatus(StrEnum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class MessageKind(StrEnum):
    USER_INPUT = "USER_INPUT"
    APPROVED_OUTPUT = "APPROVED_OUTPUT"


class SupportRunStatus(StrEnum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class SafetyAction(StrEnum):
    PROCEED = "PROCEED"
    PROCEED_WITH_BOUNDARY = "PROCEED_WITH_BOUNDARY"
    BLOCK = "BLOCK"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CRISIS_ROUTE = "CRISIS_ROUTE"


class ReviewStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class ReviewPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ReviewEventType(StrEnum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    OPENED = "OPENED"
    DECISION_RECORDED = "DECISION_RECORDED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class IdempotencyState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
