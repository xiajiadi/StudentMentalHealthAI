from __future__ import annotations

import pytest
from pydantic import ValidationError

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.assessment.binding import D3_RAG_POPULATION
from smhai_backend.domains.support.schemas import SupportRequest
from smhai_backend.integrations.d3 import default_fixture_config, retrieval_eligibility_population
from smhai_backend.integrations.d3_chain import (
    D3ChainError,
    _content_population_mapping,
    _d3_1_chunks,
)
from smhai_backend.integrations.evidence import EligibilityPolicy, build_retrieval_evidence_bundle
from smhai_backend.integrations.population_mapping import (
    UNIVERSITY_FRESHMAN_SYNTHETIC_MAPPING,
    PopulationMappingError,
    resolve_population_mapping,
)
from smhai_backend.integrations.rag import (
    Citation,
    HttpRagClient,
    KnowledgeChunk,
    RetrievalResult,
    UpstreamError,
)


def _chunk(population_scope: list[str]) -> KnowledgeChunk:
    return KnowledgeChunk(
        schema_version="knowledge.v1",
        chunk_id="CHUNK_population_1",
        document_id="KB_population_1",
        text="approved synthetic education support",
        location={"section": "support", "page_start": None, "page_end": None},
        citation=Citation(
            title="Synthetic support source",
            organization="StudentMentalHealthAI",
            locator="fixture://population/source",
        ),
        population_scope=population_scope,
        role_scope=["student"],
        risk_scope=["normal"],
        content_hash="sha256:" + "1" * 64,
    )


def test_server_mapping_separates_product_rag_eligibility_and_d3_identities():
    mapping = resolve_population_mapping(D3_RAG_POPULATION)

    assert mapping == UNIVERSITY_FRESHMAN_SYNTHETIC_MAPPING
    assert mapping.mapping_version == "1.0.0"
    assert mapping.product_population == D3_RAG_POPULATION
    assert mapping.rag_query_taxonomy == "university_freshman"
    assert mapping.evidence_eligibility_population == "university_freshman"
    assert mapping.d3_content_population == D3_RAG_POPULATION
    assert retrieval_eligibility_population(
        RetrievalResult("RETR_http_1", (_chunk(["university_freshman"]),), "REAL_HTTP"),
        config=default_fixture_config(),
    ) == "university_freshman"


@pytest.mark.asyncio
async def test_real_rag_request_uses_server_population_mapping_without_caller_override(monkeypatch):
    client = HttpRagClient(ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8170"))
    observed: dict[str, object] = {}

    async def fake_post_json(path, payload, *, context, headers=None):
        observed.update(payload)
        return {
            "data": {
                "retrieval_id": "RETR_population_1",
                "chunks": [_chunk(["university_freshman"]).model_dump(mode="json")],
                "trace": {"request_id": context.request_id, "trace_id": context.trace_id},
            }
        }

    monkeypatch.setattr(client, "post_json", fake_post_json)
    retrieval = await client.retrieve(
        assessment={"population_scope": "pending_confirmation"},
        target_role="student",
        query="synthetic normal request",
        top_k=5,
        trace_id="TRACE_population_1",
        request_id="REQ_population_1",
    )

    assert observed["target_population"] == "university_freshman"
    assert observed["target_population"] != "K12学生"
    assert "product_population" not in observed
    assert retrieval.chunks[0].population_scope == ["university_freshman"]
    policy = EligibilityPolicy(
        target_population=UNIVERSITY_FRESHMAN_SYNTHETIC_MAPPING.evidence_eligibility_population,
        target_role="student",
        risk_level="normal",
    )
    bundle = build_retrieval_evidence_bundle(retrieval, policy=policy)
    assert bundle.eligible is True
    assert bundle.items[0].eligibility.reason_codes == ()
    await client.close()


def test_unknown_population_mapping_fails_closed_and_caller_cannot_override():
    with pytest.raises(PopulationMappingError):
        resolve_population_mapping("unmapped_population")

    with pytest.raises(ValidationError):
        SupportRequest.model_validate(
            {
                "assessment_id": "ASSESS_population_1",
                "target_role": "student",
                "message": "synthetic request",
                "language": "zh-CN",
                "target_population": "university_freshman",
            }
        )


def test_k12_chunk_is_ineligible_and_never_maps_to_freshman_d3_content():
    mapping = resolve_population_mapping(D3_RAG_POPULATION)
    retrieval = RetrievalResult("RETR_k12_1", (_chunk(["k12"]),), "REAL_HTTP")
    bundle = build_retrieval_evidence_bundle(
        retrieval,
        policy=EligibilityPolicy(
            target_population=mapping.evidence_eligibility_population,
            target_role="student",
            risk_level="normal",
        ),
        strict_eligibility=False,
    )

    assert bundle.eligible is False
    assert bundle.items[0].eligibility.reason_codes == ("POPULATION_SCOPE_INCOMPATIBLE",)
    with pytest.raises(D3ChainError):
        _content_population_mapping(bundle)


def test_real_http_d3_mapping_is_detached_and_requires_exact_observed_taxonomy():
    mapping = resolve_population_mapping(D3_RAG_POPULATION)
    retrieval = RetrievalResult(
        "RETR_http_2", (_chunk(["university_freshman"]),), "REAL_HTTP"
    )
    bundle = build_retrieval_evidence_bundle(
        retrieval,
        policy=EligibilityPolicy(
            target_population=mapping.evidence_eligibility_population,
            target_role="student",
            risk_level="normal",
        ),
    )

    content_mapping = _content_population_mapping(bundle)
    projected = _d3_1_chunks(bundle, content_mapping)

    assert content_mapping.mapping_id == mapping.mapping_id
    assert content_mapping.mapping_version == mapping.mapping_version
    assert content_mapping.source_population == "university_freshman"
    assert content_mapping.target_population == D3_RAG_POPULATION
    assert projected[0]["population_scope"] == ["university_freshman", D3_RAG_POPULATION]
    assert bundle.items[0].population_scope == ("university_freshman",)


@pytest.mark.asyncio
async def test_rag_timeout_and_malformed_response_remain_dependency_errors(monkeypatch):
    client = HttpRagClient(ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8170"))
    request = {
        "assessment": {},
        "target_role": "student",
        "query": "synthetic request",
        "top_k": 5,
        "trace_id": "TRACE_population_failure",
        "request_id": "REQ_population_failure",
    }

    async def timeout_post(*_args, **_kwargs):
        raise UpstreamError(ErrorCode.DEPENDENCY_TIMEOUT, status_code=504)

    monkeypatch.setattr(client, "post_json", timeout_post)
    with pytest.raises(BackendError) as timeout:
        await client.retrieve(**request)
    assert timeout.value.code is ErrorCode.DEPENDENCY_TIMEOUT
    assert timeout.value.status_code == 504

    async def malformed_post(*_args, **_kwargs):
        return {"data": {"retrieval_id": "RETR_malformed", "chunks": {}}}

    monkeypatch.setattr(client, "post_json", malformed_post)
    with pytest.raises(BackendError) as malformed:
        await client.retrieve(**request)
    assert malformed.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert malformed.value.status_code == 502
    await client.close()
