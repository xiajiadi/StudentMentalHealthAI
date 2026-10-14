"""Pinned server configuration; contains no keys and grants no profile eligibility."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any

from .runtime import ResearchCATBindingPin, ResearchCATRuntime, ResearchCATRuntimeError
from .trust import (
    ParameterOrigin,
    ResearchProfileRegistry,
    ResearchProfileRegistryEntry,
    _assert_no_reparse_components,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CONFIG_BYTES = 1024 * 1024
_ROOT_FIELDS = frozenset({
    "schema", "school_id", "resource_root", "signing_version",
    "accepted_key_versions", "profiles", "bindings",
})
_PROFILE_FIELDS = frozenset({
    "profile_ref", "profile_schema", "expected_profile_sha256",
    "expected_manifest_sha256", "source_family", "parameter_origin",
    "profile_path", "manifest_path", "expected_fit_sha256",
    "expected_calibration_sha256",
})
_BINDING_FIELDS = frozenset({"binding_ref", "profile_ref", "config_version", "config_sha256"})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError


def _absolute_path(value: object) -> Path:
    if type(value) is not str or not value:
        raise ValueError
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError
    return path


def load_research_runtime(
    *, configuration_file: Path, expected_sha256: str,
    loopback_base_url: str, retained_key_provider: Any,
) -> ResearchCATRuntime:
    """Load exact server-configured bytes, never a request-supplied path."""
    try:
        if (
            not isinstance(configuration_file, Path) or not configuration_file.is_absolute()
            or type(expected_sha256) is not str or not _SHA256.fullmatch(expected_sha256)
        ):
            raise ValueError
        _assert_no_reparse_components(configuration_file)
        with configuration_file.open("rb") as stream:
            raw = stream.read(_MAX_CONFIG_BYTES + 1)
        if not raw or len(raw) > _MAX_CONFIG_BYTES:
            raise ValueError
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
            raise ValueError
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
        if type(document) is not dict or set(document) != _ROOT_FIELDS:
            raise ValueError
        if document["schema"] != "psynova.school-research-runtime.v1":
            raise ValueError
        profiles, bindings = document["profiles"], document["bindings"]
        if (
            type(profiles) is not list or not 1 <= len(profiles) <= 64
            or type(bindings) is not list or not 1 <= len(bindings) <= 128
            or type(document["accepted_key_versions"]) is not list
        ):
            raise ValueError
        entries = []
        for entry in profiles:
            if type(entry) is not dict or set(entry) != _PROFILE_FIELDS:
                raise ValueError
            values = dict(entry)
            values["profile_path"] = _absolute_path(values["profile_path"])
            values["manifest_path"] = _absolute_path(values["manifest_path"])
            values["parameter_origin"] = ParameterOrigin(values["parameter_origin"])
            entries.append(ResearchProfileRegistryEntry(**values))
        pins = []
        for entry in bindings:
            if type(entry) is not dict or set(entry) != _BINDING_FIELDS:
                raise ValueError
            pins.append(ResearchCATBindingPin(**entry))
        profile_refs = {entry.profile_ref for entry in entries}
        if any(pin.profile_ref not in profile_refs for pin in pins):
            raise ValueError
        registry = ResearchProfileRegistry(
            allowed_root=_absolute_path(document["resource_root"]), entries=tuple(entries)
        )
        for entry in entries:
            registry.load(entry.profile_ref)
        return ResearchCATRuntime(
            profile_registry=registry, binding_pins=tuple(pins),
            loopback_base_url=loopback_base_url, school_id=document["school_id"],
            retained_key_provider=retained_key_provider,
            signing_version=document["signing_version"],
            accepted_key_versions=tuple(document["accepted_key_versions"]),
        )
    except Exception:
        raise ResearchCATRuntimeError("runtime_configuration_invalid") from None


def build_school_research_service(settings: Any, persistence: Any) -> Any | None:
    """Explicit configuration wires the lane; it never enables a DB profile/task."""
    if settings.school_research_enabled is not True:
        return None
    try:
        if persistence is None or settings.identity_profile != "school_tenant":
            raise ValueError
        runtime = load_research_runtime(
            configuration_file=Path(settings.school_research_runtime_file),
            expected_sha256=settings.school_research_runtime_sha256,
            loopback_base_url=settings.school_research_base_url,
            retained_key_provider=persistence.protection.key_provider,
        )
        from smhai_backend.adapters.school_research import SchoolResearchPersistenceAdapter
        from smhai_backend.domains.school_research.service import SchoolResearchService

        adapter = SchoolResearchPersistenceAdapter(
            persistence, client_for_binding=runtime.client_for_binding,
            study_use_policy=build_school_research_study_policy(settings),
        )
        return SchoolResearchService(persistence=adapter)
    except Exception:
        raise ResearchCATRuntimeError("runtime_configuration_invalid") from None


def build_school_research_profiles_service(settings: Any, persistence: Any) -> Any | None:
    """Compose candidate import from the same pinned, managed server registry."""
    if (
        settings.school_research_enabled is not True
        or getattr(settings, "school_research_managed_enabled", False) is not True
    ):
        return None
    try:
        if persistence is None or settings.identity_profile != "school_tenant":
            raise ValueError
        runtime = load_research_runtime(
            configuration_file=Path(settings.school_research_runtime_file),
            expected_sha256=settings.school_research_runtime_sha256,
            loopback_base_url=settings.school_research_base_url,
            retained_key_provider=persistence.protection.key_provider,
        )
        from smhai_backend.adapters.school_research_profiles import (
            SchoolResearchProfilesPersistenceAdapter,
        )
        from smhai_backend.domains.school_research.catalog import build_school_research_catalog
        from smhai_backend.domains.school_research_profiles.service import (
            SchoolResearchProfilesService,
        )

        catalog = build_school_research_catalog(
            runtime_config_file=Path(settings.school_research_runtime_file),
            expected_runtime_config_sha256=settings.school_research_runtime_sha256,
            service_config_file=Path(settings.school_research_service_file),
            expected_service_config_sha256=settings.school_research_service_sha256,
            school_id=runtime.school_id,
            retained_key_provider=persistence.protection.key_provider,
        )
        return SchoolResearchProfilesService(
            persistence=SchoolResearchProfilesPersistenceAdapter(
                persistence, catalog,
                study_use_policy=build_school_research_study_policy(settings),
                study_use_policy_sha256=getattr(settings, "school_research_study_use_sha256", None),
            )
        )
    except Exception:
        raise ResearchCATRuntimeError("runtime_configuration_invalid") from None


def build_school_research_study_policy(settings: Any) -> Any | None:
    """Load only server-pinned, limited historical replay scope; no approval grant."""
    path = getattr(settings, "school_research_study_use_file", None)
    if path is None:
        return None
    try:
        from .study_use import load_research_study_use_policy

        return load_research_study_use_policy(
            Path(path),
            expected_sha256=settings.school_research_study_use_sha256,
            source_rights_verified=settings.school_research_source_rights_verified,
            latest_allowed_ends_at=settings.school_research_latest_study_end,
        )
    except Exception:
        raise ResearchCATRuntimeError("study_use_configuration_invalid") from None


def build_school_research_tasks_service(settings: Any, persistence: Any) -> Any | None:
    """Compose administrator publishing without modifying profile eligibility."""
    if (
        settings.school_research_enabled is not True
        or getattr(settings, "school_research_managed_enabled", False) is not True
    ):
        return None
    try:
        if persistence is None or settings.identity_profile != "school_tenant":
            raise ValueError
        from smhai_backend.adapters.school_research_tasks import (
            SchoolResearchTasksPersistenceAdapter,
        )
        from smhai_backend.domains.school_research_tasks.service import SchoolResearchTasksService

        from .catalog import build_school_research_catalog

        runtime = load_research_runtime(
            configuration_file=Path(settings.school_research_runtime_file),
            expected_sha256=settings.school_research_runtime_sha256,
            loopback_base_url=settings.school_research_base_url,
            retained_key_provider=persistence.protection.key_provider,
        )
        catalog = build_school_research_catalog(
            runtime_config_file=Path(settings.school_research_runtime_file),
            expected_runtime_config_sha256=settings.school_research_runtime_sha256,
            service_config_file=Path(settings.school_research_service_file),
            expected_service_config_sha256=settings.school_research_service_sha256,
            school_id=runtime.school_id,
            retained_key_provider=persistence.protection.key_provider,
        )
        return SchoolResearchTasksService(persistence=SchoolResearchTasksPersistenceAdapter(
            persistence, catalog,
            study_use_policy=build_school_research_study_policy(settings),
            study_use_policy_sha256=getattr(settings, "school_research_study_use_sha256", None),
        ))
    except Exception:
        raise ResearchCATRuntimeError("runtime_configuration_invalid") from None
