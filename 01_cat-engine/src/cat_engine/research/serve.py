"""Standalone loopback server entrypoint for the isolated research CAT bridge.

The Backend owns this process. A SHA-pinned, non-secret service document is
passed by absolute path/expected digest; derived authentication material is
accepted once over stdin. Stdin then remains a private stop/EOF control pipe.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import queue
import re
import socket
import stat
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO

from fastapi import Request

from cat_engine.domain.config import CATConfig
from cat_engine.domain.errors import ConfigValidationError
from cat_engine.research.http_app import ResearchCATBinding, create_research_http_app
from cat_engine.research.research_session import (
    PROMIS_PEDIATRIC_PROFILE_SCHEMA,
    ResearchCATProfile,
    _config_sha256,
)

SERVICE_CONFIG_SCHEMA = "psynova.research-cat-service.v1"
SECRET_HANDOFF_SCHEMA = "psynova.research-service-keys.v1"
STOP_SENTINEL = b"PSYNOVA_RESEARCH_STOP\n"
MAX_SERVICE_CONFIG_BYTES = 1024 * 1024
MAX_SECRET_HANDOFF_BYTES = 16 * 1024
MAX_PROFILE_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BINDINGS = 128
MAX_PROFILES = 64
MAX_KEY_VERSIONS = 16
HANDSHAKE_TIMEOUT_SECONDS = 15.0

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_KEY_VERSION = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_BEARER = re.compile(r"[A-Za-z0-9_-]{32,512}\Z")
_PROFILE_SCHEMAS = frozenset(
    {
        "psynova.research-profile.v1",
        "psynova.research-profile.v2",
        "psynova.research-profile.v3",
    }
)
_CONFIG_FIELDS = frozenset(
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
_SCOPE_FIELDS = frozenset({"school_id", "scope"})
_LISTENER_FIELDS = frozenset({"host", "port"})
_SIGNING_FIELDS = frozenset({"signing_version", "accepted_key_versions"})
_PROFILE_FIELDS = frozenset(
    {
        "profile_ref",
        "profile_schema",
        "profile_path",
        "profile_sha256",
        "manifest_path",
        "manifest_sha256",
    }
)
_BINDING_FIELDS = frozenset(
    {"binding_ref", "profile_ref", "config_version", "config_sha256", "cat_config"}
)
_HANDOFF_FIELDS = frozenset({"schema", "bearer_token", "signing_version", "keyring"})


class ResearchCATServeError(ValueError):
    """Fixed-code error safe for parent-process reporting."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "startup_failed"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _ProfilePin:
    profile_ref: str
    profile_schema: str
    profile_path: Path = field(repr=False)
    profile_sha256: str
    manifest_path: Path = field(repr=False)
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class ResearchCATServiceConfig:
    service_config_sha256: str
    school_id: int
    school_scope: str
    resource_root: Path = field(repr=False)
    host: str
    port: int
    signing_version: str
    accepted_key_versions: tuple[str, ...]
    profiles: tuple[_ProfilePin, ...] = field(repr=False)
    bindings: tuple[Mapping[str, object], ...] = field(repr=False)


class VersionedHmacSnapshotAuthenticator:
    """Existing SnapshotAuthenticator protocol with rk1 versioned signatures."""

    __slots__ = ("_keys", "_signing_version")

    def __init__(self, *, keys: Mapping[str, bytes], signing_version: str) -> None:
        if (
            not isinstance(keys, Mapping)
            or not keys
            or any(
                type(version) is not str
                or not _KEY_VERSION.fullmatch(version)
                or type(key) is not bytes
                or len(key) != 32
                for version, key in keys.items()
            )
            or signing_version not in keys
        ):
            raise ResearchCATServeError("secret_handoff_invalid")
        self._keys = MappingProxyType(dict(keys))
        self._signing_version = signing_version

    def __repr__(self) -> str:
        return "VersionedHmacSnapshotAuthenticator(versions=<redacted>, keys=<redacted>)"

    def sign(self, payload: bytes) -> str:
        if type(payload) is not bytes:
            raise ResearchCATServeError("snapshot_signing_failed")
        digest = hmac.new(
            self._keys[self._signing_version], payload, hashlib.sha256
        ).hexdigest()
        return f"rk1.{self._signing_version}.{digest}"

    def verify(self, payload: bytes, signature: str) -> bool:
        if type(payload) is not bytes or type(signature) is not str:
            return False
        match = re.fullmatch(
            r"rk1\.([A-Za-z0-9_-]{1,64})\.([0-9a-f]{64})", signature
        )
        if match is None:
            return False
        version, supplied = match.groups()
        key = self._keys.get(version)
        if key is None:
            return False
        expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied)


def load_service_config(config_path: Path, expected_sha256: str) -> ResearchCATServiceConfig:
    """Read and validate one exact, closed, SHA-pinned service JSON document."""

    try:
        if (
            not isinstance(config_path, Path)
            or not config_path.is_absolute()
            or type(expected_sha256) is not str
            or not _SHA256.fullmatch(expected_sha256)
        ):
            raise ResearchCATServeError("service_config_invalid")
        _assert_no_reparse_components(config_path, "service_config_invalid")
        resolved_config = config_path.resolve(strict=True)
        raw = _read_limited(resolved_config, MAX_SERVICE_CONFIG_BYTES)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
            raise ResearchCATServeError("service_config_hash_mismatch")
        document = _strict_json_object(raw, "service_config_invalid")
        if set(document) != _SERVICE_FIELDS or document.get("schema") != SERVICE_CONFIG_SCHEMA:
            raise ResearchCATServeError("service_config_schema_invalid")

        scope = document.get("school_scope")
        listener = document.get("listener")
        signing = document.get("signing")
        if (
            type(scope) is not dict
            or set(scope) != _SCOPE_FIELDS
            or type(scope.get("school_id")) is not int
            or scope["school_id"] <= 0
            or scope.get("scope") != f"school:{scope['school_id']}"
        ):
            raise ResearchCATServeError("school_scope_invalid")
        if (
            type(listener) is not dict
            or set(listener) != _LISTENER_FIELDS
            or listener.get("host") != "127.0.0.1"
            or type(listener.get("port")) is not int
            or not 1 <= listener["port"] <= 65535
        ):
            raise ResearchCATServeError("loopback_listener_invalid")
        if type(signing) is not dict or set(signing) != _SIGNING_FIELDS:
            raise ResearchCATServeError("signing_config_invalid")
        signing_version = signing.get("signing_version")
        accepted = signing.get("accepted_key_versions")
        if (
            type(signing_version) is not str
            or not _KEY_VERSION.fullmatch(signing_version)
            or type(accepted) is not list
            or not 1 <= len(accepted) <= MAX_KEY_VERSIONS
            or any(type(version) is not str or not _KEY_VERSION.fullmatch(version) for version in accepted)
            or len(set(accepted)) != len(accepted)
            or signing_version not in accepted
        ):
            raise ResearchCATServeError("signing_config_invalid")

        root = _absolute_existing_path(document.get("resource_root"), "resource_root_invalid")
        if not root.is_dir():
            raise ResearchCATServeError("resource_root_invalid")
        profiles_doc = document.get("profiles")
        bindings_doc = document.get("bindings")
        if (
            type(profiles_doc) is not list
            or not 1 <= len(profiles_doc) <= MAX_PROFILES
            or type(bindings_doc) is not list
            or not 1 <= len(bindings_doc) <= MAX_BINDINGS
        ):
            raise ResearchCATServeError("service_registry_invalid")

        profiles: list[_ProfilePin] = []
        profile_refs: set[str] = set()
        for raw_pin in profiles_doc:
            if type(raw_pin) is not dict or set(raw_pin) != _PROFILE_FIELDS:
                raise ResearchCATServeError("profile_pin_invalid")
            profile_ref = raw_pin.get("profile_ref")
            schema = raw_pin.get("profile_schema")
            profile_sha = raw_pin.get("profile_sha256")
            manifest_sha = raw_pin.get("manifest_sha256")
            if (
                type(profile_ref) is not str
                or not _SAFE_REF.fullmatch(profile_ref)
                or profile_ref in profile_refs
                or type(schema) is not str
                or schema not in _PROFILE_SCHEMAS
                or type(profile_sha) is not str
                or not _SHA256.fullmatch(profile_sha)
                or type(manifest_sha) is not str
                or not _SHA256.fullmatch(manifest_sha)
            ):
                raise ResearchCATServeError("profile_pin_invalid")
            profile_path = _path_under_root(raw_pin.get("profile_path"), root)
            manifest_path = _path_under_root(raw_pin.get("manifest_path"), root)
            if profile_path == manifest_path:
                raise ResearchCATServeError("profile_pin_invalid")
            profiles.append(
                _ProfilePin(
                    profile_ref=profile_ref,
                    profile_schema=schema,
                    profile_path=profile_path,
                    profile_sha256=profile_sha,
                    manifest_path=manifest_path,
                    manifest_sha256=manifest_sha,
                )
            )
            profile_refs.add(profile_ref)

        bindings: list[Mapping[str, object]] = []
        binding_refs: set[str] = set()
        for raw_binding in bindings_doc:
            if type(raw_binding) is not dict or set(raw_binding) != _BINDING_FIELDS:
                raise ResearchCATServeError("binding_config_invalid")
            binding_ref = raw_binding.get("binding_ref")
            profile_ref = raw_binding.get("profile_ref")
            config_version = raw_binding.get("config_version")
            config_sha = raw_binding.get("config_sha256")
            config_doc = raw_binding.get("cat_config")
            if (
                type(binding_ref) is not str
                or not _SAFE_REF.fullmatch(binding_ref)
                or binding_ref in binding_refs
                or type(profile_ref) is not str
                or profile_ref not in profile_refs
                or type(config_version) is not str
                or not _SAFE_REF.fullmatch(config_version)
                or type(config_sha) is not str
                or not _SHA256.fullmatch(config_sha)
                or type(config_doc) is not dict
                or set(config_doc) != _CONFIG_FIELDS
                or config_doc.get("config_version") != config_version
            ):
                raise ResearchCATServeError("binding_config_invalid")
            try:
                config = CATConfig.from_dict(config_doc)
            except (ConfigValidationError, TypeError, ValueError):
                raise ResearchCATServeError("cat_config_invalid") from None
            if _canonical_json(config.to_dict()) != _canonical_json(config_doc):
                raise ResearchCATServeError("cat_config_not_canonical")
            if not hmac.compare_digest(_config_sha256(config), config_sha):
                raise ResearchCATServeError("cat_config_hash_mismatch")
            bindings.append(MappingProxyType(dict(raw_binding)))
            binding_refs.add(binding_ref)

        return ResearchCATServiceConfig(
            service_config_sha256=expected_sha256,
            school_id=scope["school_id"],
            school_scope=scope["scope"],
            resource_root=root,
            host=listener["host"],
            port=listener["port"],
            signing_version=signing_version,
            accepted_key_versions=tuple(accepted),
            profiles=tuple(profiles),
            bindings=tuple(bindings),
        )
    except ResearchCATServeError:
        raise
    except Exception:  # noqa: BLE001 - service config diagnostics must not expose paths.
        raise ResearchCATServeError("service_config_invalid") from None


def build_research_http_app(
    config: ResearchCATServiceConfig,
    *,
    service_bearer_token: bytes,
    authenticator: VersionedHmacSnapshotAuthenticator,
) -> Any:
    """Build the existing HTTP app only from the validated static registry."""

    bindings = load_research_bindings(config)
    return _create_research_http_app(
        config,
        bindings=bindings,
        service_bearer_token=service_bearer_token,
        authenticator=authenticator,
    )


def load_research_bindings(
    config: ResearchCATServiceConfig,
) -> dict[str, ResearchCATBinding]:
    """Verify every pinned resource and construct the immutable binding map."""

    try:
        loaded_profiles: dict[str, ResearchCATProfile] = {}
        for pin in config.profiles:
            profile_raw = _read_limited(pin.profile_path, MAX_PROFILE_BYTES)
            manifest_raw = _read_limited(pin.manifest_path, MAX_MANIFEST_BYTES)
            if not hmac.compare_digest(hashlib.sha256(profile_raw).hexdigest(), pin.profile_sha256):
                raise ResearchCATServeError("profile_hash_mismatch")
            if not hmac.compare_digest(hashlib.sha256(manifest_raw).hexdigest(), pin.manifest_sha256):
                raise ResearchCATServeError("manifest_hash_mismatch")
            profile_doc = _strict_json_object(profile_raw, "profile_invalid")
            if profile_doc.get("schema") != pin.profile_schema:
                raise ResearchCATServeError("profile_schema_mismatch")
            if pin.profile_schema == PROMIS_PEDIATRIC_PROFILE_SCHEMA:
                profile = ResearchCATProfile.from_bytes(
                    profile_raw,
                    expected_file_sha256=pin.profile_sha256,
                    manifest_bytes=manifest_raw,
                    expected_manifest_sha256=pin.manifest_sha256,
                )
            else:
                # Backend registry validates the versioned non-v3 manifest
                # structure; the CAT process independently enforces its pin.
                profile = ResearchCATProfile.from_bytes(
                    profile_raw, expected_file_sha256=pin.profile_sha256
                )
            if profile.profile_id != pin.profile_ref:
                raise ResearchCATServeError("profile_ref_mismatch")
            loaded_profiles[pin.profile_ref] = profile

        bindings: dict[str, ResearchCATBinding] = {}
        for binding_doc in config.bindings:
            binding_ref = binding_doc["binding_ref"]
            profile_ref = binding_doc["profile_ref"]
            config_doc = binding_doc["cat_config"]
            assert type(binding_ref) is str and type(profile_ref) is str
            assert type(config_doc) is dict
            cat_config = CATConfig.from_dict(config_doc)
            bindings[binding_ref] = ResearchCATBinding(
                binding_ref=binding_ref,
                profile=loaded_profiles[profile_ref],
                config=cat_config,
            )
        return bindings
    except ResearchCATServeError:
        raise
    except Exception:  # noqa: BLE001 - do not expose profile data in startup errors.
        raise ResearchCATServeError("research_registry_load_failed") from None


def _create_research_http_app(
    config: ResearchCATServiceConfig,
    *,
    bindings: Mapping[str, ResearchCATBinding],
    service_bearer_token: bytes,
    authenticator: VersionedHmacSnapshotAuthenticator,
) -> Any:
    try:
        app = create_research_http_app(
            bindings=bindings,
            authenticator=authenticator,
            service_bearer_token=service_bearer_token,
        )
        registry_fingerprint = _loaded_registry_fingerprint(config)

        async def research_ready(request: Request) -> Any:
            from fastapi.responses import JSONResponse

            supplied = request.headers.get("authorization", "")
            expected = "Bearer " + service_bearer_token.decode("ascii")
            try:
                authenticated = hmac.compare_digest(
                    supplied.encode("ascii"), expected.encode("ascii")
                )
            except UnicodeEncodeError:
                authenticated = False
            if not authenticated:
                return JSONResponse(
                    {"error": {"code": "bearer_authentication_required"}},
                    status_code=401,
                )
            return {
                "schema": "psynova.research-service-ready.v1",
                "status": "READY",
                "research_only": True,
                "clinical_approval": False,
                "school_approval": False,
                "service_config_sha256": config.service_config_sha256,
                "registry_fingerprint": registry_fingerprint,
                "binding_count": len(bindings),
                "school_scope": config.school_scope,
            }

        app.add_api_route(
            "/_research/ready",
            research_ready,
            methods=["GET"],
            include_in_schema=False,
        )
        return app
    except ResearchCATServeError:
        raise
    except Exception:  # noqa: BLE001 - app construction errors may contain secret data.
        raise ResearchCATServeError("research_app_construction_failed") from None


def read_secret_handoff(
    stream: BinaryIO, config: ResearchCATServiceConfig
) -> tuple[bytes, VersionedHmacSnapshotAuthenticator]:
    """Consume one bounded JSON line containing derived material only."""

    try:
        raw = stream.readline(MAX_SECRET_HANDOFF_BYTES + 1)
        if (
            not raw
            or len(raw) > MAX_SECRET_HANDOFF_BYTES
            or not raw.endswith(b"\n")
            or raw.count(b"\n") != 1
        ):
            raise ResearchCATServeError("secret_handoff_invalid")
        document = _strict_json_object(raw[:-1], "secret_handoff_invalid")
        if (
            set(document) != _HANDOFF_FIELDS
            or document.get("schema") != SECRET_HANDOFF_SCHEMA
        ):
            raise ResearchCATServeError("secret_handoff_invalid")
        bearer_token = document.get("bearer_token")
        signing_version = document.get("signing_version")
        encoded_keys = document.get("keyring")
        if (
            type(bearer_token) is not str
            or not _BEARER.fullmatch(bearer_token)
            or signing_version != config.signing_version
            or type(encoded_keys) is not dict
            or set(encoded_keys) != set(config.accepted_key_versions)
        ):
            raise ResearchCATServeError("secret_handoff_invalid")
        bearer = bearer_token.encode("ascii")
        keys: dict[str, bytes] = {}
        for version, encoded_key in encoded_keys.items():
            if (
                type(version) is not str
                or type(encoded_key) is not str
            ):
                raise ResearchCATServeError("secret_handoff_invalid")
            keys[version] = _decode_keyring_key(encoded_key)
        authenticator = VersionedHmacSnapshotAuthenticator(
            keys=keys, signing_version=config.signing_version
        )
        return bearer, authenticator
    except ResearchCATServeError:
        raise
    except Exception:  # noqa: BLE001 - derived secret values must never reach diagnostics.
        raise ResearchCATServeError("secret_handoff_invalid") from None


def serve_from_stdin(
    config_path: Path,
    expected_config_sha256: str,
    *,
    stdin: BinaryIO | None = None,
    server_class: Any | None = None,
) -> None:
    """Run one uvicorn worker on an exclusively bound loopback socket."""

    control_stream = stdin if stdin is not None else sys.stdin.buffer
    config = load_service_config(config_path, expected_config_sha256)
    # Reject unpinned, malformed or incompatible resources before accepting any
    # derived authentication material from the parent process.
    bindings = load_research_bindings(config)
    listener = _bind_exclusive_loopback(config.host, config.port)
    try:
        bearer, authenticator = _read_handoff_with_timeout(control_stream, config)
        app = _create_research_http_app(
            config,
            bindings=bindings,
            service_bearer_token=bearer,
            authenticator=authenticator,
        )
        if server_class is None:
            import uvicorn

            server_class = uvicorn.Server
        server = server_class(
            _uvicorn_config(app, host=config.host, port=config.port)
        )
        stopper = threading.Thread(
            target=_watch_stop_pipe,
            args=(control_stream, server),
            name="research-cat-stop-pipe",
            daemon=True,
        )
        stopper.start()
        server.run(sockets=[listener])
    finally:
        listener.close()
        # This process is disposable; drop references to derived key material.
        if "authenticator" in locals():
            del authenticator
        if "bearer" in locals():
            del bearer


def _uvicorn_config(app: Any, *, host: str, port: int) -> Any:
    import uvicorn

    return uvicorn.Config(
        app,
        host=host,
        port=port,
        workers=1,
        reload=False,
        access_log=False,
        log_level="critical",
        log_config=None,
        server_header=False,
        date_header=False,
    )


def _read_handoff_with_timeout(
    stream: BinaryIO, config: ResearchCATServiceConfig
) -> tuple[bytes, VersionedHmacSnapshotAuthenticator]:
    result: queue.Queue[tuple[bytes | None, Exception | None]] = queue.Queue(maxsize=1)

    def read_once() -> None:
        try:
            result.put((stream.readline(MAX_SECRET_HANDOFF_BYTES + 1), None))
        except Exception as exc:  # noqa: BLE001 - stream errors must be redacted.
            result.put((None, exc))

    reader = threading.Thread(target=read_once, name="research-cat-secret-handoff", daemon=True)
    reader.start()
    try:
        line, failure = result.get(timeout=HANDSHAKE_TIMEOUT_SECONDS)
    except queue.Empty:
        raise ResearchCATServeError("secret_handoff_timeout") from None
    if failure is not None or line is None:
        raise ResearchCATServeError("secret_handoff_invalid") from None
    class _OneLineStream:
        def __init__(self, first_line: bytes, remaining: BinaryIO) -> None:
            self._first_line = first_line
            self._remaining = remaining

        def readline(self, limit: int = -1) -> bytes:
            if self._first_line is not None:
                line, self._first_line = self._first_line, None
                return line
            return self._remaining.readline(limit)

    return read_secret_handoff(_OneLineStream(line, stream), config)


def _watch_stop_pipe(stream: BinaryIO, server: Any) -> None:
    try:
        command = stream.readline(128)
    except Exception:  # noqa: BLE001 - stdin errors must not log control bytes.
        server.should_exit = True
        return
    if command == STOP_SENTINEL or command == b"" or command:
        # Any malformed control input also stops this owned service.
        server.should_exit = True


def _bind_exclusive_loopback(host: str, port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        listener.bind((host, port))
        listener.listen(socket.SOMAXCONN)
        listener.setblocking(False)
        return listener
    except OSError:
        listener.close()
        raise ResearchCATServeError("loopback_port_unavailable") from None


def _read_limited(path: Path, limit: int) -> bytes:
    try:
        _assert_no_reparse_components(path, "pinned_file_unavailable")
        with path.open("rb") as stream:
            value = stream.read(limit + 1)
    except ResearchCATServeError:
        raise
    except OSError:
        raise ResearchCATServeError("pinned_file_unavailable") from None
    if not value or len(value) > limit:
        raise ResearchCATServeError("pinned_file_size_invalid")
    return value


def _absolute_existing_path(value: object, code: str) -> Path:
    if type(value) is not str or not value:
        raise ResearchCATServeError(code)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ResearchCATServeError(code)
    try:
        _assert_no_reparse_components(path, code)
        return path.resolve(strict=True)
    except ResearchCATServeError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ResearchCATServeError(code) from None


def _assert_no_reparse_components(path: Path, code: str) -> None:
    """Reject symlinks and Windows reparse points before canonicalizing paths."""

    try:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            info = os.lstat(current)
            attributes = getattr(info, "st_file_attributes", 0)
            if (
                stat.S_ISLNK(info.st_mode)
                or bool(attributes & 0x400)
                or (hasattr(current, "is_junction") and current.is_junction())
            ):
                raise ResearchCATServeError(code)
    except ResearchCATServeError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ResearchCATServeError(code) from None


def _path_under_root(value: object, root: Path) -> Path:
    path = _absolute_existing_path(value, "pinned_path_invalid")
    if path == root or root not in path.parents or not path.is_file():
        raise ResearchCATServeError("pinned_path_outside_resource_root")
    return path


def _strict_json_object(raw: bytes, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ResearchCATServeError(code) from None
    if type(value) is not dict:
        raise ResearchCATServeError(code)
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _decode_keyring_key(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ResearchCATServeError("secret_handoff_invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError):
        raise ResearchCATServeError("secret_handoff_invalid") from None
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii")
    if len(decoded) != 32 or canonical.rstrip("=") != value:
        raise ResearchCATServeError("secret_handoff_invalid")
    return decoded


def _loaded_registry_fingerprint(config: ResearchCATServiceConfig) -> str:
    material = {
        "profiles": sorted(
            (
                {
                    "profile_ref": pin.profile_ref,
                    "profile_schema": pin.profile_schema,
                    "profile_sha256": pin.profile_sha256,
                    "manifest_sha256": pin.manifest_sha256,
                }
                for pin in config.profiles
            ),
            key=lambda entry: str(entry["profile_ref"]),
        ),
        "bindings": sorted(
            (
                {
                    "binding_ref": binding["binding_ref"],
                    "profile_ref": binding["profile_ref"],
                    "config_version": binding["config_version"],
                    "config_sha256": binding["config_sha256"],
                }
                for binding in config.bindings
            ),
            key=lambda entry: str(entry["binding_ref"]),
        ),
    }
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _read_expected_sha256(value: object) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ResearchCATServeError("service_config_invalid")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private loopback research CAT bridge")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        expected = _read_expected_sha256(args.config_sha256)
        serve_from_stdin(args.config, expected)
        return 0
    except ResearchCATServeError as exc:
        sys.stderr.write(f"RESEARCH_CAT_{exc.code.upper()}\n")
        return 2
    except Exception:  # noqa: BLE001 - do not expose startup errors or secret bytes.
        sys.stderr.write("RESEARCH_CAT_STARTUP_FAILED\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
