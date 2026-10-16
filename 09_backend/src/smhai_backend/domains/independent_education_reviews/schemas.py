"""Closed DTOs for encrypted, per-candidate research education release."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationSourceCard,
)
from smhai_backend.domains.support.schemas import GenerationContent, SupportCitation

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_REF = re.compile(r"^EDUREV_[0-9a-f]{32}$")
_REVIEWER_REF = re.compile(r"^ROLE_[0-9a-f-]{36}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class IndependentEducationReviewProvenance(_StrictModel):
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    source_study_ref: StrictStr = Field(min_length=1, max_length=128)
    source_package_ref: StrictStr = Field(min_length=1, max_length=128)
    source_manifest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    retrieval_id: StrictStr = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    retrieval_bundle_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    generation_id: StrictStr = Field(pattern=r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    prompt_id: StrictStr = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    prompt_version: StrictStr = Field(min_length=1, max_length=64)
    prompt_sha256: StrictStr | None
    model_id: StrictStr = Field(min_length=1, max_length=128)
    logical_model_id: StrictStr = Field(min_length=1, max_length=128)
    model_version: StrictStr = Field(min_length=1, max_length=128)
    model_digest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    runtime_version: StrictStr = Field(min_length=1, max_length=64)
    trace_id: StrictStr = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    input_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    input_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    input_safety_requires_human: Literal[False]
    retrieval_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    retrieval_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    retrieval_safety_requires_human: Literal[False]
    output_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    output_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    output_safety_requires_human: Literal[False]
    claim_boundary_status: Literal["ACCEPTED"]
    citation_binding_status: Literal["BOUND"]

    @field_validator("prompt_sha256")
    @classmethod
    def validate_optional_prompt_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("prompt hash is invalid")
        return value

    @field_validator(
        "input_safety_reason_codes", "retrieval_safety_reason_codes", "output_safety_reason_codes"
    )
    @classmethod
    def validate_reason_codes(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(
            _REASON.fullmatch(value) is None for value in values
        ):
            raise ValueError("Safety reason codes are invalid")
        return values


class IndependentEducationCandidatePayload(_StrictModel):
    schema_version: Literal["independent-research-education-candidate.v1"]
    content: GenerationContent
    citations: list[SupportCitation] = Field(min_length=1, max_length=8)
    source_cards: list[ResearchGeneralEducationSourceCard] = Field(min_length=1, max_length=8)
    provenance: IndependentEducationReviewProvenance

    @field_validator("citations", mode="before")
    @classmethod
    def citations_are_closed(cls, value: object) -> object:
        allowed = set(SupportCitation.model_fields)
        if not isinstance(value, list) or any(
            not (
                isinstance(item, SupportCitation)
                or (isinstance(item, dict) and not (set(item) - allowed))
            )
            for item in value
        ):
            raise ValueError("citations must use the closed SupportCitation fields")
        return value

    @field_validator("source_cards", mode="before")
    @classmethod
    def source_cards_are_closed(cls, value: object) -> object:
        if not isinstance(value, list) or any(
            not (
                isinstance(item, ResearchGeneralEducationSourceCard)
                or isinstance(item, dict)
            )
            for item in value
        ):
            raise ValueError("source cards are invalid")
        return value

    def model_post_init(self, __context: object) -> None:
        citation_ids = [item.chunk_id for item in self.citations]
        card_ids = [item.chunk_id for item in self.source_cards]
        if (
            any(value is None for value in citation_ids)
            or len(set(citation_ids)) != len(citation_ids)
            or len(set(card_ids)) != len(card_ids)
            or set(citation_ids) != set(card_ids)
        ):
            raise ValueError("candidate citations and source cards do not bind exactly")
        for citation, card in zip(self.citations, self.source_cards, strict=True):
            suffix = (
                f"; source population: {card.source_population_scope}; "
                f"source: {card.canonical_url}; license: {card.license} "
                f"({card.license_url}); attribution: {card.attribution}"
            )
            if (
                citation.chunk_id != card.chunk_id
                or citation.title != card.title
                or citation.organization != card.organization
                or citation.source_hash != f"sha256:{card.excerpt_sha256}"
                or citation.locator
                not in {
                    f"{card.record_locator}{suffix}",
                    f"record: {card.record_id}{suffix}",
                }
                or (card.consumer_age_min, card.consumer_age_max) != (14, 17)
            ):
                raise ValueError("candidate citation does not match its source card")


class IndependentEducationCandidateProvenanceDto(_StrictModel):
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    source_study_ref: StrictStr = Field(min_length=1, max_length=128)
    source_package_ref: StrictStr = Field(min_length=1, max_length=128)
    source_manifest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    retrieval_id: StrictStr = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    retrieval_bundle_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    prompt_id: StrictStr = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    prompt_version: StrictStr = Field(min_length=1, max_length=64)
    prompt_sha256: StrictStr | None
    model_id: StrictStr = Field(min_length=1, max_length=128)
    logical_model_id: StrictStr = Field(min_length=1, max_length=128)
    model_version: StrictStr = Field(min_length=1, max_length=128)
    model_digest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    runtime_version: StrictStr = Field(min_length=1, max_length=64)
    trace_id: StrictStr = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    input_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    input_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    retrieval_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    retrieval_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    output_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    output_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    claim_boundary_status: Literal["ACCEPTED"]
    citation_binding_status: Literal["BOUND"]


class IndependentEducationCandidateProjection(_StrictModel):
    schema_version: Literal["independent-research-education-candidate.v1"]
    content: GenerationContent
    citations: list[SupportCitation] = Field(min_length=1, max_length=8)
    source_cards: list[ResearchGeneralEducationSourceCard] = Field(min_length=1, max_length=8)
    provenance: IndependentEducationCandidateProvenanceDto

    @field_validator("citations", mode="before")
    @classmethod
    def public_citations_are_closed(cls, value: object) -> object:
        allowed = set(SupportCitation.model_fields)
        if not isinstance(value, list) or any(
            not isinstance(item, dict) or set(item) - allowed for item in value
        ):
            raise ValueError("citations must use the closed SupportCitation fields")
        return value

    def model_post_init(self, __context: object) -> None:
        if (
            len({item.chunk_id for item in self.citations}) != len(self.citations)
            or any(item.chunk_id is None for item in self.citations)
            or {item.chunk_id for item in self.citations}
            != {item.chunk_id for item in self.source_cards}
        ):
            raise ValueError("public candidate citations and source cards do not bind")


class IndependentEducationPublishSafetyCheck(_StrictModel):
    operation: Literal["OUTPUT"]
    action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    requires_human: Literal[False]
    decision_id: StrictStr | None = Field(default=None, min_length=5, max_length=160)
    trace_id: StrictStr = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    checked_material_sha256: StrictStr = Field(pattern=_SHA256.pattern)

    @field_validator("reason_codes")
    @classmethod
    def publish_reason_codes_are_closed(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(
            _REASON.fullmatch(value) is None for value in values
        ):
            raise ValueError("Safety reason codes are invalid")
        return values


class IndependentEducationDraftPayload(_StrictModel):
    schema_version: Literal["independent-research-education-reviewed-draft.v1"]
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=4000)
    citations: list[SupportCitation] = Field(min_length=1, max_length=8)
    source_cards: list[ResearchGeneralEducationSourceCard] = Field(min_length=1, max_length=8)
    candidate_content_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    source_manifest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    publish_safety_check: IndependentEducationPublishSafetyCheck | None = None


class IndependentEducationReviewedDraftDto(_StrictModel):
    title: StrictStr
    body: StrictStr
    content_revision: StrictInt = Field(ge=1)
    citations: list[SupportCitation]
    source_cards: list[ResearchGeneralEducationSourceCard]
    updated_at: datetime


class IndependentEducationPublishedContentDto(_StrictModel):
    title: StrictStr
    body: StrictStr
    citations: list[SupportCitation]
    source_cards: list[ResearchGeneralEducationSourceCard]
    published_at: datetime


class IndependentEducationReviewSummaryDto(_StrictModel):
    review_ref: StrictStr = Field(pattern=_REVIEW_REF.pattern)
    status: Literal["HELD", "SHARED", "DRAFT", "PUBLISHED", "REVOKED", "WITHDRAWN"]
    state_version: StrictInt = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    reviewer_ref: StrictStr | None = Field(default=None, pattern=_REVIEWER_REF.pattern)
    published_content: IndependentEducationPublishedContentDto | None = None


class IndependentEducationReviewPageDto(_StrictModel):
    items: list[IndependentEducationReviewSummaryDto]
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=50)
    total: StrictInt = Field(ge=0)
    has_more: StrictBool

    @model_validator(mode="after")
    def page_is_consistent(self):
        if (
            len(self.items) > self.limit
            or len({item.review_ref for item in self.items}) != len(self.items)
            or self.has_more != (self.offset + len(self.items) < self.total)
        ):
            raise ValueError("education review page is inconsistent")
        return self


class IndependentEducationReviewerDto(_StrictModel):
    reviewer_ref: StrictStr = Field(pattern=_REVIEWER_REF.pattern)
    display_name: StrictStr = Field(min_length=1, max_length=120)


class IndependentEducationReviewerListDto(_StrictModel):
    items: list[IndependentEducationReviewerDto]
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=50)
    total: StrictInt = Field(ge=0)
    has_more: StrictBool

    @model_validator(mode="after")
    def page_is_consistent(self):
        refs = [item.reviewer_ref for item in self.items]
        if (
            len(self.items) > self.limit
            or len(set(refs)) != len(refs)
            or self.has_more != (self.offset + len(self.items) < self.total)
        ):
            raise ValueError("reviewer page is inconsistent")
        return self


class IndependentEducationStaffSummaryDto(_StrictModel):
    review_ref: StrictStr = Field(pattern=_REVIEW_REF.pattern)
    status: Literal["SHARED", "DRAFT", "PUBLISHED"]
    state_version: StrictInt = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class IndependentEducationStaffPageDto(_StrictModel):
    items: list[IndependentEducationStaffSummaryDto]
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=50)
    total: StrictInt = Field(ge=0)
    has_more: StrictBool

    @model_validator(mode="after")
    def page_is_consistent(self):
        if (
            len(self.items) > self.limit
            or len({item.review_ref for item in self.items}) != len(self.items)
            or self.has_more != (self.offset + len(self.items) < self.total)
        ):
            raise ValueError("assigned education review page is inconsistent")
        return self


class IndependentEducationStaffDetailDto(_StrictModel):
    review_ref: StrictStr = Field(pattern=_REVIEW_REF.pattern)
    status: Literal["SHARED", "DRAFT", "PUBLISHED"]
    state_version: StrictInt = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    shared_at: datetime
    candidate: IndependentEducationCandidateProjection
    reviewed_draft: IndependentEducationReviewedDraftDto | None = None


def publish_material_sha256(candidate: object, draft: object) -> str:
    candidate_projection = IndependentEducationCandidateProjection.model_validate(
        candidate, strict=True
    )
    draft_value = dict(draft) if isinstance(draft, dict) else draft
    if isinstance(draft_value, dict) and isinstance(draft_value.get("updated_at"), str):
        try:
            timestamp = draft_value["updated_at"]
            draft_value["updated_at"] = datetime.fromisoformat(
                timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
            )
        except ValueError as exc:
            raise ValueError("reviewed draft timestamp is invalid") from exc
    reviewed_draft = IndependentEducationReviewedDraftDto.model_validate(
        draft_value, strict=True
    )
    payload = {
        "candidate": candidate_projection.model_dump(mode="json"),
        "reviewed_draft": reviewed_draft.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ShareEducationReviewRequest(_StrictModel):
    expected_version: StrictInt = Field(ge=1)
    reviewer_ref: StrictStr = Field(pattern=_REVIEWER_REF.pattern)
    consent: Literal[True]


class EducationReviewStateRequest(_StrictModel):
    expected_version: StrictInt = Field(ge=1)


class SaveEducationReviewDraftRequest(_StrictModel):
    expected_version: StrictInt = Field(ge=1)
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("title", "body")
    @classmethod
    def text_is_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value
