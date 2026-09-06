"""Internal domain models that keep provider details out of public contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping, Sequence

from ..exceptions import CorpusValidationError, InvalidConfigurationError

KNOWLEDGE_LAYERS = ("policy", "theory", "intervention")
ROLES = ("student", "teacher", "parent", "admin")
RISK_LEVELS = ("normal", "attention", "high", "crisis")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stable_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _safe_id(value: str, prefix: str) -> bool:
    return bool(re.fullmatch(rf"{re.escape(prefix)}[A-Za-z0-9][A-Za-z0-9_.-]*", value))


def normalize_layer(metadata: Mapping[str, Any], category: str | None = None) -> str:
    """Map existing Knowledge metadata to the three internal routing layers."""

    layer = str(metadata.get("layer") or "").strip().lower()
    if layer in KNOWLEDGE_LAYERS:
        return layer
    category_value = str(category or metadata.get("category") or "").strip().lower()
    if category_value == "policy":
        return "policy"
    if category_value == "theory":
        return "theory"
    if category_value in {"practice_guidance", "referral", "intervention"}:
        return "intervention"
    raise CorpusValidationError(
        "Knowledge record has no supported layer/category mapping",
        code="KNOWLEDGE_LAYER_UNMAPPED",
    )


@dataclass(frozen=True)
class KnowledgeRecord:
    chunk_id: str
    document_id: str
    text: str
    context_text: str
    metadata: dict[str, Any]
    citation: dict[str, str]
    layer: str

    @classmethod
    def from_embedding_record(
        cls,
        value: Mapping[str, Any],
        *,
        category_by_document: Mapping[str, str] | None = None,
    ) -> "KnowledgeRecord":
        chunk_id = str(value.get("chunk_id") or "")
        document_id = str(value.get("document_id") or "")
        text = str(value.get("text") or "").strip()
        context_text = str(value.get("context_text") or text).strip()
        raw_metadata = value.get("metadata")
        if not _safe_id(chunk_id, "CHUNK_") or not _safe_id(document_id, "KB_"):
            raise CorpusValidationError(f"Invalid Knowledge IDs: {chunk_id!r}, {document_id!r}")
        if not text:
            raise CorpusValidationError(f"Knowledge chunk {chunk_id} has empty text")
        if not isinstance(raw_metadata, Mapping):
            raise CorpusValidationError(f"Knowledge chunk {chunk_id} metadata must be an object")
        metadata = dict(raw_metadata)
        category = (category_by_document or {}).get(document_id)
        layer = normalize_layer(metadata, category)
        metadata["layer"] = layer
        metadata.setdefault("target_population", metadata.get("population_scope", []))
        metadata.setdefault("role_scope", [])
        metadata.setdefault("risk_scope", [])
        metadata.setdefault("source_filename", "unknown")
        metadata.setdefault("source_url", None)
        metadata.setdefault("title", document_id)
        metadata.setdefault("organization", "unknown")
        metadata.setdefault("section", "unknown")
        metadata.setdefault("review_status", "pending")
        metadata.setdefault("rights_status", "unknown")
        page_start = metadata.get("page_start")
        page_end = metadata.get("page_end")
        pages = "unknown"
        if page_start is not None or page_end is not None:
            pages = f"{page_start or '?'}-{page_end or '?'}"
        locator = str(
            metadata.get("citation_locator")
            or f"file:{metadata['source_filename']}; section:{metadata['section']}; pages:{pages}"
        )
        citation = {
            "title": str(metadata.get("title") or document_id),
            "organization": str(metadata.get("organization") or "unknown"),
            "locator": locator,
        }
        return cls(
            chunk_id=chunk_id,
            document_id=document_id,
            text=text,
            context_text=context_text,
            metadata=metadata,
            citation=citation,
            layer=layer,
        )

    @property
    def content_hash(self) -> str | None:
        value = self.metadata.get("content_hash")
        return str(value) if value else None

    @property
    def target_population(self) -> tuple[str, ...]:
        return _as_tuple(self.metadata.get("target_population", self.metadata.get("population_scope")))

    @property
    def role_scope(self) -> tuple[str, ...]:
        return _as_tuple(self.metadata.get("role_scope"))

    @property
    def risk_scope(self) -> tuple[str, ...]:
        return _as_tuple(self.metadata.get("risk_scope"))

    @property
    def review_status(self) -> str:
        return str(self.metadata.get("review_status") or "pending")

    @property
    def rights_status(self) -> str:
        return str(self.metadata.get("rights_status") or "unknown")

    def to_contract_projection(
        self,
        *,
        embedding_model_id: str | None = None,
        embedding_model_version: str | None = None,
        embedding_status: str | None = None,
    ) -> dict[str, Any]:
        page_start = self.metadata.get("page_start")
        page_end = self.metadata.get("page_end")
        return {
            "schema_version": "knowledge.v1",
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "content_type": str(self.metadata.get("content_type") or "source_excerpt"),
            "location": {
                "section": str(self.metadata.get("section") or "unknown"),
                "page_start": page_start,
                "page_end": page_end,
            },
            "citation": dict(self.citation),
            "population_scope": list(self.target_population),
            "role_scope": list(self.role_scope) or ["student", "teacher", "parent"],
            "risk_scope": list(self.risk_scope) or ["normal", "attention"],
            "review_status": self.review_status,
            "rights_status": self.rights_status,
            "content_hash": self.content_hash or f"sha256:{stable_digest(self.text)}",
            "embedding": {
                "model_id": embedding_model_id,
                "model_version": embedding_model_version,
                "status": embedding_status or str(self.metadata.get("embedding_status") or "not_indexed"),
            },
        }


@dataclass(frozen=True)
class MetadataFilter:
    """Provider-neutral metadata predicates; list fields use intersection semantics."""

    layers: tuple[str, ...] = ()
    review_status: tuple[str, ...] = ("approved",)
    rights_status: tuple[str, ...] = ("verified",)
    role_scope: tuple[str, ...] = ()
    target_population: tuple[str, ...] = ()
    risk_scope: tuple[str, ...] = ()
    source: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("layers", "review_status", "rights_status", "role_scope", "target_population", "risk_scope", "source", "document_ids", "chunk_ids"):
            object.__setattr__(self, field_name, tuple(str(x) for x in getattr(self, field_name) if str(x)))
        invalid_layers = set(self.layers) - set(KNOWLEDGE_LAYERS)
        if invalid_layers:
            raise InvalidConfigurationError(f"Unsupported knowledge layers: {sorted(invalid_layers)}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "MetadataFilter":
        value = value or {}
        return cls(
            layers=_as_tuple(value.get("layers", value.get("layer"))),
            review_status=_as_tuple(value.get("review_status", ("approved",))),
            rights_status=_as_tuple(value.get("rights_status", ("verified",))),
            role_scope=_as_tuple(value.get("role_scope")),
            target_population=_as_tuple(value.get("target_population", value.get("population_scope"))),
            risk_scope=_as_tuple(value.get("risk_scope")),
            source=_as_tuple(value.get("source", value.get("source_filename"))),
            document_ids=_as_tuple(value.get("document_ids", value.get("document_id"))),
            chunk_ids=_as_tuple(value.get("chunk_ids", value.get("chunk_id"))),
        )

    def matches(self, record: KnowledgeRecord) -> bool:
        if self.layers and record.layer not in self.layers:
            return False
        if self.review_status and record.review_status not in self.review_status:
            return False
        if self.rights_status and record.rights_status not in self.rights_status:
            return False
        if self.role_scope and not set(self.role_scope).intersection(record.role_scope):
            return False
        if self.target_population and not set(self.target_population).intersection(record.target_population):
            return False
        if self.risk_scope and not set(self.risk_scope).intersection(record.risk_scope):
            return False
        if self.source:
            source_values = {
                str(record.metadata.get("source_filename") or ""),
                str(record.metadata.get("source_url") or ""),
                str(record.metadata.get("organization") or ""),
            }
            if not set(self.source).intersection(source_values):
                return False
        if self.document_ids and record.document_id not in self.document_ids:
            return False
        if self.chunk_ids and record.chunk_id not in self.chunk_ids:
            return False
        return True

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "layers": list(self.layers),
            "review_status": list(self.review_status),
            "rights_status": list(self.rights_status),
            "role_scope": list(self.role_scope),
            "target_population": list(self.target_population),
            "risk_scope": list(self.risk_scope),
            "source": list(self.source),
            "document_ids": list(self.document_ids),
            "chunk_ids": list(self.chunk_ids),
        }

    def for_layer(self, layer: str) -> "MetadataFilter":
        if layer not in KNOWLEDGE_LAYERS:
            raise InvalidConfigurationError(f"Unsupported knowledge layer: {layer}")
        return replace(self, layers=(layer,))


@dataclass(frozen=True)
class LayerBudget:
    layer: str
    quota: int

    def __post_init__(self) -> None:
        if self.layer not in KNOWLEDGE_LAYERS:
            raise InvalidConfigurationError(f"Unsupported knowledge layer: {self.layer}")
        if self.quota < 1:
            raise InvalidConfigurationError("Layer quota must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "quota": self.quota}


@dataclass(frozen=True)
class RetrievalPlan:
    queries: tuple[str, ...]
    filters: MetadataFilter
    layers: tuple[LayerBudget, ...]
    retrieval_mode: Literal["dense", "bm25", "hybrid"] = "dense"
    dense_candidate_k: int = 20
    sparse_candidate_k: int = 20
    fusion_candidate_k: int = 20
    rerank_candidate_k: int = 10
    final_k: int = 5
    rerank_enabled: bool = False
    context_max_chars: int = 12000
    assessment_id: str | None = None
    role: str = "teacher"
    target_population: str | None = None
    dimension: str | None = None
    topic: str | None = None
    intent: str | None = None
    risk_level: str = "normal"
    query_type: str = "unknown"

    def __post_init__(self) -> None:
        if not self.queries or any(not str(query).strip() for query in self.queries):
            raise InvalidConfigurationError("RetrievalPlan requires at least one non-empty query")
        if self.retrieval_mode not in {"dense", "bm25", "hybrid"}:
            raise InvalidConfigurationError(f"Unsupported retrieval mode: {self.retrieval_mode}")
        if self.role not in ROLES:
            raise InvalidConfigurationError(f"Unsupported role: {self.role}")
        if self.risk_level not in RISK_LEVELS:
            raise InvalidConfigurationError(f"Unsupported risk level: {self.risk_level}")
        for name in ("dense_candidate_k", "sparse_candidate_k", "fusion_candidate_k", "rerank_candidate_k", "final_k", "context_max_chars"):
            if int(getattr(self, name)) < 1:
                raise InvalidConfigurationError(f"{name} must be positive")
        if not self.layers:
            raise InvalidConfigurationError("RetrievalPlan requires explicit layer budgets")
        object.__setattr__(self, "queries", tuple(str(query).strip() for query in self.queries))

    def to_dict(self) -> dict[str, Any]:
        return {
            "queries": list(self.queries),
            "filters": self.filters.to_dict(),
            "layers": [layer.to_dict() for layer in self.layers],
            "retrieval_mode": self.retrieval_mode,
            "dense_candidate_k": self.dense_candidate_k,
            "sparse_candidate_k": self.sparse_candidate_k,
            "fusion_candidate_k": self.fusion_candidate_k,
            "rerank_candidate_k": self.rerank_candidate_k,
            "final_k": self.final_k,
            "rerank_enabled": self.rerank_enabled,
            "context_max_chars": self.context_max_chars,
            "assessment_id": self.assessment_id,
            "role": self.role,
            "target_population": self.target_population,
            "dimension": self.dimension,
            "topic": self.topic,
            "intent": self.intent,
            "risk_level": self.risk_level,
            "query_type": self.query_type,
        }


@dataclass
class RetrievalHit:
    record: KnowledgeRecord
    retriever: str
    rank: int
    dense_score: float | None = None
    sparse_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None

    @property
    def chunk_id(self) -> str:
        return self.record.chunk_id

    @property
    def document_id(self) -> str:
        return self.record.document_id

    def clone(self, **changes: Any) -> "RetrievalHit":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.record.text,
            "citation": dict(self.record.citation),
            "metadata": dict(self.record.metadata),
            "retriever": self.retriever,
            "rank": self.rank,
            "dense_score": self.dense_score,
            "sparse_score": self.sparse_score,
            "fusion_score": self.fusion_score,
            "rerank_score": self.rerank_score,
        }


@dataclass(frozen=True)
class Citation:
    citation_id: str
    chunk_id: str
    document_id: str
    source_title: str
    source_organization: str
    source_locator: str
    source_file: str | None
    source_url: str | None
    section: str | None
    page_start: int | None
    page_end: int | None

    @classmethod
    def from_record(cls, record: KnowledgeRecord, citation_id: str) -> "Citation":
        return cls(
            citation_id=citation_id,
            chunk_id=record.chunk_id,
            document_id=record.document_id,
            source_title=record.citation["title"],
            source_organization=record.citation["organization"],
            source_locator=record.citation["locator"],
            source_file=str(record.metadata.get("source_filename") or "") or None,
            source_url=str(record.metadata.get("source_url") or "") or None,
            section=str(record.metadata.get("section") or "") or None,
            page_start=record.metadata.get("page_start"),
            page_end=record.metadata.get("page_end"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source_title": self.source_title,
            "source_organization": self.source_organization,
            "source_locator": self.source_locator,
            "source_file": self.source_file,
            "source_url": self.source_url,
            "section": self.section,
            "page_start": self.page_start,
            "page_end": self.page_end,
        }


@dataclass(frozen=True)
class CitationBundle:
    citations: tuple[Citation, ...]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(citation.citation_id for citation in self.citations)

    def to_dict(self) -> dict[str, Any]:
        return {"citations": [citation.to_dict() for citation in self.citations]}


@dataclass(frozen=True)
class ContextItem:
    citation_id: str
    source_title: str
    source_location: str
    chunk_text: str

    def to_dict(self) -> dict[str, str]:
        return {
            "citation_id": self.citation_id,
            "source_title": self.source_title,
            "source_location": self.source_location,
            "chunk_text": self.chunk_text,
        }


@dataclass(frozen=True)
class ContextBundle:
    items: tuple[ContextItem, ...]
    text: str
    citation_bundle: CitationBundle
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "text": self.text,
            "citation_bundle": self.citation_bundle.to_dict(),
            "truncated": self.truncated,
        }


@dataclass
class RetrievalTrace:
    trace_id: str
    request_id: str
    raw_query: str
    built_query: tuple[str, ...]
    retrieval_plan: dict[str, Any]
    filters: dict[str, Any]
    dense_hits: list[RetrievalHit] = field(default_factory=list)
    sparse_hits: list[RetrievalHit] = field(default_factory=list)
    fusion_hits: list[RetrievalHit] = field(default_factory=list)
    rerank_candidates: list[RetrievalHit] = field(default_factory=list)
    rerank_hits: list[RetrievalHit] = field(default_factory=list)
    final_hits: list[RetrievalHit] = field(default_factory=list)
    final_context: list[str] = field(default_factory=list)
    embedding_version: str | None = None
    reranker_version: str | None = None
    reranker_revision: str | None = None
    index_version: str | None = None
    corpus_version: str | None = None
    latency_ms: dict[str, float | None] = field(default_factory=dict)
    sparse_enabled: bool = False
    outcome: str = "success"

    @staticmethod
    def _stage(
        values: Iterable[RetrievalHit],
        *,
        before_ranks: Mapping[str, int] | None = None,
        after_rank: bool = False,
    ) -> list[dict[str, Any]]:
        before_ranks = before_ranks or {}
        return [
            {
                "chunk_id": hit.chunk_id,
                "document_id": hit.document_id,
                "rank": hit.rank,
                "before_rank": before_ranks.get(hit.chunk_id),
                "after_rank": hit.rank if after_rank else None,
                "retriever": hit.retriever,
                "dense_score": hit.dense_score,
                "sparse_score": hit.sparse_score,
                "fusion_score": hit.fusion_score,
                "rerank_score": hit.rerank_score,
            }
            for hit in values
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "raw_query": self.raw_query,
            "built_query": list(self.built_query),
            "retrieval_plan": self.retrieval_plan,
            "filters": self.filters,
            "dense_hits": self._stage(self.dense_hits),
            "sparse_hits": self._stage(self.sparse_hits),
            "fusion": self._stage(self.fusion_hits),
            "rerank_candidates": self._stage(self.rerank_candidates),
            "rerank": self._stage(
                self.rerank_hits,
                before_ranks={hit.chunk_id: hit.rank for hit in self.rerank_candidates},
                after_rank=True,
            ),
            "final": self._stage(self.final_hits),
            "final_context": list(self.final_context),
            "embedding_version": self.embedding_version,
            "reranker_version": self.reranker_version,
            "reranker_revision": self.reranker_revision,
            "index_version": self.index_version,
            "corpus_version": self.corpus_version,
            "latency_ms": dict(self.latency_ms),
            "sparse_enabled": self.sparse_enabled,
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class IndexManifest:
    index_id: str
    index_version: str
    corpus_version: str
    chunk_count: int
    embedding_provider: str
    embedding_model: str
    model_revision: str | None
    dimension: int
    store: str
    store_version: str
    distance: str
    config_hash: str
    timestamp: str
    eligible_chunk_ids: tuple[str, ...] = ()
    excluded_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_id": self.index_id,
            "index_version": self.index_version,
            "corpus_version": self.corpus_version,
            "chunk_count": self.chunk_count,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "model_revision": self.model_revision,
            "dimension": self.dimension,
            "store": self.store,
            "store_version": self.store_version,
            "distance": self.distance,
            "config_hash": self.config_hash,
            "timestamp": self.timestamp,
            "eligible_chunk_ids": list(self.eligible_chunk_ids),
            "excluded_count": self.excluded_count,
        }


@dataclass(frozen=True)
class RetrievalResult:
    retrieval_id: str
    plan: RetrievalPlan
    hits: tuple[RetrievalHit, ...]
    context: ContextBundle
    citations: CitationBundle
    trace: RetrievalTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieval_id": self.retrieval_id,
            "plan": self.plan.to_dict(),
            "chunks": [hit.to_dict() for hit in self.hits],
            "context": self.context.to_dict(),
            "citations": self.citations.to_dict(),
            "trace": self.trace.to_dict(),
        }

    def to_api_envelope(self, *, request_id: str, trace_id: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "data": {
                "retrieval_id": self.retrieval_id,
                "chunks": [hit.record.to_contract_projection() for hit in self.hits],
            },
        }
