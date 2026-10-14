"""Explicit, pinned construction of the private CAT child process manager.

This module does not launch a process at import time and does not import the
CAT engine or database/key modules until the factory is explicitly called.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .bootstrap import load_research_runtime
from .process import ResearchCATProcessManager, ResearchCATProcessSpec

_SERVICE_SCHEMA = "psynova.research-cat-service.v1"
_HANDSHAKE_SCHEMA = "psynova.research-service-keys.v1"
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_HANDSHAKE_BYTES = 16 * 1024
_REPARSE_POINT = 0x400
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_VERSION = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SCOPE = re.compile(r"school:[1-9][0-9]{0,17}\Z")
_BEARER = re.compile(r"[A-Za-z0-9_-]{32,512}\Z")

_RUNTIME_FIELDS = frozenset(
    {
        "schema",
        "school_id",
        "resource_root",
        "signing_version",
        "accepted_key_versions",
        "profiles",
        "bindings",
    }
)
_RUNTIME_PROFILE_FIELDS = frozenset(
    {
        "profile_ref",
        "profile_schema",
        "expected_profile_sha256",
        "expected_manifest_sha256",
        "source_family",
        "parameter_origin",
        "profile_path",
        "manifest_path",
        "expected_fit_sha256",
        "expected_calibration_sha256",
    }
)
_RUNTIME_BINDING_FIELDS = frozenset(
    {"binding_ref", "profile_ref", "config_version", "config_sha256"}
)
_SERVICE_FIELDS = frozenset(
    {
        "schema",
        "school_scope",
        "resource_root",
        "listener",
        "signing",
        "profiles",
        "bindings",
    }
)
_SERVICE_PROFILE_FIELDS = frozenset(
    {
        "profile_ref",
        "profile_schema",
        "profile_path",
        "profile_sha256",
        "manifest_path",
        "manifest_sha256",
    }
)
_SERVICE_BINDING_FIELDS = frozenset(
    {"binding_ref", "profile_ref", "config_version", "config_sha256", "cat_config"}
)
_SCOPE_FIELDS = frozenset({"school_id", "scope"})
_LISTENER_FIELDS = frozenset({"host", "port"})
_SIGNING_FIELDS = frozenset({"signing_version", "accepted_key_versions"})
_CAT_CONFIG_FIELDS = frozenset(
    {
        "config_version",
        "model",
        "estimator",
        "selection_method",
        "min_items",
        "max_items",
        "se_threshold",
        "initial_theta",
        "prior_mean",
        "prior_sd",
        "optimization_interval",
        "seed",
        "exposure_control",
        "content_balancing",
    }
)


class ManagedResearchProcessError(ValueError):
    """Fixed-code factory failure that never includes paths or secret values."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "managed_process_invalid"
        self.code = code
        super().__init__(code)


def build_managed_research_process(
    *,
    runtime_config_file: Path,
    expected_runtime_config_sha256: str,
    service_config_file: Path,
    expected_service_config_sha256: str,
    cat_source: Path,
    cat_dependency_path: Path | None,
    base_executable: Path,
    base_executable_probe: Callable[[Path], bool],
    retained_key_provider: Any,
    readiness_probe: Callable[[int, bytes, float], Mapping[str, object]],
    listener_owner_probe: Callable[[int, int], bool],
    port_available_probe: Callable[[int], bool] | None = None,
) -> ResearchCATProcessManager:
    """Build, but do not start, a CAT manager from two matching pinned configs.

    The Backend registry is loaded first to verify its pinned public resources.
    The CAT service document is then required to describe the exact same school,
    profiles, bindings, versions, CAT configs, and loopback listener. Only after
    both documents validate are purpose-separated derived keys placed in the
    process manager's one-shot stdin handoff.
    """

    try:
        runtime_path = _resolve_existing(runtime_config_file, "runtime_config_invalid")
        service_path = _resolve_existing(service_config_file, "service_config_invalid")
        runtime_raw = _read_config(runtime_path, expected_runtime_config_sha256)
        service_raw = _read_config(service_path, expected_service_config_sha256)
        runtime_doc = _parse_document(runtime_raw, "runtime_config_invalid")
        service_doc = _parse_document(service_raw, "service_config_invalid")
        runtime_view = _validate_runtime_document(runtime_doc)
        service_view = _validate_service_document(service_doc)
        _require_config_match(runtime_view, service_view)

        cat_source_path = _resolve_existing(cat_source, "cat_source_invalid")
        if not cat_source_path.is_dir():
            raise ManagedResearchProcessError("cat_source_invalid")
        serve_entry = cat_source_path / "cat_engine" / "research" / "serve.py"
        _assert_no_reparse_components(serve_entry, "cat_source_invalid")
        if not serve_entry.is_file():
            raise ManagedResearchProcessError("cat_source_invalid")

        if cat_dependency_path is None:
            dependency_path = None
        else:
            dependency_path = _resolve_existing(cat_dependency_path, "cat_dependency_invalid")
            if not dependency_path.is_dir():
                raise ManagedResearchProcessError("cat_dependency_invalid")

        base_path = _resolve_existing(base_executable, "base_executable_invalid")
        if not base_path.is_file() or not callable(base_executable_probe):
            raise ManagedResearchProcessError("base_executable_invalid")
        try:
            probe_valid = base_executable_probe(base_path)
        except Exception:
            raise ManagedResearchProcessError("base_executable_probe_failed") from None
        if probe_valid is not True:
            raise ManagedResearchProcessError("base_executable_probe_failed")

        # The existing Backend loader validates versioned registry entries and
        # exact profile/manifest bytes. It does not approve or enable profiles.
        try:
            load_research_runtime(
                configuration_file=runtime_path,
                expected_sha256=expected_runtime_config_sha256,
                loopback_base_url=service_view.base_url,
                retained_key_provider=retained_key_provider,
            )
        except Exception:
            raise ManagedResearchProcessError("backend_registry_invalid") from None

        handshake = _make_derived_handoff(
            retained_key_provider,
            school_scope=service_view.school_scope,
            signing_version=service_view.signing_version,
            accepted_versions=service_view.accepted_versions,
        )
        spec = ResearchCATProcessSpec(
            python_executable=base_path,
            cat_source=cat_source_path,
            cat_dependency_path=dependency_path,
            serve_config_path=service_path,
            serve_config_sha256=expected_service_config_sha256,
            expected_registry_fingerprint=service_view.registry_fingerprint,
            expected_port=service_view.port,
            expected_binding_count=len(service_view.bindings),
            expected_school_scope=service_view.school_scope,
            derived_keys_handshake=handshake,
        )
        return ResearchCATProcessManager(
            spec,
            readiness_probe=readiness_probe,
            listener_owner_probe=listener_owner_probe,
            port_available_probe=port_available_probe,
        )
    except ManagedResearchProcessError:
        raise
    except Exception:
        raise ManagedResearchProcessError("managed_process_invalid") from None


class _RuntimeView:
    __slots__ = (
        "school_id",
        "school_scope",
        "resource_root",
        "signing_version",
        "accepted_versions",
        "profiles",
        "bindings",
    )

    def __init__(
        self,
        *,
        school_id: int,
        resource_root: Path,
        signing_version: str,
        accepted_versions: tuple[str, ...],
        profiles: dict[str, dict[str, object]],
        bindings: dict[str, tuple[str, str, str]],
    ) -> None:
        self.school_id = school_id
        self.school_scope = f"school:{school_id}"
        self.resource_root = resource_root
        self.signing_version = signing_version
        self.accepted_versions = accepted_versions
        self.profiles = profiles
        self.bindings = bindings


class _ServiceView(_RuntimeView):
    __slots__ = ("base_url", "port", "registry_fingerprint")

    def __init__(self, *, base_url: str, port: int, registry_fingerprint: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.base_url = base_url
        self.port = port
        self.registry_fingerprint = registry_fingerprint


def _validate_runtime_document(document: dict[str, Any]) -> _RuntimeView:
    if (
        set(document) != _RUNTIME_FIELDS
        or document.get("schema") != "psynova.school-research-runtime.v1"
    ):
        raise ManagedResearchProcessError("runtime_config_schema_invalid")
    school_id = document.get("school_id")
    root = _configured_root(document.get("resource_root"), "runtime_resource_root_invalid")
    signing_version, accepted = _validate_versions(
        document.get("signing_version"), document.get("accepted_key_versions")
    )

    raw_profiles = document.get("profiles")
    raw_bindings = document.get("bindings")
    if (
        type(raw_profiles) is not list
        or not 1 <= len(raw_profiles) <= 64
        or type(raw_bindings) is not list
        or not 1 <= len(raw_bindings) <= 128
    ):
        raise ManagedResearchProcessError("runtime_registry_invalid")
    profiles: dict[str, dict[str, object]] = {}
    for entry in raw_profiles:
        if type(entry) is not dict or set(entry) != _RUNTIME_PROFILE_FIELDS:
            raise ManagedResearchProcessError("runtime_profile_invalid")
        ref = _safe_ref(entry.get("profile_ref"), "runtime_profile_invalid")
        schema = entry.get("profile_schema")
        if schema not in {
            "psynova.research-profile.v1",
            "psynova.research-profile.v2",
            "psynova.research-profile.v3",
        }:
            raise ManagedResearchProcessError("runtime_profile_invalid")
        profile_path = _resource_file(entry.get("profile_path"), root)
        manifest_path = _resource_file(entry.get("manifest_path"), root)
        if profile_path == manifest_path or ref in profiles:
            raise ManagedResearchProcessError("runtime_profile_invalid")
        profile_sha = _sha(entry.get("expected_profile_sha256"), "runtime_profile_invalid")
        manifest_sha = _sha(entry.get("expected_manifest_sha256"), "runtime_profile_invalid")
        source_family = entry.get("source_family")
        origin = entry.get("parameter_origin")
        if (
            type(source_family) is not str
            or not source_family
            or type(origin) is not str
            or not origin
        ):
            raise ManagedResearchProcessError("runtime_profile_invalid")
        for field_name in ("expected_fit_sha256", "expected_calibration_sha256"):
            optional_hash = entry.get(field_name)
            if optional_hash is not None:
                _sha(optional_hash, "runtime_profile_invalid")
        profiles[ref] = {
            "profile_ref": ref,
            "profile_schema": schema,
            "profile_path": profile_path,
            "profile_sha256": profile_sha,
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_sha,
        }

    bindings: dict[str, tuple[str, str, str]] = {}
    for entry in raw_bindings:
        if type(entry) is not dict or set(entry) != _RUNTIME_BINDING_FIELDS:
            raise ManagedResearchProcessError("runtime_binding_invalid")
        ref = _safe_ref(entry.get("binding_ref"), "runtime_binding_invalid")
        profile_ref = _safe_ref(entry.get("profile_ref"), "runtime_binding_invalid")
        version = _safe_ref(entry.get("config_version"), "runtime_binding_invalid")
        digest = _sha(entry.get("config_sha256"), "runtime_binding_invalid")
        if ref in bindings or profile_ref not in profiles:
            raise ManagedResearchProcessError("runtime_binding_invalid")
        bindings[ref] = (profile_ref, version, digest)

    return _RuntimeView(
        school_id=_school_id(school_id),
        resource_root=root,
        signing_version=signing_version,
        accepted_versions=accepted,
        profiles=profiles,
        bindings=bindings,
    )


def _validate_service_document(document: dict[str, Any]) -> _ServiceView:
    if set(document) != _SERVICE_FIELDS or document.get("schema") != _SERVICE_SCHEMA:
        raise ManagedResearchProcessError("service_config_schema_invalid")
    scope = document.get("school_scope")
    if type(scope) is not dict or set(scope) != _SCOPE_FIELDS:
        raise ManagedResearchProcessError("service_school_scope_invalid")
    school_id = _school_id(scope.get("school_id"))
    school_scope = scope.get("scope")
    if (
        type(school_scope) is not str
        or school_scope != f"school:{school_id}"
        or not _SCOPE.fullmatch(school_scope)
    ):
        raise ManagedResearchProcessError("service_school_scope_invalid")
    root = _configured_root(document.get("resource_root"), "service_resource_root_invalid")
    listener = document.get("listener")
    if (
        type(listener) is not dict
        or set(listener) != _LISTENER_FIELDS
        or listener.get("host") != "127.0.0.1"
        or type(listener.get("port")) is not int
        or not 1 <= listener["port"] <= 65535
    ):
        raise ManagedResearchProcessError("service_listener_invalid")
    signing = document.get("signing")
    if type(signing) is not dict or set(signing) != _SIGNING_FIELDS:
        raise ManagedResearchProcessError("service_signing_invalid")
    signing_version, accepted = _validate_versions(
        signing.get("signing_version"), signing.get("accepted_key_versions")
    )

    raw_profiles = document.get("profiles")
    raw_bindings = document.get("bindings")
    if (
        type(raw_profiles) is not list
        or not 1 <= len(raw_profiles) <= 64
        or type(raw_bindings) is not list
        or not 1 <= len(raw_bindings) <= 128
    ):
        raise ManagedResearchProcessError("service_registry_invalid")
    profiles: dict[str, dict[str, object]] = {}
    for entry in raw_profiles:
        if type(entry) is not dict or set(entry) != _SERVICE_PROFILE_FIELDS:
            raise ManagedResearchProcessError("service_profile_invalid")
        ref = _safe_ref(entry.get("profile_ref"), "service_profile_invalid")
        schema = entry.get("profile_schema")
        if schema not in {
            "psynova.research-profile.v1",
            "psynova.research-profile.v2",
            "psynova.research-profile.v3",
        }:
            raise ManagedResearchProcessError("service_profile_invalid")
        profile_path = _resource_file(entry.get("profile_path"), root)
        manifest_path = _resource_file(entry.get("manifest_path"), root)
        if profile_path == manifest_path or ref in profiles:
            raise ManagedResearchProcessError("service_profile_invalid")
        profiles[ref] = {
            "profile_ref": ref,
            "profile_schema": schema,
            "profile_path": profile_path,
            "profile_sha256": _sha(entry.get("profile_sha256"), "service_profile_invalid"),
            "manifest_path": manifest_path,
            "manifest_sha256": _sha(entry.get("manifest_sha256"), "service_profile_invalid"),
        }

    bindings: dict[str, tuple[str, str, str]] = {}
    for entry in raw_bindings:
        if type(entry) is not dict or set(entry) != _SERVICE_BINDING_FIELDS:
            raise ManagedResearchProcessError("service_binding_invalid")
        ref = _safe_ref(entry.get("binding_ref"), "service_binding_invalid")
        profile_ref = _safe_ref(entry.get("profile_ref"), "service_binding_invalid")
        config_version = _safe_ref(entry.get("config_version"), "service_binding_invalid")
        config_sha = _sha(entry.get("config_sha256"), "service_binding_invalid")
        cat_config = entry.get("cat_config")
        if ref in bindings or profile_ref not in profiles:
            raise ManagedResearchProcessError("service_binding_invalid")
        _validate_cat_config(cat_config, config_version, config_sha)
        bindings[ref] = (profile_ref, config_version, config_sha)

    base_url = f"http://127.0.0.1:{listener['port']}"
    return _ServiceView(
        school_id=school_id,
        resource_root=root,
        signing_version=signing_version,
        accepted_versions=accepted,
        profiles=profiles,
        bindings=bindings,
        base_url=base_url,
        port=listener["port"],
        registry_fingerprint=_registry_fingerprint(profiles, bindings),
    )


def _require_config_match(runtime: _RuntimeView, service: _ServiceView) -> None:
    if (
        runtime.school_id != service.school_id
        or runtime.resource_root != service.resource_root
        or runtime.signing_version != service.signing_version
        or set(runtime.accepted_versions) != set(service.accepted_versions)
        or runtime.profiles != service.profiles
        or runtime.bindings != service.bindings
    ):
        raise ManagedResearchProcessError("backend_cat_config_mismatch")


def _validate_cat_config(value: object, version: str, expected_sha256: str) -> None:
    if type(value) is not dict or set(value) != _CAT_CONFIG_FIELDS:
        raise ManagedResearchProcessError("cat_config_invalid")
    if value.get("config_version") != version:
        raise ManagedResearchProcessError("cat_config_invalid")
    if value.get("model") not in {"GRM", "GPCM"}:
        raise ManagedResearchProcessError("cat_config_invalid")
    if value.get("estimator") not in {"EAP", "BM"}:
        raise ManagedResearchProcessError("cat_config_invalid")
    if value.get("selection_method") != "MFI":
        raise ManagedResearchProcessError("cat_config_invalid")
    minimum = value.get("min_items")
    maximum = value.get("max_items")
    if type(minimum) is not int or type(maximum) is not int or minimum < 1 or maximum < minimum:
        raise ManagedResearchProcessError("cat_config_invalid")
    threshold = value.get("se_threshold")
    if threshold is not None and (
        type(threshold) not in {int, float} or not math.isfinite(threshold) or threshold <= 0
    ):
        raise ManagedResearchProcessError("cat_config_invalid")
    for name in ("initial_theta", "prior_mean", "prior_sd"):
        number = value.get(name)
        if type(number) not in {int, float} or not math.isfinite(number):
            raise ManagedResearchProcessError("cat_config_invalid")
    if value["prior_sd"] <= 0:
        raise ManagedResearchProcessError("cat_config_invalid")
    interval = value.get("optimization_interval")
    if (
        type(interval) is not list
        or len(interval) != 2
        or any(type(point) not in {int, float} or not math.isfinite(point) for point in interval)
        or interval[0] >= interval[1]
    ):
        raise ManagedResearchProcessError("cat_config_invalid")
    seed = value.get("seed")
    if seed is not None and (type(seed) is not int or seed < 0):
        raise ManagedResearchProcessError("cat_config_invalid")
    if value.get("exposure_control") != "none" or value.get("content_balancing") != "none":
        raise ManagedResearchProcessError("cat_config_invalid")
    try:
        canonical = _canonical_json(value).encode("utf-8")
    except (TypeError, ValueError):
        raise ManagedResearchProcessError("cat_config_invalid") from None
    if not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), expected_sha256):
        raise ManagedResearchProcessError("cat_config_hash_mismatch")


def _make_derived_handoff(
    provider: Any,
    *,
    school_scope: str,
    signing_version: str,
    accepted_versions: tuple[str, ...],
) -> bytes:
    try:
        from database_layer.research_keys import (
            ResearchSnapshotKeyring,
            derive_research_service_bearer,
            derive_research_snapshot_mac_key,
        )

        provider_versions = provider.versions()
        if (
            type(provider_versions) is not tuple
            or any(type(item) is not str for item in provider_versions)
            or not set(accepted_versions).issubset(provider_versions)
        ):
            raise ValueError
        keyring = ResearchSnapshotKeyring(
            provider,
            school_scope=school_scope,
            signing_version=signing_version,
            accepted_versions=accepted_versions,
        )
        bearer = derive_research_service_bearer(
            provider,
            key_version=signing_version,
            school_scope=school_scope,
        )
        bearer_text = bearer.decode("ascii")
        if _BEARER.fullmatch(bearer_text) is None:
            raise ValueError

        probe_payload = b"psynova managed CAT key-purpose compatibility v1"
        encoded_keys: dict[str, str] = {}
        for version in accepted_versions:
            key = derive_research_snapshot_mac_key(
                provider, key_version=version, school_scope=school_scope
            )
            if type(key) is not bytes or len(key) != 32:
                raise ValueError
            probe_signature = (
                "rk1." + version + "." + hmac.new(key, probe_payload, hashlib.sha256).hexdigest()
            )
            if keyring.verify(probe_payload, probe_signature) is not True:
                raise ValueError
            encoded_keys[version] = base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")

        document = {
            "schema": _HANDSHAKE_SCHEMA,
            "bearer_token": bearer_text,
            "signing_version": signing_version,
            "keyring": encoded_keys,
        }
        handoff = (_canonical_json(document) + "\n").encode("ascii")
        if len(handoff) > _MAX_HANDSHAKE_BYTES:
            raise ValueError
        return handoff
    except Exception:
        raise ManagedResearchProcessError("derived_handoff_unavailable") from None


def _read_config(path: Path, expected_sha256: str) -> bytes:
    if type(expected_sha256) is not str or _SHA256.fullmatch(expected_sha256) is None:
        raise ManagedResearchProcessError("config_hash_invalid")
    try:
        _assert_no_reparse_components(path, "config_file_unavailable")
        with path.open("rb") as stream:
            raw = stream.read(_MAX_CONFIG_BYTES + 1)
    except ManagedResearchProcessError:
        raise
    except Exception:
        raise ManagedResearchProcessError("config_file_unavailable") from None
    if not raw or len(raw) > _MAX_CONFIG_BYTES:
        raise ManagedResearchProcessError("config_size_invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        raise ManagedResearchProcessError("config_hash_mismatch")
    return raw


def _parse_document(raw: bytes, code: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ManagedResearchProcessError(code) from None
    if type(value) is not dict:
        raise ManagedResearchProcessError(code)
    return value


def _resolve_existing(value: object, code: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        raise ManagedResearchProcessError(code)
    try:
        _assert_no_reparse_components(value, code)
        return value.resolve(strict=True)
    except ManagedResearchProcessError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ManagedResearchProcessError(code) from None


def _assert_no_reparse_components(path: Path, code: str) -> None:
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
                raise ManagedResearchProcessError(code)
    except ManagedResearchProcessError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ManagedResearchProcessError(code) from None


def _configured_root(value: object, code: str) -> Path:
    root = _resolve_existing(Path(value) if type(value) is str else value, code)
    if not root.is_dir():
        raise ManagedResearchProcessError(code)
    return root


def _resource_file(value: object, root: Path) -> Path:
    path = _resolve_existing(Path(value) if type(value) is str else value, "resource_path_invalid")
    if not path.is_file() or path == root or root not in path.parents:
        raise ManagedResearchProcessError("resource_path_invalid")
    return path


def _validate_versions(signing: object, versions: object) -> tuple[str, tuple[str, ...]]:
    if (
        type(signing) is not str
        or not _VERSION.fullmatch(signing)
        or type(versions) is not list
        or not 1 <= len(versions) <= 32
        or any(type(item) is not str or not _VERSION.fullmatch(item) for item in versions)
        or len(set(versions)) != len(versions)
        or signing not in versions
    ):
        raise ManagedResearchProcessError("key_versions_invalid")
    return signing, tuple(versions)


def _school_id(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 999_999_999_999_999_999:
        raise ManagedResearchProcessError("school_id_invalid")
    return value


def _safe_ref(value: object, code: str) -> str:
    if type(value) is not str or not _REF.fullmatch(value):
        raise ManagedResearchProcessError(code)
    return value


def _sha(value: object, code: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ManagedResearchProcessError(code)
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _registry_fingerprint(
    profiles: Mapping[str, Mapping[str, object]],
    bindings: Mapping[str, tuple[str, str, str]],
) -> str:
    material = {
        "profiles": sorted(
            (
                {
                    "profile_ref": entry["profile_ref"],
                    "profile_schema": entry["profile_schema"],
                    "profile_sha256": entry["profile_sha256"],
                    "manifest_sha256": entry["manifest_sha256"],
                }
                for entry in profiles.values()
            ),
            key=lambda entry: str(entry["profile_ref"]),
        ),
        "bindings": sorted(
            (
                {
                    "binding_ref": ref,
                    "profile_ref": pin[0],
                    "config_version": pin[1],
                    "config_sha256": pin[2],
                }
                for ref, pin in bindings.items()
            ),
            key=lambda entry: str(entry["binding_ref"]),
        ),
    }
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()
