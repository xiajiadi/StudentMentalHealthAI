"""Database persistence foundation for StudentMentalHealthAI."""

from .base import Base
from .config import DatabaseSettings, create_engine, create_session_factory
from .crypto import (
    DevLocalKeyProvider,
    EncryptedPayload,
    FernetDataProtectionProvider,
    KeyProvider,
    MappingKeyProvider,
    WindowsDpapiKeyProvider,
)
from .unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "Base",
    "DatabaseSettings",
    "DevLocalKeyProvider",
    "EncryptedPayload",
    "FernetDataProtectionProvider",
    "KeyProvider",
    "MappingKeyProvider",
    "SqlAlchemyUnitOfWork",
    "WindowsDpapiKeyProvider",
    "create_engine",
    "create_session_factory",
]
