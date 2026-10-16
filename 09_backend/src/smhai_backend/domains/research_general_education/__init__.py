"""Held-only task-bound general education research generation."""

from .schemas import (
    ResearchGeneralEducationCandidatePayload,
    ResearchGeneralEducationOutcome,
    ResearchGeneralEducationProvenance,
    ResearchGeneralEducationSourceCard,
    ResearchGeneralEducationStatus,
)


def __getattr__(name: str):
    if name == "ResearchGeneralEducationDraftService":
        from .service import ResearchGeneralEducationDraftService

        return ResearchGeneralEducationDraftService
    raise AttributeError(name)

__all__ = [
    "ResearchGeneralEducationCandidatePayload",
    "ResearchGeneralEducationDraftService",
    "ResearchGeneralEducationOutcome",
    "ResearchGeneralEducationProvenance",
    "ResearchGeneralEducationSourceCard",
    "ResearchGeneralEducationStatus",
]
