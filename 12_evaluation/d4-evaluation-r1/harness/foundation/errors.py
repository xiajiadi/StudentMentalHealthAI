"""Typed failures for D4 foundation checks.

These exceptions are intentionally small and stable so a caller can turn a
foundation failure into machine evidence without parsing a human message.
"""

from __future__ import annotations


class D4FoundationError(ValueError):
    """Base class for deterministic D4 foundation failures."""


class HashIntegrityError(D4FoundationError):
    """A canonical or self-reported hash is invalid."""


class RunIdError(D4FoundationError):
    """A run ID is missing, malformed, or was changed after assignment."""


class ManifestError(D4FoundationError):
    """A run manifest is incomplete, unsafe, or internally inconsistent."""


class SplitIntegrityError(D4FoundationError):
    """Dataset split or family partitioning is invalid."""


class FixtureModeError(D4FoundationError):
    """Fixture modes were mixed, pooled, or mapped incorrectly."""


class SealedMutationError(D4FoundationError):
    """A sealed dataset or protected evaluation input changed."""


class ArtifactPathError(D4FoundationError):
    """An artifact path escapes its declared root or is otherwise unsafe."""
