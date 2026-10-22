"""Configuration and async engine construction.

The URL is environment-driven and is never logged verbatim.  SQLite is
intentionally rejected by the production/integration configuration path.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from sqlalchemy import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .errors import ConfigurationError
from .systemd_auth import load_systemd_school_database_credential


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    url: str = field(repr=False)
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout: int = 30
    pool_recycle: int = 1800
    pool_pre_ping: bool = True
    echo: bool = False

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        credential_name = os.environ.get("DATABASE_AUTH_CREDENTIAL")
        if credential_name:
            if os.name != "posix" or sys.platform != "linux":
                raise ConfigurationError("Systemd database credentials require Linux")
            if any(
                name.startswith("DB_")
                or (
                    name.startswith("DATABASE_")
                    and name not in {"DATABASE_AUTH_CREDENTIAL", "DATABASE_KEY_FILE"}
                )
                for name in os.environ
            ):
                raise ConfigurationError("Ambiguous school database credential configuration")
            credential = load_systemd_school_database_credential(credential_name)
            url = URL.create(
                "mysql+aiomysql",
                username=credential.username,
                password=credential.password,
                host=credential.host,
                port=credential.port,
                database=credential.database,
                query={"charset": "utf8mb4"},
            ).render_as_string(hide_password=False)
        else:
            url = os.environ.get("DATABASE_URL")
        if not credential_name and not url:
            user = os.environ.get("DB_USER")
            password = os.environ.get("DB_PASSWORD")
            host = os.environ.get("DB_HOST", "127.0.0.1")
            port = int(os.environ.get("DB_PORT", "3306"))
            database = os.environ.get("DB_NAME")
            if not user or password is None or not database:
                raise ConfigurationError(
                    "DATABASE_URL or DB_USER/DB_PASSWORD/DB_NAME must be configured"
                )
            url = URL.create(
                "mysql+aiomysql",
                username=user,
                password=password,
                host=host,
                port=port,
                database=database,
                query={"charset": "utf8mb4"},
            ).render_as_string(hide_password=False)

        if not url:
            raise ConfigurationError("Database URL is unavailable")
        parsed = make_url(url)
        if parsed.drivername.startswith("sqlite"):
            raise ConfigurationError("SQLite is not an acceptance database")
        if parsed.drivername not in {"mysql+aiomysql", "mysql+asyncmy"}:
            raise ConfigurationError("Database URL must use an async MySQL driver")
        return cls(
            url=url,
            pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "5")),
            pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.environ.get("DB_POOL_RECYCLE", "1800")),
            pool_pre_ping=os.environ.get("DB_POOL_PRE_PING", "1") not in {"0", "false", "False"},
            echo=os.environ.get("DB_ECHO", "0") in {"1", "true", "True"},
        )

    @property
    def sanitized_url(self) -> str:
        """Render a URL with the password hidden for evidence."""

        return make_url(self.url).render_as_string(hide_password=True)


def create_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    """Create an async MySQL engine with reliability-safe pool defaults."""

    resolved = settings or DatabaseSettings.from_env()
    parsed = make_url(resolved.url)
    connect_args: dict[str, str] = {}
    if parsed.drivername == "mysql+aiomysql":
        # DATETIME(6) values are application-owned UTC-naive values.  Pin the
        # MySQL session timezone so server-side timestamp expressions and
        # connection-level observability use the same UTC baseline.
        connect_args["init_command"] = "SET time_zone = '+00:00'"
    return create_async_engine(
        resolved.url,
        echo=resolved.echo,
        pool_pre_ping=resolved.pool_pre_ping,
        pool_recycle=resolved.pool_recycle,
        pool_size=resolved.pool_size,
        max_overflow=resolved.max_overflow,
        pool_timeout=resolved.pool_timeout,
        connect_args=connect_args,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create a factory; callers create one AsyncSession per use case."""

    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
