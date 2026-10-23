"""Tests for the credential-safe, non-generating DeepSeek model probe."""

from __future__ import annotations

import probe_deepseek_models_linux as probe


def test_service_release_layout_is_supported(tmp_path):
    expected = tmp_path / "services" / "llm" / "release" / "src"
    (expected / "llm_runtime").mkdir(parents=True)

    assert probe._runtime_source_path(tmp_path) == expected


def test_missing_systemd_credential_directory_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

    result = probe.probe(provider_factory=lambda _path: None)

    assert result == {
        "probe": "BLOCKED",
        "error_code": "CREDENTIAL_DIRECTORY_UNAVAILABLE",
    }


def test_models_probe_reports_only_model_presence_and_closes_provider(tmp_path):
    state = {"closed": False}

    class Provider:
        def discover_models(self):
            return [
                {"provider_model_id": "deepseek-flash"},
                {"provider_model_id": "deepseek-v4-pro"},
            ]

        def close(self):
            state["closed"] = True

    result = probe.probe(
        credential_directory=tmp_path,
        provider_factory=lambda path: Provider()
        if path == tmp_path / "deepseek-api-key"
        else None,
    )

    assert result == {
        "probe": "PASS",
        "api_status": "reachable",
        "expected_model_available": True,
        "models_count": 2,
        "generation_requests": 0,
    }
    assert state["closed"] is True


def test_provider_failure_redacts_message_and_details(tmp_path):
    sentinel = "api-key-sentinel-and-provider-body"

    class ProviderFailure(Exception):
        def __init__(self):
            self.code = type("Code", (), {"value": "REQUEST_TIMEOUT"})()
            self.details = {"body": sentinel}
            super().__init__(sentinel)

    class Provider:
        def discover_models(self):
            raise ProviderFailure()

        def close(self):
            pass

    result = probe.probe(
        credential_directory=tmp_path,
        provider_factory=lambda _path: Provider(),
    )

    assert result == {
        "probe": "BLOCKED",
        "error_code": "REQUEST_TIMEOUT",
        "generation_requests": 0,
    }
    assert sentinel not in repr(result)
