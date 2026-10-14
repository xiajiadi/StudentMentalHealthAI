from __future__ import annotations

from types import SimpleNamespace

import pytest

from smhai_backend.core.errors import BackendError
from smhai_backend.core.request_context import RequestContext
from smhai_backend.integrations.student_research import SchoolResearchStudentRagAdapter

_HASH = "a" * 64
_STUDY = "school-noncommercial-rag-research-2027-06"


def _fixtures(*, eligible: bool = True, rights: str = "VERIFIED_WITH_CONDITIONS"):
    record = SimpleNamespace(
        record_id="THEORY_RECORD",
        source_id="THEORY_SOURCE",
        layer="theory",
        text="School relationships are one part of the learning environment.",
        locator="Abstract, background",
        excerpt_sha256=_HASH,
        source_population_scope="Review ages 14-24; not high-school-only",
        consumer_scope="secondary_school_student_13_18",
        student_retrieval_eligible=eligible,
    )
    source = SimpleNamespace(
        source_id="THEORY_SOURCE",
        title="School connectedness concept",
        canonical_url="https://example.org/article",
        publisher="Example journal",
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Example journal, CC BY 4.0",
        rights_scope_note="Attribution required",
        rights_status=rights,
        student_retrieval_eligible=eligible,
    )
    package = SimpleNamespace(
        manifest_sha256=_HASH,
        package_id="student-package-v1",
        study_ref=_STUDY,
        records=(record,),
        sources=(source,),
    )
    citation = SimpleNamespace(
        source_id="THEORY_SOURCE",
        title=source.title,
        publisher=source.publisher,
        canonical_url=source.canonical_url,
        locator=(
            "Abstract, background; source population: Review ages 14-24; source: "
            "https://example.org/article; license: CC BY 4.0 "
            "(https://creativecommons.org/licenses/by/4.0/); "
            "attribution: Example journal, CC BY 4.0"
        ),
        license=source.license,
        license_url=source.license_url,
        attribution="Example journal, CC BY 4.0",
        rights_scope_note=source.rights_scope_note,
        source_population_scope=record.source_population_scope,
        excerpt_sha256=_HASH,
    )
    hit = SimpleNamespace(
        record_id=record.record_id,
        chunk_id="CHUNK_SCHOOL_RESEARCH_THEORY_RECORD",
        layer="theory",
        text=record.text,
        citation=citation,
        lexical_score=1.0,
    )

    class FakeRetriever:
        def __init__(self):
            self.package = package
            self.result = SimpleNamespace(
                status="MATCHES",
                package_id=package.package_id,
                manifest_sha256=package.manifest_sha256,
                study_ref=package.study_ref,
                consumer_scope="secondary_school_student",
                consumer_age_min=14,
                consumer_age_max=17,
                review_status="pending",
                rights_status="verified",
                source_rights_status="VERIFIED_WITH_CONDITIONS",
                query_transform="NONE",
                matched_layers=("theory",),
                missing_layers=("policy", "intervention"),
                hits=(hit,),
            )

        def retrieve(self, query, *, target_population, limit):
            return self.result

    return FakeRetriever(), package, hit


@pytest.mark.asyncio
async def test_adapter_returns_frozen_pending_student_chunk_with_source_boundary() -> None:
    retriever, _package, _hit = _fixtures()
    adapter = SchoolResearchStudentRagAdapter(
        retriever,
        expected_manifest_sha256=_HASH,
        expected_package_id="student-package-v1",
        expected_study_ref=_STUDY,
    )
    result = await adapter.retrieve(
        query="school connectedness",
        target_population="secondary_school_student",
        top_k=8,
        retrieval_id="RETR_student_research",
        context=RequestContext(request_id="REQ_research", trace_id="TRACE_research"),
    )

    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.review_status == "pending"
    assert chunk.rights_status == "verified"
    assert chunk.population_scope == ["secondary_school_student"]
    assert chunk.role_scope == ["student"]
    assert chunk.risk_scope == ["normal"]
    assert "source population: Review ages 14-24" in chunk.citation.locator
    assert "CC BY 4.0" in chunk.citation.locator
    assert result.trace["manifest_sha256"] == _HASH
    assert result.trace["professional_approval"] is False
    assert result.trace["consumer_age_min"] == 14
    assert result.trace["query_transform"] == "NONE"
    assert result.trace["matched_layers"] == ["theory"]
    assert result.trace["missing_layers"] == ["policy", "intervention"]


@pytest.mark.asyncio
async def test_adapter_refuses_package_pin_or_source_eligibility_mismatch() -> None:
    retriever, package, _hit = _fixtures()
    with pytest.raises(ValueError, match="does not match server pins"):
        SchoolResearchStudentRagAdapter(
            retriever,
            expected_manifest_sha256="b" * 64,
            expected_package_id=package.package_id,
            expected_study_ref=_STUDY,
        )

    invalid_retriever, _package, hit = _fixtures(eligible=True, rights="PENDING")
    invalid_retriever.result = SimpleNamespace(
        **{
            **vars(invalid_retriever.result),
            "hits": (hit,),
        }
    )
    adapter = SchoolResearchStudentRagAdapter(
        invalid_retriever,
        expected_manifest_sha256=_HASH,
        expected_package_id=invalid_retriever.package.package_id,
        expected_study_ref=_STUDY,
    )
    with pytest.raises(BackendError):
        await adapter.retrieve(
            query="school connectedness",
            target_population="secondary_school_student",
            top_k=8,
            retrieval_id="RETR_student_research",
            context=RequestContext(request_id="REQ_research", trace_id="TRACE_research"),
        )

