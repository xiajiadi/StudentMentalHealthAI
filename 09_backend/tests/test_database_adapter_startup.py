from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

import smhai_backend.adapters.database as database_adapter
from smhai_backend.adapters.database import (
    REQUIRED_DATABASE_REVISION,
    REQUIRED_SCHOOL_TENANT_DATABASE_REVISION,
    MySqlBackendAdapter,
    _create_data_protection_provider,
)


class _ScalarResult:
    def __init__(self, rows: list[str]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[str]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[str] | Exception) -> None:
        self.rows = rows
        self.queries: list[str] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def exec_driver_sql(self, statement: str) -> _ScalarResult:
        self.queries.append(statement)
        if isinstance(self.rows, Exception):
            raise self.rows
        return _ScalarResult(self.rows)


class _Engine:
    def __init__(self, rows: list[str] | Exception) -> None:
        self.connection = _Connection(rows)
        self.dispose_count = 0

    def connect(self) -> _Connection:
        return self.connection

    async def dispose(self) -> None:
        self.dispose_count += 1


class _Query:
    def where(self, *args: object) -> _Query:
        return self


class _Rows:
    def all(self) -> list[object]:
        return []


class _FixtureSession:
    def __init__(self) -> None:
        self.query_count = 0
        self.flush_count = 0

    async def scalars(self, _statement: object) -> _Rows:
        self.query_count += 1
        return _Rows()

    async def flush(self) -> None:
        self.flush_count += 1


class _UnitOfWork:
    def __init__(self, session: _FixtureSession) -> None:
        self.session = session

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _LegacyIdentityEnvironment:
    def __init__(self) -> None:
        self.values = {
            "SMHAI_M0_ADMIN_USERNAME": "SYNTHETIC_ADMIN_USERNAME_SENTINEL",
            "SMHAI_M0_ADMIN_PASSWORD": "SYNTHETIC_ADMIN_PASSWORD_SENTINEL",
            "SMHAI_M0_SPECIALIST_USERNAME": "SYNTHETIC_SPECIALIST_USERNAME_SENTINEL",
            "SMHAI_M0_SPECIALIST_PASSWORD": "SYNTHETIC_SPECIALIST_PASSWORD_SENTINEL",
        }
        self.reads: list[str] = []

    def get(self, key: str, default: object = None) -> object:
        self.reads.append(key)
        if key in self.values:
            raise AssertionError("school_tenant read a legacy identity setting")
        return default


def _adapter(revision_rows: list[str] | Exception, profile: str) -> Any:
    adapter: Any = object.__new__(MySqlBackendAdapter)
    adapter.engine = _Engine(revision_rows)
    adapter.identity_profile = profile
    adapter._started = False
    return adapter


def _required_revision(profile: str) -> str:
    return (
        REQUIRED_SCHOOL_TENANT_DATABASE_REVISION
        if profile == "school_tenant"
        else REQUIRED_DATABASE_REVISION
    )


@pytest.mark.parametrize(
    "old_revision", ["20261012_0008", "20261013_0009", "20261013_0010"]
)
async def test_school_tenant_startup_requires_post_assessment_outbox_revision(old_revision):
    assert REQUIRED_SCHOOL_TENANT_DATABASE_REVISION == "20261014_0011"
    adapter = _adapter([old_revision], "school_tenant")

    async def no_bootstrap():
        pytest.fail("old schema must not bootstrap")

    adapter._ensure_synthetic_fixtures = no_bootstrap

    with pytest.raises(RuntimeError, match="20261014_0011"):
        await adapter.start()


def _database_layer_stub(**attributes: object) -> ModuleType:
    module = ModuleType("database_layer")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


@pytest.mark.parametrize("profile", ["legacy_demo", "school_tenant"])
async def test_start_requires_exact_schema_revision_before_fixture_bootstrap(profile: str):
    adapter = _adapter([_required_revision(profile)], profile)
    bootstraps: list[bool] = []

    async def ensure_fixtures() -> None:
        bootstraps.append(True)

    adapter._ensure_synthetic_fixtures = ensure_fixtures
    await adapter.start()

    assert adapter.engine.connection.queries == [
        "SELECT version_num FROM database_alembic_version"
    ]
    assert bootstraps == [True]
    assert adapter._started is True


@pytest.mark.parametrize(
    "rows",
    [
        ["20260906_0002"],
        [],
        RuntimeError("DB_ERROR_SENTINEL"),
    ],
)
@pytest.mark.parametrize("profile", ["legacy_demo", "school_tenant"])
async def test_start_rejects_missing_or_mismatched_revision_before_bootstrap(rows, profile: str):
    adapter = _adapter(rows, profile)
    bootstraps: list[bool] = []

    async def ensure_fixtures() -> None:
        bootstraps.append(True)

    adapter._ensure_synthetic_fixtures = ensure_fixtures
    with pytest.raises(RuntimeError) as caught:
        await adapter.start()

    message = str(caught.value)
    assert _required_revision(profile) in message
    assert "does not perform migrations" in message
    assert "DB_ERROR_SENTINEL" not in message
    assert bootstraps == []
    assert adapter._started is False
    assert adapter.engine.dispose_count == 1


@pytest.mark.parametrize(
    ("profile", "other_profile_revision"),
    [
        ("school_tenant", REQUIRED_DATABASE_REVISION),
        ("legacy_demo", REQUIRED_SCHOOL_TENANT_DATABASE_REVISION),
    ],
)
async def test_start_rejects_the_other_profile_revision_before_bootstrap(
    profile: str, other_profile_revision: str
):
    adapter = _adapter([other_profile_revision], profile)
    bootstraps: list[bool] = []

    async def ensure_fixtures() -> None:
        bootstraps.append(True)

    adapter._ensure_synthetic_fixtures = ensure_fixtures
    with pytest.raises(RuntimeError) as caught:
        await adapter.start()

    assert _required_revision(profile) in str(caught.value)
    assert bootstraps == []
    assert adapter._started is False
    assert adapter.engine.dispose_count == 1


async def test_school_tenant_ignores_legacy_identity_environment_and_creates_no_identity(
    monkeypatch,
):
    tenant: Any = object.__new__(MySqlBackendAdapter)
    tenant.identity_profile = "school_tenant"
    optional_environment = _LegacyIdentityEnvironment()
    monkeypatch.setattr(
        database_adapter,
        "os",
        cast(Any, SimpleNamespace(environ=optional_environment)),
    )
    assert tenant._optional_identity_specs() == ()

    legacy: Any = object.__new__(MySqlBackendAdapter)
    legacy.identity_profile = "legacy_demo"
    assert legacy._optional_identity_specs() == (
        ("admin", "SMHAI_M0_ADMIN"),
        ("psychological_specialist", "SMHAI_M0_SPECIALIST"),
    )

    session = _FixtureSession()
    tenant._db_models = SimpleNamespace(Role=SimpleNamespace(status="ACTIVE"))
    tenant._db_enums = SimpleNamespace()
    tenant._select = lambda _model: _Query()
    tenant._uow = lambda: _UnitOfWork(session)

    async def seed_roles(_session: _FixtureSession) -> None:
        return None

    tenant._seed_reference_roles = seed_roles
    await tenant._ensure_synthetic_fixtures()
    assert optional_environment.reads == []
    assert session.query_count == 1
    assert session.flush_count == 1


def test_school_tenant_selects_explicit_dpapi_provider_without_legacy_fallback(monkeypatch):
    dpapi_roots: list[Path] = []
    legacy_calls: list[Path] = []

    class _DpapiProvider:
        def __init__(self) -> None:
            pass

        @classmethod
        def from_env(cls, repository_root: Path) -> object:
            dpapi_roots.append(repository_root)
            return cls()

    class _LegacyProvider:
        @classmethod
        def from_env(cls, repository_root: Path) -> object:
            legacy_calls.append(repository_root)
            return object()

    class _FernetProtection:
        def __init__(self, key_provider: object) -> None:
            self.key_provider = key_provider

    monkeypatch.setitem(
        sys.modules,
        "database_layer",
        _database_layer_stub(
            WindowsDpapiKeyProvider=_DpapiProvider,
            DevLocalKeyProvider=_LegacyProvider,
            FernetDataProtectionProvider=_FernetProtection,
        ),
    )
    root = Path("SYNTHETIC_REPOSITORY_ROOT_SENTINEL")
    tenant_provider = _create_data_protection_provider("school_tenant", root)

    assert isinstance(tenant_provider, _FernetProtection)
    assert isinstance(tenant_provider.key_provider, _DpapiProvider)
    assert dpapi_roots == [root]
    assert legacy_calls == []


def test_legacy_demo_keeps_dev_local_provider_selection(monkeypatch):
    legacy_calls: list[Path] = []

    class _LegacyProvider:
        @classmethod
        def from_env(cls, repository_root: Path) -> object:
            legacy_calls.append(repository_root)
            return object()

    class _DpapiProvider:
        def __init__(self, _path: Path) -> None:
            raise AssertionError("legacy_demo selected the DPAPI provider")

    class _FernetProtection:
        def __init__(self, key_provider: object) -> None:
            self.key_provider = key_provider

    monkeypatch.setitem(
        sys.modules,
        "database_layer",
        _database_layer_stub(
            DevLocalKeyProvider=_LegacyProvider,
            WindowsDpapiKeyProvider=_DpapiProvider,
            FernetDataProtectionProvider=_FernetProtection,
        ),
    )
    monkeypatch.setattr(database_adapter.os, "environ", {})
    root = Path("SYNTHETIC_REPOSITORY_ROOT_SENTINEL")

    provider = _create_data_protection_provider("legacy_demo", root)

    assert isinstance(provider, _FernetProtection)
    assert legacy_calls == [root]


def test_unknown_profile_does_not_fall_back_to_legacy_provider():
    with pytest.raises(RuntimeError, match="unsupported database identity profile"):
        _create_data_protection_provider(
            "SYNTHETIC_UNKNOWN_PROFILE_SENTINEL",
            Path("SYNTHETIC_REPOSITORY_ROOT_SENTINEL"),
        )
