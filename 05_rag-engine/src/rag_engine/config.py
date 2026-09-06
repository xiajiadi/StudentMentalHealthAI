"""Validated module-local configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .domain import stable_digest
from .exceptions import InvalidConfigurationError


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    contract_model_id: str
    model_name: str
    model_version: str
    model_revision: str | None
    device: str
    precision: str
    cache_dir_env: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, name: str) -> "ModelConfig":
        required = {
            "provider",
            "contract_model_id",
            "model_name",
            "model_version",
            "model_revision",
            "device",
            "precision",
            "cache_dir_env",
        }
        unknown = set(value) - required
        missing = required - set(value)
        if unknown or missing:
            raise InvalidConfigurationError(f"Invalid {name} model config; missing={sorted(missing)}, unknown={sorted(unknown)}")
        model = cls(
            provider=str(value["provider"]),
            contract_model_id=str(value["contract_model_id"]),
            model_name=str(value["model_name"]),
            model_version=str(value["model_version"]),
            model_revision=str(value["model_revision"]) if value["model_revision"] is not None else None,
            device=str(value["device"]),
            precision=str(value["precision"]),
            cache_dir_env=str(value["cache_dir_env"]),
        )
        if not model.model_name or not model.model_version:
            raise InvalidConfigurationError(f"{name} model name/version cannot be empty")
        if model.device not in {"auto", "cpu"} and not model.device.startswith("cuda"):
            raise InvalidConfigurationError(f"Unsupported {name} device: {model.device}")
        if model.precision not in {"auto", "fp32", "fp16", "bf16"}:
            raise InvalidConfigurationError(f"Unsupported {name} precision: {model.precision}")
        return model

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "contract_model_id": self.contract_model_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_revision": self.model_revision,
            "device": self.device,
            "precision": self.precision,
            "cache_dir_env": self.cache_dir_env,
        }


@dataclass(frozen=True)
class StoreConfig:
    chroma_collection: str
    chroma_path: Path
    qdrant_collection: str
    qdrant_path: Path
    bm25_path: Path

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, base_dir: Path) -> "StoreConfig":
        required = {"chroma_collection", "chroma_path", "qdrant_collection", "qdrant_path", "bm25_path"}
        unknown = set(value) - required
        missing = required - set(value)
        if unknown or missing:
            raise InvalidConfigurationError(f"Invalid stores config; missing={sorted(missing)}, unknown={sorted(unknown)}")

        def resolve(raw: Any) -> Path:
            path = Path(str(raw))
            return path if path.is_absolute() else (base_dir / path).resolve()

        return cls(
            chroma_collection=str(value["chroma_collection"]),
            chroma_path=resolve(value["chroma_path"]),
            qdrant_collection=str(value["qdrant_collection"]),
            qdrant_path=resolve(value["qdrant_path"]),
            bm25_path=resolve(value["bm25_path"]),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "chroma_collection": self.chroma_collection,
            "chroma_path": str(self.chroma_path),
            "qdrant_collection": self.qdrant_collection,
            "qdrant_path": str(self.qdrant_path),
            "bm25_path": str(self.bm25_path),
        }


@dataclass(frozen=True)
class RAGConfig:
    schema_version: str
    environment: str
    retrieval_mode: str
    dense_candidate_k: int
    sparse_candidate_k: int
    fusion_candidate_k: int
    rerank_candidate_k: int
    final_k: int
    context_max_chars: int
    rrf_k: int
    distance: str
    embedding: ModelConfig
    reranker: ModelConfig
    stores: StoreConfig
    source_path: Path | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, base_dir: Path | None = None) -> "RAGConfig":
        required = {
            "schema_version",
            "environment",
            "retrieval_mode",
            "dense_candidate_k",
            "sparse_candidate_k",
            "fusion_candidate_k",
            "rerank_candidate_k",
            "final_k",
            "context_max_chars",
            "rrf_k",
            "distance",
            "embedding",
            "reranker",
            "stores",
        }
        unknown = set(value) - required
        missing = required - set(value)
        if unknown or missing:
            raise InvalidConfigurationError(f"Invalid RAG config; missing={sorted(missing)}, unknown={sorted(unknown)}")
        if str(value["schema_version"]) != "rag-config.v1":
            raise InvalidConfigurationError("schema_version must be rag-config.v1")
        if str(value["environment"]) not in {"local", "test", "demo", "research"}:
            raise InvalidConfigurationError(f"Unsupported environment: {value['environment']}")
        if str(value["retrieval_mode"]) not in {"dense", "bm25", "hybrid"}:
            raise InvalidConfigurationError(f"Unsupported retrieval mode: {value['retrieval_mode']}")
        if str(value["distance"]) not in {"cosine", "l2", "ip"}:
            raise InvalidConfigurationError(f"Unsupported vector distance: {value['distance']}")

        limits = [
            "dense_candidate_k",
            "sparse_candidate_k",
            "fusion_candidate_k",
            "rerank_candidate_k",
            "final_k",
            "context_max_chars",
            "rrf_k",
        ]
        parsed: dict[str, int] = {}
        for field_name in limits:
            raw_number = value[field_name]
            if isinstance(raw_number, bool) or not isinstance(raw_number, int) or raw_number < 1:
                raise InvalidConfigurationError(f"{field_name} must be a positive integer")
            parsed[field_name] = raw_number
        if base_dir is None:
            base_dir = Path.cwd()
        embedding_value = value["embedding"]
        reranker_value = value["reranker"]
        stores_value = value["stores"]
        if not isinstance(embedding_value, Mapping) or not isinstance(reranker_value, Mapping) or not isinstance(stores_value, Mapping):
            raise InvalidConfigurationError("embedding, reranker, and stores must be objects")
        raw_copy = json.loads(json.dumps(value, ensure_ascii=False))
        return cls(
            schema_version=str(value["schema_version"]),
            environment=str(value["environment"]),
            retrieval_mode=str(value["retrieval_mode"]),
            dense_candidate_k=parsed["dense_candidate_k"],
            sparse_candidate_k=parsed["sparse_candidate_k"],
            fusion_candidate_k=parsed["fusion_candidate_k"],
            rerank_candidate_k=parsed["rerank_candidate_k"],
            final_k=parsed["final_k"],
            context_max_chars=parsed["context_max_chars"],
            rrf_k=parsed["rrf_k"],
            distance=str(value["distance"]),
            embedding=ModelConfig.from_mapping(embedding_value, name="embedding"),
            reranker=ModelConfig.from_mapping(reranker_value, name="reranker"),
            stores=StoreConfig.from_mapping(stores_value, base_dir=base_dir),
            raw=raw_copy,
        )

    @classmethod
    def load(cls, path: str | Path) -> "RAGConfig":
        config_path = Path(path).resolve()
        try:
            value = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidConfigurationError(f"Cannot load RAG config {config_path}: {exc}") from exc
        if not isinstance(value, Mapping):
            raise InvalidConfigurationError("RAG config root must be an object")
        result = cls.from_mapping(value, base_dir=config_path.parent.parent,)
        object.__setattr__(result, "source_path", config_path)
        return result

    @property
    def config_hash(self) -> str:
        return stable_digest(self.raw or self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "environment": self.environment,
            "retrieval_mode": self.retrieval_mode,
            "dense_candidate_k": self.dense_candidate_k,
            "sparse_candidate_k": self.sparse_candidate_k,
            "fusion_candidate_k": self.fusion_candidate_k,
            "rerank_candidate_k": self.rerank_candidate_k,
            "final_k": self.final_k,
            "context_max_chars": self.context_max_chars,
            "rrf_k": self.rrf_k,
            "distance": self.distance,
            "embedding": self.embedding.to_dict(),
            "reranker": self.reranker.to_dict(),
            "stores": self.stores.to_dict(),
        }

    @staticmethod
    def resolve_device(requested: str) -> str:
        if requested != "auto":
            return requested
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    @classmethod
    def resolve_model_runtime(cls, model: ModelConfig) -> dict[str, str]:
        device = cls.resolve_device(model.device)
        precision = model.precision
        if precision == "auto":
            precision = "fp16" if device.startswith("cuda") else "fp32"
        if precision in {"fp16", "bf16"} and device == "cpu":
            precision = "fp32"
        cache_path = Path(os.getenv(model.cache_dir_env, "data/model-cache")).expanduser()
        return {"device": device, "precision": precision, "cache_path": str(cache_path)}
