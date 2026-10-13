"""Strict, allowlisted L1 DTOs for the private school research CAT routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

StopReason = Literal[
    "se_threshold_reached",
    "max_items_reached",
    "item_bank_exhausted",
    "item_bank_exhausted_before_minimum",
]
SessionStatus = Literal["IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyResearchRequest(_StrictModel):
    """An optional empty request body; unknown fields are never ignored."""


class ResearchAnswerRequest(_StrictModel):
    item_id: StrictStr = Field(min_length=1, max_length=128)
    raw_value: StrictInt
    expected_state_version: StrictInt = Field(gt=0)


class ResearchResponseOptionDto(_StrictModel):
    value: StrictInt
    label: StrictStr | None


class ResearchQuestionDto(_StrictModel):
    item_id: StrictStr
    stem: StrictStr
    step: StrictInt = Field(ge=0)
    response_options: list[ResearchResponseOptionDto] = Field(min_length=1, max_length=20)


class ResearchCompletionDto(_StrictModel):
    status: Literal["COMPLETED"]
    items_answered: StrictInt = Field(ge=0)
    stop_reason: StopReason


class ResearchL1SessionDto(_StrictModel):
    """Public lifecycle/question projection; no scores, answers, or signed state."""

    session_ref: StrictStr
    status: SessionStatus
    state_version: StrictInt = Field(ge=1)
    items_answered: StrictInt = Field(ge=0)
    research_only: Literal[True] = True
    resume_required: StrictBool
    stop_reason: StopReason | None
    question: ResearchQuestionDto | None
    completion: ResearchCompletionDto | None
