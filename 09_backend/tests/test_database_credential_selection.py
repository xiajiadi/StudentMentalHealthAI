"""Provider selection only: no database connection or service startup."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from smhai_backend.adapters import database as adapter


class Unavailable(RuntimeError):
    pass


@pytest.fixture
def providers(monkeypatch):
    calls = []

    class Windows:
        @classmethod
        def from_env(cls, repository_root):
            calls.append(("windows", repository_root))
            return cls()

    class Linux:
        @classmethod
        def from_env(cls):
            calls.append(("linux", None))
            return cls()

    class Dev:
        @classmethod
        def from_env(cls, repository_root):
            pytest.fail("school_tenant attempted development fallback")

    class Protection:
        def __init__(self, key_provider):
            self.key_provider = key_provider

    layer = ModuleType("database_layer")
    layer.WindowsDpapiKeyProvider = Windows
    layer.LinuxSystemdCredentialKeyProvider = Linux
    layer.DevLocalKeyProvider = Dev
    layer.FernetDataProtectionProvider = Protection
    errors = ModuleType("database_layer.errors")
    errors.EncryptionKeyUnavailable = Unavailable
    monkeypatch.setitem(sys.modules, "database_layer", layer)
    monkeypatch.setitem(sys.modules, "database_layer.errors", errors)
    return SimpleNamespace(calls=calls, linux=Linux, windows=Windows)


def platform(monkeypatch, name, sys_platform):
    # Avoid mutating os.name globally: pathlib and pytest still use the host OS.
    monkeypatch.setattr(adapter, "os", SimpleNamespace(name=name))
    monkeypatch.setattr(adapter, "sys", SimpleNamespace(platform=sys_platform))


@pytest.mark.parametrize(
    ("name", "sys_platform", "expected"),
    [
        ("nt", "win32", "windows"),
        ("posix", "linux", "linux"),
    ],
)
def test_school_tenant_platform_selection(providers, monkeypatch, name, sys_platform, expected):
    platform(monkeypatch, name, sys_platform)
    root = Path("synthetic-repository")
    protection = adapter._create_data_protection_provider("school_tenant", root)
    assert providers.calls == [(expected, root if expected == "windows" else None)]
    assert isinstance(
        protection.key_provider, providers.windows if expected == "windows" else providers.linux
    )


@pytest.mark.parametrize(
    ("name", "sys_platform"),
    [
        ("posix", "darwin"),
        ("posix", "freebsd14"),
        ("java", "java"),
    ],
)
def test_other_operating_systems_fail_closed(providers, monkeypatch, name, sys_platform):
    platform(monkeypatch, name, sys_platform)
    with pytest.raises(Unavailable, match="platform is unsupported"):
        adapter._create_data_protection_provider("school_tenant", Path("synthetic-repository"))
    assert providers.calls == []


@pytest.mark.parametrize(
    ("name", "sys_platform", "provider_name"),
    [
        ("nt", "win32", "windows"),
        ("posix", "linux", "linux"),
    ],
)
def test_provider_failure_propagates_without_fallback(
    providers,
    monkeypatch,
    name,
    sys_platform,
    provider_name,
):
    platform(monkeypatch, name, sys_platform)

    def unavailable(*args, **kwargs):
        raise Unavailable("synthetic credential unavailable")

    monkeypatch.setattr(getattr(providers, provider_name), "from_env", unavailable)
    with pytest.raises(Unavailable, match="synthetic credential unavailable"):
        adapter._create_data_protection_provider("school_tenant", Path("synthetic-repository"))
    assert providers.calls == []


@pytest.mark.parametrize(("name", "sys_platform"), [("nt", "win32"), ("posix", "linux")])
def test_actual_missing_environment_fails_before_any_database_access(
    monkeypatch,
    name,
    sys_platform,
):
    layer = pytest.importorskip("database_layer")
    from database_layer.errors import EncryptionKeyUnavailable

    platform(monkeypatch, name, sys_platform)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.delenv("DATABASE_KEY_FILE", raising=False)

    def no_dev(*args, **kwargs):
        pytest.fail("school_tenant attempted development fallback")

    monkeypatch.setattr(layer.DevLocalKeyProvider, "from_env", no_dev)
    with pytest.raises(EncryptionKeyUnavailable) as caught:
        adapter._create_data_protection_provider("school_tenant", Path("synthetic-repository"))
    assert caught.value.__cause__ is None
