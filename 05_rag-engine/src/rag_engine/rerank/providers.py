"""Candidate-only reranker adapters."""

from __future__ import annotations

import importlib.metadata
import inspect
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any, Sequence

import numpy as np

from ..config import ModelConfig, RAGConfig
from ..domain import RetrievalHit
from ..exceptions import ProviderUnavailableError


class RerankerProvider(ABC):
    @abstractmethod
    def rerank(self, query: str, hits: Sequence[RetrievalHit], *, limit: int) -> list[RetrievalHit]:
        raise NotImplementedError

    @abstractmethod
    def model_info(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self, *, load: bool = False) -> dict[str, Any]:
        raise NotImplementedError


class NoOpReranker(RerankerProvider):
    """Explicitly disabled reranking implementation."""

    def rerank(self, query: str, hits: Sequence[RetrievalHit], *, limit: int) -> list[RetrievalHit]:
        return [hit.clone(rank=rank) for rank, hit in enumerate(list(hits)[:limit])]

    def model_info(self) -> dict[str, Any]:
        return {"provider": "noop", "model_id": None, "model_version": None, "loaded": True, "enabled": False}

    def health_check(self, *, load: bool = False) -> dict[str, Any]:
        return {"status": "disabled", **self.model_info()}


class BGERerankerProvider(RerankerProvider):
    """Lazy adapter for FlagEmbedding's current FlagAutoReranker API."""

    def __init__(self, model: ModelConfig) -> None:
        self.model = model
        self._runtime = RAGConfig.resolve_model_runtime(model)
        self._reranker: Any | None = None
        self._load_error: str | None = None
        self._load_latency_ms: float | None = None
        self._score_probe_latency_ms: float | None = None
        try:
            self.package_version = importlib.metadata.version("FlagEmbedding")
        except importlib.metadata.PackageNotFoundError:
            self.package_version = "not-installed"

    def _load(self) -> Any:
        if self._reranker is not None:
            return self._reranker
        if self._load_error:
            raise ProviderUnavailableError(self._load_error, code="BGE_RERANKER_LOAD_FAILED")
        started = perf_counter()
        try:
            from FlagEmbedding import FlagAutoReranker

            kwargs: dict[str, Any] = {
                "query_max_length": 256,
                "max_length": 512,
                "batch_size": 32,
                "use_fp16": self._runtime["precision"] == "fp16",
                "devices": self._runtime["device"],
                "cache_dir": self._runtime["cache_path"],
            }
            factory = getattr(FlagAutoReranker, "from_finetuned", None)
            if factory is None:
                raise ProviderUnavailableError(
                    "Installed FlagEmbedding has no FlagAutoReranker.from_finetuned API",
                    code="BGE_RERANKER_API_UNSUPPORTED",
                )
            signature = inspect.signature(factory)
            accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
            if not accepts_kwargs:
                kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
            self._reranker = factory(self.model.model_name, **kwargs)
            self._load_latency_ms = (perf_counter() - started) * 1000
            return self._reranker
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            self._load_latency_ms = (perf_counter() - started) * 1000
            self._load_error = f"BGE reranker could not be loaded: {type(exc).__name__}: {exc}"
            raise ProviderUnavailableError(self._load_error, code="BGE_RERANKER_LOAD_FAILED") from exc

    def _compute_scores(self, pairs: Sequence[Sequence[str]]) -> np.ndarray:
        reranker = self._load()
        pair_list = [list(pair) for pair in pairs]
        try:
            scores = reranker.compute_score(pair_list, normalize=True)
        except TypeError:
            scores = reranker.compute_score(pair_list)
        score_array = np.asarray(scores, dtype=np.float32).reshape(-1)
        if len(score_array) != len(pair_list):
            raise ProviderUnavailableError(
                f"Reranker returned {len(score_array)} scores for {len(pair_list)} candidates",
                code="BGE_RERANKER_BAD_OUTPUT",
            )
        return score_array

    def rerank(self, query: str, hits: Sequence[RetrievalHit], *, limit: int) -> list[RetrievalHit]:
        candidates = list(hits)[:limit]
        if not candidates:
            return []
        pairs = [[query, hit.record.text] for hit in candidates]
        score_array = self._compute_scores(pairs)
        ordered = sorted(
            zip(candidates, score_array.tolist()),
            key=lambda item: (-float(item[1]), item[0].chunk_id),
        )
        return [hit.clone(rank=rank, retriever="bge-reranker-v2-m3", rerank_score=float(score)) for rank, (hit, score) in enumerate(ordered)]

    def model_info(self) -> dict[str, Any]:
        return {
            "provider": "FlagEmbedding",
            "package_version": self.package_version,
            "model_id": self.model.contract_model_id,
            "model_name": self.model.model_name,
            "model_version": self.model.model_version,
            "model_revision": self.model.model_revision,
            "device": self._runtime["device"],
            "precision": self._runtime["precision"],
            "cache_path": self._runtime["cache_path"],
            "loaded": self._reranker is not None,
            "load_latency_ms": self._load_latency_ms,
            "score_probe_latency_ms": self._score_probe_latency_ms,
            "load_error": self._load_error,
        }

    def health_check(self, *, load: bool = False) -> dict[str, Any]:
        if not load:
            return {"status": "not_loaded", **self.model_info()}
        try:
            started = perf_counter()
            score = self._compute_scores([["reranker health probe", "approved support passage"]])
            self._score_probe_latency_ms = (perf_counter() - started) * 1000
            return {
                "status": "ok",
                **self.model_info(),
                "score_probe": {"status": "ok", "score": float(score[0]), "latency_ms": self._score_probe_latency_ms},
            }
        except ProviderUnavailableError as exc:
            return {"status": "unavailable", "error_code": exc.code, "error": exc.message, **self.model_info()}
        except Exception as exc:
            message = f"BGE reranker score probe failed: {type(exc).__name__}: {exc}"
            return {"status": "unavailable", "error_code": "BGE_RERANKER_SCORE_FAILED", "error": message, **self.model_info()}
