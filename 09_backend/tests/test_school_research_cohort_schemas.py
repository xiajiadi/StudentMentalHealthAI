from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smhai_backend.domains.school_research_cohorts.schemas import (
    ResearchCohortReceiptDto,
    ResearchCohortSealRequest,
)


def _request():
    return {
        "binding_ref": "promis-research-01",
        "profile_version_number": 3,
        "batch_refs": [f"BATCH_demo_{number}" for number in range(8)],
    }


def _receipt():
    return {
        "cohort_ref": "COHORT_demo_01",
        "study_ref": "STUDY_demo_01",
        "profile_ref": "promis-research-01",
        "profile_version_number": 3,
        "source_population_scope": "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        "status": "SEALED",
        "subject_count": 800,
        "class_count": 8,
        "assigned_distinct_cases": 800,
        "sealed_at": datetime(2026, 10, 14, tzinfo=UTC),
        "response_origin": "PUBLIC_OBSERVED",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
    }


def test_batch_order_normalizes_without_assigning_cases():
    value = _request()
    first = ResearchCohortSealRequest.model_validate(value)
    value["batch_refs"].reverse()
    assert ResearchCohortSealRequest.model_validate(value) == first
    assert not any("case" in key for key in first.model_dump())


@pytest.mark.parametrize("size", [0, 1, 7, 9, 800])
def test_requires_exactly_eight_batches(size):
    value = _request()
    value["batch_refs"] = [f"BATCH_demo_{n}" for n in range(size)]
    with pytest.raises(ValidationError):
        ResearchCohortSealRequest.model_validate(value)


def test_rejects_duplicate_batches():
    value = _request()
    value["batch_refs"][-1] = value["batch_refs"][0]
    with pytest.raises(ValidationError):
        ResearchCohortSealRequest.model_validate(value)


@pytest.mark.parametrize("field", [
    "school_id", "cohort_ref", "subject_ids", "case_index", "case_index_plan",
    "seed", "corpus_sha256", "manifest_sha256", "response_rows", "ethics_approval",
])
def test_rejects_client_assignment_provenance_or_approval(field):
    value = _request()
    value[field] = "untrusted-client-value"
    with pytest.raises(ValidationError):
        ResearchCohortSealRequest.model_validate(value)


@pytest.mark.parametrize("value", [True, False, "3", 3.0, 0, -1, 2_147_483_648])
def test_profile_version_is_strict_bounded_integer(value):
    payload = _request()
    payload["profile_version_number"] = value
    with pytest.raises(ValidationError):
        ResearchCohortSealRequest.model_validate(payload)


def test_receipt_is_content_free_assignment_metadata():
    value = ResearchCohortReceiptDto.model_validate(_receipt()).model_dump()
    assert value["assigned_distinct_cases"] == 800
    assert set(value) == set(_receipt())
    assert not {"case_index", "subject_id", "account_id", "completed_count", "answers"} & set(value)


@pytest.mark.parametrize("field, value", [
    ("subject_count", 799), ("subject_count", 800.0),
    ("assigned_distinct_cases", "800"), ("class_count", 8.0),
    ("status", "OPEN"), ("research_only", False),
    ("publication_status", "APPROVED"), ("response_origin", "SYNTHETIC"),
])
def test_receipt_rejects_unsealed_or_non_strict_claims(field, value):
    payload = _receipt()
    payload[field] = value
    with pytest.raises(ValidationError):
        ResearchCohortReceiptDto.model_validate(payload)
