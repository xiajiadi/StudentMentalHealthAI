"""Internal bounded metadata passed from Safety to the conversation persistence edge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True, repr=False)
class SafetyCaseSeed:
    action: Literal["REVIEW_REQUIRED", "CRISIS_ROUTE"]
    reason_codes: tuple[str, ...]
    review_reference: str | None
