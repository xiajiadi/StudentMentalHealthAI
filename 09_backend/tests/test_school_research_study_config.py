from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smhai_backend.core.config import BackendSettings
from smhai_backend.domains.school_research import bootstrap
from smhai_backend.domains.school_research.runtime import ResearchCATRuntimeError


def configured():
    return {
        "environment": "research",
        "identity_profile": "school_tenant",
        "persistence_mode": "mysql",
        "school_csrf_secret": "ab" * 32,
        "school_research_enabled": True,
        "school_research_managed_enabled": True,
        "school_research_runtime_file": "D:/isolated/runtime.json",
        "school_research_runtime_sha256": "a" * 64,
        "school_research_base_url": "http://127.0.0.1:57419",
        "school_research_service_file": "D:/isolated/service.json",
        "school_research_service_sha256": "b" * 64,
        "school_research_cat_python": "D:/isolated/python.exe",
        "school_research_cat_source": "D:/isolated/cat",
        "school_research_cat_dependencies": "D:/isolated/dependencies",
        "school_research_study_use_file": "D:/isolated/study.json",
        "school_research_study_use_sha256": "c" * 64,
        "school_research_source_rights_verified": True,
        "school_research_latest_study_end": datetime(2027, 6, 30, 16, tzinfo=UTC),
    }


def test_explicit_study_server_configuration():
    settings = BackendSettings(**configured())
    assert settings.school_research_source_rights_verified is True
    assert settings.school_research_latest_study_end.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("patch", [
    {"school_research_study_use_file": None},
    {"school_research_study_use_sha256": None},
    {"school_research_study_use_sha256": "C" * 64},
    {"school_research_source_rights_verified": False},
    {"school_research_source_rights_verified": 1},
    {"school_research_latest_study_end": None},
    {"school_research_latest_study_end": datetime(2027, 6, 30)},
    {"school_research_managed_enabled": False},
    {"school_research_enabled": False},
    {"environment": "production"},
])
def test_partial_or_untrusted_study_settings_rejected(patch):
    with pytest.raises(ValidationError):
        BackendSettings(**(configured() | patch))


def test_default_does_not_create_study_permission():
    settings = BackendSettings()
    assert bootstrap.build_school_research_study_policy(settings) is None
    assert settings.school_research_source_rights_verified is False
    assert bootstrap.build_school_research_tasks_service(settings, None) is None


def test_study_bootstrap_passes_exact_trusted_pins(monkeypatch):
    from smhai_backend.domains.school_research import study_use

    calls = []
    policy = object()

    def load(path, **kwargs):
        calls.append((str(path), kwargs))
        return policy

    monkeypatch.setattr(study_use, "load_research_study_use_policy", load)
    settings = BackendSettings(**configured())
    assert bootstrap.build_school_research_study_policy(settings) is policy
    assert calls == [("D:\\isolated\\study.json", {
        "expected_sha256": "c" * 64,
        "source_rights_verified": True,
        "latest_allowed_ends_at": settings.school_research_latest_study_end,
    })]


def test_invalid_study_bootstrap_is_redacted():
    settings = SimpleNamespace(school_research_study_use_file="private-path")
    with pytest.raises(ResearchCATRuntimeError) as caught:
        bootstrap.build_school_research_study_policy(settings)
    assert caught.value.code == "study_use_configuration_invalid"
    assert "private-path" not in str(caught.value)
