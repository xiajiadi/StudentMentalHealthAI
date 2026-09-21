from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from smhai_backend.integrations.evidence import (
    BundleIntegrityError,
    CitationIntegrityError,
    CitationMembershipError,
    EligibilityPolicy,
    EvidenceEligibilityError,
    RetrievalEvidenceBundle,
    build_retrieval_evidence_bundle,
)
from smhai_backend.integrations.rag import Citation, KnowledgeChunk, RetrievalResult


def _chunk(
    chunk_id: str = "CHUNK_evidence_1",
    *,
    review_status: str = "approved",
    rights_status: str = "verified",
    population_scope: list[str] | None = None,
    role_scope: list[str] | None = None,
    risk_scope: list[str] | None = None,
    text: str = "approved synthetic evidence",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        schema_version="knowledge.v1",
        chunk_id=chunk_id,
        document_id="KB_evidence_demo",
        text=text,
        content_type="approved_summary",
        location={"section": "synthetic", "page_start": None, "page_end": None},
        citation=Citation(
            title="Synthetic evidence source",
            organization="StudentMentalHealthAI synthetic fixture",
            locator="fixture://evidence/source",
        ),
        population_scope=population_scope or ["synthetic_demo"],
        role_scope=role_scope or ["student"],
        risk_scope=risk_scope or ["normal"],
        review_status=review_status,
        rights_status=rights_status,
        content_hash="sha256:" + ("1" * 64),
    )


def _retrieval(
    retrieval_id: str = "RETR_evidence_1",
    *,
    chunk: KnowledgeChunk | None = None,
    trace: dict[str, Any] | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        retrieval_id=retrieval_id,
        chunks=(chunk or _chunk(),),
        label="CONTRACT_FAKE",
        trace=trace,
    )


def test_observed_provenance_is_exact_and_hash_excludes_bundle_hash() -> None:
    trace = {
        "trace_id": "TRACE_evidence_1",
        "request_id": "REQ_evidence_1",
        "index_id": "INDEX_observed_1",
        "corpus_version": "CORPUS_observed_1",
        "run_id": "RUN_observed_1",
    }
    bundle = build_retrieval_evidence_bundle(
        _retrieval(trace=trace),
        transaction_id="TX_evidence_1",
        request_id="REQ_evidence_1",
        trace_id="TRACE_evidence_1",
    )

    assert bundle.provenance["index_id"] == "INDEX_observed_1"
    assert bundle.provenance["corpus_version"] == "CORPUS_observed_1"
    assert bundle.provenance["snapshot_id"] is None
    assert bundle.linkage.to_dict() == {
        "request_id": "REQ_evidence_1",
        "trace_id": "TRACE_evidence_1",
        "transaction_id": "TX_evidence_1",
    }
    assert "bundle_hash" not in bundle.canonical_payload
    expected = hashlib.sha256(
        json.dumps(
            bundle.canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert bundle.bundle_hash == expected
    assert bundle.bundle_hash not in bundle.canonical_json


def test_bundle_is_a_detached_recursive_immutable_snapshot() -> None:
    source = _chunk()
    retrieval = _retrieval(chunk=source)
    bundle = build_retrieval_evidence_bundle(retrieval)
    original_hash = bundle.bundle_hash
    detached = bundle.canonical_payload
    detached["chunks"][0]["text"] = "mutated detached copy"  # type: ignore[index]

    source.text = "mutated source after retrieval"  # type: ignore[misc]
    assert bundle.items[0].text == "approved synthetic evidence"
    assert bundle.bundle_hash == original_hash
    with pytest.raises(TypeError):
        bundle.items[0].payload["text"] = "cannot mutate"  # type: ignore[index]


def test_eligibility_is_fail_closed_for_review_rights_and_scope() -> None:
    ineligible = _chunk(
        review_status="pending",
        rights_status="unknown",
        population_scope=["other_population"],
        role_scope=["teacher"],
        risk_scope=["high"],
    )
    policy = EligibilityPolicy(
        target_population="synthetic_demo",
        target_role="student",
        risk_level="normal",
    )
    bundle = build_retrieval_evidence_bundle(
        _retrieval(chunk=ineligible),
        policy=policy,
        strict_eligibility=False,
    )

    assert bundle.eligible is False
    assert {
        "REVIEW_STATUS_INELIGIBLE",
        "RIGHTS_STATUS_INELIGIBLE",
        "POPULATION_SCOPE_INCOMPATIBLE",
        "ROLE_SCOPE_INCOMPATIBLE",
        "RISK_SCOPE_INCOMPATIBLE",
    }.issubset(set(bundle.items[0].eligibility.reason_codes))
    with pytest.raises(EvidenceEligibilityError):
        bundle.require_eligible()
    with pytest.raises(EvidenceEligibilityError):
        bundle.prompt_citations()


def test_citation_membership_integrity_and_cross_retrieval_are_bound() -> None:
    first = build_retrieval_evidence_bundle(_retrieval("RETR_evidence_1"))
    second = build_retrieval_evidence_bundle(_retrieval("RETR_evidence_2"))
    reference = first.citation_references()[0]

    assert first.validate_citations((reference,))[0].chunk_id == "CHUNK_evidence_1"
    with pytest.raises(CitationIntegrityError):
        first.validate_citation(second.citation_references()[0])
    with pytest.raises(CitationMembershipError):
        first.validate_citation("EVID_unknown")
    with pytest.raises(CitationIntegrityError):
        first.validate_citation(
            {
                **reference.to_dict(),
                "content_hash": "sha256:" + ("2" * 64),
            }
        )
    with pytest.raises(CitationIntegrityError):
        first.validate_citation({"source_chunk_id": "CHUNK_evidence_1"})


def test_same_bundle_resolution_rechecks_toc_tou_and_never_queries_rag() -> None:
    bundle = RetrievalEvidenceBundle.from_retrieval(_retrieval())
    reference = bundle.citation_references()[0]
    visible = bundle.resolve_citation(reference)
    assert visible["chunk_id"] == "CHUNK_evidence_1"
    assert visible["retrieval_id"] == "RETR_evidence_1"
    assert visible["bundle_hash"] == bundle.bundle_hash

    # A mutation through an unsafe test-only path simulates a TOCTOU swap.  The
    # display resolver re-verifies the exact snapshot before returning metadata.
    object.__setattr__(bundle, "bundle_hash", "0" * 64)
    with pytest.raises(BundleIntegrityError):
        bundle.resolve_citation(reference)
