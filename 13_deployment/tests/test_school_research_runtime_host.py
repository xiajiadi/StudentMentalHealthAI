from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

DEPLOYMENT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = DEPLOYMENT.parent / "06_llm-runtime" / "src"
sys.path.insert(0, str(DEPLOYMENT))
sys.path.insert(0, str(RUNTIME_SOURCE))
sys.path.insert(0, str(RUNTIME_SOURCE.parent / ".venv" / "Lib" / "site-packages"))

import school_llm_runtime
import school_research_runtime_host as host


class FakeService:
    def __init__(self, ready: bool = True) -> None:
        self.ready_value = ready
        self.generate_calls = 0

    def ready(self) -> bool:
        return self.ready_value


def test_external_registry_mode_reuses_pinned_model_without_process_ownership(tmp_path):
    pytest.importorskip("psutil")
    from llm_runtime.runtime.process import ProcessMode

    settings = school_llm_runtime.HostSettings(
        ollama_root=tmp_path / "ollama",
        models_root=tmp_path / "models",
        logs_root=tmp_path / "logs",
        runtime_host=host.RUNTIME_HOST,
        runtime_port=host.RUNTIME_PORT,
    )
    service = school_llm_runtime.build_service(
        settings,
        hardware=SimpleNamespace(gpu_present=True),
        provider_mode=ProcessMode.EXTERNAL.value,
    )
    try:
        host._verify_external_service(service, settings)
        definition = service.provider_registry.definition("ollama")
        assert definition.mode is ProcessMode.EXTERNAL
        assert definition.process_binding is None
        assert service.max_attempts == 1
        assert service.backoff_seconds == ()
        assert service.preload_primary is False
        assert service.registry.cloud_fallback is False
    finally:
        service.shutdown()


def test_app_registers_both_research_routes_without_changing_host_scope():
    from types import SimpleNamespace

    import school_research_general_education_runtime as education_runtime

    now = datetime(2026, 10, 14, tzinfo=UTC)
    service = FakeService()
    app = host.create_app(SimpleNamespace(service=service), clock=lambda: now)
    paths = {route.path for route in app.routes}
    assert paths == {
        host.HEALTH_PATH,
        host.ROUTE_PATH,
        education_runtime.ROUTE_PATH,
    }
    assert app.state.research_study_ref == host.STUDY_REF
    assert app.state.research_noncommercial is True
    assert app.state.research_publication_eligible is False
    assert app.state.research_production_use is False
    assert app.state.research_study_end_utc == host.STUDY_END_UTC

    with TestClient(app) as client:
        response = client.get(host.HEALTH_PATH)
    assert response.status_code == 200
    assert response.json() == {
        "status": "READY",
        "scope": "research_programme_noncommercial_hold_only",
        "runtime_version": host.RUNTIME_VERSION,
    }


def test_study_deadline_is_inclusive_and_allows_no_generation_after_expiry():
    now = host.STUDY_END_UTC
    host._require_study_active(lambda: now)
    service = FakeService()
    app = host.create_app(
        SimpleNamespace(service=service),
        clock=lambda: now + timedelta(microseconds=1),
    )
    with TestClient(app) as client:
        generation = client.post(host.ROUTE_PATH, content=b"not-read-after-expiry")
        health = client.get(host.HEALTH_PATH)
    assert generation.status_code == 410
    assert generation.json() == {"detail": {"code": "RESEARCH_STUDY_EXPIRED"}}
    assert health.status_code == 410
    assert health.json() == {
        "status": "EXPIRED",
        "scope": "research_programme_noncommercial_hold_only",
        "runtime_version": host.RUNTIME_VERSION,
    }
    assert service.generate_calls == 0


def test_study_expiry_guard_blocks_both_generation_routes():
    import school_research_general_education_runtime as education_runtime

    service = FakeService()
    app = host.create_app(
        SimpleNamespace(service=service),
        clock=lambda: host.STUDY_END_UTC + timedelta(microseconds=1),
    )

    with TestClient(app) as client:
        programme = client.post(host.ROUTE_PATH, content=b"not-read-after-expiry")
        general_education = client.post(
            education_runtime.ROUTE_PATH,
            content=b"not-read-after-expiry",
        )

    for response in (programme, general_education):
        assert response.status_code == 410
        assert response.json() == {"detail": {"code": "RESEARCH_STUDY_EXPIRED"}}
    assert service.generate_calls == 0


def test_default_cli_is_preflight_only_and_expired_preflight_fails_closed(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(host, "preflight", lambda **_kwargs: calls.append("preflight"))
    assert host.main([]) == 0
    assert calls == ["preflight"]
    assert json.loads(capsys.readouterr().out) == {
        "status": "PREFLIGHT_OK",
        "scope": "research_programme_noncommercial_hold_only",
        "runtime_version": host.RUNTIME_VERSION,
    }

    with pytest.raises(host.ResearchRuntimeHostError, match="RESEARCH_STUDY_EXPIRED"):
        host._require_study_active(
            lambda: host.STUDY_END_UTC + timedelta(seconds=1)
        )
