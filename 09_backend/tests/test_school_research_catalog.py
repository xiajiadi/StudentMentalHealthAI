from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from typing import Any

import pytest

from smhai_backend.domains.school_research.catalog import (
    SchoolResearchCatalogError,
    build_school_research_catalog,
)

PROFILE_DIR = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1"
)
PROFILE_PATH = PROFILE_DIR / "profile.json"
MANIFEST_PATH = PROFILE_DIR / "manifest.json"
PROFILE_SHA256 = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
MANIFEST_SHA256 = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
SCHOOL_ID = 71
BINDING_REF = "catalog-promis-binding-01"


class _Provider:
    def get_key(self, _version: str) -> bytes:
        raise AssertionError("catalog loading must not read a key")

    def versions(self) -> tuple[str, ...]:
        return ("v1",)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _cat_config() -> dict[str, object]:
    return {
        "config_version": "catalog-test-v1",
        "model": "GRM",
        "estimator": "EAP",
        "selection_method": "MFI",
        "min_items": 8,
        "max_items": 8,
        "se_threshold": None,
        "initial_theta": 0.0,
        "prior_mean": 0.0,
        "prior_sd": 1.0,
        "optimization_interval": [-4.0, 4.0],
        "seed": 20261014,
        "exposure_control": "none",
        "content_balancing": "none",
    }


def _write_pair(
    tmp_path: Path,
    *,
    profile_sha: str = PROFILE_SHA256,
    manifest_sha: str = MANIFEST_SHA256,
    config_override: dict[str, object] | None = None,
    profile_schema: str = "psynova.research-profile.v3",
) -> tuple[Path, str, Path, str, dict[str, Any], dict[str, Any]]:
    if PROFILE_PATH.is_file() and MANIFEST_PATH.is_file():
        resource_root = PROFILE_DIR
        profile_path = PROFILE_PATH
        manifest_path = MANIFEST_PATH
        profile_doc = json.loads(profile_path.read_bytes())
        if profile_sha == PROFILE_SHA256:
            profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        if manifest_sha == MANIFEST_SHA256:
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    else:
        resource_root = tmp_path / "resources"
        resource_root.mkdir()
        profile_path = resource_root / "profile.json"
        manifest_path = resource_root / "manifest.json"
        profile_path.write_bytes(b"synthetic pinned profile fixture")
        manifest_path.write_bytes(b"synthetic pinned manifest fixture")
        profile_doc = {}
        profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    runtime_doc: dict[str, Any] = {
        "schema": "psynova.school-research-runtime.v1",
        "school_id": SCHOOL_ID,
        "resource_root": str(resource_root),
        "signing_version": "v1",
        "accepted_key_versions": ["v1"],
        "profiles": [
            {
                "profile_ref": PROFILE_REF,
                "profile_schema": profile_schema,
                "expected_profile_sha256": profile_sha,
                "expected_manifest_sha256": manifest_sha,
                "source_family": profile_doc.get(
                    "instrument_family", "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
                ),
                "parameter_origin": "PUBLISHED_ROUNDED_REFERENCE",
                "profile_path": str(profile_path),
                "manifest_path": str(manifest_path),
                "expected_fit_sha256": None,
                "expected_calibration_sha256": None,
            }
        ],
        "bindings": [],
    }
    config = config_override or _cat_config()
    config_sha = hashlib.sha256(_canonical(config)).hexdigest()
    runtime_doc["bindings"] = [
        {
            "binding_ref": BINDING_REF,
            "profile_ref": PROFILE_REF,
            "config_version": config["config_version"],
            "config_sha256": config_sha,
        }
    ]
    service_doc: dict[str, Any] = {
        "schema": "psynova.research-cat-service.v1",
        "school_scope": {"school_id": SCHOOL_ID, "scope": f"school:{SCHOOL_ID}"},
        "resource_root": str(resource_root),
        "listener": {"host": "127.0.0.1", "port": 48182},
        "signing": {"signing_version": "v1", "accepted_key_versions": ["v1"]},
        "profiles": [
            {
                "profile_ref": PROFILE_REF,
                "profile_schema": profile_schema,
                "profile_path": str(profile_path),
                "profile_sha256": profile_sha,
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha,
            }
        ],
        "bindings": [
            {
                "binding_ref": BINDING_REF,
                "profile_ref": PROFILE_REF,
                "config_version": config["config_version"],
                "config_sha256": config_sha,
                "cat_config": config,
            }
        ],
    }
    runtime_file = tmp_path / "runtime.json"
    service_file = tmp_path / "service.json"
    runtime_bytes = _canonical(runtime_doc)
    service_bytes = _canonical(service_doc)
    runtime_file.write_bytes(runtime_bytes)
    service_file.write_bytes(service_bytes)
    return (
        runtime_file,
        hashlib.sha256(runtime_bytes).hexdigest(),
        service_file,
        hashlib.sha256(service_bytes).hexdigest(),
        runtime_doc,
        service_doc,
    )


def _build_catalog(
    runtime_file: Path,
    runtime_sha: str,
    service_file: Path,
    service_sha: str,
    *,
    school_id: int = SCHOOL_ID,
):
    return build_school_research_catalog(
        runtime_config_file=runtime_file,
        expected_runtime_config_sha256=runtime_sha,
        service_config_file=service_file,
        expected_service_config_sha256=service_sha,
        school_id=school_id,
        retained_key_provider=_Provider(),
    )


@pytest.fixture
def actual_catalog_inputs(tmp_path: Path):
    if not PROFILE_PATH.is_file() or not MANIFEST_PATH.is_file():
        pytest.skip("pinned public PROMIS profile is not staged on this host")
    assert hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest() == PROFILE_SHA256
    assert hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest() == MANIFEST_SHA256
    return _write_pair(tmp_path)


def test_catalog_selectors_return_pinned_unapproved_profile_and_safe_repo_projection(
    actual_catalog_inputs,
) -> None:
    runtime_file, runtime_sha, service_file, service_sha, _runtime, _service = actual_catalog_inputs
    catalog = _build_catalog(runtime_file, runtime_sha, service_file, service_sha)
    selection = catalog.select_profile(PROFILE_REF, school_id=SCHOOL_ID)

    assert catalog.school_id == SCHOOL_ID
    assert selection.trusted_profile.profile_ref == PROFILE_REF
    assert selection.trusted_profile.profile_sha256 == PROFILE_SHA256
    assert selection.trusted_profile.manifest_sha256 == MANIFEST_SHA256
    assert selection.trusted_profile.raw_manifest_bytes == MANIFEST_PATH.read_bytes()
    assert selection.trusted_profile.raw_profile_bytes == PROFILE_PATH.read_bytes()
    assert selection.public.instrument_id == "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
    assert selection.public.instrument_family == "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
    assert "child self-report age 8–17" in selection.public.source_population
    assert selection.public.source_version == "PROMIS Pediatric Anxiety v1.0"
    assert selection.public.parameter_origin == "PUBLISHED_ROUNDED_REFERENCE"
    assert selection.public.publication_status == "not_approved"
    assert selection.public.research_only is True
    assert selection.public.human_curated is False
    assert selection.public.psychological_interpretation_allowed is False

    repository = selection.repository
    assert repository.school_id == SCHOOL_ID
    assert repository.source_population_scope == "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17"
    assert repository.rights_status == "PENDING"
    assert repository.execution_status == "CANDIDATE_RESEARCH_ONLY"
    assert repository.expected_profile_sha256 == PROFILE_SHA256
    assert repository.expected_manifest_sha256 == MANIFEST_SHA256
    assert repository.profile.profile_id == PROFILE_REF
    assert repository.profile.profile_type == "CAT_RESEARCH_PROFILE_CANDIDATE"
    assert repository.profile.file_sha256 == PROFILE_SHA256
    assert repository.profile.manifest_sha256 == MANIFEST_SHA256
    assert repository.profile.research_only is True
    assert repository.profile.human_curated is False
    assert repository.profile.psychological_interpretation_allowed is False
    assert repository.profile.publication_status == "not_approved"
    kwargs = repository.create_profile_version_kwargs()
    assert kwargs["rights_status"] == "PENDING"
    assert kwargs["execution_status"] == "CANDIDATE_RESEARCH_ONLY"


def test_real_pinned_profile_projection_passes_database_profile_validator_without_db(
    actual_catalog_inputs,
) -> None:
    database_python = (
        Path(__file__).resolve().parents[2]
        / "11_database"
        / ".venv"
        / "Scripts"
        / "python.exe"
    )
    if not database_python.is_file():
        pytest.skip("isolated database Python runtime is not installed on this host")
    runtime_file, runtime_sha, service_file, service_sha, _runtime, _service = actual_catalog_inputs
    selection = _build_catalog(runtime_file, runtime_sha, service_file, service_sha).select_profile(
        PROFILE_REF
    )
    profile = selection.repository.profile
    script = r"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from database_layer.school_research_cat import _validate_profile_input

(path, file_sha, profile_id, instrument_id, dimension, manifest_sha,
 publication_status, profile_type) = sys.argv[1:]
candidate = SimpleNamespace(
    raw_profile_bytes=Path(path).read_bytes(),
    file_sha256=file_sha,
    profile_id=profile_id,
    instrument_id=instrument_id,
    dimension=dimension,
    manifest_sha256=manifest_sha,
    research_only=True,
    human_curated=False,
    psychological_interpretation_allowed=False,
    publication_status=publication_status,
    profile_type=profile_type,
)
projection = _validate_profile_input(candidate, file_sha, manifest_sha)
print(json.dumps({
    "profile_ref": projection.profile_ref,
    "instrument_id": projection.instrument_id,
    "dimension": projection.dimension,
    "parameter_origin": projection.parameter_origin,
    "fit_sha256": projection.fit_sha256,
    "calibration_sha256": projection.calibration_sha256,
    "published_parameter_crosswalk_sha256": projection.published_parameter_crosswalk_sha256,
}, sort_keys=True))
"""
    completed = subprocess.run(
        [
            str(database_python),
            "-c",
            script,
            str(PROFILE_PATH),
            profile.file_sha256,
            profile.profile_id,
            profile.instrument_id,
            profile.dimension,
            profile.manifest_sha256,
            profile.publication_status,
            profile.profile_type,
        ],
        cwd=Path(__file__).resolve().parents[2] / "11_database",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "profile_ref": PROFILE_REF,
        "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        "dimension": "PROMIS_PEDIATRIC_ANXIETY_RESEARCH",
        "parameter_origin": "PUBLISHED_ROUNDED_REFERENCE",
        "fit_sha256": None,
        "calibration_sha256": None,
        "published_parameter_crosswalk_sha256": (
            "2176b6cbf7498d8ef912f2902a22c31cb7b229ac82d988d54567cfe615c9066c"
        ),
    }


def test_catalog_public_dto_excludes_paths_hashes_raw_bytes_and_parameters(
    actual_catalog_inputs,
) -> None:
    runtime_file, runtime_sha, service_file, service_sha, _runtime, _service = actual_catalog_inputs
    catalog = _build_catalog(runtime_file, runtime_sha, service_file, service_sha)
    public = catalog.public_profiles[0]
    field_names = set(public.__dataclass_fields__)
    assert field_names == {
        "school_id",
        "profile_ref",
        "profile_schema",
        "source_family",
        "instrument_id",
        "instrument_family",
        "source_population",
        "source_version",
        "parameter_origin",
        "research_only",
        "human_curated",
        "psychological_interpretation_allowed",
        "publication_status",
    }
    assert not any(
        forbidden in name.casefold()
        for name in field_names
        for forbidden in ("path", "sha", "raw", "item", "theta", "threshold", "parameter_json")
    )
    assert "C:\\" not in repr(public)
    assert PROFILE_SHA256 not in repr(public)

    binding_public = catalog.public_bindings[0]
    binding_fields = set(binding_public.__dataclass_fields__)
    assert binding_fields == {
        "school_id",
        "binding_ref",
        "profile_ref",
        "config_version",
        "research_only",
        "publication_status",
    }
    assert "config_sha256" not in binding_fields
    assert "config_sha256" not in asdict(binding_public)
    assert "config_sha256" not in repr(binding_public)


def test_binding_config_is_private_immutable_and_copied_per_request(
    actual_catalog_inputs,
) -> None:
    runtime_file, runtime_sha, service_file, service_sha, _runtime, service = actual_catalog_inputs
    catalog = _build_catalog(runtime_file, runtime_sha, service_file, service_sha)
    binding = catalog.select_binding(BINDING_REF)
    first = binding.cat_config_copy()
    first["optimization_interval"][0] = -99.0
    first["max_items"] = 99
    second = binding.cat_config_copy()
    assert second == _cat_config()
    assert binding.public.school_id == SCHOOL_ID
    assert binding.public.profile_ref == PROFILE_REF
    assert binding.public.config_version == "catalog-test-v1"
    assert binding.config_sha256 == service["bindings"][0]["config_sha256"]
    assert binding.public.research_only is True
    assert binding.public.publication_status == "not_approved_for_publication_or_operational_use"
    assert "optimization_interval" not in repr(binding)
    assert "-4.0" not in repr(binding)
    assert catalog.select_binding(BINDING_REF).cat_config_copy() == _cat_config()
    with pytest.raises(TypeError):
        catalog._bindings["other-binding"] = binding
    with pytest.raises(FrozenInstanceError):
        binding.public.config_version = "changed"


def test_unknown_profile_binding_and_foreign_school_fail_with_fixed_codes(
    actual_catalog_inputs,
) -> None:
    runtime_file, runtime_sha, service_file, service_sha, _runtime, _service = actual_catalog_inputs
    catalog = _build_catalog(runtime_file, runtime_sha, service_file, service_sha)
    with pytest.raises(SchoolResearchCatalogError, match="profile_not_in_catalog"):
        catalog.select_profile("other-profile")
    with pytest.raises(SchoolResearchCatalogError, match="binding_not_in_catalog"):
        catalog.select_binding("other-binding")
    with pytest.raises(SchoolResearchCatalogError, match="school_scope_mismatch"):
        catalog.select_profile(PROFILE_REF, school_id=SCHOOL_ID + 1)
    with pytest.raises(SchoolResearchCatalogError, match="school_scope_mismatch"):
        catalog.select_binding(BINDING_REF, school_id=SCHOOL_ID + 1)
    with pytest.raises(SchoolResearchCatalogError, match="school_scope_mismatch"):
        _build_catalog(
            runtime_file, runtime_sha, service_file, service_sha, school_id=SCHOOL_ID + 1
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("profile_schema", "catalog_configuration_invalid"),
        ("profile_path", "catalog_configuration_invalid"),
        ("profile_sha", "catalog_configuration_invalid"),
        ("manifest_path", "catalog_configuration_invalid"),
        ("manifest_sha", "catalog_configuration_invalid"),
        ("binding_version", "catalog_configuration_invalid"),
        ("binding_config", "catalog_configuration_invalid"),
        ("extra_service", "catalog_configuration_invalid"),
    ],
)
def test_service_registry_must_exactly_match_backend_registry(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    runtime_file, runtime_sha, service_file, _service_sha, _runtime, service = _write_pair(tmp_path)
    profile = service["profiles"][0]
    binding = service["bindings"][0]
    if mutation == "profile_schema":
        profile["profile_schema"] = "psynova.research-profile.v2"
    elif mutation == "profile_path":
        other_profile = Path(service["resource_root"]) / "other-profile.json"
        other_profile.write_bytes(b"different synthetic profile")
        profile["profile_path"] = str(other_profile)
    elif mutation == "profile_sha":
        profile["profile_sha256"] = "c" * 64
    elif mutation == "manifest_path":
        other_manifest = Path(service["resource_root"]) / "other-manifest.json"
        other_manifest.write_bytes(b"different synthetic manifest")
        profile["manifest_path"] = str(other_manifest)
    elif mutation == "manifest_sha":
        profile["manifest_sha256"] = "d" * 64
    elif mutation == "binding_version":
        binding["config_version"] = "catalog-test-v2"
        binding["cat_config"]["config_version"] = "catalog-test-v2"
        binding["config_sha256"] = hashlib.sha256(_canonical(binding["cat_config"])).hexdigest()
    elif mutation == "binding_config":
        binding["cat_config"]["seed"] += 1
        binding["config_sha256"] = hashlib.sha256(_canonical(binding["cat_config"])).hexdigest()
    elif mutation == "extra_service":
        service["unexpected"] = "value"
    service_raw = _canonical(service)
    service_file.write_bytes(service_raw)
    with pytest.raises(SchoolResearchCatalogError, match=expected):
        _build_catalog(
            runtime_file, runtime_sha, service_file, hashlib.sha256(service_raw).hexdigest()
        )
