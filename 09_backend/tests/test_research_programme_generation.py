from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.research_programme_generation.service import (
    ResearchProgrammeGenerationService,
)
from smhai_backend.integrations.research_programme import (
    EXPECTED_CONTRACT_MODEL_ID,
    EXPECTED_MODEL_DIGEST,
    EXPECTED_MODEL_ID,
    EXPECTED_PROVIDER_MODEL_ID,
    PROMPT_VERSION,
    ROUTE_PATH,
    HttpResearchProgrammeRuntimeClient,
    RuntimeGeneration,
    RuntimeSource,
)
from smhai_backend.integrations.safety import SafetyCheckView, SafetyDecisionView

MANIFEST_SHA = "a" * 64
NOW = datetime(2026, 10, 14, tzinfo=UTC)
_SOURCE_ROWS = (
    ("WHO-HAT-STRATEGY1-POLICY-2021", "policy", "WHO-HAT-TOOLKIT-2021"),
    (
        "WHO-HAT-SCHOOL-ENVIRONMENT-OBJECTIVE-2021",
        "intervention",
        "WHO-HAT-TOOLKIT-2021",
    ),
    ("WHO-HAT-SCHOOL-CLIMATE-SUPPORT-2021", "intervention", "WHO-HAT-TOOLKIT-2021"),
    ("RAG-THEORY-002", "theory", "RAG-THEORY-002"),
)


def _hits(*, omit_layer: str | None = None) -> tuple[SimpleNamespace, ...]:
    result = []
    for record_id, layer, source_id in _SOURCE_ROWS:
        if layer == omit_layer:
            continue
        text = f"Pinned public excerpt for {record_id} and school programme planning."
        result.append(
            SimpleNamespace(
                record_id=record_id,
                text=text,
                layer=layer,
                source_population="school programme research",
                certainty="source-stated",
                citation=SimpleNamespace(
                    source_id=source_id,
                    title=f"Source {source_id}",
                    publisher="Source publisher",
                    year=2021,
                    locator=f"Section {len(result) + 1}",
                    source_url="https://example.org/source",
                    official_pdf_url="https://example.org/source.pdf",
                    rights_listing_url="https://example.org/rights",
                    license="CC BY-NC-SA 3.0 IGO",
                    license_url="https://creativecommons.org/licenses/by-nc-sa/3.0/igo/",
                    attribution="Attribution retained.",
                    source_extraction_sha256="b" * 64,
                    excerpt_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                ),
                rank=len(result) + 1,
                lexical_score=1.0,
            )
        )
    return tuple(result)


def _retrieval(*, status: str = "MATCHES", hits=None, **overrides: Any) -> SimpleNamespace:
    values = {
        "status": status,
        "retriever": "BM25S",
        "hits": _hits() if hits is None else hits,
        "package_id": "school-rag-ai-engineering-20261014-v1",
        "study_ref": "school-noncommercial-rag-research-2027-06",
        "scope": "ISOLATED_GENERAL_EDUCATION_SIMULATION",
        "use_mode": "SCHOOL_NONCOMMERCIAL_RESEARCH",
        "role_scope": ("psychological_specialist",),
        "population_scope": ("adolescent_school_programme_research",),
        "risk_scope": ("general_education_only",),
        "valid_through_month": "2027-06",
        "manifest_sha256": MANIFEST_SHA,
        "reviewer_kind": "AI_ENGINEERING",
        "noncommercial": True,
        "human_curated": False,
        "professional_approval": False,
        "ethics_approval": False,
        "clinical_approval": False,
        "psychometric_approval": False,
        "publication_eligible": False,
        "production_use": False,
        "research_only": True,
        "index_persisted": False,
        "embeddings_used": False,
        "model_called": False,
        "production_store_used": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _runtime_generation(
    *, citation_ids: tuple[str, ...] | None = None, body: str | None = None
) -> RuntimeGeneration:
    if citation_ids is None and body is not None:
        citation_ids = tuple(dict.fromkeys(re.findall(r"\[(CHUNK_[A-Za-z0-9_.-]+)\]", body)))
    citations = citation_ids or tuple(
        f"CHUNK_RESEARCH_{record_id}" for record_id, _layer, _source_id in _SOURCE_ROWS
    )
    body = body or (
        "Programme planning can use the following school-wide steps. "
        + " ".join(f"[{citation}]" for citation in citations)
    )
    return RuntimeGeneration(
        request_id="REQ_research_001",
        trace_id="TRACE_research_001",
        generation_id="GEN_research_001",
        retrieval_id="RETR_research_001",
        programme_ref="PROGRAMME_internal_001",
        source_manifest_sha256=MANIFEST_SHA,
        title="Staff programme reference",
        body=body,
        citation_chunk_ids=citations,
        model_id=EXPECTED_MODEL_ID,
        model_version=EXPECTED_PROVIDER_MODEL_ID,
        runtime_version="runtime-test",
        model_digest=EXPECTED_MODEL_DIGEST,
        prompt_sha256="c" * 64,
    )


class FakeSafety:
    def __init__(
        self, *, input_action="PROCEED", retrieval_action="PROCEED", output_action="PROCEED"
    ):
        self.input_action = input_action
        self.retrieval_action = retrieval_action
        self.output_action = output_action
        self.calls: list[str] = []
        self.contexts: list[dict[str, Any]] = []
        self.chunks: list[list[dict[str, Any]]] = []

    @staticmethod
    def _result(action: str, context: RequestContext, operation: str):
        return SafetyCheckView(
            operation=operation,
            trace_id=context.trace_id,
            decision=SafetyDecisionView(
                action=action,
                reason_codes=["TEST"],
                requires_human=action in {"REVIEW_REQUIRED", "CRISIS_ROUTE", "BLOCK"},
                trace_id=context.trace_id,
            ),
        )

    async def check_input(self, context, request_context):
        self.calls.append("input")
        self.contexts.append(dict(context))
        return self._result(self.input_action, request_context, "INPUT")

    async def check_retrieval(self, context, chunks, request_context):
        self.calls.append("retrieval")
        self.contexts.append(dict(context))
        self.chunks.append(list(chunks))
        return self._result(self.retrieval_action, request_context, "RETRIEVAL")

    async def check_output(self, context, candidate_text, request_context):
        self.calls.append("output")
        self.contexts.append(dict(context))
        self.candidate_text = candidate_text
        return self._result(self.output_action, request_context, "OUTPUT")


class FakeRetriever:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.last_role = None
        self.last_query = None

    def retrieve(self, query, *, caller_role, limit=3):
        self.calls += 1
        self.last_role = caller_role
        self.last_query = query
        self.limit = limit
        return self.result


class FakeRuntime:
    def __init__(self, response=None):
        self.response = response or _runtime_generation()
        self.calls = 0

    async def generate_programme(
        self, *, context, retrieval_id, programme_ref, source_manifest_sha256, sources
    ):
        self.calls += 1
        self.context = context
        self.retrieval_id = retrieval_id
        self.programme_ref = programme_ref
        self.source_manifest_sha256 = source_manifest_sha256
        self.sources = sources
        return replace(
            self.response,
            retrieval_id=retrieval_id,
            programme_ref=programme_ref,
            source_manifest_sha256=source_manifest_sha256,
        )


def _service(*, safety=None, retriever=None, runtime=None, clock=lambda: NOW):
    return ResearchProgrammeGenerationService(
        safety=safety or FakeSafety(),
        retriever=retriever or FakeRetriever(_retrieval()),
        runtime=runtime or FakeRuntime(),
        expected_manifest_sha256=MANIFEST_SHA,
        clock=clock,
    )


def _context() -> RequestContext:
    return RequestContext("REQ_research_001", "TRACE_research_001")


@pytest.mark.asyncio
async def test_normal_path_returns_only_held_staff_reference_and_safety_order() -> None:
    safety = FakeSafety()
    retriever = FakeRetriever(_retrieval())
    runtime = FakeRuntime()
    service = _service(safety=safety, retriever=retriever, runtime=runtime)

    result = await service.generate(
        actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        request_context=_context(),
    )

    assert result.status == "HELD"
    assert result.reason_code == "AWAITING_INTERNAL_RESEARCH_REVIEW"
    assert result.candidate is not None
    assert result.candidate.purpose == "staff_research_reference"
    assert result.candidate.student_feedback_eligible is False
    assert result.candidate.report is False
    assert result.candidate.programme_ref == "PROGRAMME_SCHOOL_CONNECTEDNESS_REFERENCE_V1"
    assert result.candidate.prompt_id == "PROMPT_staff_school_programme_research_v1"
    assert result.candidate.prompt_version == PROMPT_VERSION
    assert len(result.candidate.prompt_sha256) == 64
    assert len(result.candidate.retrieval_bundle_sha256) == 64
    assert len(result.candidate.chunk_set_sha256) == 64
    assert len(result.candidate.source_set_sha256) == 64
    assert [item.stage for item in result.candidate.safety_evidence] == [
        "INPUT", "RETRIEVAL", "OUTPUT"
    ]
    assert all(item.trace_id == _context().trace_id for item in result.candidate.safety_evidence)
    assert result.candidate.safety_version == "backend-research-programme-safety-gates.v1"
    assert (
        result.candidate.evidence_limit
        == "POTENTIAL_SCHOOL_PROGRAMME_FRAMEWORKS_ONLY_OUTCOMES_NOT_ESTABLISHED"
    )
    assert result.candidate.human_curated is False
    assert result.candidate.publication_eligible is False
    assert result.candidate.production_use is False
    assert len(result.candidate.citations) == 4
    assert safety.calls == ["input", "retrieval", "output"]
    assert retriever.last_role == "psychological_specialist"
    assert retriever.limit == 4
    assert safety.contexts[0]["actor_role"] == "SYSTEM"
    assert safety.contexts[0]["age_group"] == "UNKNOWN"
    assert safety.contexts[0]["assessment_signals"] == []
    assert safety.contexts[1]["retrieval_metadata"]["research_only"] is True
    assert safety.chunks[0][0]["review_status"] == "approved"
    assert safety.chunks[0][0]["rights_status"] == "verified"
    assert safety.chunks[0][0]["professional_approval"] is False
    assert runtime.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retrieval",
    [
        _retrieval(status="NO_MATCHES", hits=()),
        _retrieval(hits=_hits(omit_layer="theory")),
        _retrieval(manifest_sha256="f" * 64),
        _retrieval(valid_through_month="2025-06"),
        _retrieval(publication_eligible=True),
    ],
)
async def test_untrusted_or_incomplete_retrieval_abstains_before_runtime(retrieval) -> None:
    safety = FakeSafety()
    runtime = FakeRuntime()
    result = await _service(
        safety=safety,
        retriever=FakeRetriever(retrieval),
        runtime=runtime,
    ).generate(actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST, request_context=_context())

    assert result.status == "ABSTAINED"
    assert result.candidate is None
    assert runtime.calls == 0
    assert safety.calls == ["input"]


@pytest.mark.asyncio
async def test_exact_study_utc_deadline_is_inclusive_and_later_time_abstains() -> None:
    deadline = datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC)
    at_deadline_runtime = FakeRuntime()
    at_deadline = await _service(
        runtime=at_deadline_runtime,
        clock=lambda: deadline,
    ).generate(actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST, request_context=_context())
    assert at_deadline.status == "HELD"
    assert at_deadline_runtime.calls == 1

    after_deadline_runtime = FakeRuntime()
    after_deadline_safety = FakeSafety()
    after_deadline = await _service(
        safety=after_deadline_safety,
        runtime=after_deadline_runtime,
        clock=lambda: datetime(2027, 6, 30, 16, 0, 0, tzinfo=UTC),
    ).generate(actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST, request_context=_context())
    assert after_deadline.status == "ABSTAINED"
    assert after_deadline.reason_code == "RESEARCH_EVIDENCE_INCOMPLETE_OR_UNTRUSTED"
    assert after_deadline_safety.calls == ["input"]
    assert after_deadline_runtime.calls == 0


@pytest.mark.asyncio
async def test_non_specialist_is_rejected_before_safety_retrieval_or_runtime() -> None:
    safety = FakeSafety()
    retriever = FakeRetriever(_retrieval())
    runtime = FakeRuntime()

    with pytest.raises(BackendError) as raised:
        await _service(safety=safety, retriever=retriever, runtime=runtime).generate(
            actor_role=BackendRole.STUDENT,
            request_context=_context(),
        )

    assert raised.value.code is ErrorCode.FORBIDDEN
    assert safety.calls == []
    assert retriever.calls == 0
    assert runtime.calls == 0


@pytest.mark.asyncio
async def test_crisis_route_halts_before_retrieval_and_runtime() -> None:
    safety = FakeSafety(input_action="CRISIS_ROUTE")
    retriever = FakeRetriever(_retrieval())
    runtime = FakeRuntime()
    result = await _service(safety=safety, retriever=retriever, runtime=runtime).generate(
        actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        request_context=_context(),
    )

    assert result.status == "HALTED"
    assert result.safety_action == "CRISIS_ROUTE"
    assert result.candidate is None
    assert safety.calls == ["input"]
    assert retriever.calls == 0
    assert runtime.calls == 0


@pytest.mark.asyncio
async def test_retrieval_safety_stop_prevents_model_call() -> None:
    safety = FakeSafety(retrieval_action="REVIEW_REQUIRED")
    runtime = FakeRuntime()
    result = await _service(safety=safety, runtime=runtime).generate(
        actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        request_context=_context(),
    )

    assert result.status == "HALTED"
    assert result.safety_action == "REVIEW_REQUIRED"
    assert runtime.calls == 0
    assert safety.calls == ["input", "retrieval"]


@pytest.mark.asyncio
async def test_output_safety_stop_discards_generated_candidate() -> None:
    safety = FakeSafety(output_action="REVIEW_REQUIRED")
    runtime = FakeRuntime()
    result = await _service(safety=safety, runtime=runtime).generate(
        actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        request_context=_context(),
    )

    assert result.status == "HALTED"
    assert result.safety_action == "REVIEW_REQUIRED"
    assert result.candidate is None
    assert safety.calls == ["input", "retrieval", "output"]
    assert runtime.calls == 1


@pytest.mark.asyncio
async def test_forged_citation_or_claim_boundary_abstains_without_output_safety() -> None:
    forged = _runtime_generation(
        citation_ids=("CHUNK_RESEARCH_NOT_IN_PACKAGE",),
        body="Programme note. [CHUNK_RESEARCH_NOT_IN_PACKAGE]",
    )
    safety = FakeSafety()
    result = await _service(safety=safety, runtime=FakeRuntime(forged)).generate(
        actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        request_context=_context(),
    )
    assert result.status == "ABSTAINED"
    assert result.reason_code == "RESEARCH_RUNTIME_RESPONSE_INVALID"
    assert safety.calls == ["input", "retrieval"]

    claim = _runtime_generation(
        body=(
            "This programme guarantees effective treatment. "
            "[CHUNK_RESEARCH_WHO-HAT-STRATEGY1-POLICY-2021]"
        )
    )
    safety = FakeSafety()
    result = await _service(safety=safety, runtime=FakeRuntime(claim)).generate(
        actor_role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        request_context=_context(),
    )
    assert result.status == "ABSTAINED"
    assert result.reason_code == "RESEARCH_OUTPUT_OUT_OF_SCOPE"
    assert safety.calls == ["input", "retrieval"]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ("not-json private draft", "candidate_json"),
        (json.dumps({"title": "private draft"}), "candidate_schema"),
        (
            json.dumps({"title": "Reference", "passages": []}),
            "candidate_schema",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "passages": [
                        {"text": "private draft without citation", "source_chunk_ids": []}
                    ],
                }
            ),
            "candidate_schema",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "passages": [
                        {"text": "Reference passage", "source_chunk_ids": ["CHUNK_UNKNOWN"]}
                    ],
                }
            ),
            "candidate_citations",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "passages": [
                        {
                            "text": "Reference [CHUNK_SOURCE]",
                            "source_chunk_ids": ["CHUNK_SOURCE"],
                        }
                    ],
                }
            ),
            "candidate_citations",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "passages": [
                        {
                            "text": "Reference passage",
                            "source_chunk_ids": ["CHUNK_SOURCE", "CHUNK_SOURCE"],
                        }
                    ],
                }
            ),
            "candidate_citations",
        ),
        (
            json.dumps(
                {
                    "title": "Reference [CHUNK_SOURCE]",
                    "passages": [
                        {"text": "Reference passage", "source_chunk_ids": ["CHUNK_SOURCE"]}
                    ],
                }
            ),
            "candidate_citations",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "passages": [
                        {"text": "   ", "source_chunk_ids": ["CHUNK_SOURCE"]}
                    ],
                }
            ),
            "candidate_citations",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "passages": [
                        {"text": "Reference\ncontinued", "source_chunk_ids": ["CHUNK_SOURCE"]}
                    ],
                }
            ),
            "candidate_citations",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "body": "Legacy body is forbidden",
                    "passages": [
                        {"text": "Reference passage", "source_chunk_ids": ["CHUNK_SOURCE"]}
                    ],
                }
            ),
            "candidate_schema",
        ),
        (
            json.dumps(
                {
                    "title": "Reference",
                    "passages": [
                        {
                            "text": "Reference passage",
                            "source_chunk_ids": ["CHUNK_SOURCE"],
                            "extra": True,
                        }
                    ],
                }
            ),
            "candidate_schema",
        ),
    ],
)
def test_candidate_projection_diagnostics_never_include_generated_text(payload, code) -> None:
    from smhai_backend.integrations.research_programme import (
        ResearchProgrammeRuntimeError,
        _parse_candidate_text,
    )

    with pytest.raises(ResearchProgrammeRuntimeError) as caught:
        _parse_candidate_text(payload, allowed_chunk_ids=("CHUNK_SOURCE",))
    assert caught.value.code == code
    assert str(caught.value) == code
    assert "private draft" not in str(caught.value)


def test_runtime_http_client_rejects_non_loopback_origins() -> None:
    with pytest.raises(ValueError):
        HttpResearchProgrammeRuntimeClient(
            ModuleClientSettings(base_url="https://runtime.example.invalid")
        )


@pytest.mark.asyncio
async def test_runtime_http_client_sends_fixed_nonstudent_route_and_validates_response() -> None:
    captured: list[dict[str, Any]] = []
    paths: list[str] = []
    source_ids = [f"CHUNK_RESEARCH_{record_id}" for record_id, _layer, _source_id in _SOURCE_ROWS]
    candidate = {
        "title": "Staff reference",
        "passages": [
            {
                "text": "Use a school-wide planning discussion.",
                "source_chunk_ids": [source_ids[0]],
            },
            {
                "text": "Keep the framework bounded to the supplied context.",
                "source_chunk_ids": [source_ids[1]],
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "schema_version": "research_programme_generation.v1",
                "request_id": "REQ_research_001",
                "trace_id": "TRACE_research_001",
                "generation_id": body["generation_id"],
                "retrieval_id": body["retrieval_id"],
                "programme_ref": body["programme_ref"],
                "source_manifest_sha256": MANIFEST_SHA,
                "prompt_ref": body["prompt_ref"],
                "chunk_ids": body["chunk_ids"],
                "purpose": "staff_school_programme_research",
                "target_role": "psychological_specialist",
                "production_use": False,
                "publication_eligible": False,
                "status": "HOLD_FOR_REVIEW",
                "data": {
                    "text": json.dumps(candidate),
                    "model_id": EXPECTED_CONTRACT_MODEL_ID,
                    "logical_model_id": EXPECTED_MODEL_ID,
                    "model_version": "qwen2.5:7b-instruct-q4_K_M",
                    "runtime_version": "school-runtime",
                    "trace": {
                        "request_id": "REQ_research_001",
                        "trace_id": "TRACE_research_001",
                        "logical_model": EXPECTED_MODEL_ID,
                        "provider": "ollama",
                        "provider_model": EXPECTED_PROVIDER_MODEL_ID,
                    "model_revision": "school-runtime-model-revision",
                        "digest": EXPECTED_MODEL_DIGEST,
                    "quantization": "Q4_K_M",
                    "runtime_version": "school-runtime",
                    "hardware": {
                        "os": "test",
                        "cpu": "test",
                        "threads": 1,
                        "ram_bytes": 1024,
                        "gpu_present": False,
                        "gpus": [],
                        "cuda_available": False,
                        "nvidia_smi_path": None,
                        "detection_error": None,
                        "profile": "CPU_ONLY",
                    },
                    "generation_config": {
                        "max_output_tokens": 768,
                        "max_tokens": 768,
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "top_k": None,
                        "context_length": None,
                        "timeout_seconds": 8.0,
                        "keep_alive": "5m",
                        "seed": 20261014,
                        "stop": [],
                        "think": False,
                    },
                    "prompt_tokens": 20,
                    "completion_tokens": 30,
                    "ttft_ms": 10.0,
                    "generation_latency_ms": 100.0,
                    "total_latency_ms": 100.0,
                    "tokens_per_second": 300.0,
                    "retry_count": 0,
                    "requested_model": EXPECTED_MODEL_ID,
                    "actual_model": EXPECTED_MODEL_ID,
                    "fallback_reason": None,
                    "finish_reason": "stop",
                    "error": None,
                    "requested_provider_model": EXPECTED_PROVIDER_MODEL_ID,
                    "primary_error": None,
                    "primary_error_normalized_code": None,
                        "fallback_attempted": False,
                    "fallback_model": None,
                    "fallback_provider_model": None,
                    "fallback_generation_success": None,
                    "fallback_count": 0,
                    "attempts": [
                        {
                            "attempt_index": 1,
                            "provider_id": "ollama",
                            "logical_model_id": EXPECTED_MODEL_ID,
                            "provider_model_id": EXPECTED_PROVIDER_MODEL_ID,
                            "started_at": "2026-10-14T00:00:00Z",
                            "ended_at": "2026-10-14T00:00:01Z",
                            "outcome": "success",
                            "error_code": None,
                            "fallback_reason": None,
                            "retry": False,
                        }
                    ],
                    },
                    "buffered": True,
                },
            },
        )

    client = HttpResearchProgrammeRuntimeClient(
        ModuleClientSettings(base_url="http://127.0.0.1:8190")
    )
    client.client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8190",
        transport=httpx.MockTransport(handler),
    )
    sources = tuple(
        RuntimeSource(
            chunk_id=chunk_id,
            text="Pinned source excerpt",
            citation_label="Source",
            locator="Section",
        )
        for chunk_id in source_ids
    )
    try:
        result = await client.generate_programme(
            context=_context(),
            retrieval_id="RETR_test_001",
            programme_ref="PROGRAMME_staff_001",
            source_manifest_sha256=MANIFEST_SHA,
            sources=sources,
        )
    finally:
        await client.close()

    assert result.title == "Staff reference"
    assert result.retrieval_id == "RETR_test_001"
    assert result.prompt_id == "PROMPT_staff_school_programme_research_v1"
    assert result.prompt_version == PROMPT_VERSION
    assert PROMPT_VERSION == "1.1.0"
    assert "including in negative disclaimers" in captured[0]["messages"][0]["content"]
    assert result.prompt_sha256 == hashlib.sha256(
        json.dumps(
            captured[0]["messages"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert result.body == (
        f"Use a school-wide planning discussion. [{source_ids[0]}]\n\n"
        f"Keep the framework bounded to the supplied context. [{source_ids[1]}]"
    )
    assert result.citation_chunk_ids == (source_ids[0], source_ids[1])
    assert paths == [ROUTE_PATH]
    assert set(captured[0]) == {
        "schema_version", "request_id", "trace_id", "generation_id", "retrieval_id",
        "programme_ref", "source_manifest_sha256", "prompt_ref", "chunk_ids", "messages",
        "structured_schema", "config",
    }
    assert captured[0]["chunk_ids"] == source_ids
    schema = captured[0]["structured_schema"]
    properties = schema["properties"]
    assert schema["$id"] == "urn:psynova:research-programme-draft:1.1.0"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["title", "passages"]
    assert set(properties) == {"title", "passages"}
    passage_schema = properties["passages"]
    assert passage_schema["minItems"] == 1
    assert passage_schema["maxItems"] == 3
    passage_item = passage_schema["items"]
    assert passage_item["additionalProperties"] is False
    assert passage_item["required"] == ["text", "source_chunk_ids"]
    assert passage_item["properties"]["text"]["maxLength"] == 600
    assert passage_item["properties"]["text"]["pattern"] == "^[^\\r\\n]+$"
    selected_ids_schema = passage_item["properties"]["source_chunk_ids"]
    assert selected_ids_schema["minItems"] == 1
    assert selected_ids_schema["maxItems"] == 4
    assert selected_ids_schema["uniqueItems"] is True
    assert selected_ids_schema["items"]["enum"] == source_ids
    assert "citation_chunk_ids" not in properties
    assert "body" not in properties
    assert {message["role"] for message in captured[0]["messages"]} == {"system", "user"}
    payload_text = json.dumps(captured[0])
    for forbidden in ("assessment_id", "subject_id", "student_answers"):
        assert forbidden not in payload_text
