"""Strict request and candidate-only response DTOs for research profiles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


class ResearchProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchProfileImportRequest(ResearchProfileRequest):
    profile_ref: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    version_number: StrictInt = Field(ge=1, le=2_147_483_647)


class ResearchProfileSimulationEligibilityRequest(ResearchProfileImportRequest):
    """Closed request; rights, hashes, policy, and approvals stay server-owned."""


class ResearchProfileOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetime_to_utc(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class ResearchProfileCandidateDto(ResearchProfileOutput):
    profile_ref: StrictStr = Field(min_length=1, max_length=128)
    version_number: StrictInt | None = Field(ge=1, le=2_147_483_647)
    source_population_scope: StrictStr | None = Field(default=None, max_length=64)
    instrument_id: StrictStr = Field(min_length=1, max_length=128)
    research_only: Literal[True]
    publication_status: Literal["not_approved_for_publication_or_operational_use"]
    rights_status: StrictStr = Field(min_length=1, max_length=32)
    execution_status: StrictStr = Field(min_length=1, max_length=32)
    created_at: datetime | None = None
    catalog_state: Literal[
        "REGISTRY_CANDIDATE",
        "IMPORTED_CANDIDATE",
        "EXISTING_CANDIDATE",
        "IDEMPOTENT_REPLAY",
    ]


class ResearchProfileVersionDto(ResearchProfileOutput):
    """Safe database registration metadata; it is not a live use authorization."""

    profile_ref: StrictStr = Field(min_length=1, max_length=128)
    version_number: StrictInt = Field(ge=1, le=2_147_483_647)
    source_population_scope: StrictStr = Field(min_length=1, max_length=64)
    instrument_id: StrictStr = Field(min_length=1, max_length=128)
    research_only: Literal[True]
    publication_status: Literal["not_approved_for_publication_or_operational_use"]
    rights_status: Literal["PENDING", "VERIFIED", "REVOKED"]
    execution_status: Literal[
        "CANDIDATE_RESEARCH_ONLY", "SIMULATION_ENABLED", "DISABLED"
    ]
    created_at: datetime
    use_eligibility: Literal["RECHECK_REQUIRED"] = Field(
        description=(
            "Persisted registration status only. Policy and current eligibility must be "
            "rechecked before each use; SIMULATION_ENABLED alone does not authorize use."
        )
    )


class ResearchProfileVersionPageDto(ResearchProfileOutput):
    items: list[ResearchProfileVersionDto] = Field(max_length=30)
    total: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=30)
    offset: StrictInt = Field(ge=0, le=10_000)
    has_more: bool
    next_offset: StrictInt | None = Field(ge=0)


class ResearchProfileSimulationEligibilityDto(ResearchProfileOutput):
    profile_ref: StrictStr = Field(min_length=1, max_length=128)
    version_number: StrictInt = Field(ge=1, le=2_147_483_647)
    research_only: Literal[True]
    human_curated: Literal[False]
    publication_status: Literal["not_approved_for_publication_or_operational_use"]
    rights_status: Literal["VERIFIED"]
    execution_status: Literal["SIMULATION_ENABLED"]
    simulation_only: Literal[True]
    clinical_approval: Literal[False]
    ethics_approval: Literal[False]
    psychometric_approval: Literal[False]
    study_ref: StrictStr = Field(min_length=1, max_length=128)
    policy_expires_at: datetime
    catalog_state: Literal["SIMULATION_ENABLED", "IDEMPOTENT_REPLAY"]
