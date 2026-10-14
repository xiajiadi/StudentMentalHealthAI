"""Backend projection for the exact-pinned school-student research source lane."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Literal

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext

from .contracts import validate_frozen
from .rag import Citation, KnowledgeChunk, RetrievalResult

_TARGET_POPULATION = "secondary_school_student"
_TARGET_ROLE = "student"
_REVIEW_STATUS = "pending"
_RIGHTS_STATUS = "verified"
_PURPOSE = "RESEARCH_SIMULATION"
_CONSUMER_AGE_MIN = 14
_CONSUMER_AGE_MAX = 17
_LAYERS = ("policy", "theory", "intervention")
_QUERY_TRANSFORMS = frozenset({"NONE", "LEXICAL_BILINGUAL_KEYWORD_EXPANSION"})
_CHUNK_ID = re.compile(r"^CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SchoolResearchStudentRagAdapter:
    """Convert isolated package hits to pending Knowledge v1 evidence.

    The package itself is supplied by the container from a server-pinned loader;
    this adapter never takes a path, hash or population from an API request.
    """

    label = "SCHOOL_RESEARCH_STUDENT_SOURCE_PACKAGE"

    def __init__(
        self,
        retriever: Any,
        *,
        expected_manifest_sha256: str,
        expected_package_id: str,
        expected_study_ref: str,
    ) -> None:
        if (
            not isinstance(expected_manifest_sha256, str)
            or not _SHA256.fullmatch(expected_manifest_sha256)
            or not isinstance(expected_package_id, str)
            or not expected_package_id
            or not isinstance(expected_study_ref, str)
            or not expected_study_ref
        ):
            raise ValueError("student research source pins are invalid")
        package = getattr(retriever, "package", None)
        if (
            package is None
            or package.manifest_sha256 != expected_manifest_sha256
            or package.package_id != expected_package_id
            or package.study_ref != expected_study_ref
        ):
            raise ValueError("student research retriever does not match server pins")
        self._retriever = retriever
        self._manifest_sha256 = expected_manifest_sha256
        self._package_id = expected_package_id
        self._study_ref = expected_study_ref
        self._record_by_id = {record.record_id: record for record in package.records}
        self._source_by_id = {source.source_id: source for source in package.sources}

    async def retrieve(
        self,
        *,
        query: str,
        target_population: Literal["secondary_school_student"],
        top_k: int,
        retrieval_id: str,
        context: RequestContext,
    ) -> RetrievalResult:
        if target_population != _TARGET_POPULATION:
            raise error(ErrorCode.FORBIDDEN, detail="research population is not available")
        if not isinstance(retrieval_id, str) or not retrieval_id.startswith("RETR_"):
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid retrieval reference")
        try:
            result = self._retriever.retrieve(
                query,
                target_population=_TARGET_POPULATION,
                limit=top_k,
            )
            self._verify_result(result)
            chunks = tuple(self._to_knowledge_chunk(hit) for hit in result.hits)
            trace = {
                "package_id": self._package_id,
                "manifest_sha256": self._manifest_sha256,
                "study_ref": self._study_ref,
                "purpose": _PURPOSE,
                "target_population": _TARGET_POPULATION,
                "target_role": _TARGET_ROLE,
                "review_status": _REVIEW_STATUS,
                "rights_status": _RIGHTS_STATUS,
                "source_rights_status": "VERIFIED_WITH_CONDITIONS",
                "consumer_age_min": _CONSUMER_AGE_MIN,
                "consumer_age_max": _CONSUMER_AGE_MAX,
                "query_transform": result.query_transform,
                "matched_layers": list(result.matched_layers),
                "missing_layers": list(result.missing_layers),
                "reviewer_kind": "AI_ENGINEERING",
                "research_only": True,
                "professional_approval": False,
                "human_curated": False,
                "ethics_approval": False,
                "clinical_approval": False,
                "psychometric_approval": False,
                "publication_eligible": False,
                "production_use": False,
            }
            return RetrievalResult(
                retrieval_id=retrieval_id,
                chunks=chunks,
                label=self.label,
                trace=trace,
            )
        except Exception as exc:
            if getattr(exc, "code", None) == ErrorCode.FORBIDDEN:
                raise
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="school research source retrieval could not be validated",
            ) from exc

    def _verify_result(self, result: Any) -> None:
        if (
            getattr(result, "package_id", None) != self._package_id
            or not hmac.compare_digest(
                str(getattr(result, "manifest_sha256", "")), self._manifest_sha256
            )
            or getattr(result, "study_ref", None) != self._study_ref
            or getattr(result, "consumer_scope", None) != _TARGET_POPULATION
            or getattr(result, "consumer_age_min", None) != _CONSUMER_AGE_MIN
            or getattr(result, "consumer_age_max", None) != _CONSUMER_AGE_MAX
            or getattr(result, "review_status", None) != _REVIEW_STATUS
            or getattr(result, "rights_status", None) != _RIGHTS_STATUS
            or getattr(result, "source_rights_status", None) != "VERIFIED_WITH_CONDITIONS"
            or getattr(result, "status", None)
            not in {"MATCHES", "NO_MATCHES"}
            or getattr(result, "query_transform", None) not in _QUERY_TRANSFORMS
        ):
            raise ValueError("student research retrieval provenance does not match")
        hits = getattr(result, "hits", None)
        if not isinstance(hits, tuple) or len(hits) > 8:
            raise ValueError("student research hit set is invalid")
        seen: set[str] = set()
        for hit in hits:
            record_id = getattr(hit, "record_id", None)
            record = self._record_by_id.get(record_id) if isinstance(record_id, str) else None
            source = self._source_by_id.get(record.source_id) if record else None
            citation = getattr(hit, "citation", None)
            if (
                record is None
                or source is None
                or citation is None
                or record.student_retrieval_eligible is not True
                or source.student_retrieval_eligible is not True
                or source.rights_status != "VERIFIED_WITH_CONDITIONS"
                or hit.chunk_id != f"CHUNK_SCHOOL_RESEARCH_{record.record_id}"
                or hit.layer != record.layer
                or hit.text != record.text
                or citation.source_id != record.source_id
                or citation.excerpt_sha256 != record.excerpt_sha256
                or hit.chunk_id in seen
            ):
                raise ValueError("student research hit does not match the pinned package")
            seen.add(hit.chunk_id)
        matched_layers = tuple(
            layer for layer in _LAYERS if any(hit.layer == layer for hit in hits)
        )
        missing_layers = tuple(layer for layer in _LAYERS if layer not in matched_layers)
        if (
            getattr(result, "matched_layers", None) != matched_layers
            or getattr(result, "missing_layers", None) != missing_layers
            or (bool(hits) != (getattr(result, "status", None) == "MATCHES"))
        ):
            raise ValueError("student research layer coverage does not match its hits")

    def _to_knowledge_chunk(self, hit: Any) -> KnowledgeChunk:
        record = self._record_by_id[hit.record_id]
        source = self._source_by_id[record.source_id]
        locator = (
            f"{record.locator}; source population: {record.source_population_scope}; "
            f"source: {source.canonical_url}; license: {source.license} ({source.license_url}); "
            f"attribution: {source.attribution}"
        )
        if len(locator) > 512:
            raise ValueError("source locator exceeds the persisted citation boundary")
        chunk = KnowledgeChunk(
            schema_version="knowledge.v1",
            chunk_id=hit.chunk_id,
            document_id=(
                "KB_STUDENT_RESEARCH_"
                + hashlib.sha256(source.source_id.encode("utf-8")).hexdigest()[:24]
            ),
            text=hit.text,
            content_type="source_excerpt",
            location={"section": record.locator, "page_start": None, "page_end": None},
            citation=Citation(
                title=source.title,
                organization=source.publisher,
                locator=locator,
            ),
            population_scope=[_TARGET_POPULATION],
            role_scope=[_TARGET_ROLE],
            risk_scope=["normal"],
            review_status="pending",
            rights_status="verified",
            content_hash=f"sha256:{record.excerpt_sha256}",
        )
        validate_frozen("knowledge.v1.schema.json", chunk.model_dump(mode="json"))
        return chunk


__all__ = ["SchoolResearchStudentRagAdapter"]
