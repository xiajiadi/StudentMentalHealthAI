"""Explicit errors raised by the CAT domain and integration boundaries."""


class CATError(Exception):
    """Base class for expected CAT failures."""


class ValidationError(CATError):
    """Raised when an input object is structurally or semantically invalid."""


class ItemBankValidationError(ValidationError):
    """Raised when an item bank cannot be used by the runtime."""


class ConfigValidationError(ValidationError):
    """Raised when a CAT configuration is invalid."""


class SessionStateError(CATError):
    """Raised when a session operation violates its state machine."""


class SessionStoppedError(SessionStateError):
    """Raised when an operation attempts to continue a stopped session."""


class ResponseValidationError(ValidationError):
    """Raised when a response is not a valid category for the selected item."""


class ProviderError(CATError):
    """Raised when a provider cannot perform a requested operation."""


class ProviderUnavailableError(ProviderError):
    """Raised when a configured provider dependency cannot be imported."""


class ContractValidationError(ValidationError):
    """Raised when a mapped result fails a frozen public Contract."""


class SimulationError(CATError):
    """Raised when a simulation cannot produce a valid batch result."""

