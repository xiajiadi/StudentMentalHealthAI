"""In-memory lexical retrieval for the pinned research-only package."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from rag_engine.domain import KnowledgeRecord, MetadataFilter
from rag_engine.exceptions import ProviderUnavailableError
from rag_engine.sparse import BM25SRetriever

from .loader import (
    _VALIDATED_PACKAGE_TOKEN,
    POPULATION_SCOPE,
    RISK_SCOPE,
    SPECIALIST_ROLE,
    ResearchPackage,
    ResearchPackageError,
    ResearchRecord,
    _require_month_current,
    load_research_package,
)

_MAX_QUERY_LENGTH = 500
_MAX_RESULTS = 4
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ResearchAccessDenied(PermissionError):
    """The caller is outside the single role authorized by this package."""

    code = "RESEARCH_ROLE_NOT_AUTHORIZED"

    def __init__(self) -> None:
        super().__init__(self.code)


class ResearchRetrievalError(RuntimeError):
    """Stable error for bounded research-only retrieval."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResearchCitation:
    source_id: str
    title: str
    publisher: str
    year: int
    isbn: str | None
    doi: str | None
    source_url: str
    official_pdf_url: str | None
    rights_listing_url: str | None
    locator: str
    license: str
    license_url: str
    attribution: str
    source_extraction_sha256: str
    excerpt_sha256: str


@dataclass(frozen=True)
class ResearchHit:
    record_id: str
    text: str
    layer: str
    source_population: str
    certainty: str
    citation: ResearchCitation
    rank: int
    lexical_score: float


@dataclass(frozen=True)
class ResearchRetrievalResult:
    status: str
    retriever: str
    hits: tuple[ResearchHit, ...]
    package_id: str
    manifest_sha256: str
    study_ref: str
    scope: str
    use_mode: str
    role_scope: tuple[str, ...]
    population_scope: tuple[str, ...]
    risk_scope: tuple[str, ...]
    valid_through_month: str
    output_boundary: str
    reviewer_kind: str = field(default="AI_ENGINEERING", init=False)
    noncommercial: bool = field(default=True, init=False)
    human_curated: bool = field(default=False, init=False)
    professional_approval: bool = field(default=False, init=False)
    ethics_approval: bool = field(default=False, init=False)
    clinical_approval: bool = field(default=False, init=False)
    psychometric_approval: bool = field(default=False, init=False)
    publication_eligible: bool = field(default=False, init=False)
    production_use: bool = field(default=False, init=False)
    research_only: bool = field(default=True, init=False)
    index_persisted: bool = field(default=False, init=False)
    embeddings_used: bool = field(default=False, init=False)
    model_called: bool = field(default=False, init=False)
    production_store_used: bool = field(default=False, init=False)


class ResearchOnlyRetriever:
    """BM25S over one exact-hash-pinned, in-memory research package.

    This class is not wired into the production RetrievalService, API, or
    Knowledge v1 index. It returns source excerpts and citations only.
    """

    def __init__(
        self,
        package: ResearchPackage,
        *,
        clock: Callable[[], date | datetime] | None = None,
    ) -> None:
        if (
            not isinstance(package, ResearchPackage)
            or package._validation_token is not _VALIDATED_PACKAGE_TOKEN
        ):
            raise ResearchRetrievalError("RESEARCH_PACKAGE_REQUIRED")
        self._package = package
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        bm25_records = [self._to_knowledge_record(record) for record in package.records]
        self._record_by_chunk_id = {
            f"CHUNK_RESEARCH_{record.record_id}": record for record in package.records
        }
        self._lexical = BM25SRetriever(bm25_records)
        try:
            self._lexical.build()
        except ProviderUnavailableError as exc:
            # Keep backend exceptions and environment details out of the
            # research boundary; there is no alternate scorer or fallback.
            raise ResearchRetrievalError("RESEARCH_LEXICAL_BACKEND_UNAVAILABLE") from exc
        if len(bm25_records) != len(package.records):
            raise ResearchRetrievalError("RESEARCH_CORPUS_SHAPE_INVALID")

    @classmethod
    def from_manifest(
        cls,
        manifest_path: str | Path,
        *,
        expected_manifest_sha256: str,
        clock: Callable[[], date | datetime] | None = None,
    ) -> ResearchOnlyRetriever:
        try:
            package = load_research_package(
                manifest_path,
                expected_manifest_sha256=expected_manifest_sha256,
                now=clock() if clock is not None else None,
            )
        except ResearchPackageError as exc:
            raise ResearchRetrievalError(exc.code) from exc
        return cls(package, clock=clock)

    def retrieve(
        self,
        query: str,
        *,
        caller_role: str,
        limit: int = 3,
    ) -> ResearchRetrievalResult:
        if type(caller_role) is not str or caller_role != SPECIALIST_ROLE:
            raise ResearchAccessDenied()
        try:
            _require_month_current(self._package.use_policy.valid_through_month, self._clock())
        except ResearchPackageError as exc:
            raise ResearchRetrievalError(exc.code) from exc
        if (
            type(query) is not str
            or not query.strip()
            or len(query) > _MAX_QUERY_LENGTH
            or _CONTROL.search(query)
        ):
            raise ResearchRetrievalError("RESEARCH_QUERY_INVALID")
        if type(limit) is not int or not 1 <= limit <= _MAX_RESULTS:
            raise ResearchRetrievalError("RESEARCH_LIMIT_INVALID")
        try:
            results = self._lexical.search(
                query,
                limit=limit,
                # The isolated corpus has already passed its own closed schema.
                # Avoid translating its research approval into production
                # review_status/rights_status semantics.
                filters=MetadataFilter(review_status=(), rights_status=()),
            )
        except ProviderUnavailableError as exc:
            raise ResearchRetrievalError("RESEARCH_LEXICAL_SEARCH_FAILED") from exc

        hits: list[ResearchHit] = []
        for result in results:
            source_record = self._record_by_chunk_id.get(result.record.chunk_id)
            if source_record is None or result.sparse_score is None or result.sparse_score <= 0:
                continue
            source = source_record.source
            hits.append(
                ResearchHit(
                    record_id=source_record.record_id,
                    text=source_record.text,
                    layer=source_record.layer,
                    source_population=source_record.source_population,
                    certainty=source_record.certainty,
                    citation=ResearchCitation(
                        source_id=source.source_id,
                        title=source.title,
                        publisher=source.publisher,
                        year=source.year,
                        isbn=source.isbn,
                        doi=source.doi,
                        source_url=source.source_url,
                        official_pdf_url=source.official_pdf_url,
                        rights_listing_url=source.rights_listing_url,
                        locator=source_record.locator,
                        license=source.license,
                        license_url=source.license_url,
                        attribution=source.attribution,
                        source_extraction_sha256=source.source_extraction_sha256,
                        excerpt_sha256=source_record.excerpt_sha256,
                    ),
                    rank=len(hits) + 1,
                    lexical_score=float(result.sparse_score),
                )
            )
        return ResearchRetrievalResult(
            status="MATCHES" if hits else "NO_MATCHES",
            retriever="BM25S",
            hits=tuple(hits),
            package_id=self._package.package_id,
            manifest_sha256=self._package.manifest_sha256,
            study_ref=self._package.use_policy.study_ref,
            scope=self._package.scope,
            use_mode=self._package.use_policy.use_mode,
            role_scope=self._package.use_policy.role_scope,
            population_scope=self._package.use_policy.population_scope,
            risk_scope=self._package.use_policy.risk_scope,
            valid_through_month=self._package.use_policy.valid_through_month,
            output_boundary=self._package.use_policy.output_boundary,
        )

    @staticmethod
    def _to_knowledge_record(record: ResearchRecord) -> KnowledgeRecord:
        """Map to BM25S's in-memory protocol only, never to Knowledge v1."""

        source = record.source
        chunk_id = f"CHUNK_RESEARCH_{record.record_id}"
        document_id = f"KB_RESEARCH_{source.source_id}"
        metadata = {
            "target_population": [POPULATION_SCOPE],
            "role_scope": [SPECIALIST_ROLE],
            "risk_scope": [RISK_SCOPE],
            "source_filename": source.source_id,
            "source_url": source.source_url,
            "title": source.title,
            "organization": source.publisher,
            "section": record.locator,
        }
        return KnowledgeRecord(
            chunk_id=chunk_id,
            document_id=document_id,
            text=record.text,
            context_text=record.text,
            metadata=metadata,
            citation={
                "title": source.title,
                "organization": source.publisher,
                "locator": record.locator,
            },
            layer=record.layer,
        )
