"""Private, pinned response-only corpora for server-side research replay.

This module loads a server-selected v3 complete-response artifact into immutable
memory. It deliberately exposes only a match predicate; callers cannot enumerate
rows or ask for the assigned expected value through the public API.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .trust import (
    PublicationStatusProjection,
    ResearchProfileTrustError,
    TrustedResearchProfile,
    _assert_no_reparse_components,
    _read_pinned_file,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMPLETE_RESPONSE_FILENAME = "complete_observed_800.csv"
_MAX_RESPONSE_BYTES = 256 * 1024
_EXPECTED_ROWS = 800
_EXPECTED_COLUMNS = 8
_RESPONSE_VALUES = frozenset({"1", "2", "3", "4", "5"})
_COMPLETE_FIELDS = frozenset(
    {
        "path",
        "sha256",
        "rows",
        "complete_source_rows",
        "not_selected_complete_rows",
        "seed",
        "sampling",
        "python_implementation",
        "python_version",
    }
)
_NUMERIC_FIELDS = frozenset(
    {"path", "sha256", "rows", "columns", "partial_rows_NA_retained", "category_counts"}
)


class ObservedCorpusError(ValueError):
    """Stable error code with no source rows, paths, or response values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"observed response corpus is unavailable: {code}")


@dataclass(frozen=True, slots=True)
class ObservedResponseCorpus:
    """Immutable in-memory cases; access is limited to an equality predicate."""

    profile_ref: str
    profile_sha256: str
    manifest_sha256: str
    response_csv_sha256: str
    row_count: int
    _column_by_item: Mapping[str, int] = field(repr=False, compare=False)
    _rows: tuple[tuple[int, ...], ...] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        rows = tuple(tuple(row) for row in self._rows)
        columns = dict(self._column_by_item)
        if (
            type(self.row_count) is not int
            or self.row_count != _EXPECTED_ROWS
            or len(rows) != self.row_count
            or len(columns) != _EXPECTED_COLUMNS
            or set(columns.values()) != set(range(_EXPECTED_COLUMNS))
            or any(
                type(value) is not int or value not in range(1, 6)
                for row in rows
                for value in row
            )
            or any(len(row) != _EXPECTED_COLUMNS for row in rows)
        ):
            raise ObservedCorpusError("corpus_projection_invalid")
        object.__setattr__(self, "_column_by_item", MappingProxyType(columns))
        object.__setattr__(self, "_rows", rows)

    def __repr__(self) -> str:
        return (
            "ObservedResponseCorpus("
            f"profile_ref={self.profile_ref!r}, row_count={self.row_count})"
        )

    def matches(self, case_index: int, item_id: str, raw_value: int) -> bool:
        """Return whether one submitted response matches the assigned case.

        Invalid indexes, item identifiers, and values all return False. This
        keeps the expected value and row lookup out of API errors and logs.
        """

        if (
            type(case_index) is not int
            or not 0 <= case_index < self.row_count
            or type(item_id) is not str
            or type(raw_value) is not int
        ):
            return False
        column = self._column_by_item.get(item_id)
        return column is not None and self._rows[case_index][column] == raw_value


def load_observed_response_corpus(
    trusted_profile: TrustedResearchProfile,
) -> ObservedResponseCorpus:
    """Load the server-pinned 800-row response-only file for one trusted v3 profile.

    ``trusted_profile`` must come from ``ResearchProfileRegistry.load`` using
    server-injected pins. The corpus directory comes only from that registry's
    pinned manifest path; the filename is fixed here and never selected by a
    request or by manifest data.
    """

    if (
        type(trusted_profile) is not TrustedResearchProfile
        or trusted_profile.profile_schema != "psynova.research-profile.v3"
        or trusted_profile.publication_status_projection
        is not PublicationStatusProjection.NOT_APPROVED
        or type(trusted_profile.profile_ref) is not str
        or not trusted_profile.profile_ref
        or type(trusted_profile.profile_sha256) is not str
        or type(trusted_profile.manifest_sha256) is not str
        or type(trusted_profile.raw_profile_bytes) is not bytes
        or type(trusted_profile.raw_manifest_bytes) is not bytes
        or not isinstance(trusted_profile.artifact_root, Path)
        or not trusted_profile.artifact_root.is_absolute()
    ):
        raise ObservedCorpusError("registry_pin_invalid")

    profile_bytes = trusted_profile.raw_profile_bytes
    manifest_bytes = trusted_profile.raw_manifest_bytes
    expected_profile_sha256 = trusted_profile.profile_sha256
    expected_manifest_sha256 = trusted_profile.manifest_sha256
    if (
        type(profile_bytes) is not bytes
        or type(manifest_bytes) is not bytes
        or not hmac.compare_digest(_sha256(profile_bytes), expected_profile_sha256)
        or not hmac.compare_digest(_sha256(manifest_bytes), expected_manifest_sha256)
        or not hmac.compare_digest(trusted_profile.profile_sha256, expected_profile_sha256)
        or not hmac.compare_digest(trusted_profile.manifest_sha256, expected_manifest_sha256)
    ):
        raise ObservedCorpusError("profile_pin_mismatch")

    try:
        _assert_no_reparse_components(trusted_profile.artifact_root)
        root = trusted_profile.artifact_root.resolve(strict=True)
        if not root.is_dir():
            raise ObservedCorpusError("source_root_invalid")
    except ObservedCorpusError:
        raise
    except (OSError, RuntimeError, ValueError, ResearchProfileTrustError):
        raise ObservedCorpusError("source_root_invalid") from None

    try:
        profile = _parse_object(profile_bytes)
        manifest = _parse_object(manifest_bytes)
        if (
            manifest.get("profile_sha256") != expected_profile_sha256
            or manifest.get("profile_json_sha256") != expected_profile_sha256
            or manifest.get("no_person_response_hashes_or_identifiers") is not True
            or manifest.get("no_scores_or_person_parameters") is not True
        ):
            raise ObservedCorpusError("manifest_profile_pin_invalid")
        columns_by_item, source_columns = _profile_item_columns(
            profile, trusted_profile.profile_ref
        )
        complete_pin = _complete_response_pin(
            manifest, profile, columns_by_item, source_columns
        )
        response_path = root / _COMPLETE_RESPONSE_FILENAME
        response_bytes = _read_pinned_file(
            response_path, root=root, limit=_MAX_RESPONSE_BYTES
        )
    except ObservedCorpusError:
        raise
    except (ResearchProfileTrustError, OSError, RuntimeError, ValueError):
        raise ObservedCorpusError("source_artifact_invalid") from None

    response_sha256 = _sha256(response_bytes)
    if not hmac.compare_digest(response_sha256, complete_pin):
        raise ObservedCorpusError("response_hash_mismatch")
    rows = _parse_response_csv(response_bytes, source_columns)
    return ObservedResponseCorpus(
        profile_ref=trusted_profile.profile_ref,
        profile_sha256=expected_profile_sha256,
        manifest_sha256=expected_manifest_sha256,
        response_csv_sha256=response_sha256,
        row_count=len(rows),
        _column_by_item=MappingProxyType(columns_by_item),
        _rows=rows,
    )


def _profile_item_columns(
    profile: dict[str, Any], profile_ref: str
) -> tuple[dict[str, int], tuple[str, ...]]:
    if (
        profile.get("schema") != "psynova.research-profile.v3"
        or profile.get("profile_id") != profile_ref
        or profile.get("profile_type") != "research_only_candidate"
        or profile.get("research_only") is not True
        or profile.get("publication_status") != "not_approved"
        or profile.get("human_curated") is not False
        or profile.get("psychological_interpretation_allowed") is not False
    ):
        raise ObservedCorpusError("profile_schema_invalid")
    items = profile.get("items")
    if type(items) is not list or len(items) != _EXPECTED_COLUMNS:
        raise ObservedCorpusError("profile_items_invalid")
    positions: dict[str, int] = {}
    source_columns: list[str] = []
    for position, item in enumerate(items):
        if type(item) is not dict:
            raise ObservedCorpusError("profile_items_invalid")
        item_id = item.get("item_id")
        source_column = item.get("source_column")
        if (
            type(item_id) is not str
            or not item_id
            or type(source_column) is not str
            or not source_column
            or item_id in positions
            or source_column in source_columns
        ):
            raise ObservedCorpusError("profile_items_invalid")
        positions[item_id] = position
        source_columns.append(source_column)
    return positions, tuple(source_columns)


def _complete_response_pin(
    manifest: dict[str, Any],
    profile: dict[str, Any],
    columns_by_item: dict[str, int],
    source_columns: tuple[str, ...],
) -> str:
    complete = manifest.get("complete_observed_800")
    numeric = manifest.get("numeric_response_csv")
    provenance = profile.get("provenance")
    items = profile.get("items")
    if (
        type(complete) is not dict
        or set(complete) != _COMPLETE_FIELDS
        or type(numeric) is not dict
        or set(numeric) != _NUMERIC_FIELDS
        or type(provenance) is not dict
        or type(items) is not list
    ):
        raise ObservedCorpusError("manifest_schema_invalid")
    digest = complete.get("sha256")
    if (
        complete.get("path") != _COMPLETE_RESPONSE_FILENAME
        or type(digest) is not str
        or _SHA256.fullmatch(digest) is None
        or type(complete.get("rows")) is not int
        or complete["rows"] != _EXPECTED_ROWS
        or type(complete.get("complete_source_rows")) is not int
        or complete["complete_source_rows"] < _EXPECTED_ROWS
        or type(complete.get("not_selected_complete_rows")) is not int
        or complete["not_selected_complete_rows"] < 0
        or type(complete.get("seed")) is not int
        or complete.get("not_selected_complete_rows")
        != complete.get("complete_source_rows") - _EXPECTED_ROWS
        or type(numeric.get("columns")) is not list
        or numeric["columns"] != list(source_columns)
        or len(columns_by_item) != _EXPECTED_COLUMNS
        or provenance.get("complete_observed_800_csv_sha256") != digest
    ):
        raise ObservedCorpusError("manifest_response_pin_invalid")
    return digest


def _parse_response_csv(
    content: bytes, source_columns: tuple[str, ...]
) -> tuple[tuple[int, ...], ...]:
    try:
        text = content.decode("utf-8", errors="strict")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader)
        if (
            len(header) != _EXPECTED_COLUMNS
            or len(set(header)) != _EXPECTED_COLUMNS
            or tuple(header) != source_columns
        ):
            raise ObservedCorpusError("response_columns_invalid")
        rows: list[tuple[int, ...]] = []
        for values in reader:
            if len(values) != _EXPECTED_COLUMNS or any(
                value not in _RESPONSE_VALUES for value in values
            ):
                raise ObservedCorpusError("response_rows_invalid")
            rows.append(tuple(int(value) for value in values))
            if len(rows) > _EXPECTED_ROWS:
                raise ObservedCorpusError("response_rows_invalid")
    except ObservedCorpusError:
        raise
    except (UnicodeDecodeError, csv.Error, StopIteration, ValueError):
        raise ObservedCorpusError("response_csv_invalid") from None
    if len(rows) != _EXPECTED_ROWS:
        raise ObservedCorpusError("response_rows_invalid")
    return tuple(rows)


def _parse_object(content: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    value = json.loads(
        content.decode("utf-8", errors="strict"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )
    if type(value) is not dict:
        raise ValueError("JSON document must be an object")
    return value


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
