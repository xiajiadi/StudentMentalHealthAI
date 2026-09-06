"""Explicit review state separate from parser and quality state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..domain.chunk import KnowledgeChunk

ReviewDecision = Literal["pending_review", "approved", "rejected"]


@dataclass(frozen=True)
class ReviewGate:
    allow_test_auto_approve: bool = False

    def decision_for(self, chunk: KnowledgeChunk) -> ReviewDecision:
        status = str(chunk.metadata.get("review_status", "pending"))
        if status == "approved":
            return "approved"
        if status == "rejected":
            return "rejected"
        return "pending_review"

    def is_publishable(self, chunk: KnowledgeChunk, *, quality_status: str) -> bool:
        return (
            self.decision_for(chunk) == "approved"
            and chunk.metadata.get("rights_status") == "verified"
            and quality_status in {"PASS", "WARN"}
        )

    def to_record(self, chunk: KnowledgeChunk, *, quality_status: str) -> dict[str, object]:
        decision = self.decision_for(chunk)
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "review_status": decision,
            "rights_status": chunk.metadata.get("rights_status"),
            "quality_status": quality_status,
            "publishable": self.is_publishable(chunk, quality_status=quality_status),
        }

