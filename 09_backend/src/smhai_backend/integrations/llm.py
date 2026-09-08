"""LLM Runtime integration port; Backend never calls Ollama directly."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext

from .common_http import LongLivedHttpClient, UpstreamError, translate_upstream_error


@dataclass(frozen=True, slots=True)
class CandidateResponse:
    text: str
    model_id: str
    model_version: str
    runtime_version: str
    label: str


class LLMRuntimeClient(Protocol):
    label: str

    async def generate(
        self,
        *,
        prompt: str,
        model_id: str,
        provider_class: str,
        trace_id: str,
        request_id: str | None = None,
        generation_id: str | None = None,
        assessment_id: str | None = None,
        subject_id: str | None = None,
        target_role: str = "student",
        language: str = "zh-CN",
        safety_mode: str = "standard",
        retrieval_id: str | None = None,
        chunk_ids: tuple[str, ...] = (),
        prompt_id: str = "PROMPT_backend_support_v1",
        prompt_version: str = "1.0",
        metadata: dict[str, Any] | None = None,
    ) -> CandidateResponse: ...

    async def health(self) -> dict[str, str]: ...


@dataclass(slots=True)
class ContractFakeLLMRuntimeClient:
    label: str = "CONTRACT_FAKE"
    calls: int = 0
    call_order: list[str] = field(default_factory=list)
    available: bool = True

    async def generate(
        self,
        *,
        prompt: str,
        model_id: str,
        provider_class: str,
        trace_id: str,
        request_id: str | None = None,
        generation_id: str | None = None,
        assessment_id: str | None = None,
        subject_id: str | None = None,
        target_role: str = "student",
        language: str = "zh-CN",
        safety_mode: str = "standard",
        retrieval_id: str | None = None,
        chunk_ids: tuple[str, ...] = (),
        prompt_id: str = "PROMPT_backend_support_v1",
        prompt_version: str = "1.0",
        metadata: dict[str, Any] | None = None,
    ) -> CandidateResponse:
        self.calls += 1
        self.call_order.append("llm")
        if not self.available:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="required dependency could not complete the request",
                retryable=True,
            )
        if "SYNTHETIC_LLM_TIMEOUT" in prompt:
            raise error(
                ErrorCode.DEPENDENCY_TIMEOUT,
                status_code=504,
                detail="required dependency timed out",
                retryable=True,
            )
        if "SYNTHETIC_UNSAFE_OUTPUT" in prompt:
            text = (
                '{"summary":"SYNTHETIC_UNSAFE_OUTPUT","observations":[],'
                '"suggestions":[],"disclaimer":"synthetic"}'
            )
        else:
            text = (
                '{"summary":"这是合成演示中的教育支持摘要。",'
                '"observations":["当前结果仅用于工程链路演示。"],'
                '"suggestions":[{"text":"把下一步拆成一个今天可以完成的小行动。",'
                '"source_chunk_ids":["CHUNK_backend_0"]}],'
                '"disclaimer":"这不是诊断或治疗建议；需要时请使用已确认的人工支持流程。"}'
            )
        return CandidateResponse(
            text=text,
            model_id=model_id if model_id.startswith("MODEL_") else "MODEL_backend_fake",
            model_version="1.0",
            runtime_version="contract-fake-1.0",
            label=self.label,
        )

    async def health(self) -> dict[str, str]:
        return {"status": "READY" if self.available else "UNAVAILABLE", "mode": self.label}


class HttpLLMRuntimeClient(LongLivedHttpClient):
    """Thin Backend transport for the buffered local LLM Runtime."""

    label = "REAL_HTTP"

    async def generate(
        self,
        *,
        prompt: str,
        model_id: str,
        provider_class: str,
        trace_id: str,
        request_id: str | None = None,
        generation_id: str | None = None,
        assessment_id: str | None = None,
        subject_id: str | None = None,
        target_role: str = "student",
        language: str = "zh-CN",
        safety_mode: str = "standard",
        retrieval_id: str | None = None,
        chunk_ids: tuple[str, ...] = (),
        prompt_id: str = "PROMPT_backend_support_v1",
        prompt_version: str = "1.0",
        metadata: dict[str, Any] | None = None,
    ) -> CandidateResponse:
        request_id = request_id or f"REQ_llm_{trace_id.removeprefix('TRACE_')}"
        generation_id = generation_id or "GEN_backend_http"
        assessment_id = assessment_id or "ASSESS_backend_http"
        subject_id = subject_id or "SUBJ_backend_http"
        retrieval_id = retrieval_id or "RETR_backend_http"
        context = RequestContext(request_id, trace_id)
        payload = {
            "request_id": request_id,
            "trace_id": trace_id,
            "generation_id": generation_id,
            "assessment_id": assessment_id,
            "subject_id": subject_id,
            "target_role": target_role,
            "purpose": "education_support",
            "language": language,
            "safety_mode": safety_mode,
            "retrieval_id": retrieval_id,
            "chunk_ids": list(chunk_ids) or ["CHUNK_not_run"],
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "contract_model_id": model_id,
            "logical_model_id": "qwen2.5-0.5b-engineering",
            "prompt": prompt,
            "stream": False,
            "structured_schema": _generation_content_schema(),
            "config": {
                "max_output_tokens": 768,
                "temperature": 0.1,
                "top_p": 0.9,
                "timeout_seconds": 60.0,
                "seed": 20260906,
            },
            "metadata": {"synthetic_fixture": True, **dict(metadata or {})},
        }
        try:
            response = await self.post_json("/internal/llm/generations", payload, context=context)
            data = response.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("text"), str):
                raise ValueError("LLM Runtime response has no text")
            return CandidateResponse(
                text=data["text"],
                model_id=str(data.get("model_id") or model_id),
                model_version=_contract_version(data.get("model_version"), "unknown"),
                runtime_version=_contract_version(data.get("runtime_version"), "unknown"),
                label=self.label,
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except (TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="LLM Runtime returned an invalid generation projection",
            ) from exc

    async def health(self) -> dict[str, Any]:
        try:
            return await self.get_json(
                "/health/ready", context=RequestContext("REQ_llm_health", "TRACE_llm_health")
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc


def _generation_content_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "observations", "suggestions", "disclaimer"],
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "observations": {"type": "array", "items": {"type": "string"}},
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "source_chunk_ids"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "source_chunk_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "disclaimer": {"type": "string", "minLength": 1},
        },
    }


def _contract_version(value: Any, fallback: str) -> str:
    """Keep provider labels inside the frozen version-label grammar."""

    text = str(value or fallback)
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    return normalized[:64] or fallback
