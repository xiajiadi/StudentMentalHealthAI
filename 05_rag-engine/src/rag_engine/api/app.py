"""Loopback RAG service over the published Knowledge embedding boundary."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from rag_engine.cli import _default_input_paths, _prepare_bm25, _prepare_real_dense
from rag_engine.config import RAGConfig
from rag_engine.domain import stable_digest
from rag_engine.indexing import KnowledgeCorpusLoader
from rag_engine.query import DeterministicQueryBuilder
from rag_engine.retrieval import RetrievalService


class RetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment: dict[str, Any]
    target_role: str = Field(pattern=r"^(student|teacher|parent|admin)$")
    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_id: str | None = Field(default=None, pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    target_population: str = Field(default="K12学生", min_length=1, max_length=128)
    dimension: str | None = Field(default=None, max_length=128)


class RagRuntime:
    def __init__(self) -> None:
        self.paths = _default_input_paths()
        config_path = Path(os.environ.get("SMHAI_RAG_CONFIG", self.paths["config"])).resolve()
        self.config_path = config_path
        for path_key, environment_key in (
            ("corpus", "SMHAI_RAG_CORPUS"),
            ("documents", "SMHAI_RAG_DOCUMENTS"),
            ("review_queue", "SMHAI_RAG_REVIEW_QUEUE"),
        ):
            configured_path = os.environ.get(environment_key)
            if configured_path:
                self.paths[path_key] = Path(configured_path).resolve()
        self.config = RAGConfig.load(config_path)
        self.corpus = None
        self.stack: dict[str, Any] = {}
        self.provider_report: dict[str, Any] = {}
        self.load_error: str | None = None

    def load(self) -> None:
        if self.stack:
            return
        try:
            self.corpus = KnowledgeCorpusLoader().load(
                self.paths["corpus"],
                documents_path=self.paths["documents"],
                review_queue_path=self.paths["review_queue"],
            )
            bm25, bm25_manifest, _ = _prepare_bm25(self.corpus, self.config, persist=True)
            if self.config.retrieval_mode == "bm25":
                self.provider_report = {
                    "bm25s": {
                        **bm25.health_check(),
                        "index_id": bm25_manifest.get("index_id"),
                    }
                }
                self.stack = {
                    "status": "ready",
                    "bm25_service": RetrievalService(
                        embedding_provider=None,
                        dense_store=None,
                        sparse_retriever=bm25,
                        index_manifest=bm25_manifest,
                        rrf_k=self.config.rrf_k,
                    ),
                    "manifest": bm25_manifest,
                }
                return
            stack, provider_report = _prepare_real_dense(
                self.corpus,
                self.config,
                bm25=bm25,
                load_models=True,
                rerank_requested=False,
            )
            self.provider_report = provider_report
            if stack.get("status") != "ready":
                self.load_error = str(stack.get("reason") or "real RAG providers are not ready")
                return
            self.stack = stack
        except Exception as exc:
            self.load_error = f"{type(exc).__name__}: {str(exc)[:300]}"

    @property
    def ready(self) -> bool:
        return bool(
            self.stack.get("bm25_service")
            or self.stack.get("hybrid_service")
            or self.stack.get("dense_service")
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "READY" if self.ready else "NOT_READY",
            "service": "rag",
            "retrieval_mode": self.config.retrieval_mode,
            "rerank_enabled": False,
            "corpus_version": self.corpus.corpus_version if self.corpus else None,
            "eligible_chunk_count": len(self.corpus.records) if self.corpus else 0,
            "provider": self.provider_report,
            "error": self.load_error,
            "synthetic_fixture_only": True,
        }

    def retrieve(self, request: RetrieveRequest, *, request_id: str, trace_id: str) -> dict[str, Any]:
        if not self.ready:
            raise HTTPException(status_code=503, detail="RAG providers are not ready")
        assessment = dict(request.assessment)
        builder = DeterministicQueryBuilder(self.config)
        dimension = request.dimension or next(iter(assessment.get("dimensions", {})), None)
        plan = builder.build(
            assessment,
            role=request.target_role,
            target_population=request.target_population,
            dimension=dimension,
            user_query=request.query,
            query_type="integration_support",
        )
        plan = replace(
            plan,
            retrieval_mode=self.config.retrieval_mode,
            final_k=request.top_k,
            rerank_enabled=False,
        )
        service_key = {
            "bm25": "bm25_service",
            "hybrid": "hybrid_service",
            "dense": "dense_service",
        }[self.config.retrieval_mode]
        service = self.stack.get(service_key)
        if service is None:
            raise HTTPException(status_code=503, detail="configured RAG provider is not ready")
        retrieval_id = request.retrieval_id or f"RETR_{stable_digest({'trace_id': trace_id, 'query': request.query})[:20]}"
        result = service.retrieve(
            plan,
            raw_query=request.query,
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


def create_app(*, runtime: RagRuntime | None = None) -> FastAPI:
    runtime = runtime or RagRuntime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.load()
        app.state.rag_runtime = runtime
        yield

    app = FastAPI(
        title="StudentMentalHealthAI RAG Service",
        version="0.1.0",
        description="Loopback retrieval over the approved Knowledge publication boundary.",
        lifespan=lifespan,
    )
    app.state.rag_runtime = runtime

    @app.get("/health/live", operation_id="ragLiveHealth")
    async def health_live() -> dict[str, Any]:
        return {"status": "LIVE", "service": "rag"}

    @app.get("/health/ready", operation_id="ragReadyHealth")
    async def health_ready() -> dict[str, Any]:
        if not runtime.ready:
            raise HTTPException(status_code=503, detail=runtime.health())
        return runtime.health()

    @app.get("/health", operation_id="ragHealth")
    async def health() -> dict[str, Any]:
        return runtime.health()

    @app.get("/capabilities", operation_id="ragCapabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "service": "rag",
            "transport": "http",
            "retrieval_mode": runtime.config.retrieval_mode,
            "rerank_enabled": False,
            "publication_boundary": "configured Knowledge embedding-ready export",
            "synthetic_fixture_only": True,
        }

    @app.post("/internal/rag/retrievals", operation_id="ragRetrieve")
    async def retrieve(request: Request, payload: RetrieveRequest) -> dict[str, Any]:
        # Correlation headers are supplied by Backend; use generated IDs only
        # when the service is called directly in an isolated probe.
        from uuid import uuid4

        request_id = request.headers.get("X-Request-ID") or f"REQ_rag_{uuid4().hex[:20]}"
        trace_id = request.headers.get("X-Trace-ID") or f"TRACE_rag_{uuid4().hex[:20]}"
        return runtime.retrieve(payload, request_id=request_id, trace_id=trace_id)

    from rag_engine.independent import attach_independent_routes

    attach_independent_routes(app, runtime)
    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SMHAI_RAG_PORT", "8170")))


if __name__ == "__main__":
    main()
