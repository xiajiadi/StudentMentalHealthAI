"""Service-level result objects; raw input/output is intentionally absent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from safety_engine.domain import HumanReviewCase, SafetyDecision, SafetySignal, SafetyTrace


class SafetyCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["INPUT", "OUTPUT", "RETRIEVAL"]
    decision: SafetyDecision
    trace: SafetyTrace
    signals: list[SafetySignal] = Field(default_factory=list)
    sanitized_text: str | None = None
    crisis_response: str | None = None
    review_case: HumanReviewCase | None = None
    retrieval_findings: dict = Field(default_factory=dict)
    normal_llm_invoked: bool = False
