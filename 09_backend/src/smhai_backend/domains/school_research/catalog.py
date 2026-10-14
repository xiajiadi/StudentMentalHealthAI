"""Immutable school-scoped projections of trusted, unapproved research profiles."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .bootstrap import load_research_runtime
from .managed import (
    ManagedResearchProcessError,
    _parse_document,
    _read_config,
    _require_config_match,
    _validate_runtime_document,
    _validate_service_document,
)
from .trust import PublicationStatusProjection, TrustedResearchProfile

_SOURCE_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:-]{0,63}\Z")
_PROMIS_V3_PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
_PROMIS_V3_SOURCE_SCOPE = "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17"
_REPOSITORY_RIGHTS_DEFAULT = "PENDING"
_REPOSITORY_EXECUTION_DEFAULT = "CANDIDATE_RESEARCH_ONLY"


class SchoolResearchCatalogError(ValueError):
    """Stable, content-free catalog lookup or construction error."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "research_catalog_invalid"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ResearchProfilePublicMetadata:
    school_id: int
    profile_ref: str
    profile_schema: str
    source_family: str
    instrument_id: str
    instrument_family: str | None
    source_population: str | None
    source_version: str | None
    parameter_origin: str
    research_only: bool
    human_curated: bool
    psychological_interpretation_allowed: bool
    publication_status: str


@dataclass(frozen=True, slots=True)
class ResearchBindingPublicMetadata:
    school_id: int
    binding_ref: str
    profile_ref: str
    config_version: str
    research_only: bool
    publication_status: str


@dataclass(frozen=True, slots=True, repr=False)
class RepositoryResearchProfileInput:
    """Typed `profile=` value accepted by SchoolResearchCatRepository.

    The raw bytes are deliberately excluded from repr and remain exact source
    bytes. Rights and execution defaults are candidate-only; callers still
    provide school, version, role, and any missing source-population scope.
    """

    profile_id: str
    profile_type: str
    instrument_id: str
    dimension: str
    file_sha256: str
    manifest_sha256: str
    raw_profile_bytes: bytes = field(repr=False)
    research_only: bool = True
    publication_status: str = "not_approved_for_publication_or_operational_use"
    psychological_interpretation_allowed: bool = False
    human_curated: bool = False


@dataclass(frozen=True, slots=True, repr=False)
class ResearchProfileRepositoryProjection:
    school_id: int
    profile: RepositoryResearchProfileInput = field(repr=False)
    expected_profile_sha256: str
    expected_manifest_sha256: str
    source_population_scope: str | None
    rights_status: str = _REPOSITORY_RIGHTS_DEFAULT
    execution_status: str = _REPOSITORY_EXECUTION_DEFAULT

    def create_profile_version_kwargs(self) -> dict[str, object]:
        """Return safe candidate defaults plus fields required by the DB method.

        The caller must add `version_number` and `creator_membership_role_id`.
        Profiles without a trusted source-population code fail closed here.
        """

        if self.source_population_scope is None:
            raise SchoolResearchCatalogError("source_population_scope_unavailable")
        return {
            "school_id": self.school_id,
            "source_population_scope": self.source_population_scope,
            "profile": self.profile,
            "expected_profile_sha256": self.expected_profile_sha256,
            "expected_manifest_sha256": self.expected_manifest_sha256,
            "rights_status": self.rights_status,
            "execution_status": self.execution_status,
        }


@dataclass(frozen=True, slots=True, repr=False)
class ResearchProfileSelection:
    public: ResearchProfilePublicMetadata
    trusted_profile: TrustedResearchProfile = field(repr=False)
    repository: ResearchProfileRepositoryProjection = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchBindingSelection:
    public: ResearchBindingPublicMetadata
    config_sha256: str = field(repr=False)
    _canonical_cat_config_json: str = field(repr=False)

    def cat_config_copy(self) -> dict[str, Any]:
        """Return a new mutable JSON object without exposing catalog storage."""

        value = json.loads(self._canonical_cat_config_json)
        if type(value) is not dict:
            raise SchoolResearchCatalogError("binding_catalog_invalid")
        return value


@dataclass(frozen=True, slots=True, repr=False)
class SchoolResearchCatalog:
    """Immutable registry snapshot for exactly one configured school."""

    school_id: int
    _profiles: Mapping[str, ResearchProfileSelection] = field(repr=False)
    _bindings: Mapping[str, ResearchBindingSelection] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.school_id) is not int or self.school_id <= 0:
            raise SchoolResearchCatalogError("school_id_invalid")
        profiles = dict(self._profiles)
        bindings = dict(self._bindings)
        if any(
            type(ref) is not str
            or type(selection) is not ResearchProfileSelection
            or ref != selection.public.profile_ref
            or selection.public.school_id != self.school_id
            for ref, selection in profiles.items()
        ):
            raise SchoolResearchCatalogError("profile_catalog_invalid")
        if any(
            type(ref) is not str
            or type(selection) is not ResearchBindingSelection
            or ref != selection.public.binding_ref
            or selection.public.school_id != self.school_id
            for ref, selection in bindings.items()
        ):
            raise SchoolResearchCatalogError("binding_catalog_invalid")
        if any(selection.public.profile_ref not in profiles for selection in bindings.values()):
            raise SchoolResearchCatalogError("binding_profile_missing")
        object.__setattr__(self, "_profiles", MappingProxyType(profiles))
        object.__setattr__(self, "_bindings", MappingProxyType(bindings))

    def __repr__(self) -> str:
        return (
            "SchoolResearchCatalog("
            f"school_id={self.school_id}, profile_count={len(self._profiles)}, "
            f"binding_count={len(self._bindings)}, content=<redacted>)"
        )

    @property
    def public_profiles(self) -> tuple[ResearchProfilePublicMetadata, ...]:
        return tuple(selection.public for selection in self._profiles.values())

    @property
    def public_bindings(self) -> tuple[ResearchBindingPublicMetadata, ...]:
        return tuple(selection.public for selection in self._bindings.values())

    def select_profile(
        self, profile_ref: str, *, school_id: int | None = None
    ) -> ResearchProfileSelection:
        self._require_school(school_id)
        if type(profile_ref) is not str:
            raise SchoolResearchCatalogError("profile_ref_invalid")
        selection = self._profiles.get(profile_ref)
        if selection is None:
            raise SchoolResearchCatalogError("profile_not_in_catalog")
        return selection

    def select_binding(
        self, binding_ref: str, *, school_id: int | None = None
    ) -> ResearchBindingSelection:
        self._require_school(school_id)
        if type(binding_ref) is not str:
            raise SchoolResearchCatalogError("binding_ref_invalid")
        selection = self._bindings.get(binding_ref)
        if selection is None:
            raise SchoolResearchCatalogError("binding_not_in_catalog")
        return selection

    def _require_school(self, supplied: int | None) -> None:
        if supplied is not None and (type(supplied) is not int or supplied != self.school_id):
            raise SchoolResearchCatalogError("school_scope_mismatch")


def build_school_research_catalog(
    *,
    runtime_config_file: Path,
    expected_runtime_config_sha256: str,
    service_config_file: Path,
    expected_service_config_sha256: str,
    school_id: int,
    retained_key_provider: Any,
) -> SchoolResearchCatalog:
    """Load both matching server pins and materialize immutable catalog selectors.

    The key provider is only attached to the existing Backend runtime loader;
    catalog creation neither asks it for a key nor enables a profile/binding.
    """

    if type(school_id) is not int or school_id <= 0:
        raise SchoolResearchCatalogError("school_id_invalid")
    try:
        runtime_raw = _read_config(runtime_config_file, expected_runtime_config_sha256)
        service_raw = _read_config(service_config_file, expected_service_config_sha256)
        runtime_document = _parse_document(runtime_raw, "runtime_config_invalid")
        service_document = _parse_document(service_raw, "service_config_invalid")
        runtime_view = _validate_runtime_document(runtime_document)
        service_view = _validate_service_document(service_document)
        _require_config_match(runtime_view, service_view)
        if runtime_view.school_id != school_id:
            raise SchoolResearchCatalogError("school_scope_mismatch")

        # Reuse the actual Backend registry parser, hash checks and manifest
        # validation instead of interpreting source artifacts independently.
        runtime = load_research_runtime(
            configuration_file=runtime_config_file,
            expected_sha256=expected_runtime_config_sha256,
            loopback_base_url=service_view.base_url,
            retained_key_provider=retained_key_provider,
        )
        profiles: dict[str, ResearchProfileSelection] = {}
        for profile_ref, pin in runtime_view.profiles.items():
            trusted = runtime._registry.load(profile_ref)
            if (
                trusted.profile_ref != profile_ref
                or trusted.profile_schema != pin["profile_schema"]
                or trusted.profile_sha256 != pin["profile_sha256"]
                or trusted.manifest_sha256 != pin["manifest_sha256"]
                or trusted.repository_schema_compatible is not True
            ):
                raise SchoolResearchCatalogError("profile_registry_mismatch")
            profile_document = _parse_document(
                trusted.raw_profile_bytes, "profile_projection_invalid"
            )
            public, repository = _profile_projections(
                school_id=school_id,
                trusted=trusted,
                document=profile_document,
            )
            profiles[profile_ref] = ResearchProfileSelection(
                public=public,
                trusted_profile=trusted,
                repository=repository,
            )

        raw_bindings = service_document.get("bindings")
        if type(raw_bindings) is not list:
            raise SchoolResearchCatalogError("binding_catalog_invalid")
        bindings: dict[str, ResearchBindingSelection] = {}
        for binding in raw_bindings:
            if type(binding) is not dict:
                raise SchoolResearchCatalogError("binding_catalog_invalid")
            binding_ref = binding["binding_ref"]
            profile_ref = binding["profile_ref"]
            if profile_ref not in profiles:
                raise SchoolResearchCatalogError("binding_profile_missing")
            config_version = binding["config_version"]
            config_sha256 = binding["config_sha256"]
            canonical_config = _canonical_json(binding["cat_config"])
            bindings[binding_ref] = ResearchBindingSelection(
                public=ResearchBindingPublicMetadata(
                    school_id=school_id,
                    binding_ref=binding_ref,
                    profile_ref=profile_ref,
                    config_version=config_version,
                    research_only=True,
                    publication_status="not_approved_for_publication_or_operational_use",
                ),
                config_sha256=config_sha256,
                _canonical_cat_config_json=canonical_config,
            )

        return SchoolResearchCatalog(
            school_id=school_id,
            _profiles=MappingProxyType(profiles),
            _bindings=MappingProxyType(bindings),
        )
    except SchoolResearchCatalogError:
        raise
    except ManagedResearchProcessError:
        raise SchoolResearchCatalogError("catalog_configuration_invalid") from None
    except Exception:
        raise SchoolResearchCatalogError("catalog_configuration_invalid") from None


def _profile_projections(
    *,
    school_id: int,
    trusted: TrustedResearchProfile,
    document: Mapping[str, Any],
) -> tuple[ResearchProfilePublicMetadata, ResearchProfileRepositoryProjection]:
    if not document or document.get("profile_id") != trusted.profile_ref:
        raise SchoolResearchCatalogError("profile_projection_invalid")
    instrument_id = _bounded_text(document.get("instrument_id"), "profile_projection_invalid")
    profile_type = _bounded_text(document.get("profile_type"), "profile_projection_invalid")
    dimension = _bounded_text(document.get("dimension"), "profile_projection_invalid")
    publication_status = _bounded_text(
        document.get("publication_status"), "profile_projection_invalid"
    )
    research_only = document.get("research_only")
    human_curated = document.get("human_curated", False)
    interpretation_allowed = document.get("psychological_interpretation_allowed")
    if (
        type(research_only) is not bool
        or research_only is not True
        or type(human_curated) is not bool
        or human_curated is not False
        or type(interpretation_allowed) is not bool
        or interpretation_allowed is not False
        or trusted.publication_status_projection is not PublicationStatusProjection.NOT_APPROVED
    ):
        raise SchoolResearchCatalogError("profile_status_invalid")

    source_population = _source_population(document)
    source_version = _source_version(document)
    instrument_family = document.get("instrument_family")
    if instrument_family is not None:
        instrument_family = _bounded_text(instrument_family, "profile_projection_invalid")
    public = ResearchProfilePublicMetadata(
        school_id=school_id,
        profile_ref=trusted.profile_ref,
        profile_schema=trusted.profile_schema,
        source_family=trusted.source_family,
        instrument_id=instrument_id,
        instrument_family=instrument_family,
        source_population=source_population,
        source_version=source_version,
        parameter_origin=trusted.parameter_origin.value,
        research_only=True,
        human_curated=False,
        psychological_interpretation_allowed=False,
        publication_status=publication_status,
    )

    repository_profile = RepositoryResearchProfileInput(
        profile_id=trusted.profile_ref,
        profile_type=profile_type,
        instrument_id=instrument_id,
        dimension=dimension,
        file_sha256=trusted.profile_sha256,
        manifest_sha256=trusted.manifest_sha256,
        raw_profile_bytes=trusted.raw_profile_bytes,
        research_only=True,
        publication_status=publication_status,
        psychological_interpretation_allowed=False,
        human_curated=False,
    )
    source_population_scope = _repository_source_population_scope(
        profile_ref=trusted.profile_ref,
        profile_schema=trusted.profile_schema,
        document=document,
    )
    repository = ResearchProfileRepositoryProjection(
        school_id=school_id,
        profile=repository_profile,
        expected_profile_sha256=trusted.profile_sha256,
        expected_manifest_sha256=trusted.manifest_sha256,
        source_population_scope=source_population_scope,
    )
    return public, repository


def _source_population(document: Mapping[str, Any]) -> str | None:
    source = document.get("source_data")
    if isinstance(source, Mapping):
        observed = source.get("observed_response_source")
        if isinstance(observed, Mapping):
            value = observed.get("population")
            if type(value) is str and value.strip() and len(value) <= 512:
                return value
    source = document.get("source")
    if isinstance(source, Mapping):
        value = source.get("population")
        if type(value) is str and value.strip() and len(value) <= 512:
            return value
    return None


def _source_version(document: Mapping[str, Any]) -> str | None:
    model = document.get("model")
    if isinstance(model, Mapping):
        value = model.get("parameter_version")
        if type(value) is str and value.strip() and len(value) <= 128:
            return value
    return None


def _repository_source_population_scope(
    *,
    profile_ref: str,
    profile_schema: str,
    document: Mapping[str, Any],
) -> str | None:
    if profile_schema == "psynova.research-profile.v3":
        if profile_ref == _PROMIS_V3_PROFILE_REF:
            return _PROMIS_V3_SOURCE_SCOPE
        return None
    source = document.get("source")
    if isinstance(source, Mapping):
        candidate = source.get("source_population_scope")
        if type(candidate) is str and _SOURCE_SCOPE.fullmatch(candidate):
            return candidate
    return None


def _bounded_text(value: object, code: str, *, limit: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise SchoolResearchCatalogError(code)
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise SchoolResearchCatalogError("binding_config_invalid") from None
