"""Pinned, isolated school-student general-education source retrieval.

This lane is separate from the staff-only research package and from the live
Knowledge v1 index. It keeps source review status pending and carries source
rights/population metadata from an exact-hash-pinned package.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from rag_engine.domain import KnowledgeRecord, MetadataFilter
from rag_engine.exceptions import ProviderUnavailableError
from rag_engine.sparse import BM25SRetriever

PACKAGE_SCHEMA = "psynova.school-research-student-knowledge.v1"
PACKAGE_STATUS = "ENGINEERING_REVIEWED_RESEARCH_ONLY"
PACKAGE_CONSUMER_SCOPE = "secondary_school_student_13_18"
CONSUMER_SCOPE = "secondary_school_student"
CONSUMER_AGE_MIN = 14
CONSUMER_AGE_MAX = 17
STUDENT_STUDY_REF = "school-noncommercial-rag-research-2027-06"
ROLE_SCOPE = "student"
RISK_SCOPE = "normal"
REVIEW_STATUS = "pending"
MAX_PACKAGE_BYTES = 256 * 1024
MAX_RECORDS = 100
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_RECORD_CONSUMER_SCOPE = re.compile(r"^secondary_school_student_([0-9]{1,2})_([0-9]{1,2})$")
_IDENTITY_PATTERNS = (
    re.compile(r"\bSUBJ_[A-Za-z0-9_.-]+\b", re.IGNORECASE),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.IGNORECASE),
    re.compile(r"(?<!\d)\d{7,}(?!\d)"),
)
_LAYERS = frozenset({"policy", "theory", "intervention"})
_LAYER_ORDER = ("policy", "theory", "intervention")
_QUERY_TRANSFORM_NONE = "NONE"
_QUERY_TRANSFORM_BILINGUAL = "LEXICAL_BILINGUAL_KEYWORD_EXPANSION"
_BILINGUAL_QUERY_TERMS = (
    ("心理健康", ("adolescent", "mental", "health")),
    ("校园", ("school",)),
    ("学校", ("school",)),
    ("归属感", ("connectedness",)),
    ("归属", ("connectedness",)),
    ("同学关系", ("connectedness", "peers", "teachers")),
    ("同学", ("peers",)),
    ("同伴", ("peers",)),
    ("关系", ("connectedness", "peers", "teachers")),
    ("身体活动", ("physical", "activity")),
    ("运动", ("physical", "activity")),
    ("活动", ("activity",)),
    ("休息", ("sleep",)),
    ("睡眠", ("sleep",)),
    ("作息", ("sleep",)),
    # The pinned WHO policy excerpt uses this exact policy framing.
    ("支持", ("protect", "promote", "adolescent", "mental", "health")),
)
_MAX_QUERY_CHARS = 20_000

_ROOT_KEYS = frozenset(
    {
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
)
_POLICY_KEYS = frozenset(
    {
        "scope",
        "noncommercial",
        "valid_through",
        "audience",
        "allowed_content",
        "prohibited_content",
        "language",
    }
)
_FLAG_KEYS = frozenset(
    {
        "human_curated",
        "professional_approval",
        "ethics_approval",
        "clinical_approval",
        "psychometric_approval",
        "publication_eligible",
        "production_use",
    }
)
_SOURCE_KEYS = frozenset(
    {
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
)
_RECORD_KEYS = frozenset(
    {
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
)
_ELIGIBLE_RIGHTS = "VERIFIED_WITH_CONDITIONS"
_ALLOWED_RIGHTS = frozenset({_ELIGIBLE_RIGHTS, "PENDING"})
_VALIDATED_PACKAGE_TOKEN = object()


class SchoolStudentPackageError(ValueError):
    """Stable error for an invalid or unauthorized school-student package."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SchoolStudentSource:
    source_id: str
    title: str
    canonical_url: str
    publisher: str
    publication_date: str
    source_population_scope: str
    source_language: str
    license: str
    license_url: str
    attribution: str
    rights_evidence_url: str
    rights_evidence_sha256: str
    rights_status: str
    rights_scope_note: str
    student_retrieval_eligible: bool
    source_capture_sha256: str | None


@dataclass(frozen=True, slots=True)
class SchoolStudentRecord:
    record_id: str
    source_id: str
    layer: str
    text: str
    locator: str
    excerpt_sha256: str
    source_population_scope: str
    consumer_scope: str
    language: str
    certainty: str
    role_fit: str
    student_retrieval_eligible: bool


@dataclass(frozen=True, slots=True)
class SchoolStudentPackage:
    package_id: str
    study_ref: str
    manifest_sha256: str
    valid_through: datetime
    sources: tuple[SchoolStudentSource, ...]
    records: tuple[SchoolStudentRecord, ...]
    _validation_token: object = field(repr=False, compare=False)

    @property
    def eligible_records(self) -> tuple[SchoolStudentRecord, ...]:
        # This service does not receive verified individual ages, so it can
        # only retrieve records explicitly scoped to the full configured lane.
        return tuple(
            record
            for record in self.records
            if record.student_retrieval_eligible
            and _record_scope_covers_lane(record.consumer_scope)
        )


@dataclass(frozen=True, slots=True)
class SchoolStudentCitation:
    source_id: str
    title: str
    publisher: str
    canonical_url: str
    locator: str
    license: str
    license_url: str
    attribution: str
    rights_scope_note: str
    source_population_scope: str
    excerpt_sha256: str


@dataclass(frozen=True, slots=True)
class SchoolStudentHit:
    record_id: str
    chunk_id: str
    layer: str
    text: str
    citation: SchoolStudentCitation
    lexical_score: float


@dataclass(frozen=True, slots=True)
class SchoolStudentRetrievalResult:
    status: str
    package_id: str
    manifest_sha256: str
    study_ref: str
    consumer_scope: str
    consumer_age_min: int
    consumer_age_max: int
    review_status: str
    rights_status: str
    source_rights_status: str
    query_transform: str
    matched_layers: tuple[str, ...]
    missing_layers: tuple[str, ...]
    hits: tuple[SchoolStudentHit, ...]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SchoolStudentPackageError("STUDENT_PACKAGE_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise SchoolStudentPackageError("STUDENT_PACKAGE_NONFINITE_NUMBER")


def _record_scope_covers_lane(value: str) -> bool:
    match = _RECORD_CONSUMER_SCOPE.fullmatch(value)
    if match is None:
        return False
    return int(match.group(1)) <= CONSUMER_AGE_MIN and int(match.group(2)) >= CONSUMER_AGE_MAX


def _expand_bilingual_query(query: str) -> tuple[str, str]:
    """Append only source-backed English terms for recognized Chinese topics."""

    selected: list[str] = []
    seen: set[str] = set()
    for chinese_term, english_terms in _BILINGUAL_QUERY_TERMS:
        if chinese_term not in query:
            continue
        for term in english_terms:
            if term not in seen:
                seen.add(term)
                selected.append(term)
    if not selected:
        return query, _QUERY_TRANSFORM_NONE
    suffix = " ".join(selected)
    expanded = f"{query} {suffix}"
    if len(expanded) > _MAX_QUERY_CHARS:
        return query, _QUERY_TRANSFORM_NONE
    return expanded, _QUERY_TRANSFORM_BILINGUAL


def _object(value: object, keys: frozenset[str], code: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SchoolStudentPackageError(code)
    return value


def _string(value: object, code: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise SchoolStudentPackageError(code)
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
        raise SchoolStudentPackageError(code)
    return value


def _hash(value: object, code: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise SchoolStudentPackageError(code)
    return value


def _https_url(value: object, code: str) -> str:
    result = _string(value, code, maximum=2048)
    parsed = urlparse(result)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SchoolStudentPackageError(code)
    return result


def _safe_id(value: object, code: str) -> str:
    result = _string(value, code, maximum=128)
    if not _SAFE_ID.fullmatch(result):
        raise SchoolStudentPackageError(code)
    return result


def load_school_student_package(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    expected_study_ref: str,
    now: datetime | None = None,
) -> SchoolStudentPackage:
    """Load one exact pinned student package; the file cannot self-authorize."""

    _hash(expected_manifest_sha256, "STUDENT_EXPECTED_HASH_INVALID")
    if type(expected_study_ref) is not str or expected_study_ref != STUDENT_STUDY_REF:
        raise SchoolStudentPackageError("STUDENT_STUDY_PIN_INVALID")
    try:
        raw = Path(manifest_path).read_bytes()
    except OSError as exc:
        raise SchoolStudentPackageError("STUDENT_PACKAGE_UNREADABLE") from exc
    if len(raw) > MAX_PACKAGE_BYTES:
        raise SchoolStudentPackageError("STUDENT_PACKAGE_TOO_LARGE")
    actual_hash = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_hash, expected_manifest_sha256):
        raise SchoolStudentPackageError("STUDENT_PACKAGE_HASH_MISMATCH")
    try:
        root_value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except SchoolStudentPackageError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SchoolStudentPackageError("STUDENT_PACKAGE_JSON_INVALID") from exc

    root = _object(root_value, _ROOT_KEYS, "STUDENT_PACKAGE_SCHEMA_INVALID")
    if (
        root["schema_version"] != PACKAGE_SCHEMA
        or root["package_status"] != PACKAGE_STATUS
        or root["reviewer_kind"] != "AI_ENGINEERING"
        or root["consumer_scope"] != PACKAGE_CONSUMER_SCOPE
        or root["study_ref"] != expected_study_ref
        or root["role_scope"] != [ROLE_SCOPE]
        or root["risk_scope"] != [RISK_SCOPE]
        or root["review_status"] != REVIEW_STATUS
    ):
        raise SchoolStudentPackageError("STUDENT_PACKAGE_SCOPE_INVALID")
    package_id = _safe_id(root["package_id"], "STUDENT_PACKAGE_ID_INVALID")
    _string(root["review_ref"], "STUDENT_REVIEW_REF_INVALID", maximum=128)

    policy = _object(root["use_policy"], _POLICY_KEYS, "STUDENT_POLICY_SCHEMA_INVALID")
    if (
        policy["scope"] != "ISOLATED_GENERAL_EDUCATION_SIMULATION"
        or policy["noncommercial"] is not True
        or policy["audience"] != "Fictional secondary-school student simulation only"
        or policy["allowed_content"]
        != "English source excerpts and source-bound general educational information only"
        or policy["prohibited_content"]
        != [
            "individualized advice",
            "assessment score interpretation",
            "diagnosis",
            "treatment",
            "crisis or risk inference",
            "claims of guaranteed personal outcome",
        ]
        or policy["language"]
        != "Preserve source wording in English; no translation is represented as source text."
    ):
        raise SchoolStudentPackageError("STUDENT_POLICY_SCOPE_INVALID")
    flags = _object(root["flags"], _FLAG_KEYS, "STUDENT_PACKAGE_FLAGS_INVALID")
    if any(flags[key] is not False for key in _FLAG_KEYS):
        raise SchoolStudentPackageError("STUDENT_PACKAGE_FLAGS_INVALID")
    valid_through_raw = _string(
        policy["valid_through"], "STUDENT_POLICY_EXPIRY_INVALID", maximum=40
    )
    try:
        valid_through = datetime.fromisoformat(valid_through_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchoolStudentPackageError("STUDENT_POLICY_EXPIRY_INVALID") from exc
    if valid_through.tzinfo is None or valid_through.utcoffset() is None:
        raise SchoolStudentPackageError("STUDENT_POLICY_EXPIRY_INVALID")
    valid_through = valid_through.astimezone(UTC)
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise SchoolStudentPackageError("STUDENT_CLOCK_INVALID")
    if checked_at.astimezone(UTC) > valid_through:
        raise SchoolStudentPackageError("STUDENT_PACKAGE_EXPIRED")

    source_values = root["sources"]
    if type(source_values) is not list or not 1 <= len(source_values) <= MAX_RECORDS:
        raise SchoolStudentPackageError("STUDENT_SOURCE_SET_INVALID")
    sources: dict[str, SchoolStudentSource] = {}
    for raw_source in source_values:
        source = _object(raw_source, _SOURCE_KEYS, "STUDENT_SOURCE_SCHEMA_INVALID")
        source_id = _safe_id(source["source_id"], "STUDENT_SOURCE_ID_INVALID")
        if source_id in sources:
            raise SchoolStudentPackageError("STUDENT_SOURCE_SET_INVALID")
        rights_status = _string(
            source["rights_status"], "STUDENT_SOURCE_RIGHTS_INVALID", maximum=64
        )
        eligible = source["student_retrieval_eligible"]
        if rights_status not in _ALLOWED_RIGHTS or type(eligible) is not bool:
            raise SchoolStudentPackageError("STUDENT_SOURCE_RIGHTS_INVALID")
        if eligible and rights_status != _ELIGIBLE_RIGHTS:
            raise SchoolStudentPackageError("STUDENT_SOURCE_RIGHTS_INVALID")
        language = _string(source["source_language"], "STUDENT_SOURCE_LANGUAGE_INVALID", maximum=16)
        if language != "English":
            raise SchoolStudentPackageError("STUDENT_SOURCE_LANGUAGE_INVALID")
        sources[source_id] = SchoolStudentSource(
            source_id=source_id,
            title=_string(source["title"], "STUDENT_SOURCE_TITLE_INVALID", maximum=512),
            canonical_url=_https_url(source["canonical_url"], "STUDENT_SOURCE_URL_INVALID"),
            publisher=_string(source["publisher"], "STUDENT_SOURCE_PUBLISHER_INVALID", maximum=256),
            publication_date=_string(
                source["publication_date"], "STUDENT_SOURCE_DATE_INVALID", maximum=32
            ),
            source_population_scope=_string(
                source["source_population_scope"], "STUDENT_SOURCE_POPULATION_INVALID", maximum=512
            ),
            source_language=language,
            license=_string(source["license"], "STUDENT_SOURCE_LICENSE_INVALID", maximum=256),
            license_url=_https_url(source["license_url"], "STUDENT_SOURCE_LICENSE_URL_INVALID"),
            attribution=_string(
                source["attribution"], "STUDENT_SOURCE_ATTRIBUTION_INVALID", maximum=2048
            ),
            rights_evidence_url=_https_url(
                source["rights_evidence_url"], "STUDENT_RIGHTS_EVIDENCE_URL_INVALID"
            ),
            rights_evidence_sha256=_hash(
                source["rights_evidence_sha256"], "STUDENT_RIGHTS_EVIDENCE_HASH_INVALID"
            ),
            rights_status=rights_status,
            rights_scope_note=_string(
                source["rights_scope_note"], "STUDENT_SOURCE_RIGHTS_SCOPE_INVALID", maximum=1024
            ),
            student_retrieval_eligible=eligible,
            source_capture_sha256=(
                _hash(source["source_capture_sha256"], "STUDENT_SOURCE_CAPTURE_HASH_INVALID")
                if source["source_capture_sha256"] is not None
                else None
            ),
        )

    record_values = root["records"]
    if type(record_values) is not list or not 1 <= len(record_values) <= MAX_RECORDS:
        raise SchoolStudentPackageError("STUDENT_RECORD_SET_INVALID")
    records: list[SchoolStudentRecord] = []
    seen_record_ids: set[str] = set()
    for raw_record in record_values:
        record = _object(raw_record, _RECORD_KEYS, "STUDENT_RECORD_SCHEMA_INVALID")
        record_id = _safe_id(record["record_id"], "STUDENT_RECORD_ID_INVALID")
        source_id = _safe_id(record["source_id"], "STUDENT_RECORD_SOURCE_INVALID")
        source = sources.get(source_id)
        if source is None or record_id in seen_record_ids:
            raise SchoolStudentPackageError("STUDENT_RECORD_SOURCE_INVALID")
        seen_record_ids.add(record_id)
        layer = _string(record["layer"], "STUDENT_RECORD_LAYER_INVALID", maximum=32)
        if layer not in _LAYERS:
            raise SchoolStudentPackageError("STUDENT_RECORD_LAYER_INVALID")
        text = _string(record["text"], "STUDENT_RECORD_TEXT_INVALID", maximum=8000)
        excerpt_sha256 = _hash(record["excerpt_sha256"], "STUDENT_EXCERPT_HASH_INVALID")
        if not hmac.compare_digest(
            hashlib.sha256(text.encode("utf-8")).hexdigest(), excerpt_sha256
        ):
            raise SchoolStudentPackageError("STUDENT_EXCERPT_HASH_MISMATCH")
        eligible = record["student_retrieval_eligible"]
        record_consumer_scope = record["consumer_scope"]
        scope_match = (
            _RECORD_CONSUMER_SCOPE.fullmatch(record_consumer_scope)
            if type(record_consumer_scope) is str
            else None
        )
        record_min = int(scope_match.group(1)) if scope_match else -1
        record_max = int(scope_match.group(2)) if scope_match else -1
        if (
            type(eligible) is not bool
            or eligible != source.student_retrieval_eligible
            or (eligible and source.rights_status != _ELIGIBLE_RIGHTS)
            or scope_match is None
            or record_min < 13
            or record_max > 18
            or record_min > record_max
            or record["language"] != "English"
        ):
            raise SchoolStudentPackageError("STUDENT_RECORD_SCOPE_INVALID")
        record_population = _string(
            record["source_population_scope"], "STUDENT_RECORD_POPULATION_INVALID", maximum=512
        )
        records.append(
            SchoolStudentRecord(
                record_id=record_id,
                source_id=source_id,
                layer=layer,
                text=text,
                locator=_string(record["locator"], "STUDENT_RECORD_LOCATOR_INVALID", maximum=1024),
                excerpt_sha256=excerpt_sha256,
                source_population_scope=record_population,
                consumer_scope=record_consumer_scope,
                language="English",
                certainty=_string(
                    record["certainty"], "STUDENT_RECORD_CERTAINTY_INVALID", maximum=1024
                ),
                role_fit=_string(
                    record["role_fit"], "STUDENT_RECORD_ROLE_FIT_INVALID", maximum=1024
                ),
                student_retrieval_eligible=eligible,
            )
        )
    eligible_layers = {
        record.layer
        for record in records
        if record.student_retrieval_eligible and _record_scope_covers_lane(record.consumer_scope)
    }
    if not _LAYERS.issubset(eligible_layers):
        raise SchoolStudentPackageError("STUDENT_PACKAGE_LAYER_COVERAGE_INVALID")

    return SchoolStudentPackage(
        package_id=package_id,
        study_ref=expected_study_ref,
        manifest_sha256=actual_hash,
        valid_through=valid_through,
        sources=tuple(sources.values()),
        records=tuple(records),
        _validation_token=_VALIDATED_PACKAGE_TOKEN,
    )


class SchoolStudentEducationRetriever:
    """Ephemeral BM25S over only records eligible under a pinned student package."""

    def __init__(self, package: SchoolStudentPackage) -> None:
        if (
            not isinstance(package, SchoolStudentPackage)
            or package._validation_token is not _VALIDATED_PACKAGE_TOKEN
        ):
            raise SchoolStudentPackageError("STUDENT_PACKAGE_REQUIRED")
        self.package = package
        self._sources = {source.source_id: source for source in package.sources}
        self._records = {self._chunk_id(record): record for record in package.eligible_records}
        bm25_records = [self._to_knowledge_record(record) for record in package.eligible_records]
        if not bm25_records:
            raise SchoolStudentPackageError("STUDENT_PACKAGE_HAS_NO_ELIGIBLE_RECORDS")
        self._lexical = BM25SRetriever(bm25_records)
        try:
            self._lexical.build()
        except ProviderUnavailableError as exc:
            raise SchoolStudentPackageError("STUDENT_LEXICAL_PROVIDER_UNAVAILABLE") from exc

    @staticmethod
    def _chunk_id(record: SchoolStudentRecord) -> str:
        return f"CHUNK_SCHOOL_RESEARCH_{record.record_id}"

    @staticmethod
    def _to_knowledge_record(record: SchoolStudentRecord) -> KnowledgeRecord:
        chunk_id = SchoolStudentEducationRetriever._chunk_id(record)
        source_component = hashlib.sha256(record.source_id.encode("utf-8")).hexdigest()[:24]
        source_population = record.source_population_scope
        metadata = {
            "target_population": [CONSUMER_SCOPE],
            "role_scope": [ROLE_SCOPE],
            "risk_scope": [RISK_SCOPE],
            "review_status": REVIEW_STATUS,
            "rights_status": "verified",
            "content_type": "source_excerpt",
            "content_hash": f"sha256:{record.excerpt_sha256}",
            "source_filename": record.source_id,
            "section": record.locator,
            "source_population_scope": source_population,
            "student_research_lane": True,
        }
        return KnowledgeRecord(
            chunk_id=chunk_id,
            document_id=f"KB_STUDENT_RESEARCH_{source_component}",
            text=record.text,
            context_text=record.text,
            metadata=metadata,
            citation={
                "title": "Student research source",
                "organization": "Pinned source package",
                "locator": record.locator,
            },
            layer=record.layer,
        )

    def retrieve(
        self,
        query: str,
        *,
        target_population: str,
        limit: int = 8,
        now: datetime | None = None,
    ) -> SchoolStudentRetrievalResult:
        if target_population != CONSUMER_SCOPE:
            raise SchoolStudentPackageError("STUDENT_POPULATION_NOT_AUTHORIZED")
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise SchoolStudentPackageError("STUDENT_CLOCK_INVALID")
        if current.astimezone(UTC) > self.package.valid_through:
            raise SchoolStudentPackageError("STUDENT_PACKAGE_EXPIRED")
        if type(query) is not str or not query.strip() or len(query) > _MAX_QUERY_CHARS:
            raise SchoolStudentPackageError("STUDENT_QUERY_INVALID")
        if any(pattern.search(query) for pattern in _IDENTITY_PATTERNS):
            raise SchoolStudentPackageError("STUDENT_QUERY_IDENTITY_TOKEN")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 8:
            raise SchoolStudentPackageError("STUDENT_LIMIT_INVALID")
        search_query, query_transform = _expand_bilingual_query(query.strip())
        try:
            hits = self._lexical.search(
                search_query,
                limit=limit,
                filters=MetadataFilter(
                    review_status=(),
                    rights_status=(),
                    role_scope=(ROLE_SCOPE,),
                    target_population=(CONSUMER_SCOPE,),
                    risk_scope=(RISK_SCOPE,),
                ),
            )
        except ProviderUnavailableError as exc:
            raise SchoolStudentPackageError("STUDENT_LEXICAL_SEARCH_FAILED") from exc
        projected: list[SchoolStudentHit] = []
        for hit in hits:
            record = self._records.get(hit.record.chunk_id)
            source = self._sources.get(record.source_id) if record else None
            if (
                record is None
                or source is None
                or hit.sparse_score is None
                or hit.sparse_score <= 0
            ):
                continue
            projected.append(
                SchoolStudentHit(
                    record_id=record.record_id,
                    chunk_id=hit.record.chunk_id,
                    layer=record.layer,
                    text=record.text,
                    citation=SchoolStudentCitation(
                        source_id=source.source_id,
                        title=source.title,
                        publisher=source.publisher,
                        canonical_url=source.canonical_url,
                        locator=(
                            f"{record.locator}; source population: {record.source_population_scope}"
                        ),
                        license=source.license,
                        license_url=source.license_url,
                        attribution=source.attribution,
                        rights_scope_note=source.rights_scope_note,
                        source_population_scope=record.source_population_scope,
                        excerpt_sha256=record.excerpt_sha256,
                    ),
                    lexical_score=float(hit.sparse_score),
                )
            )
        matched_layers = tuple(
            layer for layer in _LAYER_ORDER if any(hit.layer == layer for hit in projected)
        )
        missing_layers = tuple(layer for layer in _LAYER_ORDER if layer not in matched_layers)
        return SchoolStudentRetrievalResult(
            status="MATCHES" if projected else "NO_MATCHES",
            package_id=self.package.package_id,
            manifest_sha256=self.package.manifest_sha256,
            study_ref=self.package.study_ref,
            consumer_scope=CONSUMER_SCOPE,
            consumer_age_min=CONSUMER_AGE_MIN,
            consumer_age_max=CONSUMER_AGE_MAX,
            review_status=REVIEW_STATUS,
            rights_status="verified",
            source_rights_status=_ELIGIBLE_RIGHTS,
            query_transform=query_transform,
            matched_layers=matched_layers,
            missing_layers=missing_layers,
            hits=tuple(projected),
        )


__all__ = [
    "CONSUMER_AGE_MAX",
    "CONSUMER_AGE_MIN",
    "CONSUMER_SCOPE",
    "PACKAGE_CONSUMER_SCOPE",
    "PACKAGE_SCHEMA",
    "REVIEW_STATUS",
    "RISK_SCOPE",
    "ROLE_SCOPE",
    "STUDENT_STUDY_REF",
    "SchoolStudentEducationRetriever",
    "SchoolStudentPackage",
    "SchoolStudentPackageError",
    "SchoolStudentRetrievalResult",
    "load_school_student_package",
]
