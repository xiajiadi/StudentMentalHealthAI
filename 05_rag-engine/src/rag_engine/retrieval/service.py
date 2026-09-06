"""Retrieval orchestration with explicit stages and complete trace evidence."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from time import perf_counter
from typing import Any, Callable, Sequence

from ..context import ContextBuilder
from ..domain import LayerBudget, MetadataFilter, RetrievalHit, RetrievalPlan, RetrievalResult, RetrievalTrace
from ..embedding import EmbeddingProvider
from ..exceptions import ProviderUnavailableError, UnsafeQueryError
from ..query import DeterministicQueryBuilder
from ..rerank import NoOpReranker, RerankerProvider
from ..sparse import BM25SRetriever
from ..stores import VectorStoreProvider
from .fusion import rrf_fuse


class RetrievalService:
    """Coordinates providers while preserving every stage score."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None,
        dense_store: VectorStoreProvider | None,
        sparse_retriever: BM25SRetriever | None = None,
        reranker: RerankerProvider | None = None,
        context_builder: ContextBuilder | None = None,
        rrf_k: int = 60,
        index_manifest: dict[str, Any] | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.dense_store = dense_store
        self.sparse_retriever = sparse_retriever
        self.reranker = reranker or NoOpReranker()
        self.context_builder = context_builder or ContextBuilder()
        self.rrf_k = rrf_k
        self.index_manifest = index_manifest or {}
        self._last_embedding_latency_ms: float | None = None

    def retrieve(
        self,
        plan: RetrievalPlan,
        *,
        raw_query: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        retrieval_id: str | None = None,
    ) -> RetrievalResult:
        raw_query = (raw_query or plan.queries[0]).strip()
        self._assert_safe_query(raw_query)
        request_id = request_id or f"REQ_{uuid.uuid4().hex[:20]}"
        trace_id = trace_id or f"TRACE_{uuid.uuid4().hex[:20]}"
        retrieval_id = retrieval_id or f"RETR_{uuid.uuid4().hex[:20]}"
        total_started = perf_counter()
        self._last_embedding_latency_ms = None
        dense_hits: list[RetrievalHit] = []
        sparse_hits: list[RetrievalHit] = []
        dense_latency = 0.0
        sparse_latency = 0.0

        if plan.retrieval_mode in {"dense", "hybrid"}:
            dense_started = perf_counter()
            dense_hits = self._dense_stage(plan)
            dense_latency = (perf_counter() - dense_started) * 1000
        if plan.retrieval_mode in {"bm25", "hybrid"}:
            sparse_started = perf_counter()
            sparse_hits = self._sparse_stage(plan)
            sparse_latency = (perf_counter() - sparse_started) * 1000

        fusion_started = perf_counter()
        if plan.retrieval_mode == "hybrid":
            candidates = rrf_fuse([dense_hits, sparse_hits], k=self.rrf_k, limit=plan.fusion_candidate_k)
            fusion_hits = list(candidates)
        elif plan.retrieval_mode == "dense":
            candidates = [hit.clone(rank=rank) for rank, hit in enumerate(dense_hits[: plan.fusion_candidate_k])]
            fusion_hits = []
        else:
            candidates = [hit.clone(rank=rank) for rank, hit in enumerate(sparse_hits[: plan.fusion_candidate_k])]
            fusion_hits = []
        fusion_latency = (perf_counter() - fusion_started) * 1000

        rerank_started = perf_counter()
        rerank_candidates: list[RetrievalHit] = []
        if plan.rerank_enabled:
            rerank_input = candidates[: plan.rerank_candidate_k]
            rerank_candidates = [hit.clone(rank=hit.rank) for hit in rerank_input]
            rerank_hits = self.reranker.rerank(plan.queries[0], rerank_input, limit=plan.rerank_candidate_k)
            final_hits = rerank_hits[: plan.final_k]
        else:
            rerank_hits = []
            final_hits = candidates[: plan.final_k]
        rerank_latency = (perf_counter() - rerank_started) * 1000

        context_started = perf_counter()
        context = self.context_builder.build(final_hits, max_chars=plan.context_max_chars)
        context_latency = (perf_counter() - context_started) * 1000
        citations = context.citation_bundle
        trace = RetrievalTrace(
            trace_id=trace_id,
            request_id=request_id,
            raw_query=raw_query,
            built_query=plan.queries,
            retrieval_plan=plan.to_dict(),
            filters=plan.filters.to_dict(),
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            fusion_hits=fusion_hits,
            rerank_candidates=rerank_candidates,
            rerank_hits=rerank_hits,
            final_hits=final_hits,
            final_context=list(citations.ids),
            embedding_version=self._embedding_version(),
            reranker_version=self._reranker_version() if plan.rerank_enabled else "disabled",
            reranker_revision=self._reranker_revision() if plan.rerank_enabled else None,
            index_version=self._index_value("index_version"),
            corpus_version=self._index_value("corpus_version"),
            latency_ms={
                "embedding_ms": self._embedding_latency(dense_hits, sparse_hits),
                "dense_retrieval_ms": dense_latency if plan.retrieval_mode in {"dense", "hybrid"} else None,
                "sparse_retrieval_ms": sparse_latency if plan.retrieval_mode in {"bm25", "hybrid"} else None,
                "retrieval_ms": dense_latency + sparse_latency,
                "fusion_ms": fusion_latency,
                "rerank_ms": rerank_latency if plan.rerank_enabled else None,
                "context_ms": context_latency,
                "total_ms": (perf_counter() - total_started) * 1000,
            },
            sparse_enabled=plan.retrieval_mode in {"bm25", "hybrid"},
            outcome="success" if final_hits else "no_results",
        )
        return RetrievalResult(
            retrieval_id=retrieval_id,
            plan=plan,
            hits=tuple(final_hits),
            context=context,
            citations=citations,
            trace=trace,
        )

    def retrieve_for_assessment(
        self,
        assessment: dict[str, Any],
        *,
        role: str,
        config_builder: DeterministicQueryBuilder,
        user_query: str | None = None,
        target_population: str | None = None,
        dimension: str | None = None,
        topic: str | None = None,
        intent: str | None = None,
        layers: Sequence[str] | None = None,
        query_type: str = "unknown",
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> RetrievalResult:
        plan = config_builder.build(
            assessment,
            role=role,
            target_population=target_population,
            dimension=dimension,
            topic=topic,
            intent=intent,
            user_query=user_query,
            layers=tuple(layers) if layers else None,
            query_type=query_type,
        )
        return self.retrieve(plan, raw_query=user_query, request_id=request_id, trace_id=trace_id)

    def _dense_stage(self, plan: RetrievalPlan) -> list[RetrievalHit]:
        if self.embedding_provider is None or self.dense_store is None:
            raise ProviderUnavailableError("Dense retrieval dependencies are not configured", code="DENSE_PROVIDER_MISSING")
        output = self.embedding_provider.embed_queries(plan.queries)
        self._last_embedding_latency_ms = output.latency_ms
        by_layer: dict[str, list[RetrievalHit]] = defaultdict(list)
        for query_vector in output.dense_vectors:
            for budget in plan.layers:
                hits = self.dense_store.search_dense(
                    query_vector,
                    limit=plan.dense_candidate_k,
                    filters=plan.filters.for_layer(budget.layer),
                )
                by_layer[budget.layer].extend(hits)
        selected: list[RetrievalHit] = []
        for budget in plan.layers:
            merged = _merge_hits(by_layer[budget.layer], score_field="dense_score")
            selected.extend(merged[: budget.quota])
        selected.sort(key=lambda hit: (-(hit.dense_score if hit.dense_score is not None else float("-inf")), hit.chunk_id))
        return [hit.clone(rank=rank, retriever="dense") for rank, hit in enumerate(selected)]

    def _sparse_stage(self, plan: RetrievalPlan) -> list[RetrievalHit]:
        if self.sparse_retriever is None:
            raise ProviderUnavailableError("BM25S retriever is not configured", code="SPARSE_PROVIDER_MISSING")
        by_layer: dict[str, list[RetrievalHit]] = defaultdict(list)
        for query in plan.queries:
            for budget in plan.layers:
                hits = self.sparse_retriever.search(
                    query,
                    limit=plan.sparse_candidate_k,
                    filters=plan.filters.for_layer(budget.layer),
                )
                by_layer[budget.layer].extend(hits)
        selected: list[RetrievalHit] = []
        for budget in plan.layers:
            merged = _merge_hits(by_layer[budget.layer], score_field="sparse_score")
            selected.extend(merged[: budget.quota])
        selected.sort(key=lambda hit: (-(hit.sparse_score if hit.sparse_score is not None else float("-inf")), hit.chunk_id))
        return [hit.clone(rank=rank, retriever="bm25s") for rank, hit in enumerate(selected)]

    def _embedding_version(self) -> str | None:
        if self.embedding_provider is None:
            return None
        info = self.embedding_provider.model_info()
        provider = info.get("provider")
        version = info.get("model_version") or info.get("package_version")
        return f"{provider}:{version}" if provider and version else str(version) if version else None

    def _embedding_latency(self, dense_hits: Sequence[RetrievalHit], sparse_hits: Sequence[RetrievalHit]) -> float | None:
        # Providers expose the precise latency on their output, but the service
        # intentionally keeps the trace independent of provider-specific state.
        # Retrieval stage timing remains the authoritative end-to-end measure.
        return self._last_embedding_latency_ms

    def _reranker_version(self) -> str | None:
        info = self.reranker.model_info()
        version = info.get("model_version") or info.get("package_version")
        provider = info.get("provider")
        return f"{provider}:{version}" if provider and version else str(version) if version else None

    def _reranker_revision(self) -> str | None:
        return self.reranker.model_info().get("model_revision")

    def _index_value(self, name: str) -> str | None:
        value = self.index_manifest.get(name)
        return str(value) if value is not None else None

    @staticmethod
    def _assert_safe_query(query: str) -> None:
        if any(
            re.search(pattern, query, re.IGNORECASE)
            for pattern in (
                r"\bSUBJ_[A-Za-z0-9_.-]+\b",
                r"[\w.+-]+@[\w-]+\.[\w.-]+",
                r"(?<!\d)\d{7,}(?!\d)",
            )
        ):
            raise UnsafeQueryError("Query contains a direct identity or identifier token")


def _merge_hits(hits: Sequence[RetrievalHit], *, score_field: str) -> list[RetrievalHit]:
    merged: dict[str, RetrievalHit] = {}
    for hit in hits:
        previous = merged.get(hit.chunk_id)
        if previous is None:
            merged[hit.chunk_id] = hit.clone(rank=0)
            continue
        left = getattr(previous, score_field)
        right = getattr(hit, score_field)
        if right is not None and (left is None or right > left):
            merged[hit.chunk_id] = hit.clone(rank=0)
    return sorted(
        merged.values(),
        key=lambda hit: (-(getattr(hit, score_field) if getattr(hit, score_field) is not None else float("-inf")), hit.chunk_id),
    )
