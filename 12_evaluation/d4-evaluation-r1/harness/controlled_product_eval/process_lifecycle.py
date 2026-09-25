"""Evaluation-owned loopback process lifecycle for a one-shot D4-3B run."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

try:
    from harness.foundation.hashing import canonical_json
except ModuleNotFoundError:  # pragma: no cover - package-relative import mode
    from ..foundation.hashing import canonical_json


class LifecycleError(RuntimeError):
    """A managed evaluation service failed to start or stop cleanly."""


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    name: str
    executable: Path
    arguments: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    readiness_url: str
    readiness_kind: str
    log_path: Path


@dataclass(slots=True)
class _OwnedProcess:
    spec: ProcessSpec
    process: subprocess.Popen[bytes]
    log_handle: Any
    command_hash: str


def _loopback_parts(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.port is None:
        raise LifecycleError("managed service readiness URL must be an absolute HTTP loopback URL")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback or parsed.hostname == "localhost"
    except ValueError:
        loopback = parsed.hostname == "localhost"
    if not loopback:
        raise LifecycleError("managed services may bind only to loopback")
    return parsed.hostname, parsed.port


def _assert_port_free(url: str) -> None:
    host, port = _loopback_parts(url)
    try:
        with socket.create_connection((host, port), timeout=0.2):
            raise LifecycleError(f"refusing to adopt an already-running service at {host}:{port}")
    except OSError:
        return


def _is_ready(kind: str, payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if kind == "backend":
        data = payload.get("data")
        return isinstance(data, dict) and data.get("status") == "ready"
    return payload.get("status") == "READY"


class ProcessSupervisor:
    """Own only explicitly started local eval services; Runtime is never a spec."""

    def __init__(self, *, startup_timeout_seconds: float = 180.0, shutdown_timeout_seconds: float = 8.0) -> None:
        self.startup_timeout_seconds = startup_timeout_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self._owned: list[_OwnedProcess] = []
        self._closed = False

    async def start(self, specs: list[ProcessSpec]) -> list[dict[str, Any]]:
        if self._owned or self._closed:
            raise LifecycleError("process supervisor can start exactly one service set")
        try:
            for spec in specs:
                await self._start_one(spec)
            return self.identities()
        except Exception:
            await self.close()
            raise

    async def _start_one(self, spec: ProcessSpec) -> None:
        executable = spec.executable.resolve()
        cwd = spec.cwd.resolve()
        if not executable.is_file() or not cwd.is_dir():
            raise LifecycleError(f"managed service {spec.name} has an unavailable executable or working directory")
        _assert_port_free(spec.readiness_url)
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [str(executable), *spec.arguments]
        command_hash = "sha256:" + hashlib.sha256(canonical_json(command).encode("utf-8")).hexdigest()
        child_environment = os.environ.copy()
        child_environment.update({str(key): str(value) for key, value in spec.environment.items()})
        log_handle = spec.log_path.open("ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=child_environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                shell=False,
                close_fds=True,
                creationflags=flags,
            )
        except OSError as exc:
            log_handle.close()
            raise LifecycleError(f"managed service {spec.name} failed to start: {type(exc).__name__}") from exc
        self._owned.append(_OwnedProcess(spec, process, log_handle, command_hash))
        await self._wait_ready(self._owned[-1])

    async def _wait_ready(self, owned: _OwnedProcess) -> None:
        deadline = time.monotonic() + self.startup_timeout_seconds
        async with httpx.AsyncClient(timeout=httpx.Timeout(1.0), trust_env=False, follow_redirects=False) as client:
            while time.monotonic() < deadline:
                if owned.process.poll() is not None:
                    raise LifecycleError(f"managed service {owned.spec.name} exited during startup")
                try:
                    response = await client.get(owned.spec.readiness_url)
                    if response.status_code == 200 and _is_ready(owned.spec.readiness_kind, response.json()):
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                await asyncio.sleep(0.25)
        raise LifecycleError(f"managed service {owned.spec.name} did not become ready before timeout")

    def identities(self) -> list[dict[str, Any]]:
        return [
            {
                "name": owned.spec.name,
                "pid": owned.process.pid,
                "command_sha256": owned.command_hash,
                "readiness_url": owned.spec.readiness_url,
                "log_path": str(owned.spec.log_path.resolve()),
            }
            for owned in self._owned
        ]

    async def close(self) -> dict[str, Any]:
        if self._closed:
            return {"cleanup_verified": True, "services": []}
        outcomes: list[dict[str, Any]] = []
        errors: list[str] = []
        for owned in reversed(self._owned):
            process = owned.process
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, self.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)
            exit_code = process.poll()
            if exit_code is None:
                errors.append(f"{owned.spec.name}: process still running")
            if not owned.log_handle.closed:
                owned.log_handle.close()
            endpoint_down = await self._wait_endpoint_down(owned.spec.readiness_url)
            if not endpoint_down:
                errors.append(f"{owned.spec.name}: readiness endpoint remained available after stop")
            outcomes.append(
                {
                    "name": owned.spec.name,
                    "pid": process.pid,
                    "exit_code": exit_code,
                    "endpoint_down": endpoint_down,
                    "stopped": exit_code is not None and endpoint_down,
                }
            )
        self._closed = True
        report = {"cleanup_verified": not errors, "services": list(reversed(outcomes)), "errors": errors}
        return report

    async def _wait_endpoint_down(self, url: str) -> bool:
        deadline = time.monotonic() + min(self.shutdown_timeout_seconds, 3.0)
        async with httpx.AsyncClient(timeout=httpx.Timeout(0.5), trust_env=False, follow_redirects=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        await asyncio.sleep(0.1)
                        continue
                except httpx.HTTPError:
                    return True
                await asyncio.sleep(0.1)
        return False
