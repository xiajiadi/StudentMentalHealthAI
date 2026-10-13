from __future__ import annotations

import hashlib
import json
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from smhai_backend.domains.school_research import trust as trust_module
from smhai_backend.domains.school_research.trust import (
    HmacSha256SnapshotAuthenticator,
    ParameterOrigin,
    PublicationStatusProjection,
    ResearchProfileRegistry,
    ResearchProfileRegistryEntry,
    ResearchProfileTrustError,
)

_V2_PROFILE_FIELDS = {
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
_V2_MANIFEST_FIELDS = {
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
_V3_PROFILE_FIELDS = {
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
_V3_MANIFEST_FIELDS = {
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
_V3_SAMPLING_DESCRIPTION = (
    "without replacement; file contains only eight response columns, no row index or ID"
)
_V3_COVERAGE_SPLIT_NOTE = (
    "none; published item parameters are used as references and no local model is fit"
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_v2_bundle(root: Path, *, profile_overrides=None, manifest_overrides=None):
    profile = {
        "schema": "psynova.research-profile.v2",
        "profile_id": "test-nhanes-fit",
        "profile_type": "CAT_RESEARCH_PROFILE_CANDIDATE",
        "instrument_id": "TEST_NHANES_DPQ",
        "instrument_family": "NHANES_DPQ",
        "dimension": "research dimension",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "response_scale": {},
        "scoring": {},
        "candidate_cat_config": {},
        "model": {"fit_sha256": "a" * 64, "calibration_sha256": "b" * 64},
        "source": {},
        "rights": {},
        "provenance": {},
        "loader_compatibility": {},
        "items": [],
        "not_approved_for": ["operation", "interpretation"],
    }
    if profile_overrides:
        profile.update(profile_overrides)
    assert set(profile) == _V2_PROFILE_FIELDS
    profile_bytes = json.dumps(profile, separators=(",", ":")).encode("utf-8")
    profile_sha = _sha(profile_bytes)
    manifest = {
        "schema": "psynova.research-profile-manifest.v2",
        "profile_id": "test-nhanes-fit",
        "profile_file": "profile.json",
        "profile_sha256": profile_sha,
        "profile_schema": "psynova.research-profile.v2",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "source_hashes": {"response_only_csv_sha256": "c" * 64},
        "item_text_rights_basis": "test metadata",
        "dataset_use_scope": "test metadata",
        "candidate_min_items": 9,
        "candidate_max_items": 9,
        "candidate_config_approved": False,
        "source_population": "test metadata",
        "age_observed": False,
        "adolescent_sample": False,
        "high_school_validity": False,
        "operational_release": False,
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    assert set(manifest) == _V2_MANIFEST_FIELDS
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    return _write_files(root, profile_bytes, manifest_bytes, profile_sha)


def _write_v3_bundle(root: Path):
    columns = [
        "Q227BR1",
        "Q2230R1",
        "Q3150BR2",
        "Q5044R1",
        "Q2220R2",
        "Q3459BR1",
        "Q713R1",
        "Q3462R1",
    ]
    numeric_sha = "a" * 64
    source_sha = "e" * 64
    complete_sha = "b" * 64
    item_map_sha = "d" * 64
    crosswalk_sha = "c" * 64
    category_counts = {
        column: {"NA": 47, "1": 958, "2": 0, "3": 0, "4": 0, "5": 0} for column in columns
    }
    profile = {
        "schema": "psynova.research-profile.v3",
        "profile_id": "test-promis-reference",
        "profile_type": "research_only_candidate",
        "instrument_id": "TEST_PROMIS_PEDIATRIC",
        "instrument_family": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        "dimension": "pediatric research dimension",
        "research_only": True,
        "publication_status": "not_approved",
        "human_curated": False,
        "psychological_interpretation_allowed": False,
        "loader_compatibility": {},
        "response_scale": {},
        "model": {
            "family": "graded response model",
            "parameter_origin": "published item bank parameters; no refit",
            "parameter_version": "reference-v1",
            "parameter_metric": "theta standard normal",
            "precision": "rounded published values",
            "version_compatibility": "candidate note only",
        },
        "scoring": {},
        "candidate_cat_config": {},
        "items": [{"source_column": column} for column in columns],
        "source_data": {
            "observed_response_source": {
                "doi": "test-only",
                "version": "test-only",
                "license": "test-only",
                "population": "test-only",
                "response_only_csv_sha256": source_sha,
                "rows_with_any_selected_response": 1005,
                "complete_on_8_selected_items": 958,
                "partial_rows_retained": 47,
            },
            "published_parameters": {},
        },
        "rights": {},
        "provenance": {
            "response_label_csv_sha256": "e" * 64,
            "numeric_1_5_csv_sha256": numeric_sha,
            "complete_observed_800_csv_sha256": complete_sha,
            "item_map_sha256": item_map_sha,
            "parameter_crosswalk_sha256": crosswalk_sha,
            "transform_script_sha256": "f" * 64,
            "source_sha256_scope": "file-level hashes; no identifiers",
            "numeric_transform": "source codes 1..5; no imputation",
            "coverage_sample": {
                "name": "COMPLETE_OBSERVED800",
                "seed": 2026101403,
                "algorithm": (
                    "Python random.Random(seed).sample without replacement over the ordered "
                    "complete-case list; output rows retain source order"
                ),
                "python_implementation": "CPython",
                "python_version": "3.14.6",
                "complete_source_rows": 958,
                "selected_rows": 800,
                "complete_rows_not_selected": 158,
                "partial_rows_retained_in_full_numeric_matrix": 47,
                "calibration_or_evaluation_split": _V3_COVERAGE_SPLIT_NOTE,
            },
        },
        "not_approved_for": ["operation", "interpretation"],
    }
    assert set(profile) == _V3_PROFILE_FIELDS
    profile_bytes = json.dumps(profile, separators=(",", ":")).encode("utf-8")
    profile_sha = _sha(profile_bytes)
    manifest = {
        "artifact_status": "research_staging_only",
        "profile_sha256": profile_sha,
        "numeric_response_csv": {
            "path": "responses_numeric_1_5.csv",
            "sha256": numeric_sha,
            "rows": 1005,
            "columns": columns,
            "partial_rows_NA_retained": 47,
            "category_counts": category_counts,
        },
        "complete_observed_800": {
            "path": "complete_observed_800.csv",
            "sha256": complete_sha,
            "rows": 800,
            "complete_source_rows": 958,
            "not_selected_complete_rows": 158,
            "seed": 2026101403,
            "sampling": _V3_SAMPLING_DESCRIPTION,
            "python_implementation": "CPython",
            "python_version": "3.14.6",
        },
        "profile_json_sha256": profile_sha,
        "build_script_sha256": "a" * 64,
        "source_response_only_sha256": source_sha,
        "parameter_crosswalk_sha256": crosswalk_sha,
        "item_map_sha256": item_map_sha,
        "no_person_response_hashes_or_identifiers": True,
        "no_scores_or_person_parameters": True,
    }
    assert set(manifest) == _V3_MANIFEST_FIELDS
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    return _write_files(root, profile_bytes, manifest_bytes, profile_sha)


def _write_files(root: Path, profile_bytes: bytes, manifest_bytes: bytes, profile_sha: str):
    root.mkdir(parents=True, exist_ok=True)
    profile_path = root / "profile.json"
    manifest_path = root / "manifest.json"
    profile_path.write_bytes(profile_bytes)
    manifest_path.write_bytes(manifest_bytes)
    is_v1 = b"research-profile.v1" in profile_bytes
    is_v2 = b"research-profile.v2" in profile_bytes
    entry = ResearchProfileRegistryEntry(
        profile_ref=(
            "test-nhanes-fit" if is_v2 else "test-sapa-v1" if is_v1 else "test-promis-reference"
        ),
        profile_schema=(
            "psynova.research-profile.v2"
            if is_v2
            else "psynova.research-profile.v1"
            if is_v1
            else "psynova.research-profile.v3"
        ),
        expected_profile_sha256=profile_sha,
        expected_manifest_sha256=_sha(manifest_bytes),
        source_family=(
            "NHANES_DPQ"
            if is_v2
            else "SAPA_IPIP100"
            if is_v1
            else "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
        ),
        parameter_origin=(
            ParameterOrigin.LOCAL_RESEARCH_FIT
            if is_v2 or is_v1
            else ParameterOrigin.PUBLISHED_ROUNDED_REFERENCE
        ),
        profile_path=profile_path,
        manifest_path=manifest_path,
        expected_fit_sha256="a" * 64 if is_v2 or is_v1 else None,
        expected_calibration_sha256="b" * 64 if is_v2 or is_v1 else None,
    )
    registry = ResearchProfileRegistry(allowed_root=root, entries=(entry,))
    return registry, entry, profile_bytes, manifest_bytes


def _replace_v2_artifacts(
    root: Path,
    entry: ResearchProfileRegistryEntry,
    profile_bytes: bytes,
) -> ResearchProfileRegistry:
    profile_sha = _sha(profile_bytes)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["profile_sha256"] = profile_sha
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    (root / "profile.json").write_bytes(profile_bytes)
    (root / "manifest.json").write_bytes(manifest_bytes)
    replacement = replace(
        entry,
        expected_profile_sha256=profile_sha,
        expected_manifest_sha256=_sha(manifest_bytes),
    )
    return ResearchProfileRegistry(allowed_root=root, entries=(replacement,))


def _mutate_v3_manifest(
    root: Path, mutation: str
) -> tuple[ResearchProfileRegistry, ResearchProfileRegistryEntry]:
    _registry, entry, _profile_bytes, manifest_bytes = _write_v3_bundle(root)
    manifest = json.loads(manifest_bytes)
    if mutation == "numeric_string":
        manifest["numeric_response_csv"] = "valid hash, wrong type"
    elif mutation == "complete_null":
        manifest["complete_observed_800"] = None
    elif mutation == "missing_columns":
        del manifest["numeric_response_csv"]["columns"]
    elif mutation == "bool_rows":
        manifest["numeric_response_csv"]["rows"] = True
    elif mutation == "bool_counts":
        manifest["numeric_response_csv"]["category_counts"]["Q227BR1"]["NA"] = True
    elif mutation == "bool_seed":
        manifest["complete_observed_800"]["seed"] = True
    elif mutation == "column_order":
        manifest["numeric_response_csv"]["columns"].reverse()
    elif mutation == "hash_mismatch":
        manifest["numeric_response_csv"]["sha256"] = "f" * 64
    elif mutation == "source_hash_mismatch":
        manifest["source_response_only_sha256"] = "f" * 64
    else:
        raise AssertionError("unknown fixture mutation")
    changed_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    (root / "manifest.json").write_bytes(changed_bytes)
    changed_entry = replace(entry, expected_manifest_sha256=_sha(changed_bytes))
    return ResearchProfileRegistry(allowed_root=root, entries=(changed_entry,)), changed_entry


def test_registry_verifies_exact_v2_bytes_and_hides_them_from_repr(tmp_path: Path) -> None:
    registry, _entry, profile_bytes, manifest_bytes = _write_v2_bundle(tmp_path)

    verified = registry.load("test-nhanes-fit")

    assert verified.raw_profile_bytes == profile_bytes
    assert verified.raw_manifest_bytes == manifest_bytes
    assert verified.profile_sha256 == _sha(profile_bytes)
    assert verified.manifest_sha256 == _sha(manifest_bytes)
    assert verified.parameter_origin is ParameterOrigin.LOCAL_RESEARCH_FIT
    assert verified.publication_status_projection is PublicationStatusProjection.NOT_APPROVED
    assert verified.repository_schema_compatible is True
    assert profile_bytes.decode("utf-8") not in repr(verified)


def test_registry_accepts_only_explicitly_mapped_v1_source_family(tmp_path: Path) -> None:
    profile = {
        "schema": "psynova.research-profile.v1",
        "profile_id": "test-sapa-v1",
        "profile_type": "CAT_RESEARCH_PROFILE_CANDIDATE",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "dimension": "research dimension",
        "instrument_id": "IPIP100_B5_E_EXTRAVERSION_20_RESEARCH",
        "response_scale": {},
        "scoring": {},
        "model": {"fit_sha256": "a" * 64, "calibration_sha256": "b" * 64},
        "source": {},
        "rights": {},
        "provenance": {},
        "items": [],
        "not_approved_for": ["operation"],
    }
    profile_bytes = json.dumps(profile, separators=(",", ":")).encode()
    profile_sha = _sha(profile_bytes)
    manifest = {
        "schema": "psynova.research-profile-manifest.v1",
        "profile_id": "test-sapa-v1",
        "profile_file": "profile.json",
        "profile_sha256": profile_sha,
        "builder_script": "build-profile.py",
        "builder_script_sha256": "c" * 64,
        "source_hashes": {"fit_summary_sha256": "d" * 64},
        "rights_status": "research rights metadata; no operational approval",
        "category_labels_confirmed": False,
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
    _registry, entry, _, _ = _write_files(tmp_path, profile_bytes, manifest_bytes, profile_sha)
    assert entry.source_family == "SAPA_IPIP100"
    assert (
        ResearchProfileRegistry(allowed_root=tmp_path, entries=(entry,))
        .load(entry.profile_ref)
        .repository_schema_compatible
    )


def test_registry_v3_preserves_negative_status_and_published_parameter_origin(
    tmp_path: Path,
) -> None:
    registry, _entry, profile_bytes, _manifest_bytes = _write_v3_bundle(tmp_path)

    verified = registry.load("test-promis-reference")

    assert verified.raw_profile_bytes == profile_bytes
    assert verified.parameter_origin is ParameterOrigin.PUBLISHED_ROUNDED_REFERENCE
    assert verified.publication_status_projection is PublicationStatusProjection.NOT_APPROVED
    # Schema 0013 can store published reference parameters without inventing
    # local fit/calibration hashes. Compatibility does not enable execution.
    assert verified.repository_schema_compatible is True
    assert b'"publication_status":"not_approved"' in verified.raw_profile_bytes
    assert b"fit_sha256" not in verified.raw_profile_bytes
    assert b"calibration_sha256" not in verified.raw_profile_bytes


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("numeric_string", "manifest_observed_response_metadata_invalid"),
        ("complete_null", "manifest_observed_response_metadata_invalid"),
        ("missing_columns", "manifest_observed_response_metadata_invalid"),
        ("bool_rows", "manifest_observed_response_metadata_invalid"),
        ("bool_counts", "manifest_observed_response_metadata_invalid"),
        ("bool_seed", "manifest_observed_response_metadata_invalid"),
        ("column_order", "manifest_observed_response_metadata_invalid"),
        ("hash_mismatch", "manifest_provenance_mismatch"),
        ("source_hash_mismatch", "manifest_provenance_mismatch"),
    ],
)
def test_registry_v3_rejects_malformed_or_inconsistent_response_metadata(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    registry, entry = _mutate_v3_manifest(tmp_path, mutation)

    # The modified manifest itself is deliberately pinned here so each case
    # reaches nested shape/provenance validation instead of failing its digest.
    with pytest.raises(ResearchProfileTrustError, match=expected_error):
        registry.load(entry.profile_ref)


def test_registry_entry_rejects_fit_hashes_for_published_parameter_profile(
    tmp_path: Path,
) -> None:
    _registry, entry, _profile_bytes, _manifest_bytes = _write_v3_bundle(tmp_path)
    with pytest.raises(ResearchProfileTrustError, match="registry_entry_invalid"):
        replace(entry, expected_fit_sha256="a" * 64)


def test_registry_rejects_wrong_pinned_hashes_and_manifest_profile_mismatch(
    tmp_path: Path,
) -> None:
    registry, entry, profile_bytes, _ = _write_v2_bundle(tmp_path)
    wrong_hash_entry = replace(entry, expected_profile_sha256="f" * 64)

    wrong_registry = ResearchProfileRegistry(allowed_root=tmp_path, entries=(wrong_hash_entry,))
    with pytest.raises(ResearchProfileTrustError, match="profile_hash_mismatch"):
        wrong_registry.load(entry.profile_ref)

    modified_manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    modified_manifest["profile_sha256"] = "e" * 64
    (tmp_path / "manifest.json").write_text(
        json.dumps(modified_manifest, separators=(",", ":")), encoding="utf-8"
    )
    with pytest.raises(ResearchProfileTrustError, match="manifest_hash_mismatch"):
        registry.load(entry.profile_ref)
    assert profile_bytes


def test_registry_requires_independently_pinned_local_fit_and_calibration_hashes(
    tmp_path: Path,
) -> None:
    _registry, entry, _profile_bytes, _manifest_bytes = _write_v2_bundle(tmp_path)
    with pytest.raises(ResearchProfileTrustError, match="registry_entry_invalid"):
        replace(
            entry,
            expected_fit_sha256=None,
            expected_calibration_sha256=None,
        )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("research_only", "profile_status_invalid"),
        ("psychological_interpretation_allowed", "profile_status_invalid"),
        ("unexpected", "profile_schema_invalid"),
        ("nonfinite", "profile_json_invalid"),
    ],
)
def test_registry_rejects_negative_flag_changes_unknown_fields_and_nonfinite_json(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    _registry, entry, profile_bytes, _ = _write_v2_bundle(tmp_path)
    if mutation == "nonfinite":
        modified = profile_bytes.replace(b'"dimension":"research dimension"', b'"dimension":NaN')
    else:
        profile = json.loads(profile_bytes)
        if mutation == "unexpected":
            profile["unexpected"] = "field"
        elif mutation == "research_only":
            profile[mutation] = False
        else:
            profile[mutation] = True
        modified = json.dumps(profile, separators=(",", ":")).encode("utf-8")
    modified_registry = _replace_v2_artifacts(tmp_path, entry, modified)
    with pytest.raises(ResearchProfileTrustError, match=expected_error):
        modified_registry.load(entry.profile_ref)


def test_registry_rejects_duplicate_json_keys_and_registry_mismatch(tmp_path: Path) -> None:
    _registry, entry, profile_bytes, _ = _write_v2_bundle(tmp_path)
    duplicate = profile_bytes[:-1] + b',"schema":"psynova.research-profile.v2"}'
    duplicate_registry = _replace_v2_artifacts(tmp_path, entry, duplicate)
    with pytest.raises(ResearchProfileTrustError, match="profile_json_invalid"):
        duplicate_registry.load(entry.profile_ref)
    with pytest.raises(ResearchProfileTrustError, match="profile_not_registered"):
        duplicate_registry.load("other-client-claimed-profile")


def test_registry_binds_source_family_to_profile_metadata(tmp_path: Path) -> None:
    _registry, entry, _profile_bytes, _manifest_bytes = _write_v2_bundle(tmp_path)
    wrong_family = replace(entry, source_family="SAPA_IPIP100")
    with pytest.raises(ResearchProfileTrustError, match="profile_source_family_mismatch"):
        ResearchProfileRegistry(allowed_root=tmp_path, entries=(wrong_family,)).load(
            entry.profile_ref
        )


def test_registry_rejects_symlinked_artifact_parent_when_supported(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    outside_root = tmp_path / "outside"
    _write_v2_bundle(outside_root)
    link_root = tmp_path / "linked"
    try:
        link_root.symlink_to(outside_root, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink unavailable on this platform: {type(exc).__name__}")
    with pytest.raises(ResearchProfileTrustError, match="artifact_reparse_point_rejected"):
        ResearchProfileRegistry(
            allowed_root=link_root,
            entries=(),
        )


def test_registry_rejects_windows_reparse_component_independent_of_symlink_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_lstat = os.lstat

    def report_reparse(path):
        info = original_lstat(path)
        if Path(path) == tmp_path:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(trust_module.os, "lstat", report_reparse)
    with pytest.raises(ResearchProfileTrustError, match="artifact_reparse_point_rejected"):
        ResearchProfileRegistry(allowed_root=tmp_path, entries=())


def test_registry_rejects_oversized_profile_before_json_parsing(tmp_path: Path) -> None:
    registry, entry, _profile_bytes, _manifest_bytes = _write_v2_bundle(tmp_path)
    (tmp_path / "profile.json").write_bytes(b" " * (4 * 1024 * 1024 + 1))

    with pytest.raises(ResearchProfileTrustError, match="artifact_size_or_type_invalid"):
        registry.load(entry.profile_ref)


def test_snapshot_hmac_requires_app_key_hides_it_and_rejects_bad_inputs() -> None:
    key = b"test-only application key material 32 bytes minimum"
    auth = HmacSha256SnapshotAuthenticator(key)
    assert "runtime configuration" in HmacSha256SnapshotAuthenticator.__doc__
    assert "versioned keyring" in HmacSha256SnapshotAuthenticator.__doc__
    assert "unverifiable" in HmacSha256SnapshotAuthenticator.__doc__
    payload = b"signed test snapshot bytes"
    signature = auth.sign(payload)

    assert len(signature) == 64
    assert auth.verify(payload, signature)
    assert not auth.verify(payload, "g" * 64)
    assert not auth.verify(payload, b"not a string")  # type: ignore[arg-type]
    assert not auth.verify("not bytes", signature)  # type: ignore[arg-type]
    assert key.decode() not in repr(auth)
    with pytest.raises(FrozenInstanceError):
        auth._key = b"x" * 32  # type: ignore[misc]
    with pytest.raises(ResearchProfileTrustError, match="snapshot_key_invalid"):
        HmacSha256SnapshotAuthenticator(b"too short")
    with pytest.raises(ResearchProfileTrustError, match="snapshot_payload_invalid"):
        auth.sign("not bytes")  # type: ignore[arg-type]
