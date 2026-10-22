from __future__ import annotations

import pytest

from llm_runtime.api.app import _load_internal_auth_token, create_app
from llm_runtime.cli import build_service


def test_deepseek_mode_uses_one_explicit_remote_model_without_fallback(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SMHAI_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    key_file = tmp_path / "deepseek-api-key"
    key_file.write_text("sk-" + "b" * 32, encoding="ascii")
    monkeypatch.delenv("SMHAI_LLM_RUNTIME_PROFILE", raising=False)

    service = build_service()
    try:
        model = service.registry.resolve("deepseek-flash-education-support")
        assert tuple(service.providers) == ("deepseek",)
        assert service.default_model_id == "deepseek-flash-education-support"
        assert service.registry.cloud_fallback is False
        assert service.registry.fallback_chain(model.logical_model_id) == ()
        assert service.max_attempts == 1
        assert service.backoff_seconds == ()
    finally:
        service.shutdown()


def test_deepseek_mode_requires_the_systemd_credential_file(monkeypatch):
    monkeypatch.setenv("SMHAI_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

    try:
        build_service()
    except ValueError as exc:
        assert "credential directory is required" in str(exc)
    else:
        raise AssertionError("missing systemd credential path must fail closed")


def test_unknown_provider_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("SMHAI_LLM_PROVIDER", "legacy_demo")

    try:
        build_service()
    except ValueError as exc:
        assert "unknown LLM provider mode" in str(exc)
    else:
        raise AssertionError("unknown provider mode must not select a fallback")


def test_deepseek_internal_auth_credential_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SMHAI_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("SMHAI_LLM_RUNTIME_AUTH_FILE", raising=False)
    with pytest.raises(ValueError, match="credential path is required"):
        _load_internal_auth_token()

    malformed = tmp_path / "auth"
    malformed.write_text("too-short", encoding="ascii")
    monkeypatch.setenv("SMHAI_LLM_RUNTIME_AUTH_FILE", str(malformed))
    with pytest.raises(ValueError, match="credential is malformed"):
        _load_internal_auth_token()

    valid = tmp_path / "valid-auth"
    valid.write_text("x" * 48 + "\n", encoding="ascii")
    monkeypatch.setenv("SMHAI_LLM_RUNTIME_AUTH_FILE", str(valid))
    assert _load_internal_auth_token() == "x" * 48


def test_create_app_rejects_empty_internal_auth_token():
    with pytest.raises(ValueError, match="credential is malformed"):
        create_app(internal_auth_token="")
