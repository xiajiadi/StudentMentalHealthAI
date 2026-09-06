"""Map rich internal objects to the deliberately strict knowledge.v1 contract."""

from __future__ import annotations

from typing import Any

from ..domain.chunk import KnowledgeChunk
from ..domain.document import CanonicalDocument


def _source_type(document: CanonicalDocument) -> str:
    declared = document.source.metadata.get("source_type", document.metadata.extra.get("source_type", "other"))
    return str(declared)


def to_contract_document(document: CanonicalDocument) -> dict[str, Any]:
    metadata = document.metadata
    return {
        "schema_version": "knowledge.v1",
        "document_id": document.document_id,
        "title": document.title,
        "source": {
            "organization": metadata.organization or "",
            "author": metadata.author,
            "published_year": metadata.published_year,
            "source_type": _source_type(document),
            "locator": {"url": metadata.source_url, "file_name": document.source.filename},
        },
        "language": document.language,
        "population_scope": list(metadata.population_scope),
        "category": metadata.category,
        "rights_status": metadata.rights_status,
        "review_status": metadata.review_status,
        "version": document.pipeline_version,
        "content_hash": document.content_hash,
        "ingestion": {
            "pipeline_version": document.pipeline_version,
            "ingested_at": document.source.received_at,
        },
    }


def to_contract_chunk(chunk: KnowledgeChunk) -> dict[str, Any]:
    metadata = chunk.metadata
    page_label = "unknown"
    if chunk.page_start is not None:
        page_label = str(chunk.page_start) if chunk.page_end in {None, chunk.page_start} else f"{chunk.page_start}-{chunk.page_end}"
    section = chunk.section or "document"
    locator = f"file:{metadata.get('source_filename')}; section:{section}; pages:{page_label}"
    return {
        "schema_version": "knowledge.v1",
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "text": chunk.text,
        "content_type": "source_excerpt",
        "location": {
            "section": section,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
        },
        "citation": {
            "title": str(metadata.get("title") or ""),
            "organization": str(metadata.get("organization") or ""),
            "locator": locator,
        },
        "population_scope": list(metadata.get("target_population") or []),
        "role_scope": list(metadata.get("role_scope") or []),
        "risk_scope": list(metadata.get("risk_scope") or []),
        "review_status": metadata.get("review_status", "pending"),
        "rights_status": metadata.get("rights_status", "unknown"),
        "content_hash": chunk.content_hash,
        "embedding": {"model_id": None, "model_version": None, "status": "not_indexed"},
    }

