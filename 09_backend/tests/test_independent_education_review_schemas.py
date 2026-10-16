from __future__ import annotations

from smhai_backend.domains.independent_education_reviews.schemas import (
    IndependentEducationCandidateProvenanceDto,
    IndependentEducationReviewedDraftDto,
    IndependentEducationReviewerListDto,
    IndependentEducationStaffSummaryDto,
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
