"""Backend trust primitives for the isolated research CAT lane.

This package intentionally does not implement routes, CAT math, database
access, or research-task authorization.
"""

from smhai_backend.domains.school_research.trust import (
    HmacSha256SnapshotAuthenticator,
    ParameterOrigin,
    PublicationStatusProjection,
    ResearchProfileRegistry,
    ResearchProfileRegistryEntry,
    ResearchProfileTrustError,
    TrustedResearchProfile,
)

__all__ = [
    "HmacSha256SnapshotAuthenticator",
    "ParameterOrigin",
    "PublicationStatusProjection",
    "ResearchProfileRegistry",
    "ResearchProfileRegistryEntry",
    "ResearchProfileTrustError",
    "TrustedResearchProfile",
]
