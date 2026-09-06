"""Vector-store adapters. Provider objects never escape this module boundary."""

from __future__ import annotations

import json
import math
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..domain import KnowledgeRecord, MetadataFilter, RetrievalHit
from ..exceptions import ProviderUnavailableError


class VectorStoreProvider(ABC):
    """Provider-neutral dense/sparse vector-store surface."""

    @abstractmethod
    def create_index(self, *, dimension: int, distance: str = "cosine") -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        records: Sequence[KnowledgeRecord],
        dense_vectors: Sequence[Sequence[float]],
        sparse_vectors: Sequence[Mapping[int, float] | None] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, *, chunk_ids: Sequence[str] | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def search_dense(self, query_vector: Sequence[float], *, limit: int, filters: MetadataFilter) -> list[RetrievalHit]:
        raise NotImplementedError

    def search_sparse(self, query_vector: Mapping[int, float], *, limit: int, filters: MetadataFilter) -> list[RetrievalHit]:
        raise ProviderUnavailableError("This vector store does not expose sparse search", code="SPARSE_STORE_UNSUPPORTED")

    def search_hybrid(
        self,
        dense_vector: Sequence[float],
        sparse_vector: Mapping[int, float],
        *,
        limit: int,
        filters: MetadataFilter,
        candidate_limit: int,
    ) -> list[RetrievalHit]:
        raise ProviderUnavailableError("This vector store does not expose native hybrid search", code="HYBRID_STORE_UNSUPPORTED")

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def index_info(self) -> dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        """Release provider resources when the store owns a local client."""

        return None


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _flat_metadata(record: KnowledgeRecord) -> dict[str, Any]:
    """Convert structured Knowledge metadata to Chroma's scalar metadata values."""

    result: dict[str, Any] = {}
    for key, value in record.metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
        elif isinstance(value, (list, tuple, dict)):
            result[f"{key}_json"] = _json_value(value)
    result.update(
        {
            "chunk_id": record.chunk_id,
            "document_id": record.document_id,
            "layer": record.layer,
            "review_status": record.review_status,
            "rights_status": record.rights_status,
            "source_filename": str(record.metadata.get("source_filename") or ""),
            "source_url": str(record.metadata.get("source_url") or ""),
            "role_scope_values": "|".join(record.role_scope),
            "target_population_values": "|".join(record.target_population),
            "risk_scope_values": "|".join(record.risk_scope),
            "record_metadata_json": _json_value(record.metadata),
            "citation_json": _json_value(record.citation),
            "context_text": record.context_text,
        }
    )
    return result


def _record_from_payload(payload: Mapping[str, Any], text: str | None = None) -> KnowledgeRecord:
    metadata_value = payload.get("record_metadata_json")
    if isinstance(metadata_value, str):
        try:
            metadata = json.loads(metadata_value)
        except json.JSONDecodeError:
            metadata = {}
    else:
        metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    metadata = dict(metadata)
    chunk_id = str(payload.get("chunk_id") or metadata.get("chunk_id") or "")
    document_id = str(payload.get("document_id") or metadata.get("document_id") or "")
    citation_value = payload.get("citation_json")
    if isinstance(citation_value, str):
        try:
            citation = json.loads(citation_value)
        except json.JSONDecodeError:
            citation = {}
    else:
        citation = payload.get("citation", {})
    if not isinstance(citation, Mapping):
        citation = {}
    return KnowledgeRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        text=str(text or payload.get("text") or ""),
        context_text=str(payload.get("context_text") or text or payload.get("text") or ""),
        metadata=metadata,
        citation={str(key): str(value) for key, value in citation.items()},
        layer=str(payload.get("layer") or metadata.get("layer") or "knowledge"),
    )


def _where_filter(filters: MetadataFilter) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []

    def add_values(field: str, values: Sequence[str]) -> None:
        if not values:
            return
        if len(values) == 1:
            clauses.append({field: {"$eq": values[0]}})
        else:
            clauses.append({"$or": [{field: {"$eq": value}} for value in values]})

    add_values("layer", filters.layers)
    add_values("review_status", filters.review_status)
    add_values("rights_status", filters.rights_status)
    add_values("document_id", filters.document_ids)
    add_values("chunk_id", filters.chunk_ids)
    add_values("source_filename", filters.source)
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vector dimensions do not match")
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


class MemoryVectorStore(VectorStoreProvider):
    """Small in-memory test double; it is not used as the Round 1 dense baseline."""

    def __init__(self) -> None:
        self._dimension = 0
        self._distance = "cosine"
        self._records: dict[str, tuple[KnowledgeRecord, tuple[float, ...]]] = {}

    def create_index(self, *, dimension: int, distance: str = "cosine") -> None:
        self._dimension = int(dimension)
        self._distance = distance

    def upsert(
        self,
        records: Sequence[KnowledgeRecord],
        dense_vectors: Sequence[Sequence[float]],
        sparse_vectors: Sequence[Mapping[int, float] | None] | None = None,
    ) -> None:
        if len(records) != len(dense_vectors):
            raise ValueError("records and dense_vectors must have equal length")
        for record, vector in zip(records, dense_vectors):
            if len(vector) != self._dimension:
                raise ValueError("vector dimension does not match index")
            self._records[record.chunk_id] = (record, tuple(float(item) for item in vector))

    def delete(self, *, chunk_ids: Sequence[str] | None = None) -> None:
        if chunk_ids is None:
            self._records.clear()
            return
        for chunk_id in chunk_ids:
            self._records.pop(chunk_id, None)

    def search_dense(self, query_vector: Sequence[float], *, limit: int, filters: MetadataFilter) -> list[RetrievalHit]:
        ranked = [
            (record, _cosine(query_vector, vector))
            for record, vector in self._records.values()
            if filters.matches(record)
        ]
        ranked.sort(key=lambda item: (-item[1], item[0].chunk_id))
        return [RetrievalHit(record=record, retriever="dense", rank=rank, dense_score=score) for rank, (record, score) in enumerate(ranked[:limit])]

    def health_check(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "memory", "count": len(self._records), "test_only": True}

    def index_info(self) -> dict[str, Any]:
        return {"provider": "memory", "dimension": self._dimension, "distance": self._distance, "count": len(self._records)}


class ChromaVectorStore(VectorStoreProvider):
    """Persistent Chroma dense adapter."""

    def __init__(self, path: str | Path, collection_name: str) -> None:
        self.path = Path(path)
        self.collection_name = collection_name
        self._client: Any | None = None
        self._collection: Any | None = None
        self._dimension = 0
        self._distance = "cosine"

    def _ensure_client(self) -> tuple[Any, Any]:
        if self._client is not None and self._collection is not None:
            return self._client, self._collection
        try:
            import chromadb

            self.path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.path))
            self._collection = self._client.get_collection(self.collection_name)
            metadata = getattr(self._collection, "metadata", None) or {}
            self._distance = str(metadata.get("hnsw:space") or self._distance)
            return self._client, self._collection
        except Exception as exc:
            raise ProviderUnavailableError(
                f"Chroma collection {self.collection_name} is unavailable: {type(exc).__name__}: {exc}",
                code="CHROMA_UNAVAILABLE",
            ) from exc

    def create_index(self, *, dimension: int, distance: str = "cosine") -> None:
        if distance not in {"cosine", "l2", "ip"}:
            raise ValueError(f"Unsupported Chroma distance: {distance}")
        try:
            import chromadb

            self.path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.path))
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": distance},
            )
            self._dimension = int(dimension)
            self._distance = distance
        except Exception as exc:
            raise ProviderUnavailableError(
                f"Chroma could not create collection {self.collection_name}: {type(exc).__name__}: {exc}",
                code="CHROMA_CREATE_FAILED",
            ) from exc

    def upsert(
        self,
        records: Sequence[KnowledgeRecord],
        dense_vectors: Sequence[Sequence[float]],
        sparse_vectors: Sequence[Mapping[int, float] | None] | None = None,
    ) -> None:
        _, collection = self._ensure_client()
        if len(records) != len(dense_vectors):
            raise ValueError("records and dense_vectors must have equal length")
        collection.upsert(
            ids=[record.chunk_id for record in records],
            embeddings=[list(map(float, vector)) for vector in dense_vectors],
            documents=[record.text for record in records],
            metadatas=[_flat_metadata(record) for record in records],
        )
        if records:
            self._dimension = len(dense_vectors[0])

    def delete(self, *, chunk_ids: Sequence[str] | None = None) -> None:
        _, collection = self._ensure_client()
        if chunk_ids is None:
            collection.delete()
        elif chunk_ids:
            collection.delete(ids=list(chunk_ids))

    def search_dense(self, query_vector: Sequence[float], *, limit: int, filters: MetadataFilter) -> list[RetrievalHit]:
        _, collection = self._ensure_client()
        count = int(collection.count())
        if count == 0:
            return []
        post_filter_required = bool(filters.role_scope or filters.target_population or filters.risk_scope or filters.source)
        requested = min(count, max(limit * 5 if post_filter_required else limit, limit))
        kwargs: dict[str, Any] = {
            "query_embeddings": [list(map(float, query_vector))],
            "n_results": requested,
            "include": ["documents", "metadatas", "distances"],
        }
        where = _where_filter(filters)
        if where is not None:
            kwargs["where"] = where
        try:
            result = collection.query(**kwargs)
        except Exception as exc:
            raise ProviderUnavailableError(
                f"Chroma dense query failed: {type(exc).__name__}: {exc}",
                code="CHROMA_QUERY_FAILED",
            ) from exc
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[RetrievalHit] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            document = documents[index] if index < len(documents) else ""
            record = _record_from_payload(metadata, document)
            if record.chunk_id != str(chunk_id):
                record = KnowledgeRecord(
                    chunk_id=str(chunk_id),
                    document_id=record.document_id,
                    text=record.text,
                    context_text=record.context_text,
                    metadata=record.metadata,
                    citation=record.citation,
                    layer=record.layer,
                )
            if not filters.matches(record):
                continue
            distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 0.0
            score = 1.0 - distance if self._distance == "cosine" else -distance
            hits.append(RetrievalHit(record=record, retriever="dense", rank=len(hits), dense_score=score))
            if len(hits) >= limit:
                break
        return hits

    def health_check(self) -> dict[str, Any]:
        try:
            _, collection = self._ensure_client()
            return {"status": "ok", "provider": "chroma", "path": str(self.path), "collection": collection.name, "count": collection.count()}
        except ProviderUnavailableError as exc:
            return {"status": "unavailable", "provider": "chroma", "error_code": exc.code, "error": exc.message}

    def index_info(self) -> dict[str, Any]:
        _, collection = self._ensure_client()
        return {
            "provider": "chroma",
            "path": str(self.path),
            "collection": collection.name,
            "dimension": self._dimension,
            "distance": self._distance,
            "count": collection.count(),
            "version": _package_version("chromadb"),
        }

    def close(self) -> None:
        client, self._client = self._client, None
        self._collection = None
        if client is not None:
            closer = getattr(client, "close", None)
            if callable(closer):
                closer()


class QdrantVectorStore(VectorStoreProvider):
    """Qdrant local-mode adapter with dense, sparse, and native RRF paths."""

    def __init__(self, path: str | Path, collection_name: str) -> None:
        self.path = Path(path)
        self.collection_name = collection_name
        self._client: Any | None = None
        self._models: Any | None = None
        self._dimension = 0
        self._distance = "cosine"

    def _ensure_client(self) -> tuple[Any, Any]:
        if self._client is not None and self._models is not None:
            return self._client, self._models
        try:
            from qdrant_client import QdrantClient, models

            self.path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(self.path))
            self._models = models
            return self._client, self._models
        except Exception as exc:
            raise ProviderUnavailableError(
                f"Qdrant local client is unavailable: {type(exc).__name__}: {exc}",
                code="QDRANT_UNAVAILABLE",
            ) from exc

    def create_index(self, *, dimension: int, distance: str = "cosine") -> None:
        client, models = self._ensure_client()
        distance_map = {
            "cosine": models.Distance.COSINE,
            "l2": models.Distance.EUCLID,
            "ip": models.Distance.DOT,
        }
        if distance not in distance_map:
            raise ValueError(f"Unsupported Qdrant distance: {distance}")
        try:
            client.get_collection(self.collection_name)
        except Exception:
            try:
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={"dense": models.VectorParams(size=dimension, distance=distance_map[distance])},
                    sparse_vectors_config={"sparse": models.SparseVectorParams()},
                )
            except Exception as exc:
                raise ProviderUnavailableError(
                    f"Qdrant could not create collection {self.collection_name}: {type(exc).__name__}: {exc}",
                    code="QDRANT_CREATE_FAILED",
                ) from exc
        self._dimension = int(dimension)
        self._distance = distance

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"student-mental-health-ai:{chunk_id}"))

    @staticmethod
    def _payload(record: KnowledgeRecord) -> dict[str, Any]:
        return {
            "chunk_id": record.chunk_id,
            "document_id": record.document_id,
            "text": record.text,
            "context_text": record.context_text,
            "layer": record.layer,
            "role_scope": list(record.role_scope),
            "target_population": list(record.target_population),
            "risk_scope": list(record.risk_scope),
            "review_status": record.review_status,
            "rights_status": record.rights_status,
            "source_filename": record.metadata.get("source_filename"),
            "source_url": record.metadata.get("source_url"),
            "metadata": dict(record.metadata),
            "citation": dict(record.citation),
        }

    def upsert(
        self,
        records: Sequence[KnowledgeRecord],
        dense_vectors: Sequence[Sequence[float]],
        sparse_vectors: Sequence[Mapping[int, float] | None] | None = None,
    ) -> None:
        client, models = self._ensure_client()
        if len(records) != len(dense_vectors):
            raise ValueError("records and dense_vectors must have equal length")
        sparse_vectors = sparse_vectors or [None for _ in records]
        points = []
        for record, dense, sparse in zip(records, dense_vectors, sparse_vectors):
            vector: dict[str, Any] = {"dense": list(map(float, dense))}
            if sparse:
                vector["sparse"] = models.SparseVector(
                    indices=[int(key) for key in sparse],
                    values=[float(sparse[key]) for key in sparse],
                )
            points.append(models.PointStruct(id=self._point_id(record.chunk_id), vector=vector, payload=self._payload(record)))
        if points:
            try:
                client.upsert(collection_name=self.collection_name, points=points, wait=True)
            except Exception as exc:
                raise ProviderUnavailableError(
                    f"Qdrant upsert failed: {type(exc).__name__}: {exc}",
                    code="QDRANT_UPSERT_FAILED",
                ) from exc
            self._dimension = len(dense_vectors[0])

    def delete(self, *, chunk_ids: Sequence[str] | None = None) -> None:
        client, models = self._ensure_client()
        if chunk_ids is None:
            client.delete_collection(self.collection_name)
            return
        if chunk_ids:
            client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[self._point_id(chunk_id) for chunk_id in chunk_ids]),
                wait=True,
            )

    @staticmethod
    def _filter(filters: MetadataFilter, models: Any) -> Any | None:
        must: list[Any] = []

        def add_match(key: str, values: Sequence[str], *, any_value: bool = False) -> None:
            if not values:
                return
            if any_value:
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=list(values))))
            elif len(values) == 1:
                must.append(models.FieldCondition(key=key, match=models.MatchValue(value=values[0])))
            else:
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=list(values))))

        add_match("layer", filters.layers)
        add_match("review_status", filters.review_status)
        add_match("rights_status", filters.rights_status)
        add_match("role_scope", filters.role_scope, any_value=True)
        add_match("target_population", filters.target_population, any_value=True)
        add_match("risk_scope", filters.risk_scope, any_value=True)
        add_match("source_filename", filters.source)
        add_match("document_id", filters.document_ids)
        add_match("chunk_id", filters.chunk_ids)
        return models.Filter(must=must) if must else None

    @staticmethod
    def _points(response: Any) -> list[Any]:
        return list(getattr(response, "points", response or []))

    @staticmethod
    def _hit(point: Any, *, retriever: str, dense: float | None = None, sparse: float | None = None, fusion: float | None = None) -> RetrievalHit:
        payload = getattr(point, "payload", None) or {}
        record = _record_from_payload(payload, str(payload.get("text") or ""))
        score = float(getattr(point, "score", 0.0))
        return RetrievalHit(record=record, retriever=retriever, rank=0, dense_score=dense if dense is not None else (score if retriever == "dense" else None), sparse_score=sparse if sparse is not None else (score if retriever == "sparse" else None), fusion_score=fusion if fusion is not None else (score if retriever == "hybrid" else None))

    def search_dense(self, query_vector: Sequence[float], *, limit: int, filters: MetadataFilter) -> list[RetrievalHit]:
        client, models = self._ensure_client()
        try:
            response = client.query_points(
                collection_name=self.collection_name,
                query=list(map(float, query_vector)),
                using="dense",
                query_filter=self._filter(filters, models),
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"Qdrant dense query failed: {type(exc).__name__}: {exc}", code="QDRANT_QUERY_FAILED") from exc
        hits = [self._hit(point, retriever="dense") for point in self._points(response)]
        return [hit.clone(rank=rank) for rank, hit in enumerate(hits)]

    def search_sparse(self, query_vector: Mapping[int, float], *, limit: int, filters: MetadataFilter) -> list[RetrievalHit]:
        client, models = self._ensure_client()
        sparse = models.SparseVector(indices=[int(key) for key in query_vector], values=[float(query_vector[key]) for key in query_vector])
        try:
            response = client.query_points(
                collection_name=self.collection_name,
                query=sparse,
                using="sparse",
                query_filter=self._filter(filters, models),
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"Qdrant sparse query failed: {type(exc).__name__}: {exc}", code="QDRANT_SPARSE_QUERY_FAILED") from exc
        hits = [self._hit(point, retriever="sparse") for point in self._points(response)]
        return [hit.clone(rank=rank) for rank, hit in enumerate(hits)]

    def search_hybrid(
        self,
        dense_vector: Sequence[float],
        sparse_vector: Mapping[int, float],
        *,
        limit: int,
        filters: MetadataFilter,
        candidate_limit: int,
    ) -> list[RetrievalHit]:
        client, models = self._ensure_client()
        sparse = models.SparseVector(indices=[int(key) for key in sparse_vector], values=[float(sparse_vector[key]) for key in sparse_vector])
        try:
            response = client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(query=list(map(float, dense_vector)), using="dense", limit=candidate_limit),
                    models.Prefetch(query=sparse, using="sparse", limit=candidate_limit),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=self._filter(filters, models),
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"Qdrant hybrid query failed: {type(exc).__name__}: {exc}", code="QDRANT_HYBRID_QUERY_FAILED") from exc
        hits = [self._hit(point, retriever="hybrid") for point in self._points(response)]
        return [hit.clone(rank=rank) for rank, hit in enumerate(hits)]

    def health_check(self) -> dict[str, Any]:
        try:
            client, _ = self._ensure_client()
            collections = client.get_collections()
            names = [str(item.name) for item in collections.collections]
            return {"status": "ok", "provider": "qdrant", "mode": "local", "path": str(self.path), "collection": self.collection_name, "collection_exists": self.collection_name in names}
        except ProviderUnavailableError as exc:
            return {"status": "unavailable", "provider": "qdrant", "error_code": exc.code, "error": exc.message}

    def index_info(self) -> dict[str, Any]:
        client, _ = self._ensure_client()
        info = client.get_collection(self.collection_name)
        return {
            "provider": "qdrant",
            "path": str(self.path),
            "collection": self.collection_name,
            "dimension": self._dimension,
            "distance": self._distance,
            "count": getattr(info, "points_count", None),
            "version": _package_version("qdrant-client"),
            "mode": "local",
        }

    def close(self) -> None:
        client, self._client = self._client, None
        self._models = None
        if client is not None:
            closer = getattr(client, "close", None)
            if callable(closer):
                closer()


def _package_version(name: str) -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"
