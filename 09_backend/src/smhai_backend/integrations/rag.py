"""RAG integration port and a clearly labelled synthetic adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.integrations.contracts import validate_frozen

from .common_http import LongLivedHttpClient, UpstreamError, translate_upstream_error


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["knowledge.v1"]
    chunk_id: str
    document_id: str
    text: str = Field(min_length=1)
    content_type: str = "approved_summary"
    location: dict[str, Any]
    citation: Citation
    population_scope: list[str] = Field(min_length=1)
    role_scope: list[str] = Field(min_length=1)
    risk_scope: list[str] = Field(min_length=1)
    review_status: str = "approved"
    rights_status: str = "verified"
    content_hash: str
    embedding: dict[str, Any] = Field(
        default_factory=lambda: {
            "model_id": None,
            "model_version": "synthetic",
            "status": "not_indexed",
        }
    )


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    retrieval_id: str
    chunks: tuple[KnowledgeChunk, ...]
    label: str
    trace: dict[str, Any] | None = None


class RagClient(Protocol):
    label: str

    async def retrieve(
        self,
        *,
        assessment: Mapping[str, Any],
        target_role: str,
        query: str,
        top_k: int,
        trace_id: str,
        retrieval_id_hint: str | None = None,
        request_id: str | None = None,
    ) -> RetrievalResult: ...

    async def health(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class ContractFakeRagClient:
    label: str = "CONTRACT_FAKE"
    calls: int = 0
    call_order: list[str] = field(default_factory=list)
    available: bool = True

    async def retrieve(
        self,
        *,
        assessment: Mapping[str, Any],
        target_role: str,
        query: str,
        top_k: int,
        trace_id: str,
        retrieval_id_hint: str | None = None,
        request_id: str | None = None,
    ) -> RetrievalResult:
        self.calls += 1
        self.call_order.append("rag")
        if not self.available:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="required dependency could not complete the request",
                retryable=True,
            )
        if "SYNTHETIC_RAG_TIMEOUT" in query:
            raise error(
                ErrorCode.DEPENDENCY_TIMEOUT,
                status_code=504,
                detail="required dependency timed out",
                retryable=True,
            )
        retrieval_id = retrieval_id_hint or f"RETR_{uuid4().hex}"
        chunk_ids = [f"CHUNK_backend_{index}" for index in range(max(1, min(top_k, 2)))]
        chunks = tuple(
            KnowledgeChunk(
                schema_version="knowledge.v1",
                chunk_id=chunk_id,
                document_id="KB_backend_synthetic",
                text=("合成教育支持资料：把问题拆成可执行的小步骤，并和可信任的支持者讨论下一步。"),
                location={"section": "synthetic-guidance", "page_start": None, "page_end": None},
                citation=Citation(
                    title="Synthetic education support guidance",
                    organization="StudentMentalHealthAI synthetic fixture",
                    locator="fixture://backend/synthetic-guidance",
                ),
                population_scope=["synthetic_demo"],
                role_scope=[target_role],
                risk_scope=["normal", "attention"],
                content_hash=f"sha256:{chunk_id.lower()}",
            )
            for index, chunk_id in enumerate(chunk_ids)
        )
        for chunk in chunks:
            validate_frozen("knowledge.v1.schema.json", chunk.model_dump(mode="json"))
        return RetrievalResult(retrieval_id=retrieval_id, chunks=chunks, label=self.label)

    async def health(self) -> dict[str, Any]:
        return {"status": "READY" if self.available else "UNAVAILABLE", "mode": self.label}


class HttpRagClient(LongLivedHttpClient):
    """Thin Backend transport for the real RAG service."""

    label = "REAL_HTTP"

    async def retrieve(
        self,
        *,
        assessment: Mapping[str, Any],
        target_role: str,
        query: str,
        top_k: int,
        trace_id: str,
        retrieval_id_hint: str | None = None,
        request_id: str | None = None,
    ) -> RetrievalResult:
        context = RequestContext(request_id or "REQ_rag", trace_id)
        try:
            response = await self.post_json(
                "/internal/rag/retrievals",
                {
                    "assessment": dict(assessment),
                    "target_role": target_role,
                    "query": query,
                    "top_k": top_k,
                    "retrieval_id": retrieval_id_hint,
                    # The CAT engineering fixture deliberately uses a
                    # pending population label.  This explicit integration
                    # fixture mapping selects the published K-12 corpus.
                    "target_population": "K12学生",
                },
                context=context,
            )
            data = response.get("data")
            if not isinstance(data, Mapping):
                raise ValueError("RAG response has no data object")
            chunks_value = data.get("chunks")
            if not isinstance(chunks_value, list):
                raise ValueError("RAG response has no chunks list")
            chunks = tuple(KnowledgeChunk.model_validate(item) for item in chunks_value)
            return RetrievalResult(
                retrieval_id=str(data["retrieval_id"]),
                chunks=chunks,
                label=self.label,
                trace=dict(data["trace"]) if isinstance(data.get("trace"), Mapping) else None,
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except (TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="RAG returned an invalid retrieval projection",
            ) from exc

    async def health(self) -> dict[str, Any]:
        try:
            return await self.get_json(
                "/health/ready", context=RequestContext("REQ_rag_health", "TRACE_rag_health")
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
