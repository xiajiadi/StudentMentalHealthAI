"""Strict, server-injected trust primitives for research CAT profile artifacts.

Expected hashes and paths are supplied by trusted application wiring. This
module never treats a submitted profile, its manifest, or a calculated digest
as a trust root, and it does not import the CAT runtime or persistence layer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_FAMILY_RE = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
_SIGNATURE_RE = _SHA256_RE
_MAX_PROFILE_BYTES = 4 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_REPARSE_POINT = 0x400
_V3_SAMPLING_DESCRIPTION = (
    "without replacement; file contains only eight response columns, no row index or ID"
)
_V3_COVERAGE_SPLIT_NOTE = (
    "none; published item parameters are used as references and no local model is fit"
)
_V1_SOURCE_FAMILY_BY_INSTRUMENT = {
    "IPIP100_B5_E_EXTRAVERSION_20_RESEARCH": "SAPA_IPIP100",
}

_V1_PROFILE_FIELDS = frozenset(
    {
        "schema",
        "profile_id",
        "profile_type",
        "research_only",
        "publication_status",
        "psychological_interpretation_allowed",
        "dimension",
        "instrument_id",
        "response_scale",
        "scoring",
        "model",
        "source",
        "rights",
        "provenance",
        "items",
        "not_approved_for",
    }
)
_V2_PROFILE_FIELDS = frozenset(
    {
        "schema",
        "profile_id",
        "profile_type",
        "instrument_id",
        "instrument_family",
        "dimension",
        "research_only",
        "publication_status",
        "psychological_interpretation_allowed",
        "response_scale",
        "scoring",
        "candidate_cat_config",
        "model",
        "source",
        "rights",
        "provenance",
        "loader_compatibility",
        "items",
        "not_approved_for",
    }
)
_V3_PROFILE_FIELDS = frozenset(
    {
        "schema",
        "profile_id",
        "profile_type",
        "instrument_id",
        "instrument_family",
        "dimension",
        "research_only",
        "publication_status",
        "human_curated",
        "psychological_interpretation_allowed",
        "loader_compatibility",
        "response_scale",
        "model",
        "scoring",
        "candidate_cat_config",
        "items",
        "source_data",
        "rights",
        "provenance",
        "not_approved_for",
    }
)
_V2_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "profile_id",
        "profile_file",
        "profile_sha256",
        "profile_schema",
        "research_only",
        "publication_status",
        "psychological_interpretation_allowed",
        "source_hashes",
        "item_text_rights_basis",
        "dataset_use_scope",
        "candidate_min_items",
        "candidate_max_items",
        "candidate_config_approved",
        "source_population",
        "age_observed",
        "adolescent_sample",
        "high_school_validity",
        "operational_release",
    }
)
_V1_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "profile_id",
        "profile_file",
        "profile_sha256",
        "builder_script",
        "builder_script_sha256",
        "source_hashes",
        "rights_status",
        "category_labels_confirmed",
    }
)
_V3_MANIFEST_FIELDS = frozenset(
    {
        "artifact_status",
        "profile_sha256",
        "numeric_response_csv",
        "complete_observed_800",
        "profile_json_sha256",
        "build_script_sha256",
        "source_response_only_sha256",
        "parameter_crosswalk_sha256",
        "item_map_sha256",
        "no_person_response_hashes_or_identifiers",
        "no_scores_or_person_parameters",
    }
)
_V3_NUMERIC_RESPONSE_FIELDS = frozenset(
    {
        "path",
        "sha256",
        "rows",
        "columns",
        "partial_rows_NA_retained",
        "category_counts",
    }
)
_V3_COMPLETE_RESPONSE_FIELDS = frozenset(
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
_V3_OBSERVED_SOURCE_FIELDS = frozenset(
    {
        "doi",
        "version",
        "license",
        "population",
        "response_only_csv_sha256",
        "rows_with_any_selected_response",
        "complete_on_8_selected_items",
        "partial_rows_retained",
    }
)
_V3_COVERAGE_FIELDS = frozenset(
    {
        "name",
        "seed",
        "algorithm",
        "python_implementation",
        "python_version",
        "complete_source_rows",
        "selected_rows",
        "complete_rows_not_selected",
        "partial_rows_retained_in_full_numeric_matrix",
        "calibration_or_evaluation_split",
    }
)
_V3_PROVENANCE_FIELDS = frozenset(
    {
        "response_label_csv_sha256",
        "numeric_1_5_csv_sha256",
        "complete_observed_800_csv_sha256",
        "item_map_sha256",
        "parameter_crosswalk_sha256",
        "transform_script_sha256",
        "source_sha256_scope",
        "numeric_transform",
        "coverage_sample",
    }
)
_V3_CATEGORY_KEYS = frozenset({"NA", "1", "2", "3", "4", "5"})


class ParameterOrigin(StrEnum):
    """Trusted profile parameter provenance class, not an approval state."""

    LOCAL_RESEARCH_FIT = "LOCAL_RESEARCH_FIT"
    PUBLISHED_ROUNDED_REFERENCE = "PUBLISHED_ROUNDED_REFERENCE"


class PublicationStatusProjection(StrEnum):
    """A deliberately lossy internal projection that preserves only denial."""

    NOT_APPROVED = "NOT_APPROVED"


class ResearchProfileTrustError(ValueError):
    """Stable, non-content-bearing trust validation error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"research profile trust validation failed: {code}")


@dataclass(frozen=True, slots=True)
class ResearchProfileRegistryEntry:
    """A reviewed registry pin injected by trusted server configuration."""

    profile_ref: str
    profile_schema: str
    expected_profile_sha256: str
    expected_manifest_sha256: str
    source_family: str
    parameter_origin: ParameterOrigin
    profile_path: Path = field(repr=False)
    manifest_path: Path = field(repr=False)
    expected_fit_sha256: str | None = field(default=None, repr=False)
    expected_calibration_sha256: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.profile_ref) is not str or not _REF_RE.fullmatch(self.profile_ref):
            raise ResearchProfileTrustError("registry_entry_invalid")
        schema_to_fields = {
            "psynova.research-profile.v1": _V1_PROFILE_FIELDS,
            "psynova.research-profile.v2": _V2_PROFILE_FIELDS,
            "psynova.research-profile.v3": _V3_PROFILE_FIELDS,
        }
        if type(self.profile_schema) is not str or self.profile_schema not in schema_to_fields:
            raise ResearchProfileTrustError("registry_entry_invalid")
        if (
            type(self.expected_profile_sha256) is not str
            or not _SHA256_RE.fullmatch(self.expected_profile_sha256)
            or type(self.expected_manifest_sha256) is not str
            or not _SHA256_RE.fullmatch(self.expected_manifest_sha256)
        ):
            raise ResearchProfileTrustError("registry_entry_invalid")
        if type(self.source_family) is not str or not _FAMILY_RE.fullmatch(self.source_family):
            raise ResearchProfileTrustError("registry_entry_invalid")
        if type(self.parameter_origin) is not ParameterOrigin:
            raise ResearchProfileTrustError("registry_entry_invalid")
        if not isinstance(self.profile_path, Path) or not isinstance(self.manifest_path, Path):
            raise ResearchProfileTrustError("registry_entry_invalid")
        if not self.profile_path.is_absolute() or not self.manifest_path.is_absolute():
            raise ResearchProfileTrustError("registry_entry_invalid")
        if self.profile_schema == "psynova.research-profile.v3":
            if (
                self.parameter_origin is not ParameterOrigin.PUBLISHED_ROUNDED_REFERENCE
                or self.expected_fit_sha256 is not None
                or self.expected_calibration_sha256 is not None
            ):
                raise ResearchProfileTrustError("registry_entry_invalid")
        elif (
            self.parameter_origin is not ParameterOrigin.LOCAL_RESEARCH_FIT
            or self.expected_fit_sha256 is None
            or self.expected_calibration_sha256 is None
        ):
            raise ResearchProfileTrustError("registry_entry_invalid")
        for digest in (self.expected_fit_sha256, self.expected_calibration_sha256):
            if digest is not None and (type(digest) is not str or not _SHA256_RE.fullmatch(digest)):
                raise ResearchProfileTrustError("registry_entry_invalid")
        if (self.expected_fit_sha256 is None) != (self.expected_calibration_sha256 is None):
            raise ResearchProfileTrustError("registry_entry_invalid")


@dataclass(frozen=True, slots=True)
class TrustedResearchProfile:
    """Backend-private verified projection retaining the exact pinned bytes."""

    profile_ref: str
    profile_schema: str
    profile_sha256: str
    manifest_sha256: str
    source_family: str
    parameter_origin: ParameterOrigin
    publication_status_projection: PublicationStatusProjection
    repository_schema_compatible: bool
    raw_profile_bytes: bytes = field(repr=False, compare=False)
    raw_manifest_bytes: bytes = field(repr=False, compare=False)


class ResearchProfileRegistry:
    """Verify registered bytes and trust metadata, not CAT parameters or approval.

    The research engine remains responsible for complete item/parameter schema
    validation. A successful load here is not professional or operational
    approval and does not enable execution.
    """

    __slots__ = ("_root", "_entries")

    def __init__(
        self,
        *,
        allowed_root: Path,
        entries: tuple[ResearchProfileRegistryEntry, ...],
    ) -> None:
        if not isinstance(allowed_root, Path) or not allowed_root.is_absolute():
            raise ResearchProfileTrustError("registry_root_invalid")
        if type(entries) is not tuple or any(
            type(entry) is not ResearchProfileRegistryEntry for entry in entries
        ):
            raise ResearchProfileTrustError("registry_entries_invalid")
        _assert_no_reparse_components(allowed_root)
        try:
            root = allowed_root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ResearchProfileTrustError("registry_root_invalid") from None
        if not root.is_dir():
            raise ResearchProfileTrustError("registry_root_invalid")
        by_ref: dict[str, ResearchProfileRegistryEntry] = {}
        for entry in entries:
            if entry.profile_ref in by_ref:
                raise ResearchProfileTrustError("registry_duplicate_profile_ref")
            _validate_path_under_root(entry.profile_path, root)
            _validate_path_under_root(entry.manifest_path, root)
            if entry.profile_path == entry.manifest_path:
                raise ResearchProfileTrustError("registry_entry_invalid")
            by_ref[entry.profile_ref] = entry
        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_entries", MappingProxyType(by_ref))

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("research profile registry is immutable")
        object.__setattr__(self, name, value)

    def load(self, profile_ref: str) -> TrustedResearchProfile:
        """Load by server-known reference; request-supplied paths/hashes are absent."""

        if type(profile_ref) is not str or not _REF_RE.fullmatch(profile_ref):
            raise ResearchProfileTrustError("profile_not_registered")
        entry = self._entries.get(profile_ref)
        if entry is None:
            raise ResearchProfileTrustError("profile_not_registered")
        profile_bytes = _read_pinned_file(
            entry.profile_path, root=self._root, limit=_MAX_PROFILE_BYTES
        )
        manifest_bytes = _read_pinned_file(
            entry.manifest_path, root=self._root, limit=_MAX_MANIFEST_BYTES
        )
        profile_sha = _sha256(profile_bytes)
        manifest_sha = _sha256(manifest_bytes)
        if not hmac.compare_digest(profile_sha, entry.expected_profile_sha256):
            raise ResearchProfileTrustError("profile_hash_mismatch")
        if not hmac.compare_digest(manifest_sha, entry.expected_manifest_sha256):
            raise ResearchProfileTrustError("manifest_hash_mismatch")
        document = _parse_json_object(profile_bytes, "profile_json_invalid")
        manifest = _parse_json_object(manifest_bytes, "manifest_json_invalid")
        publication_projection = _validate_profile(entry, document)
        _validate_manifest(entry, manifest, document)
        return TrustedResearchProfile(
            profile_ref=entry.profile_ref,
            profile_schema=entry.profile_schema,
            profile_sha256=profile_sha,
            manifest_sha256=manifest_sha,
            source_family=entry.source_family,
            parameter_origin=entry.parameter_origin,
            publication_status_projection=publication_projection,
            repository_schema_compatible=entry.profile_schema
            in {"psynova.research-profile.v1", "psynova.research-profile.v2"},
            raw_profile_bytes=profile_bytes,
            raw_manifest_bytes=manifest_bytes,
        )


@dataclass(frozen=True, slots=True)
class HmacSha256SnapshotAuthenticator:
    """Single-key HMAC primitive; key injection/IDs/rotation are not implemented.

    The caller must inject an application-managed key; this class has no active
    runtime configuration or keyring. Rotating its key would make snapshots
    signed by the prior key unverifiable. A future versioned keyring is needed
    before rotation can be supported. Keys must never be stored in the DB.
    """

    _key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self._key) is not bytes or len(self._key) < 32:
            raise ResearchProfileTrustError("snapshot_key_invalid")

    def sign(self, payload: bytes) -> str:
        if type(payload) is not bytes:
            raise ResearchProfileTrustError("snapshot_payload_invalid")
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        if (
            type(payload) is not bytes
            or type(signature) is not str
            or not _SIGNATURE_RE.fullmatch(signature)
        ):
            return False
        expected = hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def _validate_profile(
    entry: ResearchProfileRegistryEntry, document: dict[str, Any]
) -> PublicationStatusProjection:
    schema = entry.profile_schema
    expected_fields = {
        "psynova.research-profile.v1": _V1_PROFILE_FIELDS,
        "psynova.research-profile.v2": _V2_PROFILE_FIELDS,
        "psynova.research-profile.v3": _V3_PROFILE_FIELDS,
    }[schema]
    if schema == "psynova.research-profile.v1" and "human_curated" in document:
        expected_fields = expected_fields | {"human_curated"}
    if set(document) != expected_fields or document.get("schema") != schema:
        raise ResearchProfileTrustError("profile_schema_invalid")
    if document.get("profile_id") != entry.profile_ref:
        raise ResearchProfileTrustError("profile_ref_mismatch")
    if schema == "psynova.research-profile.v1":
        expected_family = _V1_SOURCE_FAMILY_BY_INSTRUMENT.get(document.get("instrument_id"))
    else:
        expected_family = document.get("instrument_family")
    if type(expected_family) is not str or expected_family != entry.source_family:
        raise ResearchProfileTrustError("profile_source_family_mismatch")
    if schema in {"psynova.research-profile.v1", "psynova.research-profile.v2"}:
        if (
            document.get("profile_type") != "CAT_RESEARCH_PROFILE_CANDIDATE"
            or type(document.get("research_only")) is not bool
            or document["research_only"] is not True
            or document.get("publication_status")
            != "not_approved_for_publication_or_operational_use"
            or type(document.get("psychological_interpretation_allowed")) is not bool
            or document["psychological_interpretation_allowed"] is not False
            or ("human_curated" in document and document["human_curated"] is not False)
            or not isinstance(document.get("not_approved_for"), list)
            or not document["not_approved_for"]
            or any(
                type(value) is not str or not value.strip()
                for value in document["not_approved_for"]
            )
        ):
            raise ResearchProfileTrustError("profile_status_invalid")
        model = document.get("model")
        if not isinstance(model, dict):
            raise ResearchProfileTrustError("profile_parameter_provenance_invalid")
        fit_sha = model.get("fit_sha256")
        calibration_sha = model.get("calibration_sha256")
        if (
            entry.parameter_origin is not ParameterOrigin.LOCAL_RESEARCH_FIT
            or type(fit_sha) is not str
            or not _SHA256_RE.fullmatch(fit_sha)
            or type(calibration_sha) is not str
            or not _SHA256_RE.fullmatch(calibration_sha)
            or (entry.expected_fit_sha256 is not None and fit_sha != entry.expected_fit_sha256)
            or (
                entry.expected_calibration_sha256 is not None
                and calibration_sha != entry.expected_calibration_sha256
            )
        ):
            raise ResearchProfileTrustError("profile_parameter_provenance_invalid")
    else:
        if (
            document.get("profile_type") != "research_only_candidate"
            or type(document.get("research_only")) is not bool
            or document["research_only"] is not True
            or document.get("publication_status") != "not_approved"
            or type(document.get("human_curated")) is not bool
            or document["human_curated"] is not False
            or type(document.get("psychological_interpretation_allowed")) is not bool
            or document["psychological_interpretation_allowed"] is not False
            or not isinstance(document.get("not_approved_for"), list)
            or not document["not_approved_for"]
            or any(
                type(value) is not str or not value.strip()
                for value in document["not_approved_for"]
            )
        ):
            raise ResearchProfileTrustError("profile_status_invalid")
        model = document.get("model")
        if (
            not isinstance(model, dict)
            or set(model)
            != {
                "family",
                "parameter_origin",
                "parameter_version",
                "parameter_metric",
                "precision",
                "version_compatibility",
            }
            or any(
                not isinstance(model.get(key), str) or not model[key].strip()
                for key in (
                    "family",
                    "parameter_origin",
                    "parameter_version",
                    "parameter_metric",
                    "precision",
                    "version_compatibility",
                )
            )
            or "fit_sha256" in model
            or "calibration_sha256" in model
            or "published" not in model["parameter_origin"].casefold()
            or entry.parameter_origin is not ParameterOrigin.PUBLISHED_ROUNDED_REFERENCE
        ):
            raise ResearchProfileTrustError("profile_parameter_provenance_invalid")
    return PublicationStatusProjection.NOT_APPROVED


def _validate_manifest(
    entry: ResearchProfileRegistryEntry,
    manifest: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    if entry.profile_schema == "psynova.research-profile.v3":
        if (
            set(manifest) != _V3_MANIFEST_FIELDS
            or manifest.get("artifact_status") != "research_staging_only"
            or manifest.get("profile_sha256") != entry.expected_profile_sha256
            or manifest.get("profile_json_sha256") != entry.expected_profile_sha256
            or manifest.get("no_person_response_hashes_or_identifiers") is not True
            or manifest.get("no_scores_or_person_parameters") is not True
        ):
            raise ResearchProfileTrustError("manifest_schema_or_status_invalid")
        for key in (
            "source_response_only_sha256",
            "parameter_crosswalk_sha256",
            "item_map_sha256",
        ):
            if type(manifest.get(key)) is not str or not _SHA256_RE.fullmatch(manifest[key]):
                raise ResearchProfileTrustError("manifest_provenance_invalid")
        _validate_v3_observed_response_manifest(manifest, profile)
        return
    if entry.profile_schema == "psynova.research-profile.v1":
        source_hashes = manifest.get("source_hashes")
        if (
            set(manifest) != _V1_MANIFEST_FIELDS
            or manifest.get("schema") != "psynova.research-profile-manifest.v1"
            or manifest.get("profile_id") != entry.profile_ref
            or manifest.get("profile_sha256") != entry.expected_profile_sha256
            or type(manifest.get("builder_script")) is not str
            or not manifest["builder_script"].strip()
            or type(manifest.get("builder_script_sha256")) is not str
            or not _SHA256_RE.fullmatch(manifest["builder_script_sha256"])
            or type(manifest.get("rights_status")) is not str
            or not manifest["rights_status"].strip()
            or type(manifest.get("category_labels_confirmed")) is not bool
            or not isinstance(source_hashes, dict)
            or not source_hashes
            or any(
                type(digest) is not str or not _SHA256_RE.fullmatch(digest)
                for digest in source_hashes.values()
            )
        ):
            raise ResearchProfileTrustError("manifest_schema_or_status_invalid")
        return
    expected_manifest_schema = "psynova.research-profile-manifest.v2"
    if (
        set(manifest) != _V2_MANIFEST_FIELDS
        or manifest.get("schema") != expected_manifest_schema
        or manifest.get("profile_id") != entry.profile_ref
        or manifest.get("profile_sha256") != entry.expected_profile_sha256
        or manifest.get("profile_schema") != entry.profile_schema
        or manifest.get("research_only") is not True
        or manifest.get("publication_status") != "not_approved_for_publication_or_operational_use"
        or manifest.get("psychological_interpretation_allowed") is not False
        or type(manifest.get("candidate_config_approved")) is not bool
        or manifest["candidate_config_approved"] is not False
        or type(manifest.get("operational_release")) is not bool
        or manifest["operational_release"] is not False
    ):
        raise ResearchProfileTrustError("manifest_schema_or_status_invalid")
    source_hashes = manifest.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ResearchProfileTrustError("manifest_provenance_invalid")
    if any(
        type(digest) is not str or not _SHA256_RE.fullmatch(digest)
        for digest in source_hashes.values()
    ):
        raise ResearchProfileTrustError("manifest_provenance_invalid")


def _validate_v3_observed_response_manifest(
    manifest: dict[str, Any], profile: dict[str, Any]
) -> None:
    numeric = manifest.get("numeric_response_csv")
    complete = manifest.get("complete_observed_800")
    if (
        type(numeric) is not dict
        or set(numeric) != _V3_NUMERIC_RESPONSE_FIELDS
        or type(complete) is not dict
        or set(complete) != _V3_COMPLETE_RESPONSE_FIELDS
    ):
        raise ResearchProfileTrustError("manifest_observed_response_metadata_invalid")

    provenance = profile.get("provenance")
    source_data = profile.get("source_data")
    items = profile.get("items")
    if (
        type(provenance) is not dict
        or set(provenance) != _V3_PROVENANCE_FIELDS
        or type(source_data) is not dict
        or set(source_data) != {"observed_response_source", "published_parameters"}
        or type(source_data.get("observed_response_source")) is not dict
        or type(items) is not list
    ):
        raise ResearchProfileTrustError("profile_provenance_metadata_invalid")
    observed = source_data["observed_response_source"]
    if set(observed) != _V3_OBSERVED_SOURCE_FIELDS:
        raise ResearchProfileTrustError("profile_provenance_metadata_invalid")
    coverage = provenance.get("coverage_sample")
    if type(coverage) is not dict or set(coverage) != _V3_COVERAGE_FIELDS:
        raise ResearchProfileTrustError("profile_provenance_metadata_invalid")

    columns = numeric.get("columns")
    profile_columns = [item.get("source_column") for item in items if type(item) is dict]
    if (
        len(profile_columns) != len(items)
        or type(columns) is not list
        or len(columns) != 8
        or any(type(column) is not str or not column for column in columns)
        or len(set(columns)) != len(columns)
        or columns != profile_columns
    ):
        raise ResearchProfileTrustError("manifest_observed_response_metadata_invalid")

    if (
        type(numeric.get("path")) is not str
        or numeric["path"] != "responses_numeric_1_5.csv"
        or type(numeric.get("sha256")) is not str
        or not _SHA256_RE.fullmatch(numeric["sha256"])
        or not _is_nonnegative_int(numeric.get("rows"))
        or numeric["rows"] == 0
        or not _is_nonnegative_int(numeric.get("partial_rows_NA_retained"))
    ):
        raise ResearchProfileTrustError("manifest_observed_response_metadata_invalid")
    for field_name in ("response_label_csv_sha256", "transform_script_sha256"):
        value = provenance.get(field_name)
        if type(value) is not str or not _SHA256_RE.fullmatch(value):
            raise ResearchProfileTrustError("profile_provenance_metadata_invalid")
    for field_name in ("doi", "version", "license", "population"):
        value = observed.get(field_name)
        if type(value) is not str or not value.strip():
            raise ResearchProfileTrustError("profile_provenance_metadata_invalid")
    if (
        coverage.get("name") != "COMPLETE_OBSERVED800"
        or coverage.get("calibration_or_evaluation_split") != _V3_COVERAGE_SPLIT_NOTE
    ):
        raise ResearchProfileTrustError("profile_provenance_metadata_invalid")
    category_counts = numeric.get("category_counts")
    if type(category_counts) is not dict or list(category_counts) != columns:
        raise ResearchProfileTrustError("manifest_observed_response_metadata_invalid")
    for column in columns:
        categories = category_counts.get(column)
        if (
            type(categories) is not dict
            or set(categories) != _V3_CATEGORY_KEYS
            or any(not _is_nonnegative_int(count) for count in categories.values())
            or sum(categories.values()) != numeric["rows"]
        ):
            raise ResearchProfileTrustError("manifest_observed_response_metadata_invalid")

    int_metadata = (
        numeric["rows"],
        numeric["partial_rows_NA_retained"],
        complete.get("rows"),
        complete.get("complete_source_rows"),
        complete.get("not_selected_complete_rows"),
        complete.get("seed"),
        observed.get("rows_with_any_selected_response"),
        observed.get("complete_on_8_selected_items"),
        observed.get("partial_rows_retained"),
        coverage.get("seed"),
        coverage.get("complete_source_rows"),
        coverage.get("selected_rows"),
        coverage.get("complete_rows_not_selected"),
        coverage.get("partial_rows_retained_in_full_numeric_matrix"),
    )
    if any(not _is_nonnegative_int(value) for value in int_metadata):
        raise ResearchProfileTrustError("manifest_observed_response_metadata_invalid")
    if (
        type(complete.get("path")) is not str
        or complete["path"] != "complete_observed_800.csv"
        or type(complete.get("sha256")) is not str
        or not _SHA256_RE.fullmatch(complete["sha256"])
        or type(complete.get("sampling")) is not str
        or complete["sampling"] != _V3_SAMPLING_DESCRIPTION
        or type(complete.get("python_implementation")) is not str
        or type(complete.get("python_version")) is not str
        or type(coverage.get("python_implementation")) is not str
        or type(coverage.get("python_version")) is not str
        or coverage.get("algorithm")
        != (
            "Python random.Random(seed).sample without replacement over the ordered "
            "complete-case list; output rows retain source order"
        )
    ):
        raise ResearchProfileTrustError("manifest_observed_response_metadata_invalid")

    expected_hash_links = (
        (numeric["sha256"], provenance.get("numeric_1_5_csv_sha256")),
        (complete["sha256"], provenance.get("complete_observed_800_csv_sha256")),
        (manifest["item_map_sha256"], provenance.get("item_map_sha256")),
        (manifest["parameter_crosswalk_sha256"], provenance.get("parameter_crosswalk_sha256")),
        (manifest["source_response_only_sha256"], observed.get("response_only_csv_sha256")),
    )
    if any(
        type(expected) is not str
        or not _SHA256_RE.fullmatch(expected)
        or not hmac.compare_digest(actual, expected)
        for actual, expected in expected_hash_links
    ):
        raise ResearchProfileTrustError("manifest_provenance_mismatch")

    if (
        numeric["rows"] != observed["rows_with_any_selected_response"]
        or numeric["partial_rows_NA_retained"] != observed["partial_rows_retained"]
        or numeric["partial_rows_NA_retained"]
        != coverage["partial_rows_retained_in_full_numeric_matrix"]
        or observed["complete_on_8_selected_items"] != coverage["complete_source_rows"]
        or numeric["rows"]
        != observed["complete_on_8_selected_items"] + observed["partial_rows_retained"]
        or complete["rows"] != coverage["selected_rows"]
        or complete["complete_source_rows"] != coverage["complete_source_rows"]
        or complete["not_selected_complete_rows"] != coverage["complete_rows_not_selected"]
        or complete["complete_source_rows"]
        != complete["rows"] + complete["not_selected_complete_rows"]
        or complete["seed"] != coverage["seed"]
        or complete["python_implementation"] != coverage["python_implementation"]
        or complete["python_version"] != coverage["python_version"]
    ):
        raise ResearchProfileTrustError("manifest_provenance_mismatch")


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _parse_json_object(raw: bytes, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ResearchProfileTrustError(error_code) from None
    if type(value) is not dict:
        raise ResearchProfileTrustError(error_code)
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> Any:
    raise ValueError("non-finite JSON number")


def _validate_path_under_root(path: Path, root: Path) -> None:
    _assert_no_reparse_components(path)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise ResearchProfileTrustError("artifact_path_invalid") from None


def _assert_no_reparse_components(path: Path) -> None:
    try:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            info = os.lstat(current)
            attributes = getattr(info, "st_file_attributes", 0)
            if (
                stat.S_ISLNK(info.st_mode)
                or bool(attributes & _REPARSE_POINT)
                or (hasattr(current, "is_junction") and current.is_junction())
            ):
                raise ResearchProfileTrustError("artifact_reparse_point_rejected")
    except ResearchProfileTrustError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ResearchProfileTrustError("artifact_path_invalid") from None


def _read_pinned_file(path: Path, *, root: Path, limit: int) -> bytes:
    _validate_path_under_root(path, root)
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > limit:
            raise ResearchProfileTrustError("artifact_size_or_type_invalid")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size != before.st_size:
                raise ResearchProfileTrustError("artifact_changed_during_read")
            content = stream.read(limit + 1)
        after = path.stat()
        if (
            len(content) != before.st_size
            or len(content) > limit
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ResearchProfileTrustError("artifact_changed_during_read")
        _validate_path_under_root(path, root)
        return content
    except ResearchProfileTrustError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ResearchProfileTrustError("artifact_unavailable") from None


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
