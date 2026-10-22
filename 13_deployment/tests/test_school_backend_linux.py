"""Offline checks for the fixed school-backend configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "09_backend" / "src"))

import school_backend_linux
import verify_school_http_linux
from smhai_backend.domains.models import BackendRole


def test_school_backend_builds_valid_mysql_settings_for_all_http_clients(monkeypatch):
    monkeypatch.delenv("PSYNOVA_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("PSYNOVA_LLM_MODEL_ID", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

    settings = school_backend_linux._build_school_backend_settings("a" * 64)

    assert settings.identity_profile == "school_tenant"
    assert settings.persistence_mode == "mysql"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8088
    assert settings.docs_enabled is False
    assert settings.llm.mode == "http"
    assert settings.llm.base_url == "http://127.0.0.1:8160"
    assert settings.llm.logical_model_id == "qwen2.5-0.5b-engineering"
    assert settings.llm.context_length is None
    assert settings.cat.base_url == "http://127.0.0.1:8180"
    assert settings.rag.base_url == "http://127.0.0.1:8170"
    assert settings.safety.base_url == "http://127.0.0.1:8190"
    assert settings.allowed_origins == ["http://127.0.0.1:4178"]
    assert settings.auth.cookie_name == "psynova_school_session"
    assert settings.auth.secure_cookie is False


def test_public_https_origin_enables_secure_host_cookie_and_host_validation(monkeypatch):
    monkeypatch.setenv("PSYNOVA_PUBLIC_ORIGIN", "https://PsyNova.top/")
    monkeypatch.delenv("PSYNOVA_LLM_MODEL_ID", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

    settings = school_backend_linux._build_school_backend_settings("a" * 64)

    assert settings.allowed_origins == ["https://psynova.top"]
    assert settings.allowed_hosts == ["psynova.top", "127.0.0.1", "localhost"]
    assert settings.auth.cookie_name == "__Host-smhai_session"
    assert settings.auth.secure_cookie is True
    assert settings.auth.same_site == "lax"


def test_school_backend_can_pin_the_registered_deepseek_demo_model(monkeypatch, tmp_path):
    monkeypatch.delenv("PSYNOVA_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("PSYNOVA_LLM_MODEL_ID", "deepseek-flash-education-support")
    (tmp_path / "llm-runtime-auth.json").write_text("x" * 48, encoding="ascii")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))

    settings = school_backend_linux._build_school_backend_settings("a" * 64)

    assert settings.llm.logical_model_id == "deepseek-flash-education-support"
    assert settings.llm.internal_auth_token is not None
    assert settings.llm.internal_auth_token.get_secret_value() == "x" * 48
    assert "x" * 48 not in repr(settings.llm)


def test_school_backend_requires_llm_auth_credential_for_deepseek(monkeypatch):
    monkeypatch.delenv("PSYNOVA_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("PSYNOVA_LLM_MODEL_ID", "deepseek-flash-education-support")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

    with pytest.raises(ValueError, match="auth credential is unavailable"):
        school_backend_linux._build_school_backend_settings("a" * 64)


def test_school_backend_rejects_unregistered_llm_model(monkeypatch):
    monkeypatch.delenv("PSYNOVA_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("PSYNOVA_LLM_MODEL_ID", "qwen2.5-7b-instruct")

    with pytest.raises(ValueError, match="not registered"):
        school_backend_linux._build_school_backend_settings("a" * 64)


@pytest.mark.parametrize(
    "origin",
    [
        "http://psynova.top",
        "https://*.psynova.top",
        "https://psynova.top/path",
        "https://user@psynova.top",
        "https://psynova.top:8443",
    ],
)
def test_public_origin_rejects_noncanonical_or_insecure_values(monkeypatch, origin):
    monkeypatch.setenv("PSYNOVA_PUBLIC_ORIGIN", origin)

    with pytest.raises(ValueError, match="public origin"):
        school_backend_linux._build_school_backend_settings("a" * 64)


def test_http_verifier_role_projection_matches_backend_role_contract():
    assert verify_school_http_linux.ROLE_PROJECTION["admin"] == (
        BackendRole.ADMIN.value,
        BackendRole.ADMIN.value,
    )


def test_deepseek_runtime_unit_keeps_secrets_and_egress_scoped():
    unit = (
        Path(__file__).resolve().parents[1]
        / "systemd"
        / "psynova-school-llm.service"
    ).read_text(encoding="utf-8")

    assert "DynamicUser=yes" in unit
    assert "SMHAI_LLM_PROVIDER=deepseek" in unit
    assert "SMHAI_LLM_RUNTIME_AUTH_FILE=%d/llm-runtime-auth.json" in unit
    assert "LoadCredentialEncrypted=deepseek-api-key:" in unit
    assert "CREDENTIALS_DIRECTORY" not in unit
    assert "API_KEY=" not in unit
    assert "LoadCredentialEncrypted=llm-runtime-auth.json:" in unit
    assert "release/13_deployment:/opt/psynova-school-demo/services/llm/release/src" in unit
    assert "/opt/psynova-school-demo/services/llm/venv/bin/python" in unit
    assert "IPAddressDeny=any" in unit
    assert "IPAddressAllow=127.0.0.1/32" in unit
    assert "IPAddressAllow=3.173.21.63/32" in unit
    assert "127.0.0.1:8160" not in unit
    assert "0.0.0.0/0" not in unit


def test_deepseek_backend_dropin_uses_only_the_encrypted_runtime_credential():
    dropin = (
        Path(__file__).resolve().parents[1]
        / "systemd"
        / "psynova-school-demo-llm.conf"
    ).read_text(encoding="utf-8")
    assert "PSYNOVA_LLM_MODEL_ID=deepseek-flash-education-support" in dropin
    assert (
        "LoadCredentialEncrypted=llm-runtime-auth.json:/etc/credstore.encrypted/"
        "psynova-school-llm-runtime-auth.cred"
    ) in dropin
    assert "TOKEN=" not in dropin
    assert "API_KEY=" not in dropin


def test_nginx_front_door_keeps_backend_and_database_on_loopback():
    config = (
        Path(__file__).resolve().parents[1]
        / "nginx"
        / "psynova-school-demo.conf"
    ).read_text(encoding="utf-8")

    assert "listen 0.0.0.0:80;" in config
    assert "listen 0.0.0.0:443 ssl;" in config
    assert "proxy_pass http://127.0.0.1:8088;" in config
    assert "server_name psynova.top;" in config
    assert ":3306" not in config
    assert ":8088;" not in config.replace("127.0.0.1:8088;", "")
    assert "[::]:" not in config
