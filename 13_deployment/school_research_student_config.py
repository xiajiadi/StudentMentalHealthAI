"""Strict standard-library reader for the opt-in student research lane."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STUDY_REF = "school-noncommercial-rag-research-2027-06"
MANIFEST_SHA256 = "70637b39cb11a34de91599a1a32e9e1a6edff6a76b19cc1b11895ee7170e9974"
SAFETY_BASE_URL = "http://127.0.0.1:8191"
MAX_CONFIG_BYTES = 16 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CONFIG_FIELDS = frozenset(
    {
        "enabled", "school_id", "purpose", "study_ref", "manifest_file",
        "manifest_sha256", "safety_base_url", "consumer_age_min", "consumer_age_max",
    }
)


class StudentResearchConfigError(ValueError):
    """Safe, content-free error code for invalid deployment config."""

    def __init__(self, code: str = "student_research_config_invalid") -> None:
        self.code = code if code in {
            "student_research_config_incomplete",
            "student_research_config_invalid",
            "student_research_config_source_invalid",
        } else "student_research_config_invalid"
        super().__init__(self.code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError


def _read_json(path: Path, limit: int) -> tuple[bytes, object]:
    raw = _read_file(path, limit)
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, TypeError):
        raise StudentResearchConfigError() from None
    return raw, document


def _read_file(value: Path, limit: int) -> bytes:
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or ".." in value.parts
    ):
        raise StudentResearchConfigError()
    try:
        absolute = Path(os.path.abspath(value))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError
        info = absolute.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > limit:
            raise ValueError
        with absolute.open("rb") as stream:
            raw = stream.read(limit + 1)
        if not raw or len(raw) > limit:
            raise ValueError
        return raw
    except (OSError, ValueError):
        raise StudentResearchConfigError() from None


def _safe_absolute_path(value: object) -> Path:
    if isinstance(value, Path):
        path = value
    elif type(value) is str:
        path = Path(value)
    else:
        raise StudentResearchConfigError()
    if not path.is_absolute() or ".." in path.parts:
        raise StudentResearchConfigError()
    return path


@dataclass(frozen=True, slots=True)
class StudentResearchConfig:
    config_file: str = field(repr=False)
    config_sha256: str
    school_id: int
    manifest_file: str = field(repr=False)
    manifest_sha256: str

    def core_settings(self) -> dict[str, object]:
        return {
            "enabled": True,
            "school_id": self.school_id,
            "purpose": "RESEARCH_SIMULATION",
            "study_ref": STUDY_REF,
            "manifest_file": self.manifest_file,
            "manifest_sha256": self.manifest_sha256,
            "safety_base_url": SAFETY_BASE_URL,
            "consumer_age_min": 14,
            "consumer_age_max": 17,
        }

    def manifest_value(self) -> dict[str, object]:
        return {
            "config_file": self.config_file,
            "config_sha256": self.config_sha256,
            **self.core_settings(),
        }


def load_student_research_config(
    config_file: Path,
    expected_sha256: object,
) -> StudentResearchConfig:
    """Read a caller-pinned config and verify its exact pinned source manifest."""
    if type(expected_sha256) is not str or _SHA256.fullmatch(expected_sha256) is None:
        raise StudentResearchConfigError()
    try:
        config_path = _safe_absolute_path(config_file)
        raw, document = _read_json(config_path, MAX_CONFIG_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_sha256 or type(document) is not dict or set(document) != _CONFIG_FIELDS:
            raise StudentResearchConfigError()
        if (
            type(document["enabled"]) is not bool or document["enabled"] is not True
            or type(document["school_id"]) is not int or document["school_id"] < 1
            or type(document["purpose"]) is not str
            or document["purpose"] != "RESEARCH_SIMULATION"
            or type(document["study_ref"]) is not str or document["study_ref"] != STUDY_REF
            or type(document["manifest_sha256"]) is not str
            or document["manifest_sha256"] != MANIFEST_SHA256
            or type(document["safety_base_url"]) is not str
            or document["safety_base_url"] != SAFETY_BASE_URL
            or type(document["consumer_age_min"]) is not int or document["consumer_age_min"] != 14
            or type(document["consumer_age_max"]) is not int or document["consumer_age_max"] != 17
        ):
            raise StudentResearchConfigError()
        manifest_path = _safe_absolute_path(document["manifest_file"])
        manifest_bytes, manifest = _read_json(manifest_path, MAX_MANIFEST_BYTES)
        if (
            hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256
            or type(manifest) is not dict
        ):
            raise StudentResearchConfigError("student_research_config_source_invalid")
        return StudentResearchConfig(
            config_file=str(config_path),
            config_sha256=digest,
            school_id=document["school_id"],
            manifest_file=str(manifest_path),
            manifest_sha256=MANIFEST_SHA256,
        )
    except StudentResearchConfigError:
        raise
    except (OSError, TypeError, ValueError):
        raise StudentResearchConfigError() from None


def restore_student_research_config(value: object) -> StudentResearchConfig | None:
    """Restore manifest-owned argv identity without opening the source file."""
    if value is None:
        return None
    fields = _CONFIG_FIELDS | {"config_file", "config_sha256"}
    if type(value) is not dict or set(value) != fields:
        raise StudentResearchConfigError()
    config_path = _safe_absolute_path(value["config_file"])
    manifest_path = _safe_absolute_path(value["manifest_file"])
    config_sha = value["config_sha256"]
    if (
        type(config_sha) is not str or _SHA256.fullmatch(config_sha) is None
        or value["enabled"] is not True
        or type(value["school_id"]) is not int or value["school_id"] < 1
        or value["purpose"] != "RESEARCH_SIMULATION"
        or value["study_ref"] != STUDY_REF
        or value["manifest_sha256"] != MANIFEST_SHA256
        or value["safety_base_url"] != SAFETY_BASE_URL
        or type(value["consumer_age_min"]) is not int or value["consumer_age_min"] != 14
        or type(value["consumer_age_max"]) is not int or value["consumer_age_max"] != 17
    ):
        raise StudentResearchConfigError()
    return StudentResearchConfig(
        config_file=str(config_path),
        config_sha256=config_sha,
        school_id=value["school_id"],
        manifest_file=str(manifest_path),
        manifest_sha256=MANIFEST_SHA256,
    )
