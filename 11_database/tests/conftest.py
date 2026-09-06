from __future__ import annotations

import os
import re

import pytest
from database_layer.config import DatabaseSettings, create_engine, create_session_factory
from database_layer.crypto import FernetDataProtectionProvider, MappingKeyProvider
from sqlalchemy import make_url, text


def configured_mysql_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not configured; real MySQL tests are not run")
    parsed = make_url(url)
    if parsed.drivername != "mysql+aiomysql":
        pytest.fail("real MySQL tests require mysql+aiomysql")
    database = parsed.database or ""
    if not re.search(r"(?i)(test|round1|synthetic|restore)", database):
        pytest.fail("destructive/integration tests require a dedicated test/round1 database name")
    return url


@pytest.fixture
async def mysql_engine():
    url = configured_mysql_url()
    settings = DatabaseSettings(url=url)
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on local service state
        await engine.dispose()
        pytest.skip(f"configured MySQL is unavailable: {type(exc).__name__}")
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(mysql_engine):
    return create_session_factory(mysql_engine)


@pytest.fixture
def protection():
    from cryptography.fernet import Fernet

    return FernetDataProtectionProvider(
        MappingKeyProvider({"test-v1": Fernet.generate_key()}, active_version="test-v1")
    )
