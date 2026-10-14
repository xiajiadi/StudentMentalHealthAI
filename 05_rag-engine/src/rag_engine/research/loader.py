"""Closed loader for pinned, isolated AI-engineering research material.

This format is deliberately separate from Knowledge v1. It does not emit
embedding-ready records and cannot express production or professional approval.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE_SCHEMA = "psynova.research-only-knowledge.v1"
PACKAGE_STATUS = "AI_ENGINEERING_APPROVED_FOR_ISOLATED_RESEARCH_ONLY"
PACKAGE_ID = "school-rag-ai-engineering-20261014-v1"
REVIEW_REF = "school-rag-review-20261014-r1"
PACKAGE_SCOPE = "ISOLATED_GENERAL_EDUCATION_SIMULATION"
STUDY_REF = "school-noncommercial-rag-research-2027-06"
SOURCE_PACKET_SHA256 = "63928edd03beac609da5ae5039d04046d17c33249291c0a642b258897cee4ca7"
SOURCE_ADDENDUM_SHA256 = "1f34e1a48557c7c0034586ef87940cec35449373fb7eafa4448dbaf6509b1163"
SOURCE_ENGINEERING_REVIEW_SHA256 = "3b867fb51c014ca1b0a6567e513230190692bb7c2f83584d5619f9c912c1f7cc"
USE_SCOPE = "This external research package and isolated noncommercial school-programme retrieval through 2027-06 only."
OUTPUT_BOUNDARY = (
    "staff research reference only; no individual scoring, interpretation, diagnosis, "
    "crisis/risk inference, personal feedback, or automated report"
)
REQUIRED_RECORD_IDS = frozenset(
    {
        "WHO-HAT-STRATEGY1-POLICY-2021",
        "WHO-HAT-SCHOOL-ENVIRONMENT-OBJECTIVE-2021",
        "WHO-HAT-SCHOOL-CLIMATE-SUPPORT-2021",
        "RAG-THEORY-002",
    }
)
SPECIALIST_ROLE = "psychological_specialist"
POPULATION_SCOPE = "adolescent_school_programme_research"
RISK_SCOPE = "general_education_only"
MAX_PACKAGE_BYTES = 256 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "package_id",
        "package_status",
        "review_ref",
        "reviewer_kind",
        "review_decision_scope",
        "human_curated",
        "professional_approval",
        "ethics_approval",
        "clinical_approval",
        "psychometric_approval",
        "publication_eligible",
        "production_use",
        "live_corpus_changed",
        "scope",
        "source_packet_sha256",
        "source_review_artifacts",
        "use_policy",
        "source_use_terms",
        "retrieval",
        "records",
    }
)
_POLICY_KEYS = frozenset(
    {
        "study_ref",
        "use_mode",
        "noncommercial",
        "valid_through_month",
        "role_scope",
        "population_scope",
        "risk_scope",
        "output_boundary",
    }
)
_TERMS_KEYS = frozenset(
    {
        "allowed_scope",
        "software_license_inference",
        "production_rights_inference",
        "commercial_use_included",
        "attribution_required",
        "sharealike_required_for_who_adaptations",
        "endorsement_claimed",
    }
)
_RETRIEVAL_KEYS = frozenset(
    {
        "kind",
        "lexical_only",
        "embeddings_used",
        "model_called",
        "index_persisted",
        "production_store_used",
    }
)
_RECORD_KEYS = frozenset(
    {
        "record_id",
        "layer",
        "text",
        "excerpt_sha256",
        "source",
        "locator",
        "source_population",
        "certainty",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "title",
        "publisher",
        "year",
        "isbn",
        "doi",
        "source_url",
        "official_pdf_url",
        "license",
        "license_url",
        "rights_listing_url",
        "attribution",
        "source_extraction_sha256",
        "rights_capture_sha256",
        "original_stage_sha256",
    }
)
_REVIEW_PROVENANCE_KEYS = frozenset(
    {"candidate_addendum_sha256", "ai_engineering_review_sha256"}
)
_SOURCE_BY_RECORD = {
    record_id: "WHO-HAT-TOOLKIT-2021"
    for record_id in REQUIRED_RECORD_IDS
    if record_id.startswith("WHO-")
}
_SOURCE_BY_RECORD["RAG-THEORY-002"] = "RAG-THEORY-002"
_LAYER_BY_RECORD = {
    "WHO-HAT-STRATEGY1-POLICY-2021": "policy",
    "WHO-HAT-SCHOOL-ENVIRONMENT-OBJECTIVE-2021": "intervention",
    "WHO-HAT-SCHOOL-CLIMATE-SUPPORT-2021": "intervention",
    "RAG-THEORY-002": "theory",
}
_VALIDATED_PACKAGE_TOKEN = object()


class ResearchPackageError(ValueError):
    """Stable failure for research package loading and authorization."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    title: str
    publisher: str
    year: int
    isbn: str | None
    doi: str | None
    source_url: str
    official_pdf_url: str | None
    license: str
    license_url: str
    rights_listing_url: str | None
    attribution: str
    source_extraction_sha256: str
    rights_capture_sha256: str | None
    original_stage_sha256: str | None


@dataclass(frozen=True)
class ResearchRecord:
    record_id: str
    layer: str
    text: str
    excerpt_sha256: str
    source: ResearchSource
    locator: str
    source_population: str
    certainty: str


@dataclass(frozen=True)
class ResearchUsePolicy:
    study_ref: str
    use_mode: str
    noncommercial: bool
    valid_through_month: str
    role_scope: tuple[str, ...]
    population_scope: tuple[str, ...]
    risk_scope: tuple[str, ...]
    output_boundary: str


@dataclass(frozen=True)
class ResearchPackage:
    package_id: str
    review_ref: str
    scope: str
    manifest_sha256: str
    use_policy: ResearchUsePolicy
    records: tuple[ResearchRecord, ...]
    _validation_token: object = field(repr=False, compare=False)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchPackageError("RESEARCH_PACKAGE_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ResearchPackageError("RESEARCH_PACKAGE_NONFINITE_NUMBER")


def _object(value: Any, expected_keys: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ResearchPackageError(code)
    return value


def _strict_string(value: Any, code: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ResearchPackageError(code)
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
        raise ResearchPackageError(code)
    return value


def _strict_optional_string(value: Any, code: str, *, maximum: int = 4096) -> str | None:
    if value is None:
        return None
    return _strict_string(value, code, maximum=maximum)


def _strict_sha256(value: Any, code: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ResearchPackageError(code)
    return value


def _strict_false(value: Any, code: str) -> None:
    if value is not False:
        raise ResearchPackageError(code)


def _require_month_current(valid_through_month: str, now: date | datetime | None) -> None:
    if now is None:
        current_date = datetime.now(timezone.utc).date()
    elif isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ResearchPackageError("RESEARCH_CLOCK_INVALID")
        current_date = now.astimezone(timezone.utc).date()
    elif type(now) is date:
        current_date = now
    else:
        raise ResearchPackageError("RESEARCH_CLOCK_INVALID")
    current_month = f"{current_date.year:04d}-{current_date.month:02d}"
    if current_month > valid_through_month:
        raise ResearchPackageError("RESEARCH_PACKAGE_EXPIRED")


def load_research_package(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    now: date | datetime | None = None,
) -> ResearchPackage:
    """Load an exact-hash-pinned package after strict closed-schema checks.

    The expected hash must come from a trusted server/controller registry, not
    from the package itself or an untrusted request. No corpus/index is written.
    """

    _strict_sha256(expected_manifest_sha256, "RESEARCH_EXPECTED_HASH_INVALID")
    path = Path(manifest_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ResearchPackageError("RESEARCH_PACKAGE_UNREADABLE") from exc
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ResearchPackageError("RESEARCH_PACKAGE_TOO_LARGE")
    actual_hash = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_hash, expected_manifest_sha256):
        raise ResearchPackageError("RESEARCH_PACKAGE_HASH_MISMATCH")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except ResearchPackageError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ResearchPackageError("RESEARCH_PACKAGE_JSON_INVALID") from exc

    root = _object(value, _ROOT_KEYS, "RESEARCH_PACKAGE_SCHEMA_INVALID")
    fixed_strings = {
        "schema_version": PACKAGE_SCHEMA,
        "package_status": PACKAGE_STATUS,
        "reviewer_kind": "AI_ENGINEERING",
        "review_decision_scope": "isolated_noncommercial_school_programme_research",
    }
    for key, expected in fixed_strings.items():
        if root[key] != expected:
            raise ResearchPackageError("RESEARCH_PACKAGE_APPROVAL_SCOPE_INVALID")
    for key in (
        "human_curated",
        "professional_approval",
        "ethics_approval",
        "clinical_approval",
        "psychometric_approval",
        "publication_eligible",
        "production_use",
        "live_corpus_changed",
    ):
        _strict_false(root[key], "RESEARCH_PACKAGE_APPROVAL_SCOPE_INVALID")

    package_id = _strict_string(root["package_id"], "RESEARCH_PACKAGE_ID_INVALID", maximum=128)
    review_ref = _strict_string(root["review_ref"], "RESEARCH_REVIEW_REF_INVALID", maximum=128)
    if package_id != PACKAGE_ID or review_ref != REVIEW_REF:
        raise ResearchPackageError("RESEARCH_PACKAGE_ID_INVALID")
    if root["scope"] != PACKAGE_SCOPE:
        raise ResearchPackageError("RESEARCH_PACKAGE_SCOPE_INVALID")
    source_packet_sha256 = _strict_sha256(root["source_packet_sha256"], "RESEARCH_SOURCE_PACKET_HASH_INVALID")
    if source_packet_sha256 != SOURCE_PACKET_SHA256:
        raise ResearchPackageError("RESEARCH_SOURCE_PACKET_HASH_INVALID")
    review_provenance = _object(
        root["source_review_artifacts"],
        _REVIEW_PROVENANCE_KEYS,
        "RESEARCH_REVIEW_PROVENANCE_INVALID",
    )
    if (
        _strict_sha256(review_provenance["candidate_addendum_sha256"], "RESEARCH_REVIEW_PROVENANCE_INVALID")
        != SOURCE_ADDENDUM_SHA256
        or _strict_sha256(review_provenance["ai_engineering_review_sha256"], "RESEARCH_REVIEW_PROVENANCE_INVALID")
        != SOURCE_ENGINEERING_REVIEW_SHA256
    ):
        raise ResearchPackageError("RESEARCH_REVIEW_PROVENANCE_INVALID")

    policy = _object(root["use_policy"], _POLICY_KEYS, "RESEARCH_POLICY_SCHEMA_INVALID")
    if (
        policy["use_mode"] != "SCHOOL_NONCOMMERCIAL_RESEARCH"
        or policy["noncommercial"] is not True
        or policy["role_scope"] != [SPECIALIST_ROLE]
        or policy["population_scope"] != [POPULATION_SCOPE]
        or policy["risk_scope"] != [RISK_SCOPE]
    ):
        raise ResearchPackageError("RESEARCH_POLICY_SCOPE_INVALID")
    valid_through_month = _strict_string(policy["valid_through_month"], "RESEARCH_POLICY_EXPIRY_INVALID", maximum=7)
    if not _MONTH.fullmatch(valid_through_month):
        raise ResearchPackageError("RESEARCH_POLICY_EXPIRY_INVALID")
    study_ref = _strict_string(policy["study_ref"], "RESEARCH_STUDY_REF_INVALID", maximum=128)
    if study_ref != STUDY_REF:
        raise ResearchPackageError("RESEARCH_STUDY_REF_INVALID")
    output_boundary = _strict_string(policy["output_boundary"], "RESEARCH_OUTPUT_BOUNDARY_INVALID")
    if output_boundary != OUTPUT_BOUNDARY:
        raise ResearchPackageError("RESEARCH_OUTPUT_BOUNDARY_INVALID")

    terms = _object(root["source_use_terms"], _TERMS_KEYS, "RESEARCH_LICENSE_SCHEMA_INVALID")
    allowed_scope = _strict_string(terms["allowed_scope"], "RESEARCH_LICENSE_SCOPE_INVALID")
    if allowed_scope != USE_SCOPE:
        raise ResearchPackageError("RESEARCH_LICENSE_SCOPE_INVALID")
    for key in (
        "software_license_inference",
        "production_rights_inference",
        "commercial_use_included",
        "endorsement_claimed",
    ):
        _strict_false(terms[key], "RESEARCH_LICENSE_SCOPE_INVALID")
    if terms["attribution_required"] is not True or terms["sharealike_required_for_who_adaptations"] is not True:
        raise ResearchPackageError("RESEARCH_LICENSE_TERMS_INVALID")

    retrieval = _object(root["retrieval"], _RETRIEVAL_KEYS, "RESEARCH_RETRIEVAL_SCHEMA_INVALID")
    if retrieval != {
        "kind": "IN_MEMORY_EPHEMERAL_BM25S",
        "lexical_only": True,
        "embeddings_used": False,
        "model_called": False,
        "index_persisted": False,
        "production_store_used": False,
    }:
        raise ResearchPackageError("RESEARCH_RETRIEVAL_MODE_INVALID")

    raw_records = root["records"]
    if type(raw_records) is not list or len(raw_records) != len(REQUIRED_RECORD_IDS):
        raise ResearchPackageError("RESEARCH_RECORD_SET_INVALID")
    records: list[ResearchRecord] = []
    seen: set[str] = set()
    for raw_record in raw_records:
        record = _object(raw_record, _RECORD_KEYS, "RESEARCH_RECORD_SCHEMA_INVALID")
        record_id = _strict_string(record["record_id"], "RESEARCH_RECORD_ID_INVALID", maximum=128)
        if record_id not in REQUIRED_RECORD_IDS or record_id in seen:
            raise ResearchPackageError("RESEARCH_RECORD_SET_INVALID")
        seen.add(record_id)
        layer = _strict_string(record["layer"], "RESEARCH_LAYER_INVALID", maximum=32)
        if layer != _LAYER_BY_RECORD[record_id]:
            raise ResearchPackageError("RESEARCH_LAYER_INVALID")
        text = _strict_string(record["text"], "RESEARCH_TEXT_INVALID", maximum=6000)
        excerpt_hash = _strict_sha256(record["excerpt_sha256"], "RESEARCH_EXCERPT_HASH_INVALID")
        if not hmac.compare_digest(hashlib.sha256(text.encode("utf-8")).hexdigest(), excerpt_hash):
            raise ResearchPackageError("RESEARCH_EXCERPT_HASH_MISMATCH")
        source_value = _object(record["source"], _SOURCE_KEYS, "RESEARCH_SOURCE_SCHEMA_INVALID")
        source_id = _strict_string(source_value["source_id"], "RESEARCH_SOURCE_ID_INVALID", maximum=128)
        if source_id != _SOURCE_BY_RECORD[record_id]:
            raise ResearchPackageError("RESEARCH_SOURCE_BINDING_INVALID")
        year = source_value["year"]
        if type(year) is not int or not 1900 <= year <= 2100:
            raise ResearchPackageError("RESEARCH_SOURCE_YEAR_INVALID")
        source_license = _strict_string(source_value["license"], "RESEARCH_LICENSE_INVALID", maximum=128)
        expected_license = "CC BY-NC-SA 3.0 IGO" if source_id.startswith("WHO-") else "CC BY 4.0"
        if source_license != expected_license:
            raise ResearchPackageError("RESEARCH_LICENSE_INVALID")
        source = ResearchSource(
            source_id=source_id,
            title=_strict_string(source_value["title"], "RESEARCH_SOURCE_TITLE_INVALID"),
            publisher=_strict_string(source_value["publisher"], "RESEARCH_SOURCE_PUBLISHER_INVALID"),
            year=year,
            isbn=_strict_optional_string(source_value["isbn"], "RESEARCH_SOURCE_ISBN_INVALID", maximum=64),
            doi=_strict_optional_string(source_value["doi"], "RESEARCH_SOURCE_DOI_INVALID", maximum=128),
            source_url=_strict_string(source_value["source_url"], "RESEARCH_SOURCE_URL_INVALID", maximum=2048),
            official_pdf_url=_strict_optional_string(source_value["official_pdf_url"], "RESEARCH_SOURCE_PDF_URL_INVALID", maximum=2048),
            license=source_license,
            license_url=_strict_string(source_value["license_url"], "RESEARCH_LICENSE_URL_INVALID", maximum=2048),
            rights_listing_url=_strict_optional_string(source_value["rights_listing_url"], "RESEARCH_RIGHTS_URL_INVALID", maximum=2048),
            attribution=_strict_string(source_value["attribution"], "RESEARCH_ATTRIBUTION_INVALID", maximum=2048),
            source_extraction_sha256=_strict_sha256(source_value["source_extraction_sha256"], "RESEARCH_SOURCE_HASH_INVALID"),
            rights_capture_sha256=(
                _strict_sha256(source_value["rights_capture_sha256"], "RESEARCH_RIGHTS_CAPTURE_HASH_INVALID")
                if source_value["rights_capture_sha256"] is not None
                else None
            ),
            original_stage_sha256=(
                _strict_sha256(source_value["original_stage_sha256"], "RESEARCH_ORIGINAL_STAGE_HASH_INVALID")
                if source_value["original_stage_sha256"] is not None
                else None
            ),
        )
        records.append(
            ResearchRecord(
                record_id=record_id,
                layer=layer,
                text=text,
                excerpt_sha256=excerpt_hash,
                source=source,
                locator=_strict_string(record["locator"], "RESEARCH_LOCATOR_INVALID", maximum=1024),
                source_population=_strict_string(record["source_population"], "RESEARCH_SOURCE_POPULATION_INVALID", maximum=512),
                certainty=_strict_string(record["certainty"], "RESEARCH_CERTAINTY_INVALID", maximum=512),
            )
        )
    if seen != REQUIRED_RECORD_IDS:
        raise ResearchPackageError("RESEARCH_RECORD_SET_INVALID")
    _require_month_current(valid_through_month, now)
    use_policy = ResearchUsePolicy(
        study_ref=study_ref,
        use_mode="SCHOOL_NONCOMMERCIAL_RESEARCH",
        noncommercial=True,
        valid_through_month=valid_through_month,
        role_scope=(SPECIALIST_ROLE,),
        population_scope=(POPULATION_SCOPE,),
        risk_scope=(RISK_SCOPE,),
        output_boundary=output_boundary,
    )
    return ResearchPackage(
        package_id=package_id,
        review_ref=review_ref,
        scope=PACKAGE_SCOPE,
        manifest_sha256=actual_hash,
        use_policy=use_policy,
        records=tuple(records),
        _validation_token=_VALIDATED_PACKAGE_TOKEN,
    )
