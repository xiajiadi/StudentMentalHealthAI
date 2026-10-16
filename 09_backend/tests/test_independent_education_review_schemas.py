from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smhai_backend.domains.independent_education_reviews.schemas import (
    IndependentEducationCandidateProvenanceDto,
    IndependentEducationReviewedDraftDto,
    IndependentEducationReviewerListDto,
    IndependentEducationReviewSummaryDto,
    IndependentEducationStaffSummaryDto,
    ShareEducationReviewRequest,
)
from smhai_backend.domains.research_general_education import ResearchGeneralEducationDraftService


def test_reviewer_page_and_staff_list_match_frozen_wire_fields() -> None:
    assert set(IndependentEducationReviewerListDto.model_fields) == {
        "items",
        "offset",
        "limit",
        "total",
        "has_more",
    }
    assert set(IndependentEducationStaffSummaryDto.model_fields) == {
        "review_ref",
        "status",
        "state_version",
        "created_at",
        "updated_at",
    }


def test_public_candidate_provenance_excludes_internal_only_values() -> None:
    fields = set(IndependentEducationCandidateProvenanceDto.model_fields)
    assert "generation_id" not in fields
    assert "input_safety_requires_human" not in fields
    assert "retrieval_safety_requires_human" not in fields
    assert "output_safety_requires_human" not in fields
    assert "prompt_sha256" in fields


def test_reviewed_draft_is_public_projection_not_encrypted_payload_schema() -> None:
    assert set(IndependentEducationReviewedDraftDto.model_fields) == {
        "title",
        "body",
        "content_revision",
        "citations",
        "source_cards",
        "updated_at",
    }
    assert "schema_version" not in IndependentEducationReviewedDraftDto.model_fields
    assert "candidate_content_sha256" not in IndependentEducationReviewedDraftDto.model_fields
    assert "source_manifest_sha256" not in IndependentEducationReviewedDraftDto.model_fields


def test_research_general_education_package_keeps_service_export() -> None:
    assert ResearchGeneralEducationDraftService.__name__ == "ResearchGeneralEducationDraftService"


def test_review_summary_requires_published_content_exactly_for_published_status() -> None:
    card = {
        "chunk_id": "CHUNK_test_1",
        "record_id": "record-1",
        "source_id": "source-1",
        "title": "Source title",
        "organization": "Source organization",
        "canonical_url": "https://example.edu/source",
        "record_locator": "Abstract",
        "source_population_scope": "Secondary school students",
        "source_language": "en",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Source organization",
        "excerpt_sha256": "a" * 64,
        "excerpt_text": "Source excerpt.",
        "consumer_age_min": 14,
        "consumer_age_max": 17,
    }
    citation = {
        "citation_id": "CITATION_test_1",
        "chunk_id": card["chunk_id"],
        "document_id": "DOC_test_1",
        "title": card["title"],
        "organization": card["organization"],
        "locator": "Abstract",
        "rank": 1,
        "source_version": "knowledge.v1",
        "source_hash": "sha256:" + card["excerpt_sha256"],
    }
    common = {
        "review_ref": "EDUREV_" + "e" * 32,
        "state_version": 4,
        "created_at": datetime(2026, 10, 16, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 16, tzinfo=UTC),
    }
    published_content = {
        "title": "Reviewed title",
        "body": "Reviewed source-grounded body.",
        "citations": [citation],
        "source_cards": [card],
        "published_at": datetime(2026, 10, 16, tzinfo=UTC),
    }

    with pytest.raises(ValidationError):
        IndependentEducationReviewSummaryDto.model_validate(
            {**common, "status": "PUBLISHED", "published_content": None}, strict=True
        )
    with pytest.raises(ValidationError):
        IndependentEducationReviewSummaryDto.model_validate(
            {**common, "status": "DRAFT", "published_content": published_content}, strict=True
        )
    valid = IndependentEducationReviewSummaryDto.model_validate(
        {**common, "status": "PUBLISHED", "published_content": published_content}, strict=True
    )
    assert valid.published_content is not None


@pytest.mark.parametrize("consent", [1, 0, "true", False])
def test_share_consent_rejects_non_boolean_true_values(consent) -> None:
    with pytest.raises(ValidationError):
        ShareEducationReviewRequest.model_validate(
            {
                "expected_version": 2,
                "reviewer_ref": "ROLE_00000000-0000-4000-8000-000000000001",
                "consent": consent,
            },
            strict=True,
        )


def test_share_consent_accepts_explicit_boolean_true() -> None:
    request = ShareEducationReviewRequest.model_validate(
        {
            "expected_version": 2,
            "reviewer_ref": "ROLE_00000000-0000-4000-8000-000000000001",
            "consent": True,
        },
        strict=True,
    )
    assert request.consent is True
