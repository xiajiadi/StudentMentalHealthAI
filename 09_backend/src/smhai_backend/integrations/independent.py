"""Assessment-free HTTP clients for independent student conversations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.integrations.contracts import validate_frozen

from .common_http import LongLivedHttpClient, UpstreamError, translate_upstream_error
from .rag import KnowledgeChunk, RetrievalResult

RAG_ROUTE = "/internal/rag/independent-retrievals"
LLM_ROUTE = "/internal/llm/independent-generations"
_RAG_BASE_URL = "http://127.0.0.1:8170"
_LLM_BASE_URL = "http://127.0.0.1:8160"

_REQUEST_ID = re.compile(r"^REQ_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_TRACE_ID = re.compile(r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_OPAQUE_IDS = {
    "generation_id": re.compile(r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$"),
    "conversation_id": re.compile(r"^CONV_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$"),
    "turn_id": re.compile(r"^TURN_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$"),
    "retrieval_id": re.compile(r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$"),
}
_CHUNK_ID = re.compile(r"^CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")

# The route resolves this identity from the server-owned Runtime registry.
_SCHOOL_LOGICAL_MODEL_ID = "qwen2.5-7b-instruct-school-demo"
_SCHOOL_CONTRACT_MODEL_ID = "MODEL_local_primary"
_SCHOOL_PROVIDER_ID = "ollama"
_SCHOOL_PROVIDER_MODEL_ID = "qwen2.5:7b-instruct-q4_K_M"
_SCHOOL_MODEL_DIGEST = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
# A complete cited GenerationContent object needs room for all required fields.
# Native 7B retrieval-context verification exhausted the previous 256-token cap.
_MAX_OUTPUT_TOKENS = 768
_CONTEXT_LENGTH = 8192
_GENERATION_TIMEOUT_SECONDS = 120.0
_MIN_LLM_HTTP_READ_TIMEOUT_SECONDS = 125.0


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _RetrievalRequest(_StrictModel):
    query: StrictStr = Field(min_length=1, max_length=20_000)
    target_population: Literal["university_freshman", "university_student"]
    top_k: StrictInt = Field(ge=1, le=20)
    retrieval_id: StrictStr = Field(pattern=_OPAQUE_IDS["retrieval_id"].pattern, max_length=160)


class _PromptRef(_StrictModel):
    prompt_id: StrictStr = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    prompt_version: StrictStr = Field(min_length=1, max_length=64)


class _Message(_StrictModel):
    role: Literal["system", "user", "assistant"]
    content: StrictStr = Field(min_length=1, max_length=16_000)


class _GenerationRequest(_StrictModel):
    request_id: StrictStr = Field(pattern=_REQUEST_ID.pattern, max_length=160)
    trace_id: StrictStr = Field(pattern=_TRACE_ID.pattern, max_length=160)
    generation_id: StrictStr = Field(pattern=_OPAQUE_IDS["generation_id"].pattern, max_length=160)
    conversation_id: StrictStr = Field(
        pattern=_OPAQUE_IDS["conversation_id"].pattern, max_length=160
    )
    turn_id: StrictStr = Field(pattern=_OPAQUE_IDS["turn_id"].pattern, max_length=160)
    retrieval_id: StrictStr = Field(pattern=_OPAQUE_IDS["retrieval_id"].pattern, max_length=160)
    chunk_ids: list[StrictStr] = Field(min_length=1, max_length=100)
    prompt_ref: _PromptRef
    messages: list[_Message] = Field(min_length=1, max_length=32)
    structured_schema: dict[str, Any] = Field(min_length=1)
    config: dict[str, Any]

    @classmethod
    def build(
        cls,
        *,
        context: RequestContext,
        generation_id: str,
        conversation_id: str,
        turn_id: str,
        retrieval_id: str,
        chunk_ids: Sequence[str],
        prompt_id: str,
        prompt_version: str,
        messages: Sequence[Mapping[str, str]],
        structured_schema: Mapping[str, Any],
    ) -> _GenerationRequest:
        schema_json = json.dumps(
            structured_schema, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        if len(schema_json.encode("utf-8")) > 64_000:
            raise ValueError("structured schema is too large")
        if not any(message.get("role") == "user" for message in messages):
            raise ValueError("at least one user message is required")
        if len(set(chunk_ids)) != len(chunk_ids) or any(
            not isinstance(item, str) or not _CHUNK_ID.fullmatch(item) for item in chunk_ids
        ):
            raise ValueError("chunk ids must be unique CHUNK_ identifiers")
        return cls.model_validate(
            {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "generation_id": generation_id,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "retrieval_id": retrieval_id,
                "chunk_ids": list(chunk_ids),
                "prompt_ref": {"prompt_id": prompt_id, "prompt_version": prompt_version},
                "messages": list(messages),
                "structured_schema": json.loads(schema_json),
                "config": {
                    "max_output_tokens": _MAX_OUTPUT_TOKENS,
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "context_length": _CONTEXT_LENGTH,
                    "timeout_seconds": _GENERATION_TIMEOUT_SECONDS,
                },
            }
        )


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Validated result from the fixed school Runtime identity."""

    request_id: str
    trace_id: str
    generation_id: str
    conversation_id: str
    turn_id: str
    text: str
    model_id: str
    logical_model_id: str
    model_version: str
    runtime_version: str
    synthetic_fixture_only: bool
    trace: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _RuntimeModelIdentity:
    logical_model_id: str
    contract_model_id: str
    provider_id: str
    provider_model_id: str
    digest: str | None


_RUNTIME_MODEL_IDENTITIES = {
    _SCHOOL_LOGICAL_MODEL_ID: _RuntimeModelIdentity(
        logical_model_id=_SCHOOL_LOGICAL_MODEL_ID,
        contract_model_id=_SCHOOL_CONTRACT_MODEL_ID,
        provider_id=_SCHOOL_PROVIDER_ID,
        provider_model_id=_SCHOOL_PROVIDER_MODEL_ID,
        digest=_SCHOOL_MODEL_DIGEST,
    ),
    "deepseek-flash-education-support": _RuntimeModelIdentity(
        logical_model_id="deepseek-flash-education-support",
        contract_model_id="MODEL_deepseek_flash_education_support",
        provider_id="deepseek",
        provider_model_id="deepseek-flash",
        digest=None,
    ),
}


def _runtime_model_identity(settings: ModuleClientSettings) -> _RuntimeModelIdentity:
    logical_model_id = getattr(settings, "logical_model_id", _SCHOOL_LOGICAL_MODEL_ID)
    if not isinstance(logical_model_id, str):
        raise ValueError("independent Runtime model identity is invalid")
    identity = _RUNTIME_MODEL_IDENTITIES.get(logical_model_id)
    if identity is None:
        raise ValueError("independent Runtime model identity is not allowlisted")
    return identity


def _raise_invalid(component: str, exc: Exception) -> NoReturn:
    raise error(
        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
        status_code=502,
        detail=f"{component} returned an invalid independent response",
    ) from exc


def _require_local_destination(settings: ModuleClientSettings, expected_url: str) -> None:
    """Fail closed unless this internal client targets its one loopback service."""
    if settings.mode != "http" or settings.base_url != expected_url:
        raise ValueError("independent module client requires its exact local service URL")


def _envelope(response: Mapping[str, Any], *, request_id: str, trace_id: str) -> Mapping[str, Any]:
    if response.get("request_id") != request_id or response.get("trace_id") != trace_id:
        raise ValueError("response correlation identity does not match")
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("response data is missing")
    return data


class IndependentRagClient(LongLivedHttpClient):
    """Call the assessment-free student retrieval endpoint exactly once."""

    label = "REAL_HTTP_INDEPENDENT"

    def __init__(self, settings: ModuleClientSettings) -> None:
        _require_local_destination(settings, _RAG_BASE_URL)
        super().__init__(settings)

    async def retrieve(
        self,
        *,
        query: str,
        target_population: Literal["university_freshman", "university_student"],
        top_k: int,
        retrieval_id: str,
        context: RequestContext,
    ) -> RetrievalResult:
        try:
            payload = _RetrievalRequest.model_validate(
                {
                    "query": query.strip() if isinstance(query, str) else query,
                    "target_population": target_population,
                    "top_k": top_k,
                    "retrieval_id": retrieval_id,
                }
            )
            response = await self.post_json(
                RAG_ROUTE,
                payload.model_dump(mode="json"),
                context=context,
            )
            if set(response) != {"request_id", "trace_id", "data"}:
                raise ValueError("retrieval response envelope fields do not match")
            data = _envelope(response, request_id=context.request_id, trace_id=context.trace_id)
            if set(data) != {"retrieval_id", "chunks", "citations", "trace", "plan"}:
                raise ValueError("retrieval response fields do not match")
            if data.get("retrieval_id") != retrieval_id:
                raise ValueError("retrieval identity does not match")
            chunks_value = data.get("chunks")
            if not isinstance(chunks_value, list):
                raise ValueError("retrieval chunks are missing")
            chunks: list[KnowledgeChunk] = []
            for item in chunks_value:
                if not isinstance(item, dict):
                    raise ValueError("retrieval chunk is not an object")
                validate_frozen("knowledge.v1.schema.json", item)
                chunks.append(KnowledgeChunk.model_validate(item))
            citations = data.get("citations")
            trace = data.get("trace")
            plan = data.get("plan")
            if (
                not isinstance(citations, Mapping)
                or not isinstance(trace, Mapping)
                or not isinstance(plan, Mapping)
            ):
                raise ValueError("retrieval provenance is missing")
            if (
                trace.get("request_id") != context.request_id
                or trace.get("trace_id") != context.trace_id
                or trace.get("raw_query") != payload.query
            ):
                raise ValueError("retrieval trace identity does not match")
            # RetrievalTrace carries the full raw query and candidate text. Only
            # the safe provenance needed by Backend evidence binding is retained.
            safe_trace = {
                key: trace[key]
                for key in (
                    "index_id",
                    "index_version",
                    "corpus_version",
                    "corpus_build_id",
                    "build_id",
                    "snapshot_id",
                    "run_id",
                    "query_id",
                    "trace_id",
                    "request_id",
                )
                if key in trace
            }
            return RetrievalResult(
                retrieval_id=retrieval_id,
                chunks=tuple(chunks),
                label=self.label,
                trace=safe_trace,
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except (TypeError, ValueError, ValidationError, KeyError) as exc:
            _raise_invalid("RAG", exc)


class IndependentLLMRuntimeClient(LongLivedHttpClient):
    """Call the independent buffered Runtime route without legacy IDs."""

    label = "REAL_HTTP_INDEPENDENT"

    def __init__(self, settings: ModuleClientSettings) -> None:
        _require_local_destination(settings, _LLM_BASE_URL)
        if settings.timeout.read < _MIN_LLM_HTTP_READ_TIMEOUT_SECONDS:
            raise ValueError("independent Runtime HTTP read timeout must be at least 125 seconds")
        self.model_identity = _runtime_model_identity(settings)
        super().__init__(settings)

    async def generate(
        self,
        *,
        context: RequestContext,
        generation_id: str,
        conversation_id: str,
        turn_id: str,
        retrieval_id: str,
        chunk_ids: Sequence[str],
        prompt_id: str,
        prompt_version: str,
        messages: Sequence[Mapping[str, str]],
        structured_schema: Mapping[str, Any],
    ) -> GenerationResult:
        try:
            payload = _GenerationRequest.build(
                context=context,
                generation_id=generation_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                retrieval_id=retrieval_id,
                chunk_ids=chunk_ids,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                messages=messages,
                structured_schema=structured_schema,
            )
            response = await self.post_json(
                LLM_ROUTE,
                payload.model_dump(mode="json"),
                context=context,
                headers=self._internal_auth_headers(),
            )
            data = _envelope(response, request_id=context.request_id, trace_id=context.trace_id)
            expected_outer = {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "generation_id": generation_id,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
            }
            if set(response) != {
                "request_id",
                "trace_id",
                "generation_id",
                "conversation_id",
                "turn_id",
                "data",
            }:
                raise ValueError("Runtime response fields do not match")
            if any(response.get(key) != value for key, value in expected_outer.items()):
                raise ValueError("Runtime resource identity does not match")
            expected_data = {
                "text",
                "model_id",
                "logical_model_id",
                "model_version",
                "runtime_version",
                "trace",
                "buffered",
                "synthetic_fixture_only",
            }
            if set(data) != expected_data:
                raise ValueError("Runtime result fields do not match")
            text = data.get("text")
            model_id = data.get("model_id")
            logical_model_id = data.get("logical_model_id")
            model_version = data.get("model_version")
            runtime_version = data.get("runtime_version")
            synthetic = data.get("synthetic_fixture_only")
            trace = data.get("trace")
            if (
                not isinstance(text, str)
                or not text.strip()
                or not isinstance(model_id, str)
                or model_id != self.model_identity.contract_model_id
                or not isinstance(logical_model_id, str)
                or logical_model_id != self.model_identity.logical_model_id
                or not isinstance(model_version, str)
                or not model_version.strip()
                or not isinstance(runtime_version, str)
                or not runtime_version.strip()
                or data.get("buffered") is not True
                or not isinstance(synthetic, bool)
                or not isinstance(trace, Mapping)
            ):
                raise ValueError("Runtime result is incomplete or used an unexpected model")
            if (
                trace.get("request_id") != context.request_id
                or trace.get("trace_id") != context.trace_id
                or trace.get("provider") != self.model_identity.provider_id
                or trace.get("logical_model") != self.model_identity.logical_model_id
                or trace.get("requested_model") != self.model_identity.logical_model_id
                or trace.get("actual_model") != self.model_identity.logical_model_id
                or trace.get("provider_model") != self.model_identity.provider_model_id
                or trace.get("digest") != self.model_identity.digest
                or trace.get("retry_count") != 0
                or trace.get("fallback_count") != 0
                or trace.get("fallback_attempted") is not False
                or not isinstance(trace.get("attempts"), list)
                or len(trace["attempts"]) != 1
                or not _is_expected_successful_attempt(
                    trace["attempts"][0], self.model_identity
                )
            ):
                raise ValueError("Runtime trace identity or attempt policy does not match")
            safe_trace = {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "requested_model": self.model_identity.logical_model_id,
                "actual_model": self.model_identity.logical_model_id,
                "provider": self.model_identity.provider_id,
                "provider_model": self.model_identity.provider_model_id,
                "digest": self.model_identity.digest,
                "runtime_version": runtime_version,
                "retry_count": 0,
                "fallback_count": 0,
                "fallback_attempted": False,
                "attempt_count": 1,
            }
            return GenerationResult(
                request_id=context.request_id,
                trace_id=context.trace_id,
                generation_id=generation_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                text=text,
                model_id=model_id,
                logical_model_id=logical_model_id,
                model_version=model_version,
                runtime_version=runtime_version,
                synthetic_fixture_only=synthetic,
                trace=safe_trace,
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except (TypeError, ValueError, ValidationError, KeyError) as exc:
            _raise_invalid("LLM Runtime", exc)

    def _internal_auth_headers(self) -> dict[str, str] | None:
        token = getattr(self.settings, "internal_auth_token", None)
        if token is None:
            return None
        value = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token)
        return {"Authorization": f"Bearer {value}"}


def _is_expected_successful_attempt(
    value: Any, identity: _RuntimeModelIdentity
) -> bool:
    """Validate the exact Runtime GenerationAttempt success projection."""
    expected_fields = {
        "attempt_index",
        "provider_id",
        "logical_model_id",
        "provider_model_id",
        "started_at",
        "ended_at",
        "outcome",
        "error_code",
        "fallback_reason",
        "retry",
    }
    return (
        isinstance(value, Mapping)
        and set(value) == expected_fields
        and value.get("attempt_index") == 1
        and value.get("provider_id") == identity.provider_id
        and value.get("logical_model_id") == identity.logical_model_id
        and value.get("provider_model_id") == identity.provider_model_id
        and isinstance(value.get("started_at"), str)
        and bool(value.get("started_at"))
        and isinstance(value.get("ended_at"), str)
        and bool(value.get("ended_at"))
        and value.get("outcome") == "success"
        and value.get("error_code") is None
        and value.get("fallback_reason") is None
        and value.get("retry") is False
    )


__all__ = [
    "GenerationResult",
    "IndependentLLMRuntimeClient",
    "IndependentRagClient",
    "LLM_ROUTE",
    "RAG_ROUTE",
]
