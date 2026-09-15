"""Stable, redacted errors for Prompt assembly."""

from __future__ import annotations

import re

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def safe_identifier(value: object) -> str | None:
    """Return an identifier safe to include in an error/audit projection."""

    if isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value):
        return value
    return None


class PromptRefusal(ValueError):
    """A fail-closed refusal whose message never includes input content."""

    def __init__(
        self,
        reason_code: str,
        *,
        request_id: object = None,
        trace_id: object = None,
    ) -> None:
        self.reason_code = reason_code
        self.code = reason_code
        self.request_id = safe_identifier(request_id)
        self.trace_id = safe_identifier(trace_id)
        identifiers = []
        if self.request_id is not None:
            identifiers.append(f"request_id={self.request_id}")
        if self.trace_id is not None:
            identifiers.append(f"trace_id={self.trace_id}")
        suffix = f" [{', '.join(identifiers)}]" if identifiers else ""
        super().__init__(f"{reason_code}{suffix}")


def refusal(
    reason_code: str,
    context: object = None,
) -> PromptRefusal:
    """Create a refusal using only validated, safe context identifiers."""

    if isinstance(context, dict):
        return PromptRefusal(
            reason_code,
            request_id=context.get("request_id"),
            trace_id=context.get("trace_id"),
        )
    return PromptRefusal(reason_code)
