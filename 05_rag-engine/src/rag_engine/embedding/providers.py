"""Embedding adapters with a narrow provider-neutral interface."""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

import numpy as np

from ..config import ModelConfig, RAGConfig
from ..exceptions import ProviderUnavailableError


@dataclass(frozen=True)
class EmbeddingOutput:
    dense_vectors: tuple[tuple[float, ...], ...]
    sparse_vectors: tuple[dict[int, float] | None, ...]
    latency_ms: float

    @property
    def dimension(self) -> int:
        return len(self.dense_vectors[0]) if self.dense_vectors else 0


class EmbeddingProvider(ABC):
    """Stable abstraction consumed by indexing and retrieval services."""

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> EmbeddingOutput:
        raise NotImplementedError

    @abstractmethod
    def embed_queries(self, texts: Sequence[str]) -> EmbeddingOutput:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def model_info(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self, *, load: bool = False) -> dict[str, Any]:
        raise NotImplementedError


def _normalise_rows(value: Any, *, expected: int, dimension: int | None = None) -> tuple[tuple[float, ...], ...]:
    if value is None:
        raise ProviderUnavailableError("Embedding provider returned no dense vectors", code="EMBEDDING_EMPTY_OUTPUT")
    array = np.asarray(value, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2 or array.shape[0] != expected:
        raise ProviderUnavailableError(
            f"Embedding provider returned shape {array.shape}; expected {expected} rows",
            code="EMBEDDING_BAD_SHAPE",
        )
    if dimension is not None and array.shape[1] != dimension:
        raise ProviderUnavailableError(
            f"Embedding dimension changed from {dimension} to {array.shape[1]}",
            code="EMBEDDING_DIMENSION_CHANGED",
        )
    return tuple(tuple(float(item) for item in row) for row in array.tolist())


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic test-only embedding provider; never represents BGE evidence."""

    def __init__(self, *, dimension: int = 64, model_version: str = "mock-deterministic-v1") -> None:
        if dimension < 8:
            raise ValueError("Mock embedding dimension must be at least 8")
        self._dimension = dimension
        self._model_version = model_version

    @staticmethod
    def _tokens(text: str) -> list[str]:
        value = " ".join(str(text).lower().split())
        tokens: list[str] = list(value)
        tokens.extend(value[index : index + 2] for index in range(max(0, len(value) - 1)))
        return tokens or ["<empty>"]

    def _embed(self, texts: Sequence[str]) -> EmbeddingOutput:
        started = perf_counter()
        rows: list[tuple[float, ...]] = []
        for text in texts:
            row = np.zeros(self._dimension, dtype=np.float32)
            for token in self._tokens(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
                index = int.from_bytes(digest[:4], "little") % self._dimension
                sign = 1.0 if digest[4] & 1 else -1.0
                row[index] += sign * (0.5 + (digest[5] / 255.0))
            norm = float(np.linalg.norm(row))
            if norm:
                row /= norm
            rows.append(tuple(float(item) for item in row.tolist()))
        return EmbeddingOutput(tuple(rows), tuple(None for _ in rows), (perf_counter() - started) * 1000)

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingOutput:
        return self._embed(texts)

    def embed_queries(self, texts: Sequence[str]) -> EmbeddingOutput:
        return self._embed(texts)

    @property
    def dimension(self) -> int:
        return self._dimension

    def model_info(self) -> dict[str, Any]:
        return {
            "provider": "mock",
            "model_id": "MODEL_mock_embedding",
            "model_name": "deterministic-hash-embedding",
            "model_version": self._model_version,
            "model_revision": self._model_version,
            "dimension": self._dimension,
            "device": "cpu",
            "precision": "fp32",
            "loaded": True,
            "test_only": True,
        }

    def health_check(self, *, load: bool = False) -> dict[str, Any]:
        return {"status": "ok", **self.model_info()}


class BGEM3EmbeddingProvider(EmbeddingProvider):
    """Lazy adapter for FlagEmbedding's current BGE-M3 implementation."""

    def __init__(
        self,
        model: ModelConfig,
        *,
        return_sparse: bool = True,
        expected_dimension: int = 1024,
    ) -> None:
        self.model = model
        self.return_sparse = return_sparse
        self.expected_dimension = expected_dimension
        self._model: Any | None = None
        self._dimension: int | None = None
        self._load_error: str | None = None
        self._sparse_output_observed = False
        self._sparse_nonempty_rows = 0
        self._sparse_terms_observed = 0
        self._runtime = RAGConfig.resolve_model_runtime(model)
        try:
            self._package_version = importlib.metadata.version("FlagEmbedding")
        except importlib.metadata.PackageNotFoundError:
            self._package_version = "not-installed"

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        if self._load_error:
            raise ProviderUnavailableError(self._load_error, code="BGE_M3_LOAD_FAILED")
        try:
            from FlagEmbedding import BGEM3FlagModel

            kwargs: dict[str, Any] = {
                "use_fp16": self._runtime["precision"] == "fp16",
                "devices": self._runtime["device"],
                "cache_dir": self._runtime["cache_path"],
            }
            signature = inspect.signature(BGEM3FlagModel)
            accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
            if not accepts_kwargs:
                kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
            self._model = BGEM3FlagModel(self.model.model_name, **kwargs)
            return self._model
        except Exception as exc:  # provider errors must become stable module errors
            self._load_error = f"BGE-M3 could not be loaded: {type(exc).__name__}: {exc}"
            raise ProviderUnavailableError(self._load_error, code="BGE_M3_LOAD_FAILED") from exc

    def _encode(self, texts: Sequence[str], *, query: bool) -> EmbeddingOutput:
        if not texts:
            return EmbeddingOutput((), (), 0.0)
        started = perf_counter()
        model = self._load()
        method_name = "encode_queries" if query else "encode_corpus"
        method = getattr(model, method_name, None)
        if method is None:
            raise ProviderUnavailableError(
                f"Installed FlagEmbedding provider has no {method_name} API",
                code="BGE_M3_API_UNSUPPORTED",
            )
        try:
            encoded = method(
                list(texts),
                return_dense=True,
                return_sparse=self.return_sparse,
                return_colbert_vecs=False,
            )
        except TypeError:
            # The current documented API is attempted first. This narrow retry
            # only accommodates a provider build that does not expose optional
            # output switches; it does not substitute a different model.
            encoded = method(list(texts))
        if not isinstance(encoded, Mapping) or "dense_vecs" not in encoded:
            raise ProviderUnavailableError("BGE-M3 output does not contain dense_vecs", code="BGE_M3_BAD_OUTPUT")
        dense = _normalise_rows(encoded["dense_vecs"], expected=len(texts), dimension=self._dimension)
        self._dimension = len(dense[0]) if dense else self.expected_dimension
        sparse_raw = encoded.get("lexical_weights")
        sparse: list[dict[int, float] | None] = []
        if isinstance(sparse_raw, Sequence) and not isinstance(sparse_raw, (str, bytes)):
            for item in sparse_raw:
                if isinstance(item, Mapping):
                    sparse.append({int(key): float(value) for key, value in item.items() if float(value) != 0.0})
                else:
                    sparse.append(None)
        else:
            sparse = [None for _ in texts]
        nonempty = [item for item in sparse if item]
        self._sparse_output_observed = self._sparse_output_observed or bool(nonempty)
        self._sparse_nonempty_rows = max(self._sparse_nonempty_rows, len(nonempty))
        self._sparse_terms_observed = max(self._sparse_terms_observed, sum(len(item) for item in nonempty))
        return EmbeddingOutput(dense, tuple(sparse), (perf_counter() - started) * 1000)

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingOutput:
        return self._encode(texts, query=False)

    def embed_queries(self, texts: Sequence[str]) -> EmbeddingOutput:
        return self._encode(texts, query=True)

    @property
    def dimension(self) -> int:
        return self._dimension or self.expected_dimension

    def model_info(self) -> dict[str, Any]:
        return {
            "provider": "FlagEmbedding",
            "package_version": self._package_version,
            "model_id": self.model.contract_model_id,
            "model_name": self.model.model_name,
            "model_version": self.model.model_version,
            "model_revision": self.model.model_revision,
            "dimension": self.dimension,
            "device": self._runtime["device"],
            "precision": self._runtime["precision"],
            "cache_path": self._runtime["cache_path"],
            "loaded": self._model is not None,
            "sparse_output_requested": self.return_sparse,
            "sparse_output_observed": self._sparse_output_observed,
            "sparse_nonempty_rows_observed": self._sparse_nonempty_rows,
            "sparse_terms_observed": self._sparse_terms_observed,
            "load_error": self._load_error,
        }

    def health_check(self, *, load: bool = False) -> dict[str, Any]:
        if not load:
            return {"status": "not_loaded", **self.model_info()}
        try:
            self._load()
            return {"status": "ok", **self.model_info()}
        except ProviderUnavailableError as exc:
            return {"status": "unavailable", "error_code": exc.code, "error": exc.message, **self.model_info()}
