"""Closed public projections for the pinned research source catalog."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class ResearchSourceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchSourcePackageReviewDto(ResearchSourceOutput):
    """Engineering review metadata; it explicitly carries no professional approval."""

    package_status: Literal["ENGINEERING_REVIEWED_RESEARCH_ONLY"]
    reviewer_kind: Literal["AI_ENGINEERING"]
    review_status: Literal["pending"]
    professional_approval: Literal[False]
    ethics_approval: Literal[False]
    clinical_approval: Literal[False]
    psychometric_approval: Literal[False]
    publication_eligible: Literal[False]
    production_use: Literal[False]


class ResearchSourceSummaryDto(ResearchSourceOutput):
    source_ref: StrictStr = Field(min_length=1, max_length=128)
    title: StrictStr = Field(min_length=1, max_length=512)
    organization: StrictStr = Field(min_length=1, max_length=256)
    publication_date: StrictStr = Field(min_length=1, max_length=32)
    canonical_url: StrictStr = Field(min_length=1, max_length=2048)
    source_population_scope: StrictStr = Field(min_length=1, max_length=512)
    source_language: Literal["English"]
    layers: list[Literal["policy", "theory", "intervention"]] = Field(max_length=3)
    rights_status: Literal["VERIFIED_WITH_CONDITIONS", "PENDING"]
    retrieval_eligible: StrictBool


class ResearchSourceDetailDto(ResearchSourceSummaryDto):
    license: StrictStr = Field(min_length=1, max_length=256)
    license_url: StrictStr = Field(min_length=1, max_length=2048)
    attribution: StrictStr = Field(min_length=1, max_length=2048)
    rights_evidence_url: StrictStr = Field(min_length=1, max_length=2048)
    rights_evidence_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    rights_scope_note: StrictStr = Field(min_length=1, max_length=1024)
    source_capture_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    review: ResearchSourcePackageReviewDto


class ResearchSourceCatalogPageDto(ResearchSourceOutput):
    schema_version: Literal["school.research-source-catalog.v1"]
    source_package_ref: StrictStr = Field(min_length=1, max_length=128)
    manifest_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    study_ref: StrictStr = Field(min_length=1, max_length=128)
    consumer_age_min: StrictInt = Field(ge=13, le=18)
    consumer_age_max: StrictInt = Field(ge=13, le=18)
    review: ResearchSourcePackageReviewDto
    items: list[ResearchSourceSummaryDto] = Field(max_length=50)
    total: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=50)
    offset: StrictInt = Field(ge=0, le=10_000)
    has_more: StrictBool
