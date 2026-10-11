from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

import smhai_backend.adapters.database as database_adapter
import smhai_backend.container as backend_container
from smhai_backend.adapters.database import (
    MySqlBackendAdapter,
    _csrf_secret_for_profile,
)
from smhai_backend.core.config import BackendSettings

_SYNTHETIC_CSRF_SECRET = "aB012345" * 8


def _empty_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})


def _settings(**values: Any) -> BackendSettings:
    settings_type: Any = BackendSettings
    return settings_type(_env_file=None, **values)


def test_school_profile_loads_exact_hex_secret_from_explicit_setting(monkeypatch):
    _empty_environment(monkeypatch)
    settings = _settings(
        identity_profile="school_tenant",
        school_csrf_secret=_SYNTHETIC_CSRF_SECRET,
    )

    assert isinstance(settings.school_csrf_secret, SecretStr)
    assert settings.school_csrf_secret.get_secret_value() == _SYNTHETIC_CSRF_SECRET
    assert _SYNTHETIC_CSRF_SECRET not in repr(settings)
    assert _SYNTHETIC_CSRF_SECRET not in settings.model_dump_json()


def test_school_profile_maps_approved_environment_name(monkeypatch):
    monkeypatch.setattr(
        os,
        "environ",
        {"SMHAI_SCHOOL_CSRF_SECRET": _SYNTHETIC_CSRF_SECRET},
    )
    settings = _settings(identity_profile="school_tenant")
    assert settings.school_csrf_secret is not None
    assert settings.school_csrf_secret.get_secret_value() == _SYNTHETIC_CSRF_SECRET


def test_school_profile_rejects_missing_secret_without_sensitive_error(monkeypatch):
    _empty_environment(monkeypatch)
    with pytest.raises(ValueError) as caught:
        _settings(identity_profile="school_tenant")
    assert "SMHAI_SCHOOL_CSRF_SECRET" in str(caught.value)
    assert _SYNTHETIC_CSRF_SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "value",
    ["SYNTHETIC_CSRF_SENTINEL_NOT_HEX", "ab"],
    ids=["malformed", "weak-length"],
)
def test_school_profile_rejects_invalid_secret_and_redacts_value(
    monkeypatch, value: str
):
    _empty_environment(monkeypatch)
    with pytest.raises(ValueError) as caught:
        _settings(
            identity_profile="school_tenant",
            school_csrf_secret=value,
        )
    assert "64 hexadecimal" in str(caught.value)
    assert value not in str(caught.value)
    assert value not in repr(caught.value)


def test_school_profile_redacts_invalid_process_environment_value(monkeypatch):
    sentinel = "SYNTHETIC_ENV_CSRF_SENTINEL"
    monkeypatch.setattr(os, "environ", {"SMHAI_SCHOOL_CSRF_SECRET": sentinel})
    with pytest.raises(ValueError) as caught:
        _settings(identity_profile="school_tenant")
    assert "64 hexadecimal" in str(caught.value)
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)


def test_valid_secret_does_not_hide_unrelated_configuration_error(monkeypatch):
    _empty_environment(monkeypatch)
    with pytest.raises(ValidationError) as caught:
        _settings(
            identity_profile="school_tenant",
            school_csrf_secret=_SYNTHETIC_CSRF_SECRET,
            allowed_origins=["*"],
        )

    assert "wildcard CORS origins are not allowed" in str(caught.value)
    assert _SYNTHETIC_CSRF_SECRET not in str(caught.value)
    assert _SYNTHETIC_CSRF_SECRET not in repr(caught.value)


def test_legacy_profile_needs_no_school_secret_and_keeps_previous_csrf_key(monkeypatch):
    monkeypatch.setattr(os, "environ", {"SMHAI_SCHOOL_CSRF_SECRET": "invalid-sentinel"})
    settings = _settings(identity_profile="legacy_demo")
    assert settings.school_csrf_secret is None
    assert _csrf_secret_for_profile("legacy_demo", None) == (
        b"smhai-round1-synthetic-csrf-secret"
    )


def test_school_adapter_csrf_hmac_uses_decoded_configured_secret(monkeypatch):
    _empty_environment(monkeypatch)
    adapter: Any = object.__new__(MySqlBackendAdapter)
    adapter._csrf_secret = _csrf_secret_for_profile(
        "school_tenant", _SYNTHETIC_CSRF_SECRET
    )

    observed = adapter._csrf_token("SYNTHETIC_SESSION_SENTINEL")
    expected = hmac.new(
        bytes.fromhex(_SYNTHETIC_CSRF_SECRET),
        b"SYNTHETIC_SESSION_SENTINEL",
        hashlib.sha256,
    ).hexdigest()
    assert observed == expected


def test_adapter_requires_secret_before_database_setup():
    with pytest.raises(ValueError, match="64 hexadecimal"):
        MySqlBackendAdapter(identity_profile="school_tenant")


def test_container_passes_school_secret_to_mysql_adapter_in_memory(monkeypatch):
    _empty_environment(monkeypatch)
    captured: dict[str, object] = {}

    class _Persistence:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(database_adapter, "MySqlBackendAdapter", _Persistence)
    settings = _settings(
        persistence_mode="mysql",
        identity_profile="school_tenant",
        school_csrf_secret=_SYNTHETIC_CSRF_SECRET,
    )

    container = backend_container.build_container(settings)

    assert isinstance(container.persistence, _Persistence)
    assert captured["identity_profile"] == "school_tenant"
    assert captured["school_csrf_secret"] == _SYNTHETIC_CSRF_SECRET
    assert "DATABASE_URL" not in os.environ
