"""Caller-pinned opt-in configuration for held research education drafts."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from school_research_student_config import (
    STUDY_REF,
    StudentResearchConfig,
    _read_json,
    _safe_absolute_path,
    load_student_research_config,
)

POLICY_VERSION = "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
SCHEMA_VERSION = "psynova.school-research-education-draft-config.v1"
SOURCE_MANIFEST_SHA256 = "ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b"
_FIELDS = frozenset({
    "schema_version", "enabled", "school_id", "school_study_ref", "purpose",
    "policy_version", "student_source_config_file", "student_source_config_sha256",
    "content_mode", "release_mode",
})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class ResearchEducationDraftConfigError(ValueError):
    def __init__(self) -> None:
        super().__init__("RESEARCH_EDUCATION_DRAFT_CONFIG_INVALID")


@dataclass(frozen=True, slots=True)
class ResearchEducationDraftConfig:
    config_file: str = field(repr=False)
    config_sha256: str
    school_id: int
    school_study_ref: str
    student_source: StudentResearchConfig = field(repr=False)

    @property
    def policy_version(self) -> str:
        return POLICY_VERSION

    @property
    def policy_hash(self) -> str:
        return self.config_sha256

    @property
    def source_manifest_sha256(self) -> str:
        return self.student_source.manifest_sha256

    @property
    def source_study_ref(self) -> str:
        return STUDY_REF

    def core_settings(self) -> dict[str, object]:
        return {
            "enabled": True,
            "school_id": self.school_id,
            "school_study_ref": self.school_study_ref,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "source_study_ref": self.source_study_ref,
            "source_manifest_sha256": self.source_manifest_sha256,
            "source_manifest_file": self.student_source.manifest_file,
        }

    def manifest_value(self) -> dict[str, object]:
        return {
            "config_file": self.config_file,
            "config_sha256": self.config_sha256,
            **self.core_settings(),
            "student_source_config_sha256": self.student_source.config_sha256,
            "content_mode": "GENERAL_INFORMATION_NO_ASSESSMENT_INPUT",
            "release_mode": "HELD_THEN_EXPLICIT_REVIEW_AND_PUBLISH",
        }


def load_research_education_draft_config(
    config_file: Path, expected_sha256: str,
) -> ResearchEducationDraftConfig:
    """Absence disables the lane; supplied files must match the entire policy."""
    try:
        if type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256):
            raise ValueError
        path = _safe_absolute_path(config_file)
        raw, doc = _read_json(path, 8192)
        if (
            hashlib.sha256(raw).hexdigest() != expected_sha256
            or type(doc) is not dict or set(doc) != _FIELDS
            or doc["schema_version"] != SCHEMA_VERSION
            or doc["enabled"] is not True
            or type(doc["school_id"]) is not int or doc["school_id"] <= 0
            or type(doc["school_study_ref"]) is not str
            or not _TOKEN.fullmatch(doc["school_study_ref"])
            or doc["purpose"] != "RESEARCH_SIMULATION"
            or doc["policy_version"] != POLICY_VERSION
            or doc["content_mode"] != "GENERAL_INFORMATION_NO_ASSESSMENT_INPUT"
            or doc["release_mode"] != "HELD_THEN_EXPLICIT_REVIEW_AND_PUBLISH"
        ):
            raise ValueError
        source = load_student_research_config(
            _safe_absolute_path(doc["student_source_config_file"]),
            doc["student_source_config_sha256"],
        )
        if source.school_id != doc["school_id"] or source.manifest_sha256 != SOURCE_MANIFEST_SHA256:
            raise ValueError
        return ResearchEducationDraftConfig(
            config_file=str(path), config_sha256=expected_sha256,
            school_id=doc["school_id"], school_study_ref=doc["school_study_ref"],
            student_source=source,
        )
    except Exception:  # noqa: BLE001 - redact parser and filesystem details at the config boundary.
        # Paths, source documents and parser errors are intentionally not exposed.
        raise ResearchEducationDraftConfigError() from None
