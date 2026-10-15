"""Isolated source qualification for the student research retrieval lane.

This module does not change the knowledge.v1 approval rule. It only recognizes
one externally pinned, noncommercial research package and keeps its records in
the pending-human-review state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from safety_engine.adapters.presidio import PresidioPrivacyAdapter
from safety_engine.retrieval.adapter import RetrievalSafetyAdapter

R1_MANIFEST_SHA256 = "70637b39cb11a34de91599a1a32e9e1a6edff6a76b19cc1b11895ee7170e9974"
R1_PACKAGE_ID = "student-general-education-source-review-20261015-r1"
R1_REVIEW_REF = "AI-ENG-2026-10-15-STUDENT-GENERAL-EDUCATION-SOURCE-TRACEABILITY"
R3_MANIFEST_SHA256 = "ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b"
R3_PACKAGE_ID = "student-general-education-source-review-20261015-r3"
R3_REVIEW_REF = "AI-ENG-2026-10-15-STUDENT-GENERAL-EDUCATION-SOURCE-TRACEABILITY-R3"
# Backward-compatible defaults remain bound to r1. The registry is closed: a
# manifest is selectable only by one of these two exact reviewed byte hashes.
PINNED_MANIFEST_SHA256 = R1_MANIFEST_SHA256
PINNED_PACKAGE_ID = R1_PACKAGE_ID
PINNED_STUDY_REF = "school-noncommercial-rag-research-2027-06"
PINNED_REVIEW_REF = R1_REVIEW_REF
PINNED_CONSUMER_AGE_SCOPE = "14-17"
STUDY_END_UTC = datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC)
_MAX_MANIFEST_BYTES = 512 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REGISTRY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _ManifestPin:
    version: str
    sha256: str
    package_id: str
    review_ref: str


_MANIFEST_VERSIONS = MappingProxyType(
    {
        "r1": _ManifestPin("r1", R1_MANIFEST_SHA256, R1_PACKAGE_ID, R1_REVIEW_REF),
        "r3": _ManifestPin("r3", R3_MANIFEST_SHA256, R3_PACKAGE_ID, R3_REVIEW_REF),
    }
)
_MANIFEST_PIN_BY_SHA256 = MappingProxyType({pin.sha256: pin for pin in _MANIFEST_VERSIONS.values()})
SUPPORTED_MANIFEST_SHA256S = frozenset(_MANIFEST_PIN_BY_SHA256)

_TOP_LEVEL_KEYS = {
    "schema_version",
    "package_id",
    "package_status",
    "reviewer_kind",
    "review_ref",
    "consumer_scope",
    "study_ref",
    "use_policy",
    "flags",
    "role_scope",
    "risk_scope",
    "review_status",
    "sources",
    "records",
}
_USE_POLICY_KEYS = {
    "scope",
    "noncommercial",
    "valid_through",
    "audience",
    "allowed_content",
    "prohibited_content",
    "language",
}
_FLAG_KEYS = {
    "human_curated",
    "professional_approval",
    "ethics_approval",
    "clinical_approval",
    "psychometric_approval",
    "publication_eligible",
    "production_use",
}
_SOURCE_KEYS = {
    "source_id",
    "title",
    "canonical_url",
    "publisher",
    "publication_date",
    "source_population_scope",
    "source_language",
    "license",
    "license_url",
    "attribution",
    "rights_evidence_url",
    "rights_evidence_sha256",
    "rights_status",
    "rights_scope_note",
    "student_retrieval_eligible",
    "source_capture_sha256",
}
_RECORD_KEYS = {
    "record_id",
    "source_id",
    "layer",
    "text",
    "locator",
    "excerpt_sha256",
    "source_population_scope",
    "consumer_scope",
    "language",
    "certainty",
    "role_fit",
    "student_retrieval_eligible",
}

# Numeric age limits are server-owned. Free-text source population metadata is
# also pinned and compared exactly below; it is never parsed as authority.
_SOURCE_SPEC = {
    "WHO-HAT-TOOLKIT-2021": (
        "Adolescents aged 10–19; global policy framework, not grade- or China-specific",
        10,
        19,
        "VERIFIED_WITH_CONDITIONS",
        True,
    ),
    "RANITI-SCHOOL-CONNECTEDNESS-2022": (
        "Review ages 14–24 in education settings across countries; primarily US studies; "
        "not high-school-only",
        14,
        24,
        "VERIFIED_WITH_CONDITIONS",
        True,
    ),
    "CDC-SCHOOL-CONNECTEDNESS-2024": (
        "Youth and students in school settings; source page does not define one exact age band; "
        "US agency context",
        None,
        None,
        "PENDING",
        False,
    ),
    "WHO-PHYSICAL-ACTIVITY-GUIDELINES-2020": (
        "Children and adolescents aged 5–17 for the cited recommendation; broader guideline also "
        "covers adults and older adults",
        5,
        17,
        "VERIFIED_WITH_CONDITIONS",
        True,
    ),
    "GASKIN-SCHOOL-SLEEP-INTERVENTIONS-2024": (
        "School-age children and adolescents aged 5–18; review of 21 trials across 13 countries; "
        "most studies in secondary schools",
        5,
        18,
        "VERIFIED_WITH_CONDITIONS",
        True,
    ),
}
_RECORD_SPEC = {
    "POLICY-WHO-HAT-STRATEGY1-2021": (
        "WHO-HAT-TOOLKIT-2021",
        "Adolescents aged 10–19; global normative policy framework",
        "secondary_school_student_13_18",
        10,
        19,
        True,
    ),
    "THEORY-RANITI-SCHOOL-CONNECTEDNESS-2022": (
        "RANITI-SCHOOL-CONNECTEDNESS-2022",
        "Review ages 14–24 in education settings; not high-school-only",
        "secondary_school_student_13_18",
        14,
        24,
        True,
    ),
    "INTERVENTION-WHO-PHYSICAL-ACTIVITY-START-2020": (
        "WHO-PHYSICAL-ACTIVITY-GUIDELINES-2020",
        "Children and adolescents aged 5–17; this consumer record is limited to ages 13–17",
        "secondary_school_student_13_17",
        5,
        17,
        True,
    ),
    "INTERVENTION-GASKIN-SCHOOL-SLEEP-REVIEW-2024": (
        "GASKIN-SCHOOL-SLEEP-INTERVENTIONS-2024",
        "School-based review ages 5–18; 21 trials across 13 countries",
        "secondary_school_student_13_18",
        5,
        18,
        True,
    ),
    "TRACE-CDC-SCHOOL-CONNECTEDNESS-2024": (
        "CDC-SCHOOL-CONNECTEDNESS-2024",
        "School-level youth guidance; no exact age band",
        "secondary_school_student_13_18",
        None,
        None,
        False,
    ),
}


class ResearchStudentQualificationError(ValueError):
    """Stable error without manifest text, paths, or request content."""

    def __init__(self, code: str = "RESEARCH_SOURCE_PACKAGE_INVALID") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _Source:
    source_id: str
    min_age: int | None
    max_age: int | None
    rights_status: str
    rights_scope_note: str
    eligible: bool


@dataclass(frozen=True, slots=True)
class _Record:
    record_id: str
    source_id: str
    text: str
    content_sha256: str
    min_age: int | None
    max_age: int | None
    consumer_min_age: int
    consumer_max_age: int
    eligible: bool


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchStudentQualificationError()
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ResearchStudentQualificationError()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _is_nonempty_string(value: Any) -> bool:
    return type(value) is str and bool(value.strip())


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ResearchStudentQualificationError() from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ResearchStudentQualificationError()
    return parsed.astimezone(UTC)


class ResearchStudentSourceRegistry:
    """Server-loaded allowlist for one of the two externally pinned packages."""

    __slots__ = (
        "manifest_version",
        "manifest_sha256",
        "package_id",
        "review_ref",
        "study_ref",
        "_sources",
        "_records",
        "_clock",
    )

    def __init__(
        self,
        *,
        manifest_sha256: str,
        sources: Mapping[str, _Source],
        records: Mapping[str, _Record],
        clock: Callable[[], datetime],
        _verified_token: object,
    ) -> None:
        pin = _MANIFEST_PIN_BY_SHA256.get(manifest_sha256)
        if _verified_token is not _REGISTRY_TOKEN or pin is None:
            raise ResearchStudentQualificationError()
        self.manifest_sha256 = manifest_sha256
        self.manifest_version = pin.version
        self.package_id = pin.package_id
        self.review_ref = pin.review_ref
        self.study_ref = PINNED_STUDY_REF
        self._sources = MappingProxyType(dict(sources))
        self._records = MappingProxyType(dict(records))
        self._clock = clock

    @classmethod
    def load(
        cls,
        manifest_file: Path,
        *,
        expected_manifest_sha256: str,
        study_ref: str,
        consumer_age_scope: str,
        clock: Callable[[], datetime] | None = None,
    ) -> ResearchStudentSourceRegistry:
        selected_clock = clock or (lambda: datetime.now(UTC))
        if (
            not isinstance(manifest_file, Path)
            or not manifest_file.is_absolute()
            or manifest_file.is_symlink()
            or type(expected_manifest_sha256) is not str
            or expected_manifest_sha256 not in _MANIFEST_PIN_BY_SHA256
            or study_ref != PINNED_STUDY_REF
            or consumer_age_scope != PINNED_CONSUMER_AGE_SCOPE
        ):
            raise ResearchStudentQualificationError()
        try:
            file_stat = manifest_file.stat()
            is_reparse_point = os.name == "nt" and bool(
                getattr(file_stat, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            if (
                not manifest_file.is_file()
                or is_reparse_point
                or file_stat.st_size < 1
                or file_stat.st_size > _MAX_MANIFEST_BYTES
            ):
                raise ResearchStudentQualificationError()
            with manifest_file.open("rb") as source_file:
                raw = source_file.read(_MAX_MANIFEST_BYTES + 1)
            if len(raw) > _MAX_MANIFEST_BYTES:
                raise ResearchStudentQualificationError()
        except ResearchStudentQualificationError:
            raise
        except OSError as exc:
            raise ResearchStudentQualificationError() from exc
        return cls.from_bytes(
            raw,
            expected_manifest_sha256=expected_manifest_sha256,
            study_ref=study_ref,
            consumer_age_scope=consumer_age_scope,
            clock=selected_clock,
        )

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        expected_manifest_sha256: str,
        study_ref: str,
        consumer_age_scope: str,
        clock: Callable[[], datetime],
    ) -> ResearchStudentSourceRegistry:
        pin = (
            _MANIFEST_PIN_BY_SHA256.get(expected_manifest_sha256)
            if type(expected_manifest_sha256) is str
            else None
        )
        if (
            type(raw) is not bytes
            or not raw
            or len(raw) > _MAX_MANIFEST_BYTES
            or pin is None
            or study_ref != PINNED_STUDY_REF
            or consumer_age_scope != PINNED_CONSUMER_AGE_SCOPE
            or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), pin.sha256)
        ):
            raise ResearchStudentQualificationError()
        try:
            manifest = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_duplicate_rejecting_object,
                parse_constant=_reject_nonfinite,
            )
        except ResearchStudentQualificationError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ResearchStudentQualificationError() from exc
        if type(manifest) is not dict or set(manifest) != _TOP_LEVEL_KEYS:
            raise ResearchStudentQualificationError()
        _validate_package_metadata(manifest, study_ref=study_ref, pin=pin)
        sources = _parse_sources(manifest["sources"])
        records = _parse_records(manifest["records"], sources)
        registry = cls(
            manifest_sha256=pin.sha256,
            sources=sources,
            records=records,
            clock=clock,
            _verified_token=_REGISTRY_TOKEN,
        )
        if not registry.is_active():
            raise ResearchStudentQualificationError("RESEARCH_STUDY_EXPIRED")
        return registry

    def is_active(self) -> bool:
        try:
            now = self._clock()
        except Exception:
            return False
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
            return False
        return now.astimezone(UTC) <= STUDY_END_UTC

    def allows_chunk(self, content: str, metadata: Mapping[str, Any]) -> bool:
        if not self.is_active() or type(content) is not str or type(metadata) is not dict:
            return False
        expected_keys = {
            "source_id",
            "record_id",
            "content_hash",
            "manifest_sha256",
            "rights_scope_note",
            "review_status",
            "rights_status",
            "role_scope",
            "population_scope",
            "risk_scope",
        }
        if set(metadata) != expected_keys:
            return False
        record_id = metadata.get("record_id")
        source_id = metadata.get("source_id")
        record = self._records.get(record_id) if type(record_id) is str else None
        source = self._sources.get(source_id) if type(source_id) is str else None
        if record is None or source is None:
            return False
        try:
            actual_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        except UnicodeEncodeError:
            return False
        return (
            source_id == record.source_id
            and source.eligible is True
            and source.rights_status == "VERIFIED_WITH_CONDITIONS"
            and metadata.get("manifest_sha256") == self.manifest_sha256
            and metadata.get("rights_scope_note") == source.rights_scope_note
            and record.eligible is True
            and record.min_age is not None
            and record.max_age is not None
            and record.consumer_min_age <= 14
            and record.consumer_max_age >= 17
            and record.min_age <= 14
            and record.max_age >= 17
            and content == record.text
            and _is_sha256(metadata.get("content_hash"))
            and hmac.compare_digest(actual_sha, record.content_sha256)
            and hmac.compare_digest(actual_sha, metadata["content_hash"])
            and metadata.get("review_status") == "pending"
            and metadata.get("rights_status") == "verified"
            and metadata.get("role_scope") == ["student"]
            and metadata.get("population_scope") == ["secondary_school_student"]
            and metadata.get("risk_scope") == ["normal"]
        )


class ResearchStudentRetrievalSafetyAdapter(RetrievalSafetyAdapter):
    """Research-only composition; the standard adapter remains approved-only."""

    component = "research_student_retrieval_safety"
    version = "1.0-research-student"
    integration_status = "RESEARCH_ONLY"

    def __init__(
        self,
        privacy: PresidioPrivacyAdapter,
        registry: ResearchStudentSourceRegistry,
    ) -> None:
        self.registry = registry
        super().__init__(privacy, source_eligibility=registry.allows_chunk)


def _validate_package_metadata(
    manifest: dict[str, Any], *, study_ref: str, pin: _ManifestPin
) -> None:
    if (
        manifest.get("schema_version") != "psynova.school-research-student-knowledge.v1"
        or manifest.get("package_id") != pin.package_id
        or manifest.get("package_status") != "ENGINEERING_REVIEWED_RESEARCH_ONLY"
        or manifest.get("reviewer_kind") != "AI_ENGINEERING"
        or manifest.get("review_ref") != pin.review_ref
        or manifest.get("consumer_scope") != "secondary_school_student_13_18"
        or manifest.get("study_ref") != study_ref
        or manifest.get("review_status") != "pending"
        or manifest.get("role_scope") != ["student"]
        or manifest.get("risk_scope") != ["normal"]
    ):
        raise ResearchStudentQualificationError()
    flags = manifest.get("flags")
    if (
        type(flags) is not dict
        or set(flags) != _FLAG_KEYS
        or any(value is not False for value in flags.values())
    ):
        raise ResearchStudentQualificationError()
    use_policy = manifest.get("use_policy")
    if type(use_policy) is not dict or set(use_policy) != _USE_POLICY_KEYS:
        raise ResearchStudentQualificationError()
    if (
        use_policy.get("scope") != "ISOLATED_GENERAL_EDUCATION_SIMULATION"
        or use_policy.get("noncommercial") is not True
        or use_policy.get("valid_through") != "2027-06-30T15:59:59Z"
        or use_policy.get("audience") != "Fictional secondary-school student simulation only"
        or use_policy.get("allowed_content")
        != "English source excerpts and source-bound general educational information only"
        or use_policy.get("prohibited_content")
        != [
            "individualized advice",
            "assessment score interpretation",
            "diagnosis",
            "treatment",
            "crisis or risk inference",
            "claims of guaranteed personal outcome",
        ]
        or use_policy.get("language")
        != "Preserve source wording in English; no translation is represented as source text."
        or _parse_utc(use_policy["valid_through"]) != STUDY_END_UTC
    ):
        raise ResearchStudentQualificationError()


def _parse_sources(value: Any) -> dict[str, _Source]:
    if type(value) is not list or len(value) != len(_SOURCE_SPEC):
        raise ResearchStudentQualificationError()
    result: dict[str, _Source] = {}
    for item in value:
        if type(item) is not dict or set(item) != _SOURCE_KEYS:
            raise ResearchStudentQualificationError()
        source_id = item.get("source_id")
        spec = _SOURCE_SPEC.get(source_id) if type(source_id) is str else None
        if spec is None or source_id in result:
            raise ResearchStudentQualificationError()
        population, min_age, max_age, rights_status, eligible = spec
        required_strings = (
            "title",
            "canonical_url",
            "publisher",
            "publication_date",
            "source_language",
            "license",
            "license_url",
            "attribution",
            "rights_evidence_url",
            "rights_scope_note",
        )
        if any(not _is_nonempty_string(item.get(key)) for key in required_strings):
            raise ResearchStudentQualificationError()
        if (
            item.get("source_population_scope") != population
            or item.get("source_language") != "English"
            or item.get("rights_status") != rights_status
            or type(item.get("student_retrieval_eligible")) is not bool
            or item.get("student_retrieval_eligible") is not eligible
            or not _is_sha256(item.get("rights_evidence_sha256"))
            or (
                item.get("source_capture_sha256") is not None
                and not _is_sha256(item.get("source_capture_sha256"))
            )
        ):
            raise ResearchStudentQualificationError()
        result[source_id] = _Source(
            source_id,
            min_age,
            max_age,
            rights_status,
            item["rights_scope_note"],
            eligible,
        )
    return result


def _parse_records(value: Any, sources: Mapping[str, _Source]) -> dict[str, _Record]:
    if type(value) is not list or len(value) != len(_RECORD_SPEC):
        raise ResearchStudentQualificationError()
    result: dict[str, _Record] = {}
    for item in value:
        if type(item) is not dict or set(item) != _RECORD_KEYS:
            raise ResearchStudentQualificationError()
        record_id = item.get("record_id")
        spec = _RECORD_SPEC.get(record_id) if type(record_id) is str else None
        if spec is None or record_id in result:
            raise ResearchStudentQualificationError()
        source_id, population, consumer_scope, min_age, max_age, eligible = spec
        if source_id not in sources:
            raise ResearchStudentQualificationError()
        content = item.get("text")
        if (
            item.get("source_id") != source_id
            or item.get("source_population_scope") != population
            or item.get("consumer_scope") != consumer_scope
            or item.get("student_retrieval_eligible") is not eligible
            or type(item.get("student_retrieval_eligible")) is not bool
            or item.get("layer") not in {"policy", "theory", "intervention"}
            or item.get("language") != "English"
            or not _is_nonempty_string(content)
            or not _is_nonempty_string(item.get("locator"))
            or not _is_nonempty_string(item.get("certainty"))
            or not _is_nonempty_string(item.get("role_fit"))
            or not _is_sha256(item.get("excerpt_sha256"))
        ):
            raise ResearchStudentQualificationError()
        actual_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual_sha, item["excerpt_sha256"]):
            raise ResearchStudentQualificationError()
        consumer_min, consumer_max = _consumer_age_range(consumer_scope)
        result[record_id] = _Record(
            record_id=record_id,
            source_id=source_id,
            text=content,
            content_sha256=actual_sha,
            min_age=min_age,
            max_age=max_age,
            consumer_min_age=consumer_min,
            consumer_max_age=consumer_max,
            eligible=eligible,
        )
    return result


def _consumer_age_range(value: str) -> tuple[int, int]:
    ranges = {
        "secondary_school_student_13_17": (13, 17),
        "secondary_school_student_13_18": (13, 18),
    }
    try:
        return ranges[value]
    except (KeyError, TypeError) as exc:
        raise ResearchStudentQualificationError() from exc
