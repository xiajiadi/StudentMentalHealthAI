from __future__ import annotations

import ast
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
for _candidate in (
    REPO / "11_database",
    REPO / "11_database" / ".venv" / "Lib" / "site-packages",
):
    if _candidate.is_dir() and str(_candidate.resolve()) not in sys.path:
        sys.path.insert(0, str(_candidate.resolve()))

from smhai_backend.domains.school_research.managed import (  # noqa: E402
    ManagedResearchProcessError,
    build_managed_research_process,
)
from smhai_backend.domains.school_research.process import ResearchCATProcessManager  # noqa: E402

PROFILE_DIR = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1"
)
PROFILE_PATH = PROFILE_DIR / "profile.json"
MANIFEST_PATH = PROFILE_DIR / "manifest.json"
PROFILE_SHA256 = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
MANIFEST_SHA256 = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
CONFIG_VERSION = "managed-test-config-v1"
SCHOOL_ID = 701
BINDING_REF = "managed-test-binding-01"


class _SyntheticKeyProvider:
    def __init__(self) -> None:
        self._encoded = base64.urlsafe_b64encode(b"\x87" * 32)

    def versions(self) -> tuple[str, ...]:
        return ("v1", "v2")

    def get_key(self, version: str) -> bytes:
        if version not in self.versions():
            raise KeyError
        return self._encoded


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
        "config_version": CONFIG_VERSION,
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


def _write_config_pair(
    tmp_path: Path,
    *,
    resource_root: Path | None = None,
    profile_path: Path | None = None,
    manifest_path: Path | None = None,
    profile_sha: str | None = None,
    manifest_sha: str | None = None,
    profile_schema: str = "psynova.research-profile.v3",
) -> tuple[Path, str, Path, str, dict[str, Any], dict[str, Any]]:
    if resource_root is None:
        resource_root = tmp_path / "resources"
        resource_root.mkdir()
        profile_path = resource_root / "profile.json"
        manifest_path = resource_root / "manifest.json"
        profile_path.write_bytes(b"synthetic profile fixture")
        manifest_path.write_bytes(b"synthetic manifest fixture")
        profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert profile_path is not None and manifest_path is not None
    assert profile_sha is not None and manifest_sha is not None

    cat_config = _cat_config()
    config_sha = hashlib.sha256(_canonical(cat_config)).hexdigest()
    backend_profile = {
        "profile_ref": "synthetic-profile-01",
        "profile_schema": profile_schema,
        "expected_profile_sha256": profile_sha,
        "expected_manifest_sha256": manifest_sha,
        "source_family": "synthetic-tests-only",
        "parameter_origin": "PUBLISHED_ROUNDED_REFERENCE",
        "profile_path": str(profile_path),
        "manifest_path": str(manifest_path),
        "expected_fit_sha256": None,
        "expected_calibration_sha256": None,
    }
    backend_binding = {
        "binding_ref": BINDING_REF,
        "profile_ref": "synthetic-profile-01",
        "config_version": CONFIG_VERSION,
        "config_sha256": config_sha,
    }
    runtime_doc: dict[str, Any] = {
        "schema": "psynova.school-research-runtime.v1",
        "school_id": SCHOOL_ID,
        "resource_root": str(resource_root),
        "signing_version": "v2",
        "accepted_key_versions": ["v1", "v2"],
        "profiles": [backend_profile],
        "bindings": [backend_binding],
    }
    service_doc: dict[str, Any] = {
        "schema": "psynova.research-cat-service.v1",
        "school_scope": {"school_id": SCHOOL_ID, "scope": f"school:{SCHOOL_ID}"},
        "resource_root": str(resource_root),
        "listener": {"host": "127.0.0.1", "port": 48182},
        "signing": {
            "signing_version": "v2",
            "accepted_key_versions": ["v1", "v2"],
        },
        "profiles": [
            {
                "profile_ref": backend_profile["profile_ref"],
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
                "profile_ref": "synthetic-profile-01",
                "config_version": CONFIG_VERSION,
                "config_sha256": config_sha,
                "cat_config": cat_config,
            }
        ],
    }
    runtime_file = tmp_path / "runtime.json"
    service_file = tmp_path / "cat-service.json"
    runtime_raw = _canonical(runtime_doc)
    service_raw = _canonical(service_doc)
    runtime_file.write_bytes(runtime_raw)
    service_file.write_bytes(service_raw)
    return (
        runtime_file,
        hashlib.sha256(runtime_raw).hexdigest(),
        service_file,
        hashlib.sha256(service_raw).hexdigest(),
        runtime_doc,
        service_doc,
    )


def _factory(
    runtime_file: Path,
    runtime_sha: str,
    service_file: Path,
    service_sha: str,
    tmp_path: Path,
    *,
    provider: Any | None = None,
    base_probe=None,
):
    cat_source = tmp_path / "cat-source"
    entry = cat_source / "cat_engine" / "research"
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "serve.py").write_text("# synthetic test entrypoint\n", encoding="utf-8")
    dependency = tmp_path / "cat-dependencies"
    dependency.mkdir(exist_ok=True)
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic executable marker")
    return build_managed_research_process(
        runtime_config_file=runtime_file,
        expected_runtime_config_sha256=runtime_sha,
        service_config_file=service_file,
        expected_service_config_sha256=service_sha,
        cat_source=cat_source,
        cat_dependency_path=dependency,
        base_executable=executable,
        base_executable_probe=base_probe or (lambda _path: True),
        retained_key_provider=provider or _SyntheticKeyProvider(),
        readiness_probe=lambda _port, _bearer, _timeout: {},
        listener_owner_probe=lambda _pid, _port: False,
        port_available_probe=lambda _port: True,
    )


def test_module_import_does_not_load_cat_or_database_packages() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "smhai_backend"
        / "domains"
        / "school_research"
        / "managed.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    top_level_imports = [node.module for node in tree.body if isinstance(node, ast.ImportFrom)]
    top_level_imports.extend(
        alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    )
    assert not any(
        module == "cat_engine"
        or module.startswith("cat_engine.")
        or module == "database_layer"
        or module.startswith("database_layer.")
        for module in top_level_imports
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("school", "backend_cat_config_mismatch"),
        ("profile_schema", "backend_cat_config_mismatch"),
        ("profile_path", "backend_cat_config_mismatch"),
        ("profile_hash", "backend_cat_config_mismatch"),
        ("manifest_path", "backend_cat_config_mismatch"),
        ("manifest_hash", "backend_cat_config_mismatch"),
        ("binding", "backend_cat_config_mismatch"),
        ("binding_version", "backend_cat_config_mismatch"),
        ("binding_ref", "backend_cat_config_mismatch"),
        ("accepted_versions", "backend_cat_config_mismatch"),
    ],
)
def test_runtime_and_cat_service_registry_must_match_exactly(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    runtime_file, runtime_sha, service_file, service_sha, runtime, service = _write_config_pair(
        tmp_path
    )
    if mutation == "school":
        service["school_scope"]["school_id"] += 1
        service["school_scope"]["scope"] = f"school:{service['school_scope']['school_id']}"
    elif mutation == "profile_schema":
        service["profiles"][0]["profile_schema"] = "psynova.research-profile.v2"
    elif mutation == "profile_path":
        other_profile = Path(runtime["resource_root"]) / "other-profile.json"
        other_profile.write_bytes(b"another synthetic profile")
        service["profiles"][0]["profile_path"] = str(other_profile)
    elif mutation == "profile_hash":
        service["profiles"][0]["profile_sha256"] = "c" * 64
    elif mutation == "manifest_path":
        other_manifest = Path(runtime["resource_root"]) / "other-manifest.json"
        other_manifest.write_bytes(b"another synthetic manifest")
        service["profiles"][0]["manifest_path"] = str(other_manifest)
    elif mutation == "manifest_hash":
        service["profiles"][0]["manifest_sha256"] = "d" * 64
    elif mutation == "binding":
        service["bindings"][0]["cat_config"]["seed"] += 1
        service["bindings"][0]["config_sha256"] = hashlib.sha256(
            _canonical(service["bindings"][0]["cat_config"])
        ).hexdigest()
    elif mutation == "binding_version":
        service["bindings"][0]["config_version"] = "managed-test-config-v2"
        service["bindings"][0]["cat_config"]["config_version"] = "managed-test-config-v2"
        service["bindings"][0]["config_sha256"] = hashlib.sha256(
            _canonical(service["bindings"][0]["cat_config"])
        ).hexdigest()
    elif mutation == "binding_ref":
        service["bindings"][0]["binding_ref"] = "another-binding-01"
    elif mutation == "accepted_versions":
        service["signing"]["accepted_key_versions"] = ["v2"]
    del runtime
    service_raw = _canonical(service)
    service_file.write_bytes(service_raw)
    service_sha = hashlib.sha256(service_raw).hexdigest()
    with pytest.raises(ManagedResearchProcessError, match=expected):
        _factory(runtime_file, runtime_sha, service_file, service_sha, tmp_path)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("extra_root", "service_config_schema_invalid"),
        ("bool_port", "service_listener_invalid"),
        ("bool_minimum", "cat_config_invalid"),
        ("cat_hash", "cat_config_hash_mismatch"),
        ("duplicate_binding", "service_binding_invalid"),
    ],
)
def test_service_document_and_cat_config_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    runtime_file, runtime_sha, service_file, _service_sha, _runtime, service = _write_config_pair(
        tmp_path
    )
    if mutation == "extra_root":
        service["unrecognized"] = True
    elif mutation == "bool_port":
        service["listener"]["port"] = True
    elif mutation == "bool_minimum":
        service["bindings"][0]["cat_config"]["min_items"] = True
        config_hash = hashlib.sha256(_canonical(service["bindings"][0]["cat_config"])).hexdigest()
        service["bindings"][0]["config_sha256"] = config_hash
        service["bindings"][0]["config_version"] = CONFIG_VERSION
    elif mutation == "cat_hash":
        service["bindings"][0]["config_sha256"] = "f" * 64
    elif mutation == "duplicate_binding":
        service["bindings"].append(dict(service["bindings"][0]))
    raw = _canonical(service)
    service_file.write_bytes(raw)
    with pytest.raises(ManagedResearchProcessError, match=expected):
        _factory(
            runtime_file,
            runtime_sha,
            service_file,
            hashlib.sha256(raw).hexdigest(),
            tmp_path,
        )


def test_config_file_hash_and_json_are_closed_and_bounded(tmp_path: Path) -> None:
    runtime_file, runtime_sha, service_file, service_sha, _runtime, _service = _write_config_pair(
        tmp_path
    )
    with pytest.raises(ManagedResearchProcessError, match="config_hash_mismatch"):
        _factory(runtime_file, runtime_sha, service_file, "0" * 64, tmp_path)

    service_file.write_bytes(b'{"schema":"a","schema":"b"}')
    duplicate_sha = hashlib.sha256(service_file.read_bytes()).hexdigest()
    with pytest.raises(ManagedResearchProcessError, match="service_config_invalid"):
        _factory(runtime_file, runtime_sha, service_file, duplicate_sha, tmp_path)

    service_file.write_bytes(b"x" * (1024 * 1024 + 1))
    oversized_sha = hashlib.sha256(service_file.read_bytes()).hexdigest()
    with pytest.raises(ManagedResearchProcessError, match="config_size_invalid"):
        _factory(runtime_file, runtime_sha, service_file, oversized_sha, tmp_path)


def test_base_executable_probe_is_required_and_fail_closed(tmp_path: Path) -> None:
    runtime_file, runtime_sha, service_file, service_sha, _runtime, _service = _write_config_pair(
        tmp_path
    )
    with pytest.raises(ManagedResearchProcessError, match="base_executable_probe_failed"):
        _factory(
            runtime_file,
            runtime_sha,
            service_file,
            service_sha,
            tmp_path,
            base_probe=lambda _path: False,
        )


def test_matching_pinned_public_profile_builds_manager_without_starting_child(
    tmp_path: Path,
) -> None:
    if not PROFILE_PATH.is_file() or not MANIFEST_PATH.is_file():
        pytest.skip("pinned public PROMIS research profile is not staged on this host")
    profile_bytes = PROFILE_PATH.read_bytes()
    manifest_bytes = MANIFEST_PATH.read_bytes()
    assert hashlib.sha256(profile_bytes).hexdigest() == PROFILE_SHA256
    assert hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256
    profile_doc = json.loads(profile_bytes)

    runtime_file, runtime_sha, service_file, service_sha, runtime, service = _write_config_pair(
        tmp_path,
        resource_root=PROFILE_DIR,
        profile_path=PROFILE_PATH,
        manifest_path=MANIFEST_PATH,
        profile_sha=PROFILE_SHA256,
        manifest_sha=MANIFEST_SHA256,
        profile_schema=profile_doc["schema"],
    )
    runtime_profile = runtime["profiles"][0]
    runtime_profile["profile_ref"] = PROFILE_REF
    runtime_profile["source_family"] = profile_doc["instrument_family"]
    runtime_profile["profile_path"] = str(PROFILE_PATH)
    runtime_profile["manifest_path"] = str(MANIFEST_PATH)
    runtime_profile["expected_profile_sha256"] = PROFILE_SHA256
    runtime_profile["expected_manifest_sha256"] = MANIFEST_SHA256

    service_profile = service["profiles"][0]
    service_profile["profile_ref"] = PROFILE_REF
    service_profile["profile_path"] = str(PROFILE_PATH)
    service_profile["manifest_path"] = str(MANIFEST_PATH)
    service_profile["profile_sha256"] = PROFILE_SHA256
    service_profile["manifest_sha256"] = MANIFEST_SHA256
    runtime["bindings"][0]["profile_ref"] = PROFILE_REF
    service["bindings"][0]["profile_ref"] = PROFILE_REF

    runtime_raw = _canonical(runtime)
    service_raw = _canonical(service)
    runtime_file.write_bytes(runtime_raw)
    service_file.write_bytes(service_raw)
    runtime_sha = hashlib.sha256(runtime_raw).hexdigest()
    service_sha = hashlib.sha256(service_raw).hexdigest()

    manager = _factory(
        runtime_file,
        runtime_sha,
        service_file,
        service_sha,
        tmp_path,
        provider=_SyntheticKeyProvider(),
    )
    assert isinstance(manager, ResearchCATProcessManager)
    spec = manager._spec
    assert spec.expected_school_scope == f"school:{SCHOOL_ID}"
    assert spec.expected_binding_count == 1
    assert spec.expected_port == 48182
    assert spec.serve_config_sha256 == service_sha
    fingerprint_material = {
        "profiles": [
            {
                "profile_ref": PROFILE_REF,
                "profile_schema": profile_doc["schema"],
                "profile_sha256": PROFILE_SHA256,
                "manifest_sha256": MANIFEST_SHA256,
            }
        ],
        "bindings": [
            {
                "binding_ref": BINDING_REF,
                "profile_ref": PROFILE_REF,
                "config_version": CONFIG_VERSION,
                "config_sha256": service["bindings"][0]["config_sha256"],
            }
        ],
    }
    expected_fingerprint = hashlib.sha256(_canonical(fingerprint_material)).hexdigest()
    assert spec.expected_registry_fingerprint == expected_fingerprint
    assert manager._health.status == "STOPPED"
    assert manager._process is None
    assert manager._handshake_line is not None
    handoff = json.loads(manager._handshake_line)
    assert set(handoff) == {"schema", "bearer_token", "signing_version", "keyring"}
    assert handoff["schema"] == "psynova.research-service-keys.v1"
    assert handoff["signing_version"] == "v2"
    assert set(handoff["keyring"]) == {"v1", "v2"}
    assert len(handoff["bearer_token"]) == 43
    assert "87" * 32 not in repr(manager)
