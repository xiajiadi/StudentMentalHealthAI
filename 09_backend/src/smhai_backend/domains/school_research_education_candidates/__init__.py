"""Task-bound research education candidate API."""

from .router import router
from .service import SchoolResearchEducationCandidateService

__all__ = ["SchoolResearchEducationCandidateService", "router"]
