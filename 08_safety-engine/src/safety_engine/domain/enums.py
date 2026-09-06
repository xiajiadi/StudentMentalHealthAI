"""Enumerations deliberately kept independent from project-wide public contracts."""

from enum import StrEnum


class Action(StrEnum):
    """Engineering control actions; these are not clinical risk labels."""

    PROCEED = "PROCEED"
    PROCEED_WITH_BOUNDARY = "PROCEED_WITH_BOUNDARY"
    BLOCK = "BLOCK"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CRISIS_ROUTE = "CRISIS_ROUTE"


class ActorRole(StrEnum):
    STUDENT = "STUDENT"
    TEACHER = "TEACHER"
    PARENT = "PARENT"
    REVIEWER = "REVIEWER"
    SYSTEM = "SYSTEM"


class DisclosurePolicy(StrEnum):
    FULL = "FULL"
    SUMMARY = "SUMMARY"
    REDACTED = "REDACTED"
    HIDDEN = "HIDDEN"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class SeverityHint(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SignalSource(StrEnum):
    ASSESSMENT = "ASSESSMENT"
    PRESIDIO = "PRESIDIO"
    NEMO = "NEMO"
    QWEN3GUARD = "QWEN3GUARD"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    SYSTEM_HEALTH = "SYSTEM_HEALTH"


class SignalType(StrEnum):
    ASSESSMENT = "ASSESSMENT"
    CONTENT = "CONTENT"
    PRIVACY = "PRIVACY"
    INJECTION = "INJECTION"
    CRISIS = "CRISIS"
    CLINICAL_BOUNDARY = "CLINICAL_BOUNDARY"
    RETRIEVAL = "RETRIEVAL"
    DISCLOSURE = "DISCLOSURE"
    COMPONENT_HEALTH = "COMPONENT_HEALTH"
