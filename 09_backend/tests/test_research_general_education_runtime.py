from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smhai_backend.core.config import ModuleClientSettings, TimeoutSettings
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.research_general_education.prompt import (
    OUTPUT_SCHEMA_FILENAME,
    OUTPUT_SCHEMA_SHA256,
)
from smhai_backend.domains.research_general_education.service import (
    EXPECTED_MODEL_DIGEST_SHA256,
    EXPECTED_MODEL_ID,
    EXPECTED_MODEL_VERSION,
    FIXED_GENERAL_EDUCATION_REQUEST,
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    ResearchGeneralEducationRuntimeSource,
)
from smhai_backend.domains.support.schemas import GenerationContent
from smhai_backend.integrations.research_general_education import (
    ROUTE_PATH,
    ResearchGeneralEducationRuntimeClient,
)

CONTEXT = RequestContext(
    request_id="REQ_runtime_test",
    trace_id="TRACE_runtime_test",
)
GENERATION_ID = "GEN_runtime_test"
RETRIEVAL_ID = "RETR_runtime_test"
MANIFEST_SHA = "a" * 64
RAW_PROVIDER_JSON = '{"summary":"synthetic raw provider response"}'


def _settings() -> ModuleClientSettings:
    return ModuleClientSettings(
        mode="http",
        base_url="http://127.0.0.1:8161",
        timeout=TimeoutSettings(connect=1, read=65, write=8, pool=1),
    )


def _sources() -> tuple[ResearchGeneralEducationRuntimeSource, ...]:
    return (
        ResearchGeneralEducationRuntimeSource(
            chunk_id="CHUNK_SCHOOL_RESEARCH_POLICY_1",
            text="Synthetic excerpt text.",
            title="Synthetic source title",
            organization="Synthetic publisher",
            locator="Section 1",
        ),
    )


def _data() -> dict[str, Any]:
    return {
        "request_id": CONTEXT.request_id,
        "trace_id": CONTEXT.trace_id,
        "generation_id": GENERATION_ID,
        "retrieval_id": RETRIEVAL_ID,
        "prompt_id": PROMPT_ID,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
        "content_json": RAW_PROVIDER_JSON,
        "model_id": EXPECTED_MODEL_ID,
        "model_version": EXPECTED_MODEL_VERSION,
        "model_digest_sha256": EXPECTED_MODEL_DIGEST_SHA256,
        "runtime_version": "local-runtime-test",
        "attempt_count": 1,
        "retry_count": 0,
        "fallback_count": 0,
        "fallback_attempted": False,
        "local_only": True,
        "synthetic_fixture_only": False,
    }


def _response() -> dict[str, Any]:
    return {
        "schema_version": "research_general_education_generation.v1",
        "purpose": "research_general_education_draft",
        "source_manifest_sha256": MANIFEST_SHA,
        "status": "HOLD_FOR_REVIEW",
        "production_use": False,
        "publication_eligible": False,
        "data": _data(),
    }


async def _run_client(handler, *, sources=None, prompt_sha=PROMPT_SHA256):
    client = ResearchGeneralEducationRuntimeClient(_settings())
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8161",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.generate(
            context=CONTEXT,
            generation_id=GENERATION_ID,
            retrieval_id=RETRIEVAL_ID,
            source_manifest_sha256=MANIFEST_SHA,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=prompt_sha,
            sources=sources or _sources(),
        )
        return result
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_adapter_posts_only_fixed_person_free_evidence_and_preserves_raw_json():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert request.method == "POST"
        assert request.url.path == ROUTE_PATH
        assert body["fixed_request"] == FIXED_GENERAL_EDUCATION_REQUEST
        assert body["prompt_template"] == PROMPT_TEMPLATE
        assert body["prompt_sha256"] == PROMPT_SHA256
        assert body["chunk_ids"] == ["CHUNK_SCHOOL_RESEARCH_POLICY_1"]
        assert json.loads(body["evidence_json"]) == [
            {
                "chunk_id": "CHUNK_SCHOOL_RESEARCH_POLICY_1",
                "text": "Synthetic excerpt text.",
                "title": "Synthetic source title",
                "organization": "Synthetic publisher",
                "locator": "Section 1",
            }
        ]
        for forbidden in (
            "assessment_id",
            "subject_id",
            "conversation_id",
            "turn_id",
            "actor_id",
            "school_id",
            "task_ref",
        ):
            assert forbidden not in body
        return httpx.Response(200, json=_response())

    result = await _run_client(handler)

    assert result.content_json == RAW_PROVIDER_JSON
    assert len(seen) == 1


def test_canonical_output_schema_asset_matches_generation_content_model():
    asset = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "smhai_backend"
        / "domains"
        / "research_general_education"
        / OUTPUT_SCHEMA_FILENAME
    )
    raw = asset.read_bytes()

    assert hashlib.sha256(raw).hexdigest() == OUTPUT_SCHEMA_SHA256
    assert json.loads(raw) == GenerationContent.model_json_schema()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("request_id",), "REQ_other"),
        (("trace_id",), "TRACE_other"),
        (("generation_id",), "GEN_other"),
        (("retrieval_id",), "RETR_other"),
        (("prompt_id",), "PROMPT_other"),
        (("prompt_version",), "9.9"),
        (("prompt_sha256",), "b" * 64),
        (("model_id",), "remote-model"),
        (("model_version",), "remote-revision"),
        (("model_digest_sha256",), "c" * 64),
        (("attempt_count",), 2),
        (("retry_count",), 1),
        (("fallback_count",), 1),
        (("fallback_attempted",), True),
        (("local_only",), False),
        (("synthetic_fixture_only",), True),
    ],
)
@pytest.mark.asyncio
async def test_adapter_rejects_mismatched_runtime_identity_and_attempt_flags(path, value):
    response = _response()
    target = response["data"]
    target[path[0]] = value
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response)

    client = ResearchGeneralEducationRuntimeClient(_settings())
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8161",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError) as exc:
            await client.generate(
                context=CONTEXT,
                generation_id=GENERATION_ID,
                retrieval_id=RETRIEVAL_ID,
                source_manifest_sha256=MANIFEST_SHA,
                prompt_id=PROMPT_ID,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=PROMPT_SHA256,
                sources=_sources(),
            )
        assert exc.value.code == ErrorCode.DEPENDENCY_INVALID_RESPONSE
        assert calls == 1
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "other"),
        ("purpose", "education_support"),
        ("source_manifest_sha256", "d" * 64),
        ("status", "COMPLETED"),
        ("production_use", True),
        ("publication_eligible", True),
    ],
)
@pytest.mark.asyncio
async def test_adapter_rejects_outer_hold_envelope_mismatch(field, value):
    response = _response()
    response[field] = value

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    client = ResearchGeneralEducationRuntimeClient(_settings())
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8161",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError) as exc:
            await client.generate(
                context=CONTEXT,
                generation_id=GENERATION_ID,
                retrieval_id=RETRIEVAL_ID,
                source_manifest_sha256=MANIFEST_SHA,
                prompt_id=PROMPT_ID,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=PROMPT_SHA256,
                sources=_sources(),
            )
        assert exc.value.code == ErrorCode.DEPENDENCY_INVALID_RESPONSE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_adapter_rejects_unknown_nested_fields_and_non_pinned_prompt_before_http():
    calls = 0
    response = _response()
    response["data"]["unexpected"] = "rejected"

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response)

    client = ResearchGeneralEducationRuntimeClient(_settings())
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8161",
        transport=httpx.MockTransport(handler),
    )
    try:
        response = _response()
        response["data"]["unexpected"] = "rejected"
        with pytest.raises(BackendError) as exc:
            await client.generate(
                context=CONTEXT,
                generation_id=GENERATION_ID,
                retrieval_id=RETRIEVAL_ID,
                source_manifest_sha256=MANIFEST_SHA,
                prompt_id=PROMPT_ID,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=PROMPT_SHA256,
                sources=_sources(),
            )
        assert exc.value.code == ErrorCode.DEPENDENCY_INVALID_RESPONSE
        assert calls == 1

        with pytest.raises(BackendError) as exc:
            await client.generate(
                context=CONTEXT,
                generation_id=GENERATION_ID,
                retrieval_id=RETRIEVAL_ID,
                source_manifest_sha256=MANIFEST_SHA,
                prompt_id=PROMPT_ID,
                prompt_version=PROMPT_VERSION,
                prompt_sha256="e" * 64,
                sources=_sources(),
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert calls == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_adapter_does_not_retry_failed_runtime_response():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"detail": "synthetic unavailable"})

    client = ResearchGeneralEducationRuntimeClient(_settings())
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8161",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError):
            await client.generate(
                context=CONTEXT,
                generation_id=GENERATION_ID,
                retrieval_id=RETRIEVAL_ID,
                source_manifest_sha256=MANIFEST_SHA,
                prompt_id=PROMPT_ID,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=PROMPT_SHA256,
                sources=_sources(),
            )
        assert calls == 1
    finally:
        await client.close()
