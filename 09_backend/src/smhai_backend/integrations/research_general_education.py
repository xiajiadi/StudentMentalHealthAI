"""Fixed local Runtime adapter for person-free, held education drafts."""
from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.research_general_education.service import (
    EXPECTED_MODEL_DIGEST_SHA256,
    EXPECTED_MODEL_ID,
    EXPECTED_MODEL_VERSION,
    FIXED_GENERAL_EDUCATION_REQUEST,
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    ResearchGeneralEducationRuntimeResult,
    ResearchGeneralEducationRuntimeSource,
)
from smhai_backend.domains.support.schemas import GenerationContent

from .common_http import LongLivedHttpClient, UpstreamError, translate_upstream_error

ROUTE_PATH = "/internal/llm/research-general-education-generations"
SCHEMA_VERSION = "research_general_education_generation.v1"
PURPOSE = "research_general_education_draft"


class ResearchGeneralEducationRuntimeClient(LongLivedHttpClient):
    def __init__(self, settings: ModuleClientSettings) -> None:
        if settings.mode != "http" or settings.base_url != "http://127.0.0.1:8161":
            raise ValueError("private research Runtime required")
        if settings.timeout.read < 65:
            raise ValueError("Runtime read timeout must cover the bounded generation")
        super().__init__(settings)

    async def generate(
        self, *, context: RequestContext, generation_id: str, retrieval_id: str,
        source_manifest_sha256: str, prompt_id: str, prompt_version: str,
        prompt_sha256: str, sources: tuple[ResearchGeneralEducationRuntimeSource, ...],
    ) -> ResearchGeneralEducationRuntimeResult:
        if (
            prompt_id != PROMPT_ID or prompt_version != PROMPT_VERSION
            or prompt_sha256 != PROMPT_SHA256
            or hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest() != PROMPT_SHA256
            or not sources or len(sources) > 8
            or any(type(source) is not ResearchGeneralEducationRuntimeSource for source in sources)
            or sum(len(source.text) for source in sources) > 6000
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="research Runtime input is invalid")
        evidence = [{
            "chunk_id": source.chunk_id, "text": source.text,
            "title": source.title, "organization": source.organization, "locator": source.locator,
        } for source in sources]
        evidence_json = json.dumps(
            evidence,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        payload = {
            "schema_version": SCHEMA_VERSION, "request_id": context.request_id,
            "trace_id": context.trace_id, "generation_id": generation_id,
            "retrieval_id": retrieval_id, "source_manifest_sha256": source_manifest_sha256,
            "prompt_ref": {"prompt_id": prompt_id, "prompt_version": prompt_version},
            "prompt_sha256": prompt_sha256, "prompt_template": PROMPT_TEMPLATE,
            "chunk_ids": [source.chunk_id for source in sources], "evidence_json": evidence_json,
            "fixed_request": FIXED_GENERAL_EDUCATION_REQUEST,
            "structured_schema": GenerationContent.model_json_schema(),
        }
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()) > 96000:
            raise error(ErrorCode.VALIDATION_FAILED, detail="research Runtime input exceeds budget")
        try:
            response = await self.post_json(ROUTE_PATH, payload, context=context)
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from None
        try:
            if (
                set(response) != {"schema_version", "purpose", "source_manifest_sha256", "status",
                                  "production_use", "publication_eligible", "data"}
                or response["schema_version"] != SCHEMA_VERSION or response["purpose"] != PURPOSE
                or response["source_manifest_sha256"] != source_manifest_sha256
                or response["status"] != "HOLD_FOR_REVIEW"
                or response["production_use"] is not False
                or response["publication_eligible"] is not False
            ):
                raise ValueError
            result = ResearchGeneralEducationRuntimeResult.model_validate(
                response["data"], strict=True
            )
            if (
                result.request_id != context.request_id or result.trace_id != context.trace_id
                or result.generation_id != generation_id or result.retrieval_id != retrieval_id
                or result.prompt_id != prompt_id or result.prompt_version != prompt_version
                or result.prompt_sha256 != prompt_sha256 or result.model_id != EXPECTED_MODEL_ID
                or result.model_version != EXPECTED_MODEL_VERSION
                or result.model_digest_sha256 != EXPECTED_MODEL_DIGEST_SHA256
                or not result.runtime_version or result.runtime_version == "unknown"
                or result.attempt_count != 1
                or result.retry_count != 0
                or result.fallback_count != 0
                or result.fallback_attempted is not False or result.local_only is not True
                or result.synthetic_fixture_only is not False
                or not 0 < len(result.content_json) <= 100000
            ):
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError, ValidationError):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                        detail="research Runtime response identity is invalid") from None
