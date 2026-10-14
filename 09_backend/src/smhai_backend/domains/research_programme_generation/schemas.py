"""Private, strict DTOs for staff-only research programme candidates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

RESEARCH_SCOPE = "ISOLATED_GENERAL_EDUCATION_SIMULATION"
STUDY_REF = "school-noncommercial-rag-research-2027-06"
ROLE_SCOPE = "psychological_specialist"
POPULATION_SCOPE = "adolescent_school_programme_research"
RISK_SCOPE = "general_education_only"
# Local ordering/projection contract; this is not an upstream Safety policy version.
SAFETY_GATE_VERSION = "backend-research-programme-safety-gates.v1"
STUDY_END_UTC = datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC)
EVIDENCE_LIMIT = "POTENTIAL_SCHOOL_PROGRAMME_FRAMEWORKS_ONLY_OUTCOMES_NOT_ESTABLISHED"
_CHUNK_ID = re.compile(r"^CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_INLINE_CITATION = re.compile(r"\[(CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159})\]")


@dataclass(frozen=True, slots=True)
class ResearchProgrammeCitation:
    chunk_id: str
    layer: Literal["policy", "intervention", "theory"]
    source_id: str
    title: str
    publisher: str
    year: int
    locator: str
    source_url: str
    license: str
    license_url: str
    attribution: str
    source_extraction_sha256: str
    excerpt_sha256: str
    source_population: str
    certainty: str


@dataclass(frozen=True, slots=True)
class ResearchProgrammeSafetyEvidence:
    stage: Literal["INPUT", "RETRIEVAL", "OUTPUT"]
    action: str
    reason_codes: tuple[str, ...]
    trace_id: str
    requires_human: bool


@dataclass(frozen=True, slots=True)
class ResearchProgrammeCandidate:
    """Internal candidate shape; never represents a published or student report."""

    programme_ref: str
    title: str
    body: str
    citations: tuple[ResearchProgrammeCitation, ...]
    request_id: str
    trace_id: str
    generation_id: str
    retrieval_id: str
    source_manifest_sha256: str
    study_ref: str
    valid_through_month: str
    prompt_id: str
    prompt_version: str
    prompt_sha256: str
    retrieval_bundle_sha256: str
    chunk_set_sha256: str
    source_set_sha256: str
    safety_evidence: tuple[
        ResearchProgrammeSafetyEvidence,
        ResearchProgrammeSafetyEvidence,
        ResearchProgrammeSafetyEvidence,
    ]
    safety_version: str = field(default=SAFETY_GATE_VERSION, init=False)
    evidence_limit: str = field(default=EVIDENCE_LIMIT, init=False)
    research_scope: str = field(default=RESEARCH_SCOPE, init=False)
    purpose: str = field(default="staff_research_reference", init=False)
    status: Literal["HELD"] = field(default="HELD", init=False)
    target_role: str = field(default=ROLE_SCOPE, init=False)
    population_scope: str = field(default=POPULATION_SCOPE, init=False)
    risk_scope: str = field(default=RISK_SCOPE, init=False)
    reviewer_kind: str = field(default="AI_ENGINEERING", init=False)
    human_curated: bool = field(default=False, init=False)
    professional_approval: bool = field(default=False, init=False)
    ethics_approval: bool = field(default=False, init=False)
    clinical_approval: bool = field(default=False, init=False)
    psychometric_approval: bool = field(default=False, init=False)
    publication_eligible: bool = field(default=False, init=False)
    production_use: bool = field(default=False, init=False)
    student_feedback_eligible: bool = field(default=False, init=False)
    report: bool = field(default=False, init=False)
    model_id: str = field(default="qwen2.5-7b-instruct-school-demo", init=False)
    model_version: str = ""
    runtime_version: str = ""
    model_digest: str = ""


@dataclass(frozen=True, slots=True)
class ResearchProgrammeOutcome:
    status: Literal["HELD", "ABSTAINED", "HALTED"]
    reason_code: str
    candidate: ResearchProgrammeCandidate | None = None
    safety_action: str | None = None
    research_only: bool = field(default=True, init=False)
    publication_eligible: bool = field(default=False, init=False)
    production_use: bool = field(default=False, init=False)
    student_feedback_eligible: bool = field(default=False, init=False)
    _validation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (self.status == "HELD") != (self.candidate is not None):
            raise ValueError("research programme outcome candidate/status mismatch")


def validate_source_bound_body(body: str, citation_chunk_ids: list[str]) -> None:
    if type(body) is not str or not body.strip() or not citation_chunk_ids:
        raise ValueError("research draft is empty")
    if any(
        type(value) is not str or _CHUNK_ID.fullmatch(value) is None
        for value in citation_chunk_ids
    ):
        raise ValueError("invalid source citation")
    if len(set(citation_chunk_ids)) != len(citation_chunk_ids):
        raise ValueError("duplicate source citation")
    body_markers = _INLINE_CITATION.findall(body)
    if not body_markers or set(body_markers) != set(citation_chunk_ids):
        raise ValueError("draft citations do not bind to body markers")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    if not paragraphs or any(not _INLINE_CITATION.search(paragraph) for paragraph in paragraphs):
        raise ValueError("each draft paragraph must cite its source")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_retrieval_evidence(retrieval: Any, expected_sha256: str, now: datetime) -> bool:
    """Backend-owned closed evidence projection, importable without Backend runtime deps."""

    expected_records = {
        "WHO-HAT-STRATEGY1-POLICY-2021": ("WHO-HAT-TOOLKIT-2021", "policy"),
        "WHO-HAT-SCHOOL-ENVIRONMENT-OBJECTIVE-2021": (
            "WHO-HAT-TOOLKIT-2021",
            "intervention",
        ),
        "WHO-HAT-SCHOOL-CLIMATE-SUPPORT-2021": ("WHO-HAT-TOOLKIT-2021", "intervention"),
        "RAG-THEORY-002": ("RAG-THEORY-002", "theory"),
    }
    try:
        if (
            type(expected_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            return False
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
            return False
        now_utc = now.astimezone(UTC)
        current_month = now_utc.strftime("%Y-%m")
        valid_through = retrieval.valid_through_month
        hits = retrieval.hits
        if (
            now_utc > STUDY_END_UTC
            or retrieval.status != "MATCHES"
            or retrieval.retriever != "BM25S"
            or retrieval.package_id != "school-rag-ai-engineering-20261014-v1"
            or retrieval.manifest_sha256 != expected_sha256
            or retrieval.study_ref != STUDY_REF
            or retrieval.scope != RESEARCH_SCOPE
            or retrieval.use_mode != "SCHOOL_NONCOMMERCIAL_RESEARCH"
            or retrieval.role_scope != (ROLE_SCOPE,)
            or retrieval.population_scope != (POPULATION_SCOPE,)
            or retrieval.risk_scope != (RISK_SCOPE,)
            or type(valid_through) is not str
            or re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", valid_through) is None
            or valid_through < current_month
            or retrieval.reviewer_kind != "AI_ENGINEERING"
            or retrieval.noncommercial is not True
            or retrieval.human_curated is not False
            or retrieval.professional_approval is not False
            or retrieval.ethics_approval is not False
            or retrieval.clinical_approval is not False
            or retrieval.psychometric_approval is not False
            or retrieval.publication_eligible is not False
            or retrieval.production_use is not False
            or retrieval.research_only is not True
            or retrieval.index_persisted is not False
            or retrieval.embeddings_used is not False
            or retrieval.model_called is not False
            or retrieval.production_store_used is not False
            or type(hits) is not tuple
            or len(hits) != 4
        ):
            return False
        ids: set[str] = set()
        layers: set[str] = set()
        for hit in hits:
            citation = hit.citation
            record_fields = (
                "source_id", "title", "publisher", "year", "locator", "source_url",
                "license", "license_url", "attribution", "source_extraction_sha256",
                "excerpt_sha256",
            )
            if (
                not all(hasattr(citation, name) for name in record_fields)
                or type(hit.text) is not str
                or not hit.text
                or type(hit.lexical_score) not in {int, float}
                or not math.isfinite(hit.lexical_score)
                or hit.lexical_score <= 0
                or type(hit.record_id) is not str
                or hit.record_id not in expected_records
                or hit.layer not in {"policy", "intervention", "theory"}
                or expected_records[hit.record_id] != (citation.source_id, hit.layer)
                or type(citation.year) is not int
                or any(
                    type(getattr(citation, name)) is not str or not getattr(citation, name)
                    for name in (
                        "source_id", "title", "publisher", "locator", "source_url",
                        "license", "license_url", "attribution",
                    )
                )
                or not citation.source_url.startswith("https://")
                or re.fullmatch(r"[0-9a-f]{64}", citation.source_extraction_sha256) is None
                or citation.excerpt_sha256 != hashlib.sha256(hit.text.encode("utf-8")).hexdigest()
            ):
                return False
            ids.add(hit.record_id)
            layers.add(hit.layer)
        return ids == set(expected_records) and layers == {"policy", "intervention", "theory"}
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
