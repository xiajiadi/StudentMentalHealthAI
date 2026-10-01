"""Loopback-only TCP evidence for the bounded D4-3B data plane."""

from __future__ import annotations

import ipaddress
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


FORMAL_DATA_PLANE_PORTS = frozenset({
    8080, 8160, 8170, 8180, 8181, 8190, 11437, 3307, 8271, 8272,
})
FORBIDDEN_REMOTE_PORTS = frozenset({3306, 11434})


class NetworkIntegrityError(RuntimeError):
    """The formal data-plane network state could not be observed reliably."""


def _endpoint(value: str) -> tuple[str, int] | None:
    host: str
    port_text: str
    if value.startswith("["):
        close = value.find("]")
        if close < 0 or value[close + 1 : close + 2] != ":":
            return None
        host, port_text = value[1:close], value[close + 2 :]
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            return None
    try:
        return host, int(port_text)
    except ValueError:
        return None


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_netstat_output(
    output: str,
    *,
    required_ports: frozenset[int] = FORMAL_DATA_PLANE_PORTS,
    require_listeners: bool = True,
    observer_pid: int | None = None,
    owned_pids: Iterable[int] = (),
) -> dict[str, Any]:
    """Parse `netstat -ano -p tcp` and fail closed on exposed or remote sockets."""

    listeners: list[dict[str, Any]] = []
    all_listeners: list[dict[str, Any]] = []
    established: list[dict[str, Any]] = []
    owned_pid_set = {int(pid) for pid in owned_pids}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local = _endpoint(parts[1])
        remote = _endpoint(parts[2])
        state = parts[3].upper()
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if state == "LISTENING" and local:
            row = {"address": local[0], "port": local[1], "pid": pid}
            all_listeners.append(row)
            if local[1] in required_ports:
                listeners.append(row)
        elif state == "ESTABLISHED" and local and remote:
            established.append({
                "local_address": local[0],
                "local_port": local[1],
                "remote_address": remote[0],
                "remote_port": remote[1],
                "pid": pid,
            })

    issues: list[dict[str, Any]] = []
    listening_ports = {item["port"] for item in listeners}
    if require_listeners:
        for port in sorted(required_ports - listening_ports):
            issues.append({"code": "REQUIRED_LISTENER_MISSING", "port": port})
    for item in listeners:
        if not _is_loopback(item["address"]):
            issues.append({"code": "NON_LOOPBACK_LISTENER", **item})
    for item in all_listeners:
        if item["pid"] in owned_pid_set and not _is_loopback(item["address"]):
            issue = {"code": "OWNED_NON_LOOPBACK_LISTENER", **item}
            if issue not in issues:
                issues.append(issue)

    monitored_pids = {item["pid"] for item in listeners} | owned_pid_set
    if observer_pid is not None:
        monitored_pids.add(observer_pid)
    external = [
        item for item in established
        if item["pid"] in monitored_pids and not _is_loopback(item["remote_address"])
    ]
    for item in external:
        issues.append({"code": "EXTERNAL_ESTABLISHED_CONNECTION", **item})
    forbidden = [
        item
        for item in established
        if item["pid"] in monitored_pids
        and item["remote_port"] in FORBIDDEN_REMOTE_PORTS
    ]
    for item in forbidden:
        issues.append({"code": "FORBIDDEN_FORMAL_ENDPOINT_CONNECTION", **item})

    listener_map: dict[int, tuple[str, int]] = {}
    for item in listeners:
        listener_map[item["port"]] = (item["address"], item["pid"])
    return {
        "status": "FAIL" if issues else "PASS",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "listeners": listeners,
        "all_listeners": all_listeners,
        "listener_map": listener_map,
        "external_established_connections": external,
        "forbidden_endpoint_connections": forbidden,
        "monitored_process_pids": sorted(monitored_pids),
        "issues": issues,
    }


def capture_data_plane_network(
    *,
    required_ports: frozenset[int] = FORMAL_DATA_PLANE_PORTS,
    require_listeners: bool = True,
    observer_pid: int | None = None,
    owned_pids: Iterable[int] = (),
) -> dict[str, Any]:
    """Capture the live Windows TCP table without relying on a third-party package."""

    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not system_root:
        raise NetworkIntegrityError("netstat executable is unavailable")
    binary_path = (Path(system_root) / "System32" / "netstat.exe").resolve()
    if not binary_path.is_absolute() or not binary_path.is_file():
        raise NetworkIntegrityError("fixed Windows netstat executable is unavailable")
    try:
        result = subprocess.run(
            [str(binary_path), "-ano", "-p", "tcp"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkIntegrityError(f"TCP table capture failed: {type(exc).__name__}") from exc
    return parse_netstat_output(
        result.stdout,
        required_ports=required_ports,
        require_listeners=require_listeners,
        observer_pid=observer_pid,
        owned_pids=owned_pids,
    )


class LoopbackNetworkMonitor:
    """Sample the formal TCP data plane while cases are executing."""

    def __init__(
        self,
        *,
        required_ports: frozenset[int] = FORMAL_DATA_PLANE_PORTS,
        sample_interval_seconds: float = 0.5,
        observer_pid: int | None = None,
        owned_pids: Iterable[int] | Callable[[], Iterable[int]] = (),
    ) -> None:
        self.required_ports = required_ports
        self.sample_interval_seconds = sample_interval_seconds
        self.observer_pid = observer_pid or os.getpid()
        self.owned_pids = owned_pids
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._baseline_listener_map: dict[int, tuple[str, int]] | None = None
        self._latest: dict[str, Any] = {
            "observed_at": None,
            "listeners": [],
            "listener_map": {},
            "external_established_connections": [],
            "issues": [],
        }
        self._issues: dict[tuple[Any, ...], dict[str, Any]] = {}

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is None:
                self._sample_locked()
                self._thread = threading.Thread(
                    target=self._run,
                    name="d4-formal-network-integrity",
                    daemon=True,
                )
                self._thread.start()
            else:
                self._sample_locked()
            return self._snapshot_locked()

    def sample(self) -> dict[str, Any]:
        with self._lock:
            self._sample_locked()
            return self._snapshot_locked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _run(self) -> None:
        while not self._stop.wait(self.sample_interval_seconds):
            try:
                self.sample()
            except Exception as exc:  # integrity observation failure itself is material
                with self._lock:
                    self._record_issue({
                        "code": "NETWORK_OBSERVER_FAILURE",
                        "error_type": type(exc).__name__,
                    })

    def _sample_locked(self) -> None:
        observation = capture_data_plane_network(
            required_ports=self.required_ports,
            observer_pid=self.observer_pid,
            owned_pids=(
                self.owned_pids()
                if callable(self.owned_pids)
                else self.owned_pids
            ),
        )
        listener_map = observation["listener_map"]
        if self._baseline_listener_map is None:
            self._baseline_listener_map = dict(listener_map)
        elif listener_map != self._baseline_listener_map:
            self._record_issue({"code": "DATA_PLANE_LISTENER_IDENTITY_CHANGED"})
        for issue in observation["issues"]:
            self._record_issue(issue)
        self._latest = observation

    def _record_issue(self, issue: dict[str, Any]) -> None:
        key = tuple(sorted(issue.items()))
        self._issues.setdefault(key, issue)

    def _snapshot_locked(self) -> dict[str, Any]:
        return {
            **self._latest,
            "issues": list(self._issues.values()),
            "status": "FAIL" if self._issues else "PASS",
        }

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(2.0, self.sample_interval_seconds * 4))
            self._thread = None
