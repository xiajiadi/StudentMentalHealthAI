"""Persistence-layer errors that do not expose raw SQL or credentials."""


class PersistenceError(Exception):
    """Base class for safe persistence failures."""


class ConfigurationError(PersistenceError):
    """The database configuration is missing or unsafe."""


class UniqueConflict(PersistenceError):
    """A unique business key already exists."""


class ForeignKeyConflict(PersistenceError):
    """A referenced record does not exist or cannot be removed."""


class NotFound(PersistenceError):
    """The requested resource was not found."""


class OptimisticConcurrencyConflict(PersistenceError):
    """The record changed after the caller read it."""


class DatabaseUnavailable(PersistenceError):
    """The database could not be reached."""


class EncryptionKeyUnavailable(PersistenceError):
    """An encryption key is missing or cannot be read."""


class EncryptionFailure(PersistenceError):
    """Ciphertext could not be authenticated or decoded."""
