from __future__ import annotations

import pytest

from smhai_backend.core.config import (
    BackendSettings,
    LLMModuleClientSettings,
    ModuleClientSettings,
    SchoolResearchStudentConversationSettings,
)

_MANIFEST_SHA = "70637b39cb11a34de91599a1a32e9e1a6edff6a76b19cc1b11895ee7170e9974"
_STUDY_REF = "school-noncommercial-rag-research-2027-06"


def test_school_research_student_lane_is_off_by_default() -> None:
    lane = SchoolResearchStudentConversationSettings()
    assert lane.enabled is False
    assert lane.purpose == "RESEARCH_SIMULATION"
    assert lane.consumer_age_min == 14
    assert lane.consumer_age_max == 17
    assert lane.safety_base_url is None


def test_enabled_lane_requires_exact_absolute_server_pins() -> None:
    with pytest.raises(ValueError, match="exact server pins"):
        SchoolResearchStudentConversationSettings(
            enabled=True,
            school_id=41,
            study_ref=_STUDY_REF,
            manifest_file="student-manifest.json",
            manifest_sha256=_MANIFEST_SHA,
        )
    with pytest.raises(ValueError, match="exact server pins"):
        SchoolResearchStudentConversationSettings(
            enabled=True,
            school_id=41,
            study_ref=_STUDY_REF,
            manifest_file=r"D:\research\student-manifest.json",
            manifest_sha256="0" * 64,
        )
    with pytest.raises(ValueError, match="consumer_age_min"):
        SchoolResearchStudentConversationSettings(
            enabled=True,
            school_id=41,
            study_ref=_STUDY_REF,
            manifest_file=r"D:\research\student-manifest.json",
            manifest_sha256=_MANIFEST_SHA,
            safety_base_url="http://127.0.0.1:8191",
            consumer_age_min=13,
        )


def test_enabled_lane_requires_nonproduction_school_mysql_and_fixed_local_safety_runtime() -> None:
    lane = {
        "enabled": True,
        "school_id": 41,
        "study_ref": _STUDY_REF,
        "manifest_file": r"D:\research\student-manifest.json",
        "manifest_sha256": _MANIFEST_SHA,
        "safety_base_url": "http://127.0.0.1:8191",
    }
    with pytest.raises(ValueError, match="nonproduction school MySQL"):
        BackendSettings(
            environment="test",
            identity_profile="school_tenant",
            persistence_mode="mysql",
            school_csrf_secret="a" * 64,
            school_research_student_conversation=lane,
            safety=ModuleClientSettings(mode="contract_fake", base_url="http://127.0.0.1:8190"),
            llm=LLMModuleClientSettings(mode="http", base_url="http://127.0.0.1:8160"),
        )
    settings = BackendSettings(
        environment="research",
        identity_profile="school_tenant",
        persistence_mode="mysql",
        school_csrf_secret="a" * 64,
        school_research_student_conversation=lane,
        safety=ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8190"),
        llm=LLMModuleClientSettings(mode="http", base_url="http://127.0.0.1:8160"),
    )
    assert settings.school_research_student_conversation.enabled is True


def test_enabled_lane_requires_the_isolated_research_safety_url() -> None:
    with pytest.raises(ValueError, match="exact server pins"):
        SchoolResearchStudentConversationSettings(
            enabled=True,
            school_id=41,
            study_ref=_STUDY_REF,
            manifest_file=r"D:\research\student-manifest.json",
            manifest_sha256=_MANIFEST_SHA,
        )
    with pytest.raises(ValueError):
        SchoolResearchStudentConversationSettings(
            enabled=True,
            school_id=41,
            study_ref=_STUDY_REF,
            manifest_file=r"D:\research\student-manifest.json",
            manifest_sha256=_MANIFEST_SHA,
            safety_base_url="http://127.0.0.1:8190",
        )
