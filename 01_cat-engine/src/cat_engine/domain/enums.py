"""Stable domain enums used in traces and result summaries."""

from enum import StrEnum


class ItemBankStatus(StrEnum):
    """Lifecycle state of a versioned item bank."""

    DRAFT = "draft"
    CALIBRATING = "calibrating"
    VALIDATED = "validated"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class SessionStatus(StrEnum):
    """CAT session lifecycle, including reserved exceptional states."""

    CREATED = "CREATED"
    INITIALIZED = "INITIALIZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class ResponseStatus(StrEnum):
    """Distinguishes an answer from every supported missing-response state."""

    ANSWERED = "answered"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    INVALID = "invalid"
    NOT_PRESENTED = "not_presented"


class StopReason(StrEnum):
    """Why a CAT session ended or was stopped."""

    SE_THRESHOLD_REACHED = "SE_THRESHOLD_REACHED"
    MAX_ITEMS_REACHED = "MAX_ITEMS_REACHED"
    ITEM_BANK_EXHAUSTED = "ITEM_BANK_EXHAUSTED"
    MANUAL_TERMINATION = "MANUAL_TERMINATION"
    ERROR = "ERROR"
    NOT_STOPPED = "NOT_STOPPED"

