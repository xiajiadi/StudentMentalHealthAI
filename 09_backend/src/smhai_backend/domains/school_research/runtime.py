"""Explicit factory for Backend-private research CAT HTTP clients.

This module is intentionally inert at import time. It does not load CAT,
database, profile bytes, or authentication key material until an explicitly
constructed runtime receives a matching binding metadata projection.
"""

from __future__ import annotations

import ipaddress
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_CONFIG_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_KEY_VERSION = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class ResearchCATRuntimeError(ValueError):
    """Stable runtime-construction failure without credential-bearing detail."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "runtime_configuration_invalid"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ResearchCATBindingPin:
    """Immutable server-owned binding identity and CAT configuration pin."""

    binding_ref: str
    profile_ref: str
    config_version: str
    config_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.binding_ref) is not str
            or not _REF.fullmatch(self.binding_ref)
            or type(self.profile_ref) is not str
            or not _REF.fullmatch(self.profile_ref)
            or type(self.config_version) is not str
            or not _CONFIG_VERSION.fullmatch(self.config_version)
            or type(self.config_sha256) is not str
            or not _SHA256.fullmatch(self.config_sha256)
        ):
            raise ResearchCATRuntimeError("binding_pin_invalid")


class ResearchCATRuntime:
    """Construct one short-lived client after exact DB metadata pin checks.

    The injected registry is the Backend trust registry. Its successful load
    verifies exact profile/manifest bytes and repository compatibility; it
    does not confer professional, rights, or publication approval.
    """

    __slots__ = (
        "_registry", "_pins", "_school_id", "_base_url", "_key_provider",
        "_signing_version", "_accepted_versions", "_timeout", "_initialized",
    )

    def __init__(
        self,
        *,
        profile_registry: Any,
        binding_pins: tuple[ResearchCATBindingPin, ...],
        loopback_base_url: str,
        school_id: int,
        retained_key_provider: Any,
        signing_version: str,
        accepted_key_versions: tuple[str, ...],
        timeout: float = 5.0,
    ) -> None:
        if not callable(getattr(profile_registry, "load", None)):
            raise ResearchCATRuntimeError("profile_registry_invalid")
        if type(binding_pins) is not tuple or not binding_pins or any(
            type(pin) is not ResearchCATBindingPin for pin in binding_pins
        ):
            raise ResearchCATRuntimeError("binding_pins_invalid")
        if len({pin.binding_ref for pin in binding_pins}) != len(binding_pins):
            raise ResearchCATRuntimeError("binding_pin_duplicate")
        if type(school_id) is not int or school_id <= 0:
            raise ResearchCATRuntimeError("school_id_invalid")
        if retained_key_provider is None or not all(
            callable(getattr(retained_key_provider, name, None))
            for name in ("get_key", "versions")
        ):
            raise ResearchCATRuntimeError("key_provider_invalid")
        if (
            type(signing_version) is not str
            or not _KEY_VERSION.fullmatch(signing_version)
            or type(accepted_key_versions) is not tuple
            or not accepted_key_versions
            or any(type(version) is not str or not _KEY_VERSION.fullmatch(version)
                   for version in accepted_key_versions)
            or len(set(accepted_key_versions)) != len(accepted_key_versions)
            or signing_version not in accepted_key_versions
        ):
            raise ResearchCATRuntimeError("key_versions_invalid")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ResearchCATRuntimeError("timeout_invalid")

        normalized_url = _validate_loopback_base_url(loopback_base_url)
        object.__setattr__(self, "_registry", profile_registry)
        object.__setattr__(
            self, "_pins", MappingProxyType({pin.binding_ref: pin for pin in binding_pins})
        )
        object.__setattr__(self, "_school_id", school_id)
        object.__setattr__(self, "_base_url", normalized_url)
        object.__setattr__(self, "_key_provider", retained_key_provider)
        object.__setattr__(self, "_signing_version", signing_version)
        object.__setattr__(self, "_accepted_versions", accepted_key_versions)
        object.__setattr__(self, "_timeout", float(timeout))
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_initialized", False):
            raise AttributeError("research CAT runtime configuration is immutable")
        object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return (
            "ResearchCATRuntime("
            f"school_id={self._school_id}, binding_count={len(self._pins)}, "
            f"signing_version={self._signing_version!r})"
        )

    @property
    def school_id(self) -> int:
        """Configured tenant identity; immutable and independent of a request."""
        return self._school_id

    def client_for_binding(self, database_metadata: object) -> Any:
        """Return a fresh client only when DB metadata matches explicit pins."""

        school_id = _metadata_value(database_metadata, "school_id")
        if type(school_id) is not int or school_id != self._school_id:
            raise ResearchCATRuntimeError("binding_school_mismatch")

        profile_ref = _metadata_value(database_metadata, "profile_ref")
        config_version = _metadata_value(database_metadata, "config_version")
        config_sha256 = _metadata_value(database_metadata, "config_sha256")
        profile_sha256 = _metadata_value(database_metadata, "profile_sha256")
        if (
            type(profile_ref) is not str
            or type(config_version) is not str
            or type(config_sha256) is not str
            or type(profile_sha256) is not str
            or not _SHA256.fullmatch(config_sha256)
            or not _SHA256.fullmatch(profile_sha256)
        ):
            raise ResearchCATRuntimeError("binding_metadata_invalid")

        has_binding_ref = _metadata_has(database_metadata, "binding_ref")
        requested_binding_ref = _metadata_value(
            database_metadata, "binding_ref", required=False
        )
        if has_binding_ref:
            if type(requested_binding_ref) is not str:
                raise ResearchCATRuntimeError("binding_metadata_invalid")
            pin = self._pins.get(requested_binding_ref)
            if pin is None:
                raise ResearchCATRuntimeError("binding_not_pinned")
            candidates = (pin,)
        else:
            candidates = tuple(
                pin for pin in self._pins.values()
                if pin.profile_ref == profile_ref
                and pin.config_version == config_version
                and pin.config_sha256 == config_sha256
            )
            if len(candidates) != 1:
                raise ResearchCATRuntimeError("binding_pin_ambiguous_or_missing")
            pin = candidates[0]

        if (
            profile_ref != pin.profile_ref
            or config_version != pin.config_version
            or config_sha256 != pin.config_sha256
        ):
            raise ResearchCATRuntimeError("binding_pin_mismatch")

        try:
            trusted_profile = self._registry.load(pin.profile_ref)
        except Exception:
            raise ResearchCATRuntimeError("profile_registry_load_failed") from None
        if (
            getattr(trusted_profile, "profile_ref", None) != pin.profile_ref
            or getattr(trusted_profile, "repository_schema_compatible", None) is not True
            or getattr(trusted_profile, "profile_sha256", None) != profile_sha256
            or type(getattr(trusted_profile, "profile_sha256", None)) is not str
            or not _SHA256.fullmatch(trusted_profile.profile_sha256)
        ):
            raise ResearchCATRuntimeError("profile_pin_mismatch")

        # Keep database and CAT imports lazy for Backend 3.12 and disabled lanes.
        try:
            from database_layer.research_keys import (
                ResearchSnapshotKeyring,
                derive_research_service_bearer,
            )

            from smhai_backend.domains.school_research.client import ResearchCATHttpClient

            school_scope = f"school:{self._school_id}"
            snapshot_verifier = ResearchSnapshotKeyring(
                self._key_provider,
                school_scope=school_scope,
                signing_version=self._signing_version,
                accepted_versions=self._accepted_versions,
            )
            service_bearer = derive_research_service_bearer(
                self._key_provider,
                key_version=self._signing_version,
                school_scope=school_scope,
            )
            return ResearchCATHttpClient(
                base_url=self._base_url,
                service_bearer_token=service_bearer,
                binding_ref=pin.binding_ref,
                expected_profile_sha256=trusted_profile.profile_sha256,
                expected_config_sha256=pin.config_sha256,
                snapshot_verifier=snapshot_verifier,
                timeout=self._timeout,
            )
        except ResearchCATRuntimeError:
            raise
        except Exception:
            raise ResearchCATRuntimeError("research_client_construction_failed") from None


def _metadata_value(metadata: object, name: str, *, required: bool = True) -> Any:
    if isinstance(metadata, Mapping):
        if name in metadata:
            return metadata[name]
    elif hasattr(metadata, name):
        return getattr(metadata, name)
    if required:
        raise ResearchCATRuntimeError("binding_metadata_invalid")
    return None


def _metadata_has(metadata: object, name: str) -> bool:
    if isinstance(metadata, Mapping):
        return name in metadata
    return hasattr(metadata, name)


def _validate_loopback_base_url(value: object) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise ResearchCATRuntimeError("loopback_url_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        address = ipaddress.ip_address(host) if host is not None else None
    except (ValueError, UnicodeError):
        raise ResearchCATRuntimeError("loopback_url_invalid") from None
    expected_host = (
        f"[{address.compressed}]" if address is not None and address.version == 6
        else address.compressed if address is not None
        else ""
    )
    expected_netloc = f"{expected_host}:{port}" if port is not None else expected_host
    if (
        parsed.scheme != "http"
        or not parsed.netloc
        or "?" in value
        or "#" in value
        or parsed.netloc.casefold() != expected_netloc.casefold()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or address is None
        or not address.is_loopback
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ResearchCATRuntimeError("loopback_url_must_be_loopback_http")
    return f"http://{parsed.netloc.rstrip('/')}"
