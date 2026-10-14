"""Isolated, read-only research retrieval; never part of the production index."""

from .loader import (
    ResearchPackage,
    ResearchPackageError,
    ResearchRecord,
    ResearchSource,
    ResearchUsePolicy,
    load_research_package,
)
from .retrieval import (
    ResearchAccessDenied,
    ResearchHit,
    ResearchOnlyRetriever,
    ResearchRetrievalError,
    ResearchRetrievalResult,
)

__all__ = [
    "ResearchAccessDenied",
    "ResearchHit",
    "ResearchOnlyRetriever",
    "ResearchPackage",
    "ResearchPackageError",
    "ResearchRecord",
    "ResearchRetrievalError",
    "ResearchRetrievalResult",
    "ResearchSource",
    "ResearchUsePolicy",
    "load_research_package",
]
