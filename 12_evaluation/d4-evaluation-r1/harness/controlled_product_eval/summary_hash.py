"""Round-trip-stable canonical hashing for D4-3B run summaries."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


def _json_normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str):
                normalized_key = key
            elif isinstance(key, int) and not isinstance(key, bool):
                normalized_key = str(key)
            else:
                raise TypeError("summary object keys must be strings or integers")
            if normalized_key in normalized:
                raise ValueError("summary keys collide after JSON key normalization")
            normalized[normalized_key] = _json_normalize(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_normalize(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError("summary contains a value that is not safe JSON")


def canonical_summary_json(summary: Mapping[str, Any]) -> str:
    """Serialize JSON-normalized keys using the single D4-3B hash format."""

    normalized = _json_normalize(summary)
    if not isinstance(normalized, dict):
        raise TypeError("summary must be a JSON object")
    normalized.pop("run_summary_hash", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_summary_hash(summary: Mapping[str, Any]) -> str:
    payload = canonical_summary_json(summary).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
