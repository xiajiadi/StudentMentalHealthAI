"""Loopback-only OPA sidecar integration.

OPA is a mandatory V0.1 dependency.  If the sidecar is unavailable or returns
an invalid result, callers receive a typed error and the service creates a
non-PROCEED decision.
"""

from __future__ import annotations

import hashlib
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from safety_engine.domain import ComponentHealth, ErrorCode, SafetyError


class OPAProcessManager:
    def __init__(
        self,
        *,
        binary: str | Path,
        policy_dir: str | Path,
        runtime_dir: str | Path,
        port: int | None = None,
        startup_timeout_seconds: float = 8.0,
    ) -> None:
        self.binary = Path(binary)
        self.policy_dir = Path(policy_dir)
        self.runtime_dir = Path(runtime_dir)
        self.port = port or _free_port()
        self.startup_timeout_seconds = startup_timeout_seconds
        self.process: subprocess.Popen[str] | None = None
        self.stdout_path = self.runtime_dir / "opa.stdout.log"
        self.stderr_path = self.runtime_dir / "opa.stderr.log"
        self._stdout_handle: Any | None = None
        self._stderr_handle: Any | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        if self.process is not None:
            self.stop()
        if not self.binary.exists():
            raise SafetyError(
                ErrorCode.POLICY_ENGINE_UNAVAILABLE,
                "OPA executable is missing",
                details={"binary": str(self.binary)},
            )
        if not self.policy_dir.exists():
            raise SafetyError(
                ErrorCode.POLICY_ENGINE_UNAVAILABLE,
                "OPA policy directory is missing",
                details={"policy_dir": str(self.policy_dir)},
            )
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        stdout = self.stdout_path.open("a", encoding="utf-8")
        stderr = self.stderr_path.open("a", encoding="utf-8")
        self._stdout_handle = stdout
        self._stderr_handle = stderr
        command = [
            str(self.binary),
            "run",
            "--server",
            "--addr=127.0.0.1:" + str(self.port),
            "--skip-version-check",
            str(self.policy_dir),
        ]
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(self.policy_dir.parent),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            stdout.close()
            stderr.close()
            self._stdout_handle = None
            self._stderr_handle = None
            raise SafetyError(
                ErrorCode.POLICY_ENGINE_UNAVAILABLE,
                "OPA process could not start",
                details={"binary": str(self.binary)},
            ) from exc
        deadline = time.monotonic() + self.startup_timeout_seconds
        client = PolicyClient(base_url=self.base_url)
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.stop()
                raise SafetyError(
                    ErrorCode.POLICY_ENGINE_UNAVAILABLE,
                    "OPA process exited during startup",
                    details={"returncode": self.process.returncode},
                )
            if client.health().ready:
                return
            time.sleep(0.1)
        self.stop()
        raise SafetyError(
            ErrorCode.POLICY_ENGINE_UNAVAILABLE,
            "OPA health check timed out",
            details={"base_url": self.base_url},
        )

    def stop(self) -> None:
        process = self.process
        self.process = None
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        finally:
            for handle in (self._stdout_handle, self._stderr_handle):
                if handle is not None:
                    handle.close()
            self._stdout_handle = None
            self._stderr_handle = None

    def __enter__(self) -> OPAProcessManager:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


class PolicyClient:
    component = "opa"
    version = "1.20.2"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8181",
        timeout_seconds: float = 2.0,
        policy_dir: str | Path | None = None,
    ) -> None:
        if not base_url.startswith("http://127.0.0.1:"):
            raise ValueError("OPA must bind to loopback HTTP")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.policy_revision = hash_policy_files(Path(policy_dir)) if policy_dir else "unknown"

    def health(self) -> ComponentHealth:
        started = time.perf_counter()
        try:
            response = httpx.get(
                f"{self.base_url}/health",
                timeout=self.timeout_seconds,
            )
            ready = response.status_code == 200
            detail = None if ready else f"HTTP_{response.status_code}"
        except httpx.HTTPError as exc:
            ready = False
            detail = type(exc).__name__
        return ComponentHealth(
            component=self.component,
            available=ready,
            ready=ready,
            version=self.version,
            detail_code=detail,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def evaluate(self, normalized_input: dict[str, Any]) -> dict[str, Any]:
        """Evaluate normalized, non-raw signals through the local OPA REST API."""

        try:
            response = httpx.post(
                f"{self.base_url}/v1/data/student_mental_health_ai/safety/decision",
                json={"input": normalized_input},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SafetyError(
                ErrorCode.POLICY_EVALUATION_FAILED,
                "OPA policy evaluation failed",
                details={"base_url": self.base_url},
            ) from exc
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict) or result.get("action") not in {
            "PROCEED",
            "PROCEED_WITH_BOUNDARY",
            "BLOCK",
            "REVIEW_REQUIRED",
            "CRISIS_ROUTE",
        }:
            raise SafetyError(
                ErrorCode.POLICY_EVALUATION_FAILED,
                "OPA returned an invalid control decision",
                details={"result_type": type(result).__name__},
            )
        return result


def hash_policy_files(policy_dir: Path | None) -> str:
    if policy_dir is None or not policy_dir.exists():
        return "unknown"
    digest = hashlib.sha256()
    for path in sorted(policy_dir.glob("*.rego")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
