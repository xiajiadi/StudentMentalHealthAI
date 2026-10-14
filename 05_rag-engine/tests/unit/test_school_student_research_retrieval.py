from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rag_engine.research.student_education import (
    CONSUMER_SCOPE,
    SchoolStudentEducationRetriever,
    SchoolStudentPackageError,
    load_school_student_package,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _package() -> dict[str, object]:
    sources = [
        {
            "source_id": "POLICY_SRC",
            "title": "School policy excerpt",
            "canonical_url": "https://example.org/policy",
            "publisher": "Example policy body",
            "publication_date": "2024",
            "source_population_scope": "Adolescents 10-19; policy context",
            "source_language": "English",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Example policy body, CC BY 4.0",
            "rights_evidence_url": "https://example.org/rights",
            "rights_evidence_sha256": _sha("policy-rights"),
            "rights_status": "VERIFIED_WITH_CONDITIONS",
            "rights_scope_note": "Noncommercial research with attribution",
            "student_retrieval_eligible": True,
            "source_capture_sha256": _sha("policy-page"),
        },
        {
            "source_id": "THEORY_SRC",
            "title": "Connectedness concept",
            "canonical_url": "https://example.org/theory",
            "publisher": "Example journal",
            "publication_date": "2022",
            "source_population_scope": "Review ages 14-24",
            "source_language": "English",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Example journal, CC BY 4.0",
            "rights_evidence_url": "https://example.org/theory-rights",
            "rights_evidence_sha256": _sha("theory-rights"),
            "rights_status": "VERIFIED_WITH_CONDITIONS",
            "rights_scope_note": "Attribution required",
            "student_retrieval_eligible": True,
            "source_capture_sha256": _sha("theory-page"),
        },
        {
            "source_id": "INTERVENTION_SRC",
            "title": "School sleep review",
            "canonical_url": "https://example.org/intervention",
            "publisher": "Example journal",
            "publication_date": "2024",
            "source_population_scope": "School age 5-18",
            "source_language": "English",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Example journal, CC BY 4.0",
            "rights_evidence_url": "https://example.org/intervention-rights",
            "rights_evidence_sha256": _sha("intervention-rights"),
            "rights_status": "VERIFIED_WITH_CONDITIONS",
            "rights_scope_note": "Attribution required",
            "student_retrieval_eligible": True,
            "source_capture_sha256": None,
        },
        {
            "source_id": "CDC_PENDING_SRC",
            "title": "Pending international reuse source",
            "canonical_url": "https://example.org/pending",
            "publisher": "Agency",
            "publication_date": "2024",
            "source_population_scope": "School youth",
            "source_language": "English",
            "license": "Public domain with conditions",
            "license_url": "https://example.org/terms",
            "attribution": "Agency attribution required",
            "rights_evidence_url": "https://example.org/rights-pending",
            "rights_evidence_sha256": _sha("pending-rights"),
            "rights_status": "PENDING",
            "rights_scope_note": "International scope has not been resolved",
            "student_retrieval_eligible": False,
            "source_capture_sha256": _sha("pending-page"),
        },
    ]
    records = []
    record_defs = [
        (
            "POLICY_REC",
            "POLICY_SRC",
            "policy",
            "school policy helps create a supportive environment",
            "secondary_school_student_13_18",
            True,
        ),
        (
            "THEORY_REC",
            "THEORY_SRC",
            "theory",
            "school connectedness describes relationships and belonging in school",
            "secondary_school_student_13_18",
            True,
        ),
        (
            "INTERVENTION_REC",
            "INTERVENTION_SRC",
            "intervention",
            "sleep education evidence in schools has limitations",
            "secondary_school_student_13_17",
            True,
        ),
        (
            "PENDING_REC",
            "CDC_PENDING_SRC",
            "intervention",
            "school resources and general student guidance",
            "secondary_school_student_13_18",
            False,
        ),
    ]
    for record_id, source_id, layer, text, consumer_scope, eligible in record_defs:
        source = next(source for source in sources if source["source_id"] == source_id)
        records.append(
            {
                "record_id": record_id,
                "source_id": source_id,
                "layer": layer,
                "text": text,
                "locator": "Abstract, conclusion",
                "excerpt_sha256": _sha(text),
                "source_population_scope": source["source_population_scope"],
                "consumer_scope": consumer_scope,
                "language": "English",
                "certainty": "General source statement; no individual outcome claim",
                "role_fit": "General education only",
                "student_retrieval_eligible": eligible,
            }
        )
    return {
        "schema_version": "psynova.school-research-student-knowledge.v1",
        "package_id": "student-package-fixture-v1",
        "package_status": "ENGINEERING_REVIEWED_RESEARCH_ONLY",
        "reviewer_kind": "AI_ENGINEERING",
        "review_ref": "source-review-fixture-v1",
        "consumer_scope": "secondary_school_student_13_18",
        "study_ref": "school-noncommercial-rag-research-2027-06",
        "use_policy": {
            "scope": "ISOLATED_GENERAL_EDUCATION_SIMULATION",
            "noncommercial": True,
            "valid_through": "2027-06-30T15:59:59Z",
            "audience": "Fictional secondary-school student simulation only",
            "allowed_content": (
                "English source excerpts and source-bound general educational information only"
            ),
            "prohibited_content": [
                "individualized advice",
                "assessment score interpretation",
                "diagnosis",
                "treatment",
                "crisis or risk inference",
                "claims of guaranteed personal outcome",
            ],
            "language": (
                "Preserve source wording in English; no translation is represented as source text."
            ),
        },
        "flags": {
            "human_curated": False,
            "professional_approval": False,
            "ethics_approval": False,
            "clinical_approval": False,
            "psychometric_approval": False,
            "publication_eligible": False,
            "production_use": False,
        },
        "role_scope": ["student"],
        "risk_scope": ["normal"],
        "review_status": "pending",
        "sources": sources,
        "records": records,
    }


def _write_package(tmp_path: Path, value: dict[str, object]) -> tuple[Path, str]:
    target = tmp_path / "student-manifest.json"
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    target.write_bytes(payload)
    return target, hashlib.sha256(payload).hexdigest()


def test_pinned_retrieval_keeps_pending_state_and_excludes_pending_rights(tmp_path: Path) -> None:
    path, digest = _write_package(tmp_path, _package())
    package = load_school_student_package(
        path,
        expected_manifest_sha256=digest,
        expected_study_ref="school-noncommercial-rag-research-2027-06",
        now=datetime(2026, 10, 15, tzinfo=UTC),
    )
    retriever = SchoolStudentEducationRetriever(package)
    result = retriever.retrieve(
        "school connectedness and general educational support",
        target_population=CONSUMER_SCOPE,
        now=datetime(2026, 10, 15, tzinfo=UTC),
    )

    assert result.status == "MATCHES"
    assert result.review_status == "pending"
    assert result.rights_status == "verified"
    assert {record.layer for record in package.eligible_records} == {
        "policy",
        "theory",
        "intervention",
    }
    assert all(hit.citation.source_id != "CDC_PENDING_SRC" for hit in result.hits)
    assert all(hit.citation.source_population_scope for hit in result.hits)


def test_retriever_returns_no_match_without_fabricating_hits(tmp_path: Path) -> None:
    path, digest = _write_package(tmp_path, _package())
    package = load_school_student_package(
        path,
        expected_manifest_sha256=digest,
        expected_study_ref="school-noncommercial-rag-research-2027-06",
    )
    result = SchoolStudentEducationRetriever(package).retrieve(
        "zzzxqvnonmatchingterm",
        target_population=CONSUMER_SCOPE,
    )
    assert result.status == "NO_MATCHES"
    assert result.hits == ()


def test_bilingual_query_expansion_is_bounded_and_layer_coverage_is_observed(
    tmp_path: Path,
) -> None:
    path, digest = _write_package(tmp_path, _package())
    package = load_school_student_package(
        path,
        expected_manifest_sha256=digest,
        expected_study_ref="school-noncommercial-rag-research-2027-06",
    )
    retriever = SchoolStudentEducationRetriever(package)

    broad = retriever.retrieve(
        "校园心理健康、归属感、身体活动和睡眠",
        target_population=CONSUMER_SCOPE,
    )
    assert broad.query_transform == "LEXICAL_BILINGUAL_KEYWORD_EXPANSION"
    assert broad.matched_layers == ("policy", "theory", "intervention")
    assert broad.missing_layers == ()
    assert {hit.layer for hit in broad.hits} == set(broad.matched_layers)

    scenario = retriever.retrieve(
        "活动、休息和归属",
        target_population=CONSUMER_SCOPE,
    )
    assert scenario.query_transform == "LEXICAL_BILINGUAL_KEYWORD_EXPANSION"
    assert scenario.matched_layers == ("theory", "intervention")
    assert scenario.missing_layers == ("policy",)

    unrelated = retriever.retrieve(
        "量子引力黑洞",
        target_population=CONSUMER_SCOPE,
    )
    assert unrelated.status == "NO_MATCHES"
    assert unrelated.hits == ()
    assert unrelated.query_transform == "NONE"
    assert unrelated.matched_layers == ()
    assert unrelated.missing_layers == ("policy", "theory", "intervention")


def test_loader_rejects_wrong_hash_and_cannot_relabel_pending_rights(tmp_path: Path) -> None:
    package = _package()
    path, digest = _write_package(tmp_path, package)
    with pytest.raises(SchoolStudentPackageError, match="STUDENT_PACKAGE_HASH_MISMATCH"):
        load_school_student_package(
            path,
            expected_manifest_sha256="0" * 64,
            expected_study_ref="school-noncommercial-rag-research-2027-06",
        )

    source = package["sources"][-1]
    source["student_retrieval_eligible"] = True
    package["records"][-1]["student_retrieval_eligible"] = True
    path, digest = _write_package(tmp_path, package)
    with pytest.raises(SchoolStudentPackageError, match="STUDENT_SOURCE_RIGHTS_INVALID"):
        load_school_student_package(
            path,
            expected_manifest_sha256=digest,
            expected_study_ref="school-noncommercial-rag-research-2027-06",
        )


def test_retriever_rejects_a_caller_selected_population(tmp_path: Path) -> None:
    path, digest = _write_package(tmp_path, _package())
    package = load_school_student_package(
        path,
        expected_manifest_sha256=digest,
        expected_study_ref="school-noncommercial-rag-research-2027-06",
    )
    with pytest.raises(SchoolStudentPackageError, match="STUDENT_POPULATION_NOT_AUTHORIZED"):
        SchoolStudentEducationRetriever(package).retrieve(
            "school support", target_population="university_student"
        )
