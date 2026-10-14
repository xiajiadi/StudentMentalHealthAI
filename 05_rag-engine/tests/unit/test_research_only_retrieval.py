from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from rag_engine.research import (
    ResearchAccessDenied,
    ResearchPackageError,
    ResearchRetrievalError,
    ResearchOnlyRetriever,
    load_research_package,
)

SPECIALIST = "psychological_specialist"


def _package_value() -> dict:
    who_source = {
        "source_id": "WHO-HAT-TOOLKIT-2021",
        "title": "Synthetic WHO source fixture",
        "publisher": "Synthetic source fixture",
        "year": 2021,
        "isbn": None,
        "doi": None,
        "source_url": "https://example.invalid/who",
        "official_pdf_url": "https://example.invalid/who.pdf",
        "license": "CC BY-NC-SA 3.0 IGO",
        "license_url": "https://example.invalid/who-license",
        "rights_listing_url": "https://example.invalid/who-rights",
        "attribution": "Synthetic test fixture; not source reproduction.",
        "source_extraction_sha256": "a" * 64,
        "rights_capture_sha256": "b" * 64,
        "original_stage_sha256": None,
    }
    raniti_source = {
        "source_id": "RAG-THEORY-002",
        "title": "Synthetic research article fixture",
        "publisher": "Synthetic source fixture",
        "year": 2022,
        "isbn": None,
        "doi": "10.0000/example",
        "source_url": "https://example.invalid/raniti",
        "official_pdf_url": None,
        "license": "CC BY 4.0",
        "license_url": "https://example.invalid/cc-by",
        "rights_listing_url": None,
        "attribution": "Synthetic test fixture; not source reproduction.",
        "source_extraction_sha256": "c" * 64,
        "rights_capture_sha256": None,
        "original_stage_sha256": "d" * 64,
    }
    record_data = [
        (
            "WHO-HAT-STRATEGY1-POLICY-2021",
            "policy",
            "Policies can support adolescent school wellbeing.",
            who_source,
        ),
        (
            "WHO-HAT-SCHOOL-ENVIRONMENT-OBJECTIVE-2021",
            "intervention",
            "Supportive healthy safe school environments matter for adolescents.",
            who_source,
        ),
        (
            "WHO-HAT-SCHOOL-CLIMATE-SUPPORT-2021",
            "intervention",
            "A positive supportive school climate can help school wellbeing.",
            who_source,
        ),
        (
            "RAG-THEORY-002",
            "theory",
            "Evidence remains uncertain about whether school connectedness promotes remission.",
            raniti_source,
        ),
    ]
    records = []
    for record_id, layer, text, source in record_data:
        records.append(
            {
                "record_id": record_id,
                "layer": layer,
                "text": text,
                "excerpt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source": source,
                "locator": "Synthetic unit-test locator.",
                "source_population": "Synthetic adolescent school programme fixture.",
                "certainty": "Synthetic test text; no evidence claim.",
            }
        )
    return {
        "schema_version": "psynova.research-only-knowledge.v1",
        "package_id": "school-rag-ai-engineering-20261014-v1",
        "package_status": "AI_ENGINEERING_APPROVED_FOR_ISOLATED_RESEARCH_ONLY",
        "review_ref": "school-rag-review-20261014-r1",
        "reviewer_kind": "AI_ENGINEERING",
        "review_decision_scope": "isolated_noncommercial_school_programme_research",
        "human_curated": False,
        "professional_approval": False,
        "ethics_approval": False,
        "clinical_approval": False,
        "psychometric_approval": False,
        "publication_eligible": False,
        "production_use": False,
        "live_corpus_changed": False,
        "scope": "ISOLATED_GENERAL_EDUCATION_SIMULATION",
        "source_packet_sha256": "63928edd03beac609da5ae5039d04046d17c33249291c0a642b258897cee4ca7",
        "source_review_artifacts": {
            "candidate_addendum_sha256": (
                "1f34e1a48557c7c0034586ef87940cec35449373fb7eafa4448dbaf6509b1163"
            ),
            "ai_engineering_review_sha256": (
                "3b867fb51c014ca1b0a6567e513230190692bb7c2f83584d5619f9c912c1f7cc"
            ),
        },
        "use_policy": {
            "study_ref": "school-noncommercial-rag-research-2027-06",
            "use_mode": "SCHOOL_NONCOMMERCIAL_RESEARCH",
            "noncommercial": True,
            "valid_through_month": "2027-06",
            "role_scope": [SPECIALIST],
            "population_scope": ["adolescent_school_programme_research"],
            "risk_scope": ["general_education_only"],
            "output_boundary": (
                "staff research reference only; no individual scoring, interpretation, "
                "diagnosis, crisis/risk inference, personal feedback, or automated report"
            ),
        },
        "source_use_terms": {
            "allowed_scope": (
                "This external research package and isolated noncommercial school-programme "
                "retrieval through 2027-06 only."
            ),
            "software_license_inference": False,
            "production_rights_inference": False,
            "commercial_use_included": False,
            "attribution_required": True,
            "sharealike_required_for_who_adaptations": True,
            "endorsement_claimed": False,
        },
        "retrieval": {
            "kind": "IN_MEMORY_EPHEMERAL_BM25S",
            "lexical_only": True,
            "embeddings_used": False,
            "model_called": False,
            "index_persisted": False,
            "production_store_used": False,
        },
        "records": records,
    }


def _write_mutated_package(tmp_path: Path, mutate) -> tuple[Path, str]:
    value = _package_value()
    mutate(value)
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_specialist_gets_cited_lexical_research_excerpt_only(tmp_path: Path):
    package_path, package_sha256 = _write_mutated_package(tmp_path, lambda _value: None)
    package = load_research_package(
        package_path,
        expected_manifest_sha256=package_sha256,
        now=date(2026, 10, 14),
    )
    retriever = ResearchOnlyRetriever(package, clock=lambda: date(2026, 10, 14))

    result = retriever.retrieve(
        "supportive healthy safe school environments",
        caller_role=SPECIALIST,
        limit=2,
    )

    assert result.status == "MATCHES"
    assert result.retriever == "BM25S"
    assert result.hits[0].record_id == "WHO-HAT-SCHOOL-ENVIRONMENT-OBJECTIVE-2021"
    assert "Supportive healthy safe school environments" in result.hits[0].text
    assert result.hits[0].citation.source_url == "https://example.invalid/who"
    assert result.hits[0].citation.official_pdf_url == "https://example.invalid/who.pdf"
    assert result.hits[0].citation.license == "CC BY-NC-SA 3.0 IGO"
    assert result.hits[0].citation.excerpt_sha256
    assert result.package_id == "school-rag-ai-engineering-20261014-v1"
    assert result.scope == "ISOLATED_GENERAL_EDUCATION_SIMULATION"
    assert result.role_scope == (SPECIALIST,)
    assert result.population_scope == ("adolescent_school_programme_research",)
    assert result.risk_scope == ("general_education_only",)
    assert result.reviewer_kind == "AI_ENGINEERING"
    assert result.noncommercial is True
    assert "no individual scoring" in result.output_boundary
    assert result.human_curated is False
    assert result.professional_approval is False
    assert result.ethics_approval is False
    assert result.clinical_approval is False
    assert result.psychometric_approval is False
    assert result.publication_eligible is False
    assert result.production_use is False
    assert result.research_only is True
    assert result.index_persisted is False
    assert result.embeddings_used is False
    assert result.model_called is False
    assert result.production_store_used is False


def test_non_specialist_role_is_denied_before_retrieval(tmp_path: Path):
    package_path, package_sha256 = _write_mutated_package(tmp_path, lambda _value: None)
    package = load_research_package(
        package_path,
        expected_manifest_sha256=package_sha256,
        now=date(2026, 10, 14),
    )
    retriever = ResearchOnlyRetriever(package, clock=lambda: date(2026, 10, 14))

    with pytest.raises(ResearchAccessDenied) as error:
        retriever.retrieve("school climate", caller_role="teacher")

    assert error.value.code == "RESEARCH_ROLE_NOT_AUTHORIZED"


def test_expired_package_is_rejected_on_load_and_retrieval(tmp_path: Path):
    package_path, package_sha256 = _write_mutated_package(tmp_path, lambda _value: None)
    with pytest.raises(ResearchPackageError) as load_error:
        load_research_package(
            package_path,
            expected_manifest_sha256=package_sha256,
            now=date(2027, 7, 1),
        )
    assert load_error.value.code == "RESEARCH_PACKAGE_EXPIRED"

    package = load_research_package(
        package_path,
        expected_manifest_sha256=package_sha256,
        now=date(2027, 6, 30),
    )
    retriever = ResearchOnlyRetriever(package, clock=lambda: date(2027, 7, 1))
    with pytest.raises(ResearchRetrievalError) as retrieval_error:
        retriever.retrieve("school climate", caller_role=SPECIALIST)
    assert retrieval_error.value.code == "RESEARCH_PACKAGE_EXPIRED"


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("human_curated", True),
        ("professional_approval", True),
        ("ethics_approval", True),
        ("clinical_approval", True),
        ("psychometric_approval", True),
        ("publication_eligible", True),
        ("production_use", True),
    ],
)
def test_changed_approval_flag_fails_closed_even_with_matching_new_hash(
    tmp_path: Path,
    field: str,
    changed: bool,
):
    path, new_hash = _write_mutated_package(
        tmp_path,
        lambda value: value.__setitem__(field, changed),
    )

    with pytest.raises(ResearchPackageError) as error:
        load_research_package(path, expected_manifest_sha256=new_hash, now=date(2026, 10, 14))

    assert error.value.code == "RESEARCH_PACKAGE_APPROVAL_SCOPE_INVALID"


def test_changed_research_role_fails_closed_even_with_matching_new_hash(tmp_path: Path):
    path, new_hash = _write_mutated_package(
        tmp_path,
        lambda value: value["use_policy"].__setitem__("role_scope", ["teacher"]),
    )

    with pytest.raises(ResearchPackageError) as error:
        load_research_package(path, expected_manifest_sha256=new_hash, now=date(2026, 10, 14))

    assert error.value.code == "RESEARCH_POLICY_SCOPE_INVALID"


def test_package_hash_mismatch_fails_closed(tmp_path: Path):
    package_path, _ = _write_mutated_package(tmp_path, lambda _value: None)
    with pytest.raises(ResearchPackageError) as error:
        load_research_package(
            package_path,
            expected_manifest_sha256="0" * 64,
            now=date(2026, 10, 14),
        )
    assert error.value.code == "RESEARCH_PACKAGE_HASH_MISMATCH"


def test_hand_constructed_package_cannot_bypass_loader_validation(tmp_path: Path):
    package_path, package_sha256 = _write_mutated_package(tmp_path, lambda _value: None)
    package = load_research_package(
        package_path,
        expected_manifest_sha256=package_sha256,
        now=date(2026, 10, 14),
    )
    unvalidated = replace(package, _validation_token=object())

    with pytest.raises(ResearchRetrievalError) as error:
        ResearchOnlyRetriever(unvalidated, clock=lambda: date(2026, 10, 14))

    assert error.value.code == "RESEARCH_PACKAGE_REQUIRED"


def test_unknown_package_fields_and_duplicate_json_keys_fail_closed(tmp_path: Path):
    unknown_path, unknown_hash = _write_mutated_package(
        tmp_path,
        lambda value: value.__setitem__("approved_for_production", True),
    )
    with pytest.raises(ResearchPackageError) as unknown_error:
        load_research_package(
            unknown_path,
            expected_manifest_sha256=unknown_hash,
            now=date(2026, 10, 14),
        )
    assert unknown_error.value.code == "RESEARCH_PACKAGE_SCHEMA_INVALID"

    duplicate_path = tmp_path / "duplicate.json"
    raw = json.dumps(_package_value(), ensure_ascii=False, indent=2).replace(
        '"human_curated": false,', '"human_curated": false,\n  "human_curated": false,', 1
    )
    duplicate_path.write_text(raw, encoding="utf-8")
    duplicate_hash = hashlib.sha256(duplicate_path.read_bytes()).hexdigest()
    with pytest.raises(ResearchPackageError) as duplicate_error:
        load_research_package(
            duplicate_path,
            expected_manifest_sha256=duplicate_hash,
            now=date(2026, 10, 14),
        )
    assert duplicate_error.value.code == "RESEARCH_PACKAGE_DUPLICATE_KEY"


def test_real_four_record_package_passes_backend_retrieval_evidence_validation():
    """Exercise actual RAG output against the Backend's shared evidence validator."""
    manifest_path = Path(
        os.environ.get(
            "PSYNOVA_RESEARCH_PROGRAMME_MANIFEST",
            str(
                Path(r"D:\Dev\datasets\psynova-public-research\research-packages")
                / "school-rag-ai-engineering-20261014-v1"
                / "manifest.json"
            ),
        )
    )
    if not manifest_path.is_file():
        pytest.skip("the separately staged local research package is not present")
    # Controller-confirmed application trust pin. The test does not trust a
    # checksum stored beside the package or derive an authority from the file.
    trusted_manifest_sha256 = (
        "f8af1a33487f175b02400fbfcf5f655cd93b40c7a5a35e0582dc363b11401a45"
    )
    retriever = ResearchOnlyRetriever.from_manifest(
        manifest_path,
        expected_manifest_sha256=trusted_manifest_sha256,
        clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
    )
    result = retriever.retrieve(
        "WHO HAT strategy policy healthy school environment school climate "
        "supportive school programme implementation theory",
        caller_role=SPECIALIST,
        limit=4,
    )

    backend_schemas = (
        Path(__file__).resolve().parents[3]
        / "09_backend"
        / "src"
        / "smhai_backend"
        / "domains"
        / "research_programme_generation"
        / "schemas.py"
    )
    spec = importlib.util.spec_from_file_location(
        "smhai_backend_research_programme_schemas", backend_schemas
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert result.manifest_sha256 == trusted_manifest_sha256
    assert len(result.hits) == 4
    assert {hit.layer for hit in result.hits} == {"policy", "intervention", "theory"}
    assert module.validate_retrieval_evidence(
        result,
        trusted_manifest_sha256,
        datetime(2026, 10, 14, tzinfo=timezone.utc),
    ) is True
