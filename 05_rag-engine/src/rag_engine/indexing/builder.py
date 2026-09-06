"""Explicit, stable index construction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..config import RAGConfig
from ..domain import IndexManifest, KnowledgeRecord, stable_digest, utc_now
from ..embedding import EmbeddingProvider
from ..exceptions import ProviderUnavailableError
from ..stores import VectorStoreProvider


@dataclass(frozen=True)
class IndexBuildResult:
    manifest: IndexManifest
    records: tuple[KnowledgeRecord, ...]
    embedding_latency_ms: float
    reused: bool


class IndexBuilder:
    """Builds an index as an explicit operation, never at application startup."""

    def __init__(self, embedding_provider: EmbeddingProvider, vector_store: VectorStoreProvider) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def build(
        self,
        records: Sequence[KnowledgeRecord],
        *,
        config: RAGConfig,
        index_dir: str | Path,
        excluded_count: int = 0,
        timestamp: str | None = None,
    ) -> IndexBuildResult:
        if not records:
            raise ProviderUnavailableError("Cannot build an index from an empty corpus", code="INDEX_EMPTY_CORPUS")
        records = tuple(records)
        model_info = self.embedding_provider.model_info()
        corpus_version = f"sha256:{stable_digest([self._record_fingerprint(record) for record in sorted(records, key=lambda item: item.chunk_id)])}"
        config_hash = f"sha256:{config.config_hash}"
        index_key = stable_digest(
            {
                "corpus_version": corpus_version,
                "embedding_provider": model_info.get("provider"),
                "embedding_model": model_info.get("model_name"),
                "model_version": model_info.get("model_version"),
                "model_revision": model_info.get("model_revision"),
                "store": type(self.vector_store).__name__,
                "distance": config.distance,
                "config_hash": config_hash,
            }
        )[:24]
        index_id = f"INDEX_{index_key}"
        target = Path(index_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)
        manifest_path = target / "manifest.json"
        existing = self._read_manifest(manifest_path)
        if existing is not None and existing.get("index_id") == index_id and int(existing.get("chunk_count", -1)) == len(records):
            # A manifest alone is not enough: a caller may point at a fresh
            # provider instance or a missing store directory.  Reuse only when
            # the underlying provider confirms the expected population.
            try:
                current_count = existing.get("chunk_count")
                store_count = self.vector_store.index_info().get("count")
                if store_count is not None:
                    current_count = int(store_count)
            except Exception:
                current_count = None
            if current_count == len(records):
                manifest = self._manifest_from_dict(existing)
                return IndexBuildResult(manifest=manifest, records=records, embedding_latency_ms=0.0, reused=True)

        output = self.embedding_provider.embed_documents([record.context_text for record in records])
        dimension = output.dimension
        if dimension < 1:
            raise ProviderUnavailableError("Embedding provider returned zero dimension", code="EMBEDDING_DIMENSION_EMPTY")
        self.vector_store.create_index(dimension=dimension, distance=config.distance)
        if existing is not None:
            previous_ids = {str(item) for item in existing.get("eligible_chunk_ids", [])}
            current_ids = {record.chunk_id for record in records}
            stale_ids = sorted(previous_ids - current_ids)
            if stale_ids:
                self.vector_store.delete(chunk_ids=stale_ids)
        self.vector_store.upsert(records, output.dense_vectors, output.sparse_vectors)
        store_info = self.vector_store.index_info()
        manifest = IndexManifest(
            index_id=index_id,
            index_version="1.0.0",
            corpus_version=corpus_version,
            chunk_count=len(records),
            embedding_provider=str(model_info.get("provider") or type(self.embedding_provider).__name__),
            embedding_model=str(model_info.get("model_name") or model_info.get("model_id") or "unknown"),
            model_revision=str(model_info.get("model_revision")) if model_info.get("model_revision") else None,
            dimension=dimension,
            store=str(store_info.get("provider") or type(self.vector_store).__name__),
            store_version=str(store_info.get("version") or "unknown"),
            distance=config.distance,
            config_hash=config_hash,
            timestamp=timestamp or utc_now(),
            eligible_chunk_ids=tuple(record.chunk_id for record in records),
            excluded_count=excluded_count,
        )
        manifest_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (target / "corpus_ids.json").write_text(json.dumps(list(manifest.eligible_chunk_ids), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return IndexBuildResult(manifest=manifest, records=records, embedding_latency_ms=output.latency_ms, reused=False)

    @staticmethod
    def _record_fingerprint(record: KnowledgeRecord) -> dict[str, Any]:
        return {
            "chunk_id": record.chunk_id,
            "document_id": record.document_id,
            "text": record.text,
            "context_text": record.context_text,
            "content_hash": record.content_hash,
        }

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _manifest_from_dict(value: dict[str, Any]) -> IndexManifest:
        return IndexManifest(
            index_id=str(value["index_id"]),
            index_version=str(value["index_version"]),
            corpus_version=str(value["corpus_version"]),
            chunk_count=int(value["chunk_count"]),
            embedding_provider=str(value["embedding_provider"]),
            embedding_model=str(value["embedding_model"]),
            model_revision=value.get("model_revision"),
            dimension=int(value["dimension"]),
            store=str(value["store"]),
            store_version=str(value["store_version"]),
            distance=str(value["distance"]),
            config_hash=str(value["config_hash"]),
            timestamp=str(value["timestamp"]),
            eligible_chunk_ids=tuple(str(item) for item in value.get("eligible_chunk_ids", [])),
            excluded_count=int(value.get("excluded_count", 0)),
        )
