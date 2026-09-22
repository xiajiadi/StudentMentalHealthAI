"""Canonical JSON and SHA-256 helpers for D4 evidence.

The canonical form is deliberately narrow and explicit:

* UTF-8 encoded JSON;
* Unicode preserved (``ensure_ascii=False``);
* recursively sorted object keys;
* stable compact separators (`,`, ``:``);
* non-finite floats rejected;
* list order retained;
* only explicitly named top-level self fields excluded from a hash.

Hashing never mutates the supplied object.  A self field is excluded at the
object being hashed rather than recursively, because nested ``hash`` fields
are data belonging to their own object.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence

from .errors import HashIntegrityError

SHA256_HEX_LENGTH = 64
SHA256_TAG_PREFIX = "sha256:"


def _normalise_excluded_fields(
    exclude_fields: Iterable[str] | None,
    *,
    self_field: str | None = None,
) -> frozenset[str]:
    fields = set(exclude_fields or ())
    if self_field is not None:
        fields.add(self_field)
    if any(not isinstance(field, str) or not field for field in fields):
        raise TypeError("exclude_fields must contain non-empty strings")
    return frozenset(fields)


def _without_top_level_fields(value: Any, fields: frozenset[str]) -> Any:
    if not fields:
        return value
    if not isinstance(value, Mapping):
        return value
    # Deep-copy only when an exclusion is requested.  This also prevents a
    # custom Mapping or nested mutable object from being modified by hashing.
    copied = deepcopy(dict(value))
    for field in fields:
        copied.pop(field, None)
    return copied


def canonical_json_bytes(
    value: Any,
    *,
    exclude_fields: Iterable[str] | None = None,
    self_field: str | None = None,
) -> bytes:
    """Serialize *value* into the D4 canonical JSON byte representation."""

    fields = _normalise_excluded_fields(exclude_fields, self_field=self_field)
    prepared = _without_top_level_fields(value, fields)
    try:
        text = json.dumps(
            prepared,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise HashIntegrityError(f"value cannot be canonically encoded: {exc}") from exc
    return text.encode("utf-8")


def canonical_json(
    value: Any,
    *,
    exclude_fields: Iterable[str] | None = None,
    self_field: str | None = None,
) -> str:
    """Return canonical JSON text, useful for audit/debug output."""

    return canonical_json_bytes(
        value, exclude_fields=exclude_fields, self_field=self_field
    ).decode("utf-8")


def sha256_hex(data: bytes | bytearray | memoryview | str) -> str:
    """Hash bytes or UTF-8 text and return lowercase hexadecimal SHA-256."""

    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        return hashlib.sha256(bytes(data)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise HashIntegrityError(f"value cannot be SHA-256 hashed: {exc}") from exc


def canonical_sha256(
    value: Any,
    *,
    exclude_fields: Iterable[str] | None = None,
    self_field: str | None = None,
) -> str:
    """Return lowercase SHA-256 of canonical JSON for *value*."""

    return sha256_hex(
        canonical_json_bytes(
            value, exclude_fields=exclude_fields, self_field=self_field
        )
    )


def canonical_sha256_tag(
    value: Any,
    *,
    exclude_fields: Iterable[str] | None = None,
    self_field: str | None = None,
) -> str:
    """Return a schema-friendly ``sha256:<hex>`` value."""

    return SHA256_TAG_PREFIX + canonical_sha256(
        value, exclude_fields=exclude_fields, self_field=self_field
    )


def validate_sha256_hex(value: str, *, allow_tag: bool = False) -> str:
    """Validate and return a lowercase SHA-256 value."""

    if not isinstance(value, str):
        raise HashIntegrityError(f"invalid SHA-256 value: {value!r}")
    candidate = value
    if allow_tag and candidate.startswith(SHA256_TAG_PREFIX):
        candidate = candidate[len(SHA256_TAG_PREFIX) :]
    if (
        not isinstance(candidate, str)
        or len(candidate) != SHA256_HEX_LENGTH
        or any(char not in "0123456789abcdef" for char in candidate)
    ):
        raise HashIntegrityError(f"invalid SHA-256 value: {value!r}")
    return candidate


def verify_self_hash(
    value: Mapping[str, Any],
    *,
    field: str = "hash",
    tagged: bool = True,
) -> bool:
    """Verify an object's self hash without changing the object.

    The object's self field is excluded from the canonical input.  Both
    ``sha256:<hex>`` and bare hexadecimal values are accepted according to
    *tagged*.
    """

    if field not in value or not isinstance(value[field], str):
        raise HashIntegrityError(f"missing self hash field: {field}")
    reported = value[field]
    expected = canonical_sha256(value, self_field=field)
    if tagged:
        expected = SHA256_TAG_PREFIX + expected
        valid_reported = reported == expected
    else:
        valid_reported = reported == expected
    if not valid_reported:
        raise HashIntegrityError(
            f"self hash mismatch for {field}: expected {expected}, got {reported}"
        )
    return True


def canonical_dataset_hash(
    records: Sequence[Mapping[str, Any]],
    *,
    self_field: str = "hash",
) -> str:
    """Hash a dataset independently of filesystem order and self hashes.

    Records are sorted by ``case_id``.  Duplicate or missing case IDs are
    rejected because silently selecting an order would make a dataset hash
    ambiguous.  The returned value is bare lowercase hexadecimal.
    """

    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise HashIntegrityError("dataset records must be JSON objects")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise HashIntegrityError("dataset records require a non-empty case_id")
        if case_id in seen:
            raise HashIntegrityError(f"duplicate case_id in dataset: {case_id}")
        seen.add(case_id)
        clean_record = dict(record)
        clean_record.pop(self_field, None)
        prepared.append(clean_record)
    prepared.sort(key=lambda item: item["case_id"])
    return canonical_sha256({"cases": prepared}, self_field=None)


# Friendly aliases used by small wrappers and external test harnesses.
canonical_hash = canonical_sha256
canonical_hash_tag = canonical_sha256_tag
canonical_json_hash = canonical_sha256
canonical_json_sha256 = canonical_sha256
hash_canonical_json = canonical_sha256
hash_json = canonical_sha256
