"""Held-only generation for staff school-programme research references."""

from .schemas import (
    ResearchProgrammeCandidate,
    ResearchProgrammeCitation,
    ResearchProgrammeOutcome,
)
from .service import ResearchProgrammeGenerationService

__all__ = [
    "ResearchProgrammeCandidate",
    "ResearchProgrammeCitation",
    "ResearchProgrammeGenerationService",
    "ResearchProgrammeOutcome",
]
