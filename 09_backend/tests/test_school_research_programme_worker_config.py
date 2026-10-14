from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smhai_backend.core import config as backend_config
from smhai_backend.core.config import (
    RESEARCH_PROGRAMME_PROCESSOR_POLICY_SHA256,
    BackendSettings,
    ResearchProgrammeWorkerSettings,
)
from smhai_backend.domains.research_programme_generation.schemas import STUDY_REF
from smhai_backend.integrations.research_programme import PROMPT_ID, PROMPT_VERSION


def _enabled_settings(**overrides):
    values = {
        "enabled": True,
        "package_manifest_file": r"D:\Dev\datasets\research\programme-manifest.json",
        "package_manifest_sha256": (
            "f8af1a33487f175b02400fbfcf5f655cd93b40c7a5a35e0582dc363b11401a45"
        ),
        "processor_policy_sha256": RESEARCH_PROGRAMME_PROCESSOR_POLICY_SHA256,
        "model_ref": "qwen2.5-7b-instruct-school-demo",
        "model_digest_sha256": "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
        "prompt_ref": "PROMPT_staff_school_programme_research_v1",
        "prompt_version": "1.1.0",
    }
    values.update(overrides)
    return values


def _enabled_backend_settings():
    return {
        "_env_file": None,
        "environment": "research",
        "identity_profile": "school_tenant",
        "persistence_mode": "mysql",
        "school_csrf_secret": "c" * 64,
        "school_research_enabled": True,
        "school_research_runtime_file": r"D:\research\runtime.json",
        "school_research_runtime_sha256": "d" * 64,
        "school_research_base_url": "http://127.0.0.1:8182",
        "school_research_managed_enabled": True,
        "school_research_service_file": r"D:\research\service.json",
        "school_research_service_sha256": "e" * 64,
        "school_research_cat_python": r"D:\Python314\python.exe",
        "school_research_cat_source": r"D:\cat\src",
        "school_research_cat_dependencies": r"D:\cat\deps",
        "school_research_study_use_file": r"D:\research\study-use.json",
        "school_research_study_use_sha256": "b" * 64,
        "school_research_source_rights_verified": True,
        "school_research_latest_study_end": datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC),
        "safety": {"mode": "http", "base_url": "http://127.0.0.1:8190"},
        "llm": {"mode": "http", "base_url": "http://127.0.0.1:8160"},
        "research_programme_runtime": {
            "mode": "http",
            "base_url": "http://127.0.0.1:8161",
        },
        "research_programme_worker": _enabled_settings(),
    }


def test_staff_programme_worker_defaults_off_and_requires_explicit_pins():
    assert ResearchProgrammeWorkerSettings().enabled is False
    with pytest.raises(ValidationError):
        ResearchProgrammeWorkerSettings(enabled=True)

    config = ResearchProgrammeWorkerSettings(**_enabled_settings())
    assert config.enabled is True
    assert config.package_manifest_sha256.startswith("f8af")


def test_staff_programme_prompt_pin_matches_generation_runtime():
    config = ResearchProgrammeWorkerSettings(**_enabled_settings())

    assert config.prompt_ref == PROMPT_ID
    assert config.prompt_version == PROMPT_VERSION == "1.1.0"


@pytest.mark.parametrize(
    "override",
    [
        {"model_ref": "other-model"},
        {"prompt_version": "1.0.0"},
        {"prompt_version": "1.0.1"},
        {"prompt_version": "1.0.2"},
        {"prompt_version": "1.0.3"},
        {"prompt_version": "latest"},
        {"processor_policy_sha256": "a" * 64},
        {"package_manifest_file": "relative/package.json"},
        {"package_manifest_sha256": "F" * 64},
        {"processor_policy_sha256": None},
        {"poll_interval_seconds": True},
    ],
)
def test_staff_programme_pins_and_bounds_are_closed(override):
    with pytest.raises(ValidationError):
        ResearchProgrammeWorkerSettings(**_enabled_settings(**override))


def test_backend_rejects_enabled_programme_worker_without_school_policy():
    with pytest.raises(ValidationError):
        BackendSettings(
            _env_file=None,
            research_programme_worker=_enabled_settings(),
        )


@pytest.mark.parametrize(
    "runtime_url",
    [
        "http://127.0.0.1:8160",
        "http://localhost:8161",
        "http://127.0.0.1:8161/research",
    ],
)
def test_programme_runtime_is_pinned_to_private_loopback_8161(runtime_url):
    values = _enabled_backend_settings()
    values["research_programme_runtime"] = {"mode": "http", "base_url": runtime_url}
    with pytest.raises(ValidationError):
        BackendSettings(**values)


def test_effective_job_policy_hash_binds_source_study_model_and_prompt_pins():
    assert backend_config._RESEARCH_PROGRAMME_SOURCE_STUDY_REF == STUDY_REF
    values = _enabled_backend_settings()
    settings = BackendSettings(**values)
    school_study_ref = "HUNNU_PROMIS_HISTORICAL_REPLAY_2026_R1"
    pinned = settings.research_programme_job_policy_sha256_for(
        school_study_ref=school_study_ref
    )
    assert isinstance(pinned, str) and len(pinned) == 64
    assert set(pinned) <= set("0123456789abcdef")
    changed_study = BackendSettings(
        **{**values, "school_research_study_use_sha256": "9" * 64}
    )
    assert changed_study.research_programme_job_policy_sha256_for(
        school_study_ref=school_study_ref
    ) != pinned
    assert settings.research_programme_job_policy_sha256_for(
        school_study_ref="OTHER_STUDY_REF"
    ) != pinned
    assert settings.research_programme_job_policy_sha256_for(school_study_ref="") is None
    with pytest.raises(ValidationError):
        BackendSettings(
            **{
                **values,
                "safety": {"mode": "http", "base_url": "https://safety.example.org"},
            }
        )
