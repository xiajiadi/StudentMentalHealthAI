"""Assessment-free retrieval for independent student education support.

This path is deliberately separate from the frozen assessment-bound query
builder and request contract. It carries no assessment signals and applies no
risk filter; population eligibility remains an explicit server-owned scope.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from .config import RAGConfig
from .domain import KNOWLEDGE_LAYERS, LayerBudget, MetadataFilter, stable_digest
from .exceptions import InvalidConfigurationError, UnsafeQueryError

INDEPENDENT_STUDENT_POPULATIONS = frozenset(
    {"university_freshman", "university_student"}
)
_ID_RE = re.compile(r"^(REQ|TRACE)_[A-Za-z0-9][A-Za-z0-9_.-]{0,150}$")


@dataclass(frozen=True, slots=True)
class IndependentRetrievalPlan:
    """RetrievalService-compatible plan with explicit absence of assessment."""

    queries: tuple[str, ...]
    filters: MetadataFilter
    layers: tuple[LayerBudget, ...]
    retrieval_mode: Literal["dense", "bm25", "hybrid"]
    dense_candidate_k: int
    sparse_candidate_k: int
    fusion_candidate_k: int
    rerank_candidate_k: int
    final_k: int
    rerank_enabled: bool
    context_max_chars: int
    assessment_id: None
    role: Literal["student"]
    target_population: str
    dimension: None
    topic: None
    intent: None
    risk_level: None
    query_type: Literal["independent_support"] = "independent_support"

    def to_dict(self) -> dict[str, Any]:
        """Match the retrieval-plan trace projection without assessment data."""

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
            "assessment_id": None,
            "role": self.role,
            "target_population": self.target_population,
            "dimension": None,
            "topic": None,
            "intent": None,
            "risk_level": None,
            "query_type": self.query_type,
        }


def build_independent_plan(
    config: RAGConfig,
    query: str,
    target_population: str,
    *,
    top_k: int | None = None,
) -> IndependentRetrievalPlan:
    """Build a student-scoped plan without manufacturing assessment signals."""

    if not isinstance(query, str) or not query.strip():
        raise InvalidConfigurationError("independent query must be non-empty")
    if (
        not isinstance(target_population, str)
        or target_population not in INDEPENDENT_STUDENT_POPULATIONS
    ):
        raise InvalidConfigurationError("unsupported independent student population")
    if config.retrieval_mode not in {"dense", "bm25", "hybrid"}:
        raise InvalidConfigurationError("unsupported configured retrieval mode")
    if top_k is None:
        result_limit = config.final_k
    elif isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise InvalidConfigurationError("top_k must be an integer between 1 and 20")
    else:
        result_limit = top_k

    normalized_query = query.strip()
    _assert_safe_query(normalized_query)
    quota = max(1, math.ceil(result_limit / len(KNOWLEDGE_LAYERS)))
    return IndependentRetrievalPlan(
        queries=(normalized_query,),
        filters=MetadataFilter(
            review_status=("approved",),
            rights_status=("verified",),
            role_scope=("student",),
            target_population=(target_population,),
            risk_scope=(),
        ),
        layers=tuple(
            LayerBudget(layer=layer, quota=quota) for layer in KNOWLEDGE_LAYERS
        ),
        retrieval_mode=config.retrieval_mode,
        dense_candidate_k=config.dense_candidate_k,
        sparse_candidate_k=config.sparse_candidate_k,
        fusion_candidate_k=config.fusion_candidate_k,
        rerank_candidate_k=config.rerank_candidate_k,
        final_k=result_limit,
        rerank_enabled=False,
        context_max_chars=config.context_max_chars,
        assessment_id=None,
        role="student",
        target_population=target_population,
        dimension=None,
        topic=None,
        intent=None,
        risk_level=None,
    )


class IndependentRetrieveRequest(BaseModel):
    """Strict payload: only user query and bounded routing/result references."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    target_population: Literal["university_freshman", "university_student"]
    top_k: StrictInt = Field(default=5, ge=1, le=20)
    retrieval_id: str | None = Field(
        default=None, pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )

    @field_validator("query")
    @classmethod
    def _normalize_and_validate_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must contain non-whitespace text")
        try:
            _assert_safe_query(normalized)
        except UnsafeQueryError as exc:
            raise ValueError(
                "query contains a direct identity or identifier token"
            ) from exc
        return normalized


def attach_independent_routes(app: FastAPI, runtime: Any) -> None:
    """Attach the independent endpoint to a configured RAG runtime instance."""

    @app.post(
        "/internal/rag/independent-retrievals",
        operation_id="ragIndependentRetrieve",
    )
    async def retrieve_independent(
        request: Request, payload: IndependentRetrieveRequest
    ) -> dict[str, Any]:
        request_id = _correlation_id(request.headers.get("X-Request-ID"), "REQ")
        trace_id = _correlation_id(request.headers.get("X-Trace-ID"), "TRACE")
        if not bool(getattr(runtime, "ready", False)):
            raise HTTPException(status_code=503, detail="RAG providers are not ready")

        plan = build_independent_plan(
            runtime.config,
            payload.query,
            payload.target_population,
            top_k=payload.top_k,
        )
        service_key = {
            "bm25": "bm25_service",
            "hybrid": "hybrid_service",
            "dense": "dense_service",
        }[plan.retrieval_mode]
        services = getattr(runtime, "stack", {})
        service = services.get(service_key) if isinstance(services, Mapping) else None
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="configured RAG provider is not ready",
            )

        retrieval_id = (
            payload.retrieval_id
            or f"RETR_{stable_digest({'trace_id': trace_id, 'query': payload.query, 'target_population': payload.target_population})[:20]}"
        )
        result = service.retrieve(
            plan,  # type: ignore[arg-type] -- independent plan intentionally has null assessment/risk.
            raw_query=payload.query,
            request_id=request_id,
            trace_id=trace_id,
            retrieval_id=retrieval_id,
        )
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "data": {
                "retrieval_id": result.retrieval_id,
                "chunks": [hit.record.to_contract_projection() for hit in result.hits],
                "citations": result.citations.to_dict(),
                "trace": result.trace.to_dict(),
                "plan": result.plan.to_dict(),
            },
        }


def _correlation_id(value: str | None, prefix: Literal["REQ", "TRACE"]) -> str:
    if value and _ID_RE.fullmatch(value) and value.startswith(f"{prefix}_"):
        return value
    return f"{prefix}_{uuid4().hex[:20]}"


def _assert_safe_query(value: str) -> None:
    """Apply the same direct-identifier exclusions as RetrievalService."""

    for pattern in (
        r"\bSUBJ_[A-Za-z0-9_.-]+\b",
        r"[\w.+-]+@[\w-]+\.[\w.-]+",
        r"(?<!\d)\d{7,}(?!\d)",
    ):
        if re.search(pattern, value, re.IGNORECASE):
            raise UnsafeQueryError(
                "Query contains a direct identity or identifier token"
            )


__all__ = [
    "INDEPENDENT_STUDENT_POPULATIONS",
    "IndependentRetrievalPlan",
    "IndependentRetrieveRequest",
    "attach_independent_routes",
    "build_independent_plan",
]
