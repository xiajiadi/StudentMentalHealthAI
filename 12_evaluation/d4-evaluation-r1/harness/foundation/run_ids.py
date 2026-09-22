"""Immutable D4 run ID policy."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .errors import RunIdError

# The suffix is deliberately opaque.  It contains no subject, case, provider,
# or path information and therefore cannot be used to infer identity.
# The schema intentionally leaves the suffix opaque.  The generator below
# emits a timestamped form, while readers accept any safe schema-shaped ID so
# controller-issued IDs remain valid and immutable.
RUN_ID_PATTERN = re.compile(r"^D4RUN-[A-Za-z0-9][A-Za-z0-9._-]*$")
RUN_ID_PREFIX = "D4RUN-"


def _utc_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if value.tzinfo is None:
        raise RunIdError("run ID timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def create_run_id(
    *,
    timestamp: datetime | None = None,
    entropy: str | bytes | None = None,
) -> str:
    """Create a new opaque, machine-readable D4 run ID.

    Supplying *entropy* makes test IDs reproducible for a fixed timestamp.  A
    random value is used by default so two runs in the same second do not
    collide.
    """

    stamp = _utc_timestamp(timestamp)
    if entropy is None:
        entropy_bytes = secrets.token_bytes(32)
    elif isinstance(entropy, str):
        entropy_bytes = entropy.encode("utf-8")
    elif isinstance(entropy, bytes):
        entropy_bytes = entropy
    else:
        raise TypeError("entropy must be str, bytes, or None")
    digest = hashlib.sha256(
        stamp.strftime("%Y%m%dT%H%M%SZ").encode("ascii") + b"\x00" + entropy_bytes
    ).hexdigest()[:12]
    return f"{RUN_ID_PREFIX}{stamp:%Y%m%dT%H%M%SZ}-{digest}"


def validate_run_id(run_id: str) -> str:
    """Validate and return a run ID."""

    if (
        not isinstance(run_id, str)
        or len(run_id) < 8
        or not RUN_ID_PATTERN.fullmatch(run_id)
    ):
        raise RunIdError(
            "run_id must match D4RUN- followed by a safe non-empty identifier"
        )
    return run_id


@dataclass(frozen=True)
class ImmutableRunId:
    """A one-assignment run ID holder.

    A manifest writer should keep this object for the life of a run.  Calling
    :meth:`assign` with a different value is always an error, including after
    :meth:`freeze`; reusing the same value is idempotent.
    """

    value: str
    frozen: bool = True

    def __post_init__(self) -> None:
        validate_run_id(self.value)

    @classmethod
    def create(
        cls,
        *,
        timestamp: datetime | None = None,
        entropy: str | bytes | None = None,
    ) -> "ImmutableRunId":
        return cls(create_run_id(timestamp=timestamp, entropy=entropy))

    def assert_unchanged(self, candidate: str) -> str:
        validate_run_id(candidate)
        if candidate != self.value:
            raise RunIdError(
                f"immutable run_id changed from {self.value} to {candidate}"
            )
        return self.value

    def assign(self, candidate: str | None = None) -> str:
        """Validate an optional candidate and return the held ID."""

        if candidate is None:
            return self.value
        return self.assert_unchanged(candidate)


def assert_immutable_run_id(existing: str, candidate: str) -> str:
    """Small functional form used by manifest persistence code."""

    validate_run_id(existing)
    validate_run_id(candidate)
    if existing != candidate:
        raise RunIdError(
            f"immutable run_id changed from {existing} to {candidate}"
        )
    return existing


def run_id_from_manifest(manifest: dict[str, Any]) -> ImmutableRunId:
    """Build an immutable holder from a manifest mapping."""

    value = manifest.get("run_id")
    if not isinstance(value, str):
        raise RunIdError("manifest has no run_id")
    return ImmutableRunId(value)
