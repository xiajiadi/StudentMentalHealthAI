"""Owned CAT research child-process lifecycle.

The manager accepts one already-derived, versioned key handoff and sends it
once over the child's private stdin pipe.  Readiness and listener ownership
are injected so a successful HTTP response alone can never establish process
ownership.  This module does not load profiles, database credentials, or keys
from configuration and does not manage processes by PID lookup or port kill.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import socket
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,512}\Z")
_KEY_VERSION = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SCHOOL_SCOPE = re.compile(r"school:[1-9][0-9]{0,17}\Z")
_HANDSHAKE_SCHEMA = "psynova.research-service-keys.v1"
_HANDSHAKE_FIELDS = frozenset({"schema", "bearer_token", "signing_version", "keyring"})
_READY_SCHEMA = "psynova.research-service-ready.v1"
_READY_FIELDS = frozenset(
    {
        "schema",
        "status",
        "research_only",
        "clinical_approval",
        "school_approval",
        "service_config_sha256",
        "registry_fingerprint",
        "binding_count",
        "school_scope",
    }
)
_STOP_SENTINEL = b"PSYNOVA_RESEARCH_STOP\n"
_MAX_HANDSHAKE_BYTES = 16 * 1024
_MAX_BINDINGS = 128
_SAFE_ENVIRONMENT_NAMES = frozenset(
    {
        "systemroot",
        "windir",
        "temp",
        "tmp",
        "username",
        "userprofile",
        "localappdata",
        "appdata",
        "programdata",
        "homedrive",
        "homepath",
        "os",
    }
)


class ResearchCATProcessError(RuntimeError):
    """Stable, content-free process lifecycle failure."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
            code = "process_failed"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchCATProcessSpec:
    """Pinned launch inputs; deployments should provide Python's base exe.

    ``cat_dependency_path`` is an optional, pre-existing isolated venv
    site-packages directory for CAT dependencies. The private key handoff is
    deliberately hidden and is copied out of this spec at manager creation.
    """

    python_executable: Path
    cat_source: Path
    serve_config_path: Path
    serve_config_sha256: str
    expected_registry_fingerprint: str
    expected_port: int
    expected_binding_count: int
    expected_school_scope: str
    derived_keys_handshake: bytes = field(repr=False)
    cat_dependency_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ResearchCATProcessHealth:
    status: str
    failure_code: str | None = None


class ResearchCATProcessManager:
    """Start and stop exactly one injected, loopback research CAT child.

    ``readiness_probe`` must perform the bounded private ``/_research/ready``
    request using the supplied derived bearer and return its decoded JSON
    object. ``listener_owner_probe`` must independently confirm that the
    listener on ``port`` belongs to the exact PID returned by this manager's
    Popen handle. Deployments must launch the verified base Python executable
    directly; listener ownership may not be inferred from descendants. Both
    probes are mandatory; HTTP health alone is never ownership. Shutdown
    authority remains this manager's Popen handle; it never terminates a PID
    discovered from the listener.
    """

    def __init__(
        self,
        spec: ResearchCATProcessSpec,
        *,
        readiness_probe: Callable[[int, bytes, float], Mapping[str, object]],
        listener_owner_probe: Callable[[int, int], bool],
        port_available_probe: Callable[[int], bool] | None = None,
        startup_timeout_seconds: float = 15.0,
        shutdown_timeout_seconds: float = 5.0,
        probe_timeout_seconds: float = 1.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if not callable(readiness_probe) or not callable(listener_owner_probe):
            raise TypeError("bounded readiness and listener-owner probes are required")
        if port_available_probe is not None and not callable(port_available_probe):
            raise TypeError("port availability probe is invalid")
        for value in (
            startup_timeout_seconds,
            shutdown_timeout_seconds,
            probe_timeout_seconds,
            poll_interval_seconds,
        ):
            if type(value) not in {int, float} or not 0 < value <= 120:
                raise ValueError("process timeout is invalid")
        # Keep only a redacted copy in the long-lived manager. The caller owns
        # its input object; this manager's one-shot handoff bytes live only in
        # the private temporary field below and are cleared after any start
        # outcome.
        self._spec = replace(spec, derived_keys_handshake=b"")
        self._readiness_probe = readiness_probe
        self._listener_owner_probe = listener_owner_probe
        self._port_available_probe = port_available_probe or _loopback_port_is_available
        self._startup_timeout = float(startup_timeout_seconds)
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._probe_timeout = float(probe_timeout_seconds)
        self._poll_interval = float(poll_interval_seconds)
        self._process: subprocess.Popen[bytes] | Any | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._bearer_token: bytes | None = None
        self._handshake_line: bytes | None = spec.derived_keys_handshake
        self._start_attempted = False
        self._closed = False
        self._health = ResearchCATProcessHealth("STOPPED")
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"ResearchCATProcessManager(status={self._health.status!r}, secrets=<redacted>)"

    async def start(self) -> ResearchCATProcessHealth:
        async with self._lock:
            if self._health.status == "READY" and self._process is not None:
                return await self._inspect_health_locked()
            if self._closed or self._start_attempted:
                raise ResearchCATProcessError("manager_not_restartable")
            self._start_attempted = True
            try:
                paths = _validate_spec(self._spec)
                bearer = _validate_handshake(self._handshake_line)
                if self._port_available_probe(self._spec.expected_port) is not True:
                    raise ResearchCATProcessError("loopback_port_unavailable")
                env = _child_environment(os.environ, paths[1], paths[3])
                command = [
                    str(paths[0]),
                    "-S",
                    "-m",
                    "cat_engine.research.serve",
                    "--config",
                    str(paths[2]),
                    "--config-sha256",
                    self._spec.serve_config_sha256,
                ]
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    cwd=str(paths[1]),
                    env=env,
                    creationflags=creationflags,
                )
                self._process = process
                if process.stdin is None or type(process.pid) is not int or process.pid <= 0:
                    raise ResearchCATProcessError("child_pipe_unavailable")
                written = process.stdin.write(self._handshake_line)
                if written != len(self._handshake_line):
                    raise ResearchCATProcessError("child_pipe_write_failed")
                process.stdin.flush()
                self._bearer_token = bearer
                self._handshake_line = None

                deadline = time.monotonic() + self._startup_timeout
                while True:
                    if process.poll() is not None:
                        raise ResearchCATProcessError("child_exited_during_start")
                    if await self._probe_owned_ready(process.pid):
                        if process.poll() is not None:
                            raise ResearchCATProcessError("child_exited_during_start")
                        self._health = ResearchCATProcessHealth("READY")
                        return self._health
                    if time.monotonic() >= deadline:
                        raise ResearchCATProcessError("readiness_timeout")
                    await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                try:
                    await self._cleanup_with_cancellation_protection(self._process)
                except ResearchCATProcessError:
                    pass
                self._health = ResearchCATProcessHealth("UNAVAILABLE", "start_cancelled")
                raise
            except ResearchCATProcessError:
                try:
                    await self._cleanup_with_cancellation_protection(self._process)
                except asyncio.CancelledError:
                    self._health = ResearchCATProcessHealth("UNAVAILABLE", "start_cancelled")
                    raise
                self._health = ResearchCATProcessHealth("UNAVAILABLE", "start_failed")
                raise
            except Exception:
                try:
                    await self._cleanup_with_cancellation_protection(self._process)
                except asyncio.CancelledError:
                    self._health = ResearchCATProcessHealth("UNAVAILABLE", "start_cancelled")
                    raise
                self._health = ResearchCATProcessHealth("UNAVAILABLE", "start_failed")
                raise ResearchCATProcessError("start_failed") from None
            finally:
                self._handshake_line = None

    async def health(self) -> ResearchCATProcessHealth:
        async with self._lock:
            return await self._inspect_health_locked()

    async def close(self) -> ResearchCATProcessHealth:
        async with self._lock:
            process = self._process
            if process is None:
                self._closed = True
                self._handshake_line = None
                self._health = ResearchCATProcessHealth("STOPPED")
                return self._health
            try:
                await self._cleanup_with_cancellation_protection(process)
            except asyncio.CancelledError:
                self._closed = True
                if self._process is not None:
                    self._health = ResearchCATProcessHealth(
                        "UNAVAILABLE", "shutdown_cancelled_child_unconfirmed"
                    )
                else:
                    self._health = ResearchCATProcessHealth("STOPPED")
                raise
            except ResearchCATProcessError as exc:
                self._health = ResearchCATProcessHealth("UNAVAILABLE", exc.code)
                self._closed = True
                raise
            except Exception:
                self._health = ResearchCATProcessHealth("UNAVAILABLE", "shutdown_failed")
                self._closed = True
                raise ResearchCATProcessError("shutdown_failed") from None
            self._process = None
            self._bearer_token = None
            self._handshake_line = None
            self._closed = True
            self._health = ResearchCATProcessHealth("STOPPED")
            return self._health

    async def _inspect_health_locked(self) -> ResearchCATProcessHealth:
        process = self._process
        if process is None:
            if not self._start_attempted or self._closed:
                self._health = ResearchCATProcessHealth("STOPPED")
            return self._health
        try:
            returncode = process.poll()
        except Exception:
            self._health = ResearchCATProcessHealth("UNAVAILABLE", "process_state_unavailable")
            return self._health
        if returncode is not None:
            self._health = ResearchCATProcessHealth("UNAVAILABLE", "child_exited")
            return self._health
        try:
            still_running = (
                process.poll() is None if await self._probe_owned_ready(process.pid) else False
            )
        except Exception:
            still_running = False
        if still_running:
            self._health = ResearchCATProcessHealth("READY")
            return self._health
        self._health = ResearchCATProcessHealth("UNAVAILABLE", "service_not_ready_or_unowned")
        return self._health

    async def _probe_owned_ready(self, pid: int) -> bool:
        bearer = self._bearer_token
        # The first readiness probe runs immediately after sending the derived
        # line. Recover only the bearer from that exact validated line.
        if bearer is None:
            try:
                bearer = _validate_handshake(self._handshake_line)
            except ResearchCATProcessError:
                return False
        try:
            body = await asyncio.wait_for(
                asyncio.to_thread(
                    self._readiness_probe,
                    self._spec.expected_port,
                    bearer,
                    self._probe_timeout,
                ),
                timeout=self._probe_timeout,
            )
            if not _valid_ready_body(body, self._spec):
                return False
            owned = await asyncio.wait_for(
                asyncio.to_thread(self._listener_owner_probe, pid, self._spec.expected_port),
                timeout=self._probe_timeout,
            )
            return owned is True
        except Exception:
            return False

    async def _cleanup_owned_process(self) -> None:
        process = self._process
        if process is None:
            self._handshake_line = None
            return
        try:
            await self._stop_owned_process(process)
        except ResearchCATProcessError as exc:
            self._health = ResearchCATProcessHealth("UNAVAILABLE", exc.code)
            raise
        try:
            running = process.poll() is None
        except Exception:
            raise ResearchCATProcessError("process_state_unavailable") from None
        if running:
            self._health = ResearchCATProcessHealth("UNAVAILABLE", "owned_child_will_not_stop")
            raise ResearchCATProcessError("owned_child_will_not_stop")
        self._process = None
        self._bearer_token = None
        self._handshake_line = None

    async def _cleanup_with_cancellation_protection(self, process: Any | None) -> None:
        if process is None:
            self._handshake_line = None
            return
        cleanup = self._cleanup_task
        if cleanup is None or cleanup.done():
            cleanup = asyncio.create_task(self._cleanup_owned_process())
            self._cleanup_task = cleanup
        timeout = self._shutdown_timeout + max(self._poll_interval, 0.1)
        try:
            await asyncio.wait_for(asyncio.shield(cleanup), timeout=timeout)
        except asyncio.CancelledError:
            # Cancellation of this waiter must not cancel the shielded cleanup.
            # Give the owned process its own bounded stop attempt, then preserve
            # the cancellation signal if another cancellation arrives.
            try:
                await asyncio.wait_for(asyncio.shield(cleanup), timeout=timeout)
            except asyncio.CancelledError:
                self._record_cleanup_state(process)
                raise
            except Exception:
                self._record_cleanup_state(process)
            self._record_cleanup_state(process)
            raise
        except TimeoutError:
            self._record_cleanup_state(process)
            raise ResearchCATProcessError("owned_child_will_not_stop") from None
        except Exception:
            self._record_cleanup_state(process)
            if self._process is not None:
                raise ResearchCATProcessError("owned_child_will_not_stop") from None
        else:
            self._record_cleanup_state(process)

    def _record_cleanup_state(self, process: Any) -> None:
        try:
            running = process.poll() is None
        except Exception:
            running = True
        if running:
            self._process = process
            self._health = ResearchCATProcessHealth("UNAVAILABLE", "owned_child_will_not_stop")
        else:
            self._process = None
            self._bearer_token = None
            self._handshake_line = None
        cleanup = self._cleanup_task
        if cleanup is not None and cleanup.done():
            self._cleanup_task = None

    async def _stop_owned_process(self, process: Any) -> None:
        stream = getattr(process, "stdin", None)
        if stream is not None and not getattr(stream, "closed", False):
            try:
                stream.write(_STOP_SENTINEL)
                stream.flush()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        started = time.monotonic()
        deadline = started + self._shutdown_timeout
        graceful_deadline = started + self._shutdown_timeout / 3
        terminate_deadline = started + (self._shutdown_timeout * 2 / 3)
        if await self._poll_until_exit(process, graceful_deadline):
            return
        try:
            process.terminate()
        except Exception:
            pass
        if await self._poll_until_exit(process, terminate_deadline):
            return
        try:
            process.kill()
        except Exception:
            pass
        if not await self._poll_until_exit(process, deadline):
            raise ResearchCATProcessError("owned_child_will_not_stop")

    async def _poll_until_exit(self, process: Any, deadline: float) -> bool:
        while True:
            try:
                if process.poll() is not None:
                    return True
            except Exception:
                raise ResearchCATProcessError("process_state_unavailable") from None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(self._poll_interval, remaining))


def _validate_spec(
    spec: ResearchCATProcessSpec,
) -> tuple[Path, Path, Path, Path | None]:
    if type(spec) is not ResearchCATProcessSpec:
        raise ResearchCATProcessError("process_spec_invalid")
    if (
        type(spec.serve_config_sha256) is not str
        or _SHA256.fullmatch(spec.serve_config_sha256) is None
        or type(spec.expected_registry_fingerprint) is not str
        or _SHA256.fullmatch(spec.expected_registry_fingerprint) is None
        or type(spec.expected_port) is not int
        or not 1 <= spec.expected_port <= 65535
        or type(spec.expected_binding_count) is not int
        or not 1 <= spec.expected_binding_count <= _MAX_BINDINGS
        or type(spec.expected_school_scope) is not str
        or _SCHOOL_SCOPE.fullmatch(spec.expected_school_scope) is None
    ):
        raise ResearchCATProcessError("process_spec_invalid")
    resolved: list[Path] = []
    for path, kind in (
        (spec.python_executable, "file"),
        (spec.cat_source, "directory"),
        (spec.serve_config_path, "file"),
    ):
        if not isinstance(path, Path) or not path.is_absolute():
            raise ResearchCATProcessError("process_path_invalid")
        try:
            canonical = path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ResearchCATProcessError("process_path_invalid") from None
        if (kind == "file" and not canonical.is_file()) or (
            kind == "directory" and not canonical.is_dir()
        ):
            raise ResearchCATProcessError("process_path_invalid")
        resolved.append(canonical)
    dependency_path = spec.cat_dependency_path
    if dependency_path is not None:
        if not isinstance(dependency_path, Path) or not dependency_path.is_absolute():
            raise ResearchCATProcessError("process_path_invalid")
        try:
            dependency_path = dependency_path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ResearchCATProcessError("process_path_invalid") from None
        if not dependency_path.is_dir():
            raise ResearchCATProcessError("process_path_invalid")
    return resolved[0], resolved[1], resolved[2], dependency_path


def _validate_handshake(value: object) -> bytes:
    if (
        type(value) is not bytes
        or not value
        or len(value) > _MAX_HANDSHAKE_BYTES
        or not value.endswith(b"\n")
        or value.count(b"\n") != 1
    ):
        raise ResearchCATProcessError("derived_handshake_invalid")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, item in pairs:
            if key in parsed:
                raise ValueError
            parsed[key] = item
        return parsed

    try:
        document = json.loads(
            value[:-1].decode("ascii"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except Exception:
        raise ResearchCATProcessError("derived_handshake_invalid") from None
    if (
        type(document) is not dict
        or set(document) != _HANDSHAKE_FIELDS
        or document.get("schema") != _HANDSHAKE_SCHEMA
    ):
        raise ResearchCATProcessError("derived_handshake_invalid")
    bearer = document.get("bearer_token")
    signing_version = document.get("signing_version")
    keyring = document.get("keyring")
    if (
        type(bearer) is not str
        or _TOKEN.fullmatch(bearer) is None
        or type(signing_version) is not str
        or _KEY_VERSION.fullmatch(signing_version) is None
        or type(keyring) is not dict
        or not 1 <= len(keyring) <= 32
        or signing_version not in keyring
    ):
        raise ResearchCATProcessError("derived_handshake_invalid")
    for version, encoded_key in keyring.items():
        if (
            type(version) is not str
            or _KEY_VERSION.fullmatch(version) is None
            or type(encoded_key) is not str
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", encoded_key)
        ):
            raise ResearchCATProcessError("derived_handshake_invalid")
        try:
            decoded = base64.b64decode(
                encoded_key + "=" * (-len(encoded_key) % 4),
                altchars=b"-_",
                validate=True,
            )
        except Exception:
            raise ResearchCATProcessError("derived_handshake_invalid") from None
        canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
        if len(decoded) != 32 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", canonical):
            raise ResearchCATProcessError("derived_handshake_invalid")
        if canonical != encoded_key.rstrip("="):
            raise ResearchCATProcessError("derived_handshake_invalid")
    return bearer.encode("ascii")


def _valid_ready_body(body: object, spec: ResearchCATProcessSpec) -> bool:
    return (
        type(body) is dict
        and set(body) == _READY_FIELDS
        and body.get("schema") == _READY_SCHEMA
        and body.get("status") == "READY"
        and body.get("research_only") is True
        and body.get("clinical_approval") is False
        and body.get("school_approval") is False
        and type(body.get("service_config_sha256")) is str
        and body["service_config_sha256"] == spec.serve_config_sha256
        and type(body.get("registry_fingerprint")) is str
        and body["registry_fingerprint"] == spec.expected_registry_fingerprint
        and type(body.get("binding_count")) is int
        and body["binding_count"] == spec.expected_binding_count
        and type(body.get("school_scope")) is str
        and body["school_scope"] == spec.expected_school_scope
    )


def _child_environment(
    source: Mapping[str, str], cat_source: Path, cat_dependency_path: Path | None
) -> dict[str, str]:
    env = {key: value for key, value in source.items() if key.casefold() in _SAFE_ENVIRONMENT_NAMES}
    python_paths = [str(cat_source)]
    if cat_dependency_path is not None:
        python_paths.append(str(cat_dependency_path))
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _loopback_port_is_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()
