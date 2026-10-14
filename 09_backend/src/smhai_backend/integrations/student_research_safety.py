"""Safety composition for the pinned, pending-source student research lane."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext

from .common_http import LongLivedHttpClient, UpstreamError, translate_upstream_error
from .safety import SafetyCheckView, SafetyClient

_BASE_URL = "http://127.0.0.1:8191"
_ROUTE = "/_research/safety/check-retrieval"
_HEALTH_ROUTE = "/health"
_SCHEMA = "psynova.school-student-research-safety.v1"
_PURPOSE = "RESEARCH_SIMULATION"
_CONSUMER_AGE_SCOPE = "14-17"
_ROLE_SCOPE = ["student"]
_POPULATION_SCOPE = ["secondary_school_student"]
_RISK_SCOPE = ["normal"]
_SAFE_CORRELATION_ID = re.compile(r"^(?:REQ|TRACE)_[A-Za-z0-9_-]{1,127}$")


class SchoolResearchStudentSafetyClient(LongLivedHttpClient):
    """Use normal Safety for user text and the private host only for retrieval.

    The source package and its crosswalk are supplied by the trusted container.
    Request-provided metadata never determines the source identity or eligibility.
    """

    label = "SCHOOL_RESEARCH_COMPOSITE"

    def __init__(
        self,
        *,
        standard_safety: SafetyClient,
        settings: ModuleClientSettings,
        package: Any,
        expected_manifest_sha256: str,
        expected_package_id: str,
        expected_study_ref: str,
    ) -> None:
        if (
            settings.mode != "http"
            or settings.base_url != _BASE_URL
            or not isinstance(expected_manifest_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None
            or getattr(package, "manifest_sha256", None) != expected_manifest_sha256
            or getattr(package, "package_id", None) != expected_package_id
            or getattr(package, "study_ref", None) != expected_study_ref
        ):
            raise ValueError("student research Safety pins are invalid")
        super().__init__(settings)
        self._standard = standard_safety
        self._manifest_sha256 = expected_manifest_sha256
        self._package_id = expected_package_id
        self._study_ref = expected_study_ref
        records = {item.record_id: item for item in package.records}
        sources = {item.source_id: item for item in package.sources}
        self._records_by_chunk: dict[str, tuple[Any, Any]] = {}
        for record in records.values():
            source = sources.get(record.source_id)
            chunk_id = f"CHUNK_SCHOOL_RESEARCH_{record.record_id}"
            if (
                source is None
                or record.student_retrieval_eligible is not True
                or source.student_retrieval_eligible is not True
                or source.rights_status != "VERIFIED_WITH_CONDITIONS"
            ):
                continue
            self._records_by_chunk[chunk_id] = (record, source)

    async def check_input(
        self, context: Mapping[str, Any], request_context: RequestContext
    ) -> SafetyCheckView:
        return await self._standard.check_input(context, request_context)

    async def check_output(
        self, context: Mapping[str, Any], candidate_text: str, request_context: RequestContext
    ) -> SafetyCheckView:
        return await self._standard.check_output(context, candidate_text, request_context)

    async def check_retrieval(
        self,
        context: Mapping[str, Any],
        chunks: Sequence[Mapping[str, Any]],
        request_context: RequestContext,
    ) -> SafetyCheckView:
        payload_chunks = self._project_chunks(chunks)
        if (
            not _SAFE_CORRELATION_ID.fullmatch(request_context.request_id)
            or not _SAFE_CORRELATION_ID.fullmatch(request_context.trace_id)
        ):
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="student research Safety correlation is invalid",
            )
        payload = {
            "schema_version": _SCHEMA,
            "request_id": request_context.request_id,
            "trace_id": request_context.trace_id,
            "study_ref": self._study_ref,
            "package_id": self._package_id,
            "manifest_sha256": self._manifest_sha256,
            "purpose": _PURPOSE,
            "consumer_age_scope": _CONSUMER_AGE_SCOPE,
            "chunks": payload_chunks,
        }
        try:
            result = await self.post_json(_ROUTE, payload, context=request_context)
            view = SafetyCheckView.from_payload(result)
            if view.operation != "RETRIEVAL":
                raise ValueError("research Safety returned the wrong operation")
            return view
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except ValueError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="research Safety returned an invalid decision",
            ) from exc

    async def health(self, request_context: RequestContext) -> dict[str, Any]:
        try:
            private_health = await self.get_json(_HEALTH_ROUTE, context=request_context)
            standard_health = await self._standard.health(request_context)
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        if (
            set(private_health) != {"status", "research_only", "port"}
            or private_health.get("status") != "READY"
            or private_health.get("research_only") is not True
            or private_health.get("port") != 8191
            or standard_health.get("status") != "READY"
        ):
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                status_code=503,
                detail="required Safety dependency is not ready",
                retryable=True,
            )
        return {"status": "READY", "research_only": True}

    async def finalize_review(
        self, review_case_id: str, *, request_context: RequestContext
    ) -> None:
        await self._standard.finalize_review(review_case_id, request_context=request_context)

    def _project_chunks(
        self, chunks: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        if not 1 <= len(chunks) <= 32:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="research retrieval evidence is invalid",
            )
        projected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if not isinstance(chunk_id, str):
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    status_code=502,
                    detail="research retrieval evidence is invalid",
                )
            pair = self._records_by_chunk.get(chunk_id)
            if pair is None:
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    status_code=502,
                    detail="research retrieval evidence is invalid",
                )
            record, source = pair
            content = chunk.get("text")
            expected_hash = f"sha256:{record.excerpt_sha256}"
            if (
                chunk_id in seen
                or content != record.text
                or chunk.get("content_hash") != expected_hash
                or chunk.get("review_status") != "pending"
                or chunk.get("rights_status") != "verified"
                or tuple(chunk.get("population_scope") or ()) != (_POPULATION_SCOPE[0],)
                or tuple(chunk.get("role_scope") or ()) != (_ROLE_SCOPE[0],)
                or tuple(chunk.get("risk_scope") or ()) != (_RISK_SCOPE[0],)
                or not isinstance(content, str)
                or not 1 <= len(content) <= 4000
            ):
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    status_code=502,
                    detail="research retrieval evidence is invalid",
                )
            seen.add(chunk_id)
            projected.append(
                {
                    "chunk_id": chunk_id,
                    "content": content,
                    "metadata": {
                        "source_id": source.source_id,
                        "record_id": record.record_id,
                        "content_hash": record.excerpt_sha256,
                        "manifest_sha256": self._manifest_sha256,
                        "rights_scope_note": source.rights_scope_note,
                        "review_status": "pending",
                        "rights_status": "verified",
                        "role_scope": ["student"],
                        "population_scope": ["secondary_school_student"],
                        "risk_scope": ["normal"],
                    },
                }
            )
        return projected
