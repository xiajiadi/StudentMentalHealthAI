from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smhai_backend.core.config import (
    BackendSettings,
    ResearchGeneralEducationDraftSettings,
)

_SOURCE_STUDY_REF = "school-noncommercial-rag-research-2027-06"
_SOURCE_MANIFEST_SHA256 = "ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b"
_MANIFEST_FILE = r"D:\Dev\datasets\student-research\manifest.json"


def _draft_settings(**overrides):
    values = {
        "enabled": True,
        "school_id": 17,
        "school_study_ref": "HUNNU_PROMIS_HISTORICAL_REPLAY_2026_R1",
        "policy_version": "RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        "policy_hash": "c" * 64,
        "source_study_ref": _SOURCE_STUDY_REF,
        "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        "source_manifest_file": _MANIFEST_FILE,
    }
    values.update(overrides)
    return values


def _enabled_backend_settings(**overrides):
    values = {
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
        "school_research_cat_python": r"D:\Dev\pythons\python.exe",
        "school_research_cat_source": r"D:\cat\src",
        "school_research_cat_dependencies": r"D:\cat\deps",
        "school_research_study_use_file": r"D:\research\study-use.json",
        "school_research_study_use_sha256": "b" * 64,
        "school_research_source_rights_verified": True,
        "school_research_latest_study_end": datetime(
            2027, 6, 30, 15, 59, 59, tzinfo=UTC
        ),
        "school_research_student_conversation": {
            "enabled": True,
            "school_id": 17,
            "study_ref": _SOURCE_STUDY_REF,
            "manifest_file": _MANIFEST_FILE,
            "manifest_sha256": _SOURCE_MANIFEST_SHA256,
            "safety_base_url": "http://127.0.0.1:8191",
        },
        "safety": {"mode": "http", "base_url": "http://127.0.0.1:8190"},
        "llm": {"mode": "http", "base_url": "http://127.0.0.1:8160"},
        "research_programme_runtime": {
            "mode": "http",
            "base_url": "http://127.0.0.1:8161",
            "timeout": {"read": 65.0},
        },
        "research_general_education_draft": _draft_settings(),
    }
    values.update(overrides)
    return values


def test_general_education_draft_is_off_by_default_with_single_attempt_bounds():
    settings = ResearchGeneralEducationDraftSettings()
    backend = BackendSettings(_env_file=None)

    assert settings.enabled is False
    assert settings.poll_interval_seconds == 1.0
    assert settings.lease_seconds == 300
    assert settings.max_attempts == 1
    assert settings.shutdown_drain_seconds == 10.0
    assert backend.research_general_education_draft.enabled is False


def test_enabled_draft_requires_exact_trusted_config_pins():
    settings = ResearchGeneralEducationDraftSettings.model_validate(_draft_settings())

    assert settings.enabled is True
    assert settings.policy_version == "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
    assert settings.policy_hash == "c" * 64
    assert settings.source_manifest_sha256 == _SOURCE_MANIFEST_SHA256
    assert settings.source_manifest_file == _MANIFEST_FILE


@pytest.mark.parametrize(
    "override",
    [
        {"school_id": 0},
        {"school_id": True},
        {"school_study_ref": "../other-study"},
        {"school_study_ref": "s" * 129},
        {"policy_version": "OTHER_POLICY_V1"},
        {"policy_hash": "C" * 64},
        {"source_study_ref": "other-source-study"},
        {"source_manifest_sha256": "0" * 64},
        {"source_manifest_file": "relative/manifest.json"},
        {"source_manifest_file": r"D:\data\..\manifest.json"},
    ],
)
def test_enabled_draft_rejects_wrong_or_unbounded_source_pins(override):
    with pytest.raises(ValidationError):
        ResearchGeneralEducationDraftSettings.model_validate(
            _draft_settings(**override)
        )


@pytest.mark.parametrize(
    "override",
    [
        {"poll_interval_seconds": True},
        {"poll_interval_seconds": "1.0"},
        {"poll_interval_seconds": float("nan")},
        {"lease_seconds": 119},
        {"lease_seconds": True},
        {"max_attempts": 2},
        {"max_attempts": True},
        {"shutdown_drain_seconds": float("inf")},
    ],
)
def test_worker_bounds_are_strict_and_single_attempt(override):
    with pytest.raises(ValidationError):
        ResearchGeneralEducationDraftSettings.model_validate(override)


def test_backend_requires_school_research_mysql_matching_r3_and_private_runtime():
    configured = BackendSettings(**_enabled_backend_settings())

    assert configured.research_general_education_draft.enabled is True
    assert configured.research_programme_runtime.base_url == "http://127.0.0.1:8161"


@pytest.mark.parametrize(
    "override",
    [
        {"environment": "production"},
        {"identity_profile": "legacy_demo"},
        {"persistence_mode": "memory"},
        {"school_research_managed_enabled": False},
        {"school_research_student_conversation": {"enabled": False}},
        {
            "school_research_student_conversation": {
                "enabled": True,
                "school_id": 18,
                "study_ref": _SOURCE_STUDY_REF,
                "manifest_file": _MANIFEST_FILE,
                "manifest_sha256": _SOURCE_MANIFEST_SHA256,
                "safety_base_url": "http://127.0.0.1:8191",
            }
        },
        {
            "research_general_education_draft": _draft_settings(
                source_manifest_file=r"D:\Dev\datasets\student-research\other.json"
            )
        },
        {
            "research_programme_runtime": {
                "mode": "http",
                "base_url": "http://127.0.0.1:8160",
                "timeout": {"read": 65.0},
            }
        },
        {
            "research_programme_runtime": {
                "mode": "http",
                "base_url": "http://127.0.0.1:8161",
                "timeout": {"read": 64.0},
            }
        },
    ],
)
def test_backend_rejects_disabled_or_mismatched_dependencies(override):
    with pytest.raises(ValidationError):
        BackendSettings(**_enabled_backend_settings(**override))
