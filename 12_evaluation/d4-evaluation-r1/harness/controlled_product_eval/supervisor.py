"""Persistent, allow-listed JSONL supervisor for D4 evaluation-owned services.

The supervisor owns only the RAG service, two observers, and Backend started by
this process. MySQL, CAT, Runtime/Ollama, Safety, and OPA remain external
dependencies and are never adopted or stopped here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from .cli import _evaluation_database_endpoint, _managed_specs
from .environment_profiles import BACKEND_PYTHON, D4_TASK_TOOLS_ROOT, RAG_PYTHON
from .network_integrity import FORMAL_DATA_PLANE_PORTS, capture_data_plane_network
from .process_lifecycle import LifecycleError, ProcessSpec, ProcessSupervisor
from .runner import RunnerError


DEFAULT_TOOLS_ROOT = D4_TASK_TOOLS_ROOT
OWNED_GROUPS = {
    "rag": ("d4-rag",),
    "observers": ("d4-rag-observer", "d4-llm-observer"),
    "backend": ("d4-backend",),
}
START_ORDER = ("d4-rag", "d4-rag-observer", "d4-llm-observer", "d4-backend")
EXTERNAL_DEPENDENCIES = {
    "mysql": (3307, "EXTERNALLY_OPERATOR_MANAGED"),
    "cat": (8180, "EXTERNALLY_OPERATOR_MANAGED"),
    "opa": (8181, "EXTERNALLY_OPERATOR_MANAGED"),
    "safety": (8190, "EXTERNALLY_OPERATOR_MANAGED"),
    "runtime": (8160, "EXTERNALLY_OPERATOR_MANAGED"),
    "ollama": (11437, "EXTERNALLY_OPERATOR_MANAGED"),
}
MAX_REQUEST_BYTES = 65_536


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@dataclass(slots=True)
class SupervisorConfig:
    repo_root: Path
    tools_root: Path
    service_root: Path
    corpus_manifest: Path
    backend_python: Path
    rag_python: Path
    startup_timeout_seconds: float = 180.0


def build_service_profiles(config: SupervisorConfig) -> dict[str, ProcessSpec]:
    repo_root = config.repo_root.resolve()
    tools_root = config.tools_root.resolve()
    service_root = config.service_root.resolve()
    corpus_manifest = config.corpus_manifest.resolve()
    if tools_root != DEFAULT_TOOLS_ROOT.resolve():
        raise RunnerError("supervisor task-tools root is pinned and cannot be overridden")
    if repo_root != Path(__file__).resolve().parents[4]:
        raise RunnerError("supervisor repository root must match the checked-out evaluation source")
    service_parent = tools_root / "supervisor-runs"
    if not _within(service_root, service_parent) or service_root == service_parent.resolve():
        raise RunnerError("supervisor output must use a new run directory under the pinned supervisor-runs root")
    if _within(service_root, repo_root):
        raise RunnerError("supervisor output must stay outside the project checkout")
    if service_root.exists() and any(service_root.iterdir()):
        raise RunnerError("supervisor output directory must be new or empty")
    if not _within(corpus_manifest, tools_root) or not corpus_manifest.is_file():
        raise RunnerError("supervisor requires an existing approved corpus manifest under the D4 task tools root")

    expected_backend = BACKEND_PYTHON.resolve()
    expected_rag = RAG_PYTHON.resolve()
    if config.backend_python.resolve() != expected_backend:
        raise RunnerError("supervisor Backend interpreter must use the pinned task-local Python 3.12 environment")
    if config.rag_python.resolve() != expected_rag:
        raise RunnerError("supervisor RAG interpreter must use the pinned task-local RAG environment")

    event_root = service_root / "events"
    rag_events = event_root / "rag.jsonl"
    llm_events = event_root / "llm.jsonl"
    specs = _managed_specs(
        args=argparse.Namespace(
            backend_python=str(expected_backend),
            rag_python=str(expected_rag),
        ),
        repo_root=repo_root,
        service_root=service_root,
        corpus_manifest_path=corpus_manifest,
        runtime=None,
        rag_events=rag_events,
        llm_events=llm_events,
    )
    return {spec.name: spec for spec in specs}


class JsonlSupervisor:
    """Serve a bounded JSONL protocol; no request can supply a command or path."""

    def __init__(
        self,
        *,
        profiles: dict[str, ProcessSpec],
        supervisor: ProcessSupervisor,
        event_log: Path,
    ) -> None:
        if set(profiles) != set(START_ORDER):
            raise ValueError("supervisor profiles do not match the fixed D4 service allowlist")
        self.profiles = profiles
        self.supervisor = supervisor
        self.event_log = event_log
        self.stopping = False

    def serve(self, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
        self.event_log.parent.mkdir(parents=True, exist_ok=True)
        while not self.stopping:
            line = input_stream.readline(MAX_REQUEST_BYTES + 1)
            if line == "":
                break
            if len(line.encode("utf-8", errors="replace")) > MAX_REQUEST_BYTES or not line.endswith("\n"):
                if not line.endswith("\n"):
                    while True:
                        tail = input_stream.readline(MAX_REQUEST_BYTES + 1)
                        if tail == "" or tail.endswith("\n"):
                            break
                self._respond(
                    {"op": "invalid"},
                    {"ok": False, "error_type": "RequestError", "error": "request exceeds JSONL limits"},
                    output_stream,
                )
                continue
            try:
                request = json.loads(line, object_pairs_hook=_unique_pairs)
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
                response = self.dispatch(request)
                event_request = request
            except (json.JSONDecodeError, ValueError, TypeError):
                response = {"ok": False, "error_type": "RequestError", "error": "invalid allow-listed request"}
                event_request = {"op": "invalid"}
            except Exception as exc:  # fail closed without serializing exception details
                response = {"ok": False, "error_type": type(exc).__name__, "error": "operation failed"}
                event_request = request if isinstance(locals().get("request"), dict) else {"op": "invalid"}
            self._respond(event_request, response, output_stream)

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        allowed_keys = {
            "health": {"op"},
            "services": {"op"},
            "network_inventory": {"op"},
            "start": {"op", "service"},
            "stop": {"op", "service"},
            "start_stack": {"op"},
            "stop_stack": {"op"},
            "cleanup": {"op"},
        }
        if op not in allowed_keys or set(request) != allowed_keys[op]:
            return {"ok": False, "error_type": "RequestError", "error": "operation is not allow-listed"}
        if op == "health":
            return {
                "ok": True,
                "status": "READY",
                "pid": os.getpid(),
                "protocol": "D4_SUPERVISOR_JSONL_V1",
                "owned_service_count": len(self.supervisor.identities()),
            }
        if op == "services":
            return self._service_inventory()
        if op == "network_inventory":
            return {"ok": True, "inventory": capture_data_plane_network()}
        if op == "start":
            service = request["service"]
            if not isinstance(service, str) or service not in OWNED_GROUPS:
                return self._external_operation_denied(service)
            return self._start_group(service)
        if op == "stop":
            service = request["service"]
            if not isinstance(service, str) or service not in OWNED_GROUPS:
                return self._external_operation_denied(service)
            return self._stop_group(service)
        if op == "start_stack":
            _evaluation_database_endpoint()
            return self._start_names(START_ORDER)
        if op == "stop_stack":
            return self._stop_names(tuple(reversed(START_ORDER)))
        if op == "cleanup":
            result = asyncio.run(self.supervisor.close())
            self.stopping = bool(result["cleanup_verified"])
            return {
                "ok": result["cleanup_verified"],
                "cleanup": result,
                "shutdown": self.stopping,
            }
        return {"ok": False, "error_type": "RequestError", "error": "operation is not allow-listed"}

    def _start_group(self, service: str) -> dict[str, Any]:
        if service == "backend":
            _evaluation_database_endpoint()
        return self._start_names(OWNED_GROUPS[service])

    def _start_names(self, names: tuple[str, ...]) -> dict[str, Any]:
        started: list[str] = []
        results: list[dict[str, Any]] = []
        try:
            for name in START_ORDER:
                if name not in names:
                    continue
                results.append(asyncio.run(self.supervisor.start_service(self.profiles[name])))
                started.append(name)
        except Exception:
            for name in reversed(started):
                try:
                    asyncio.run(self.supervisor.stop_service(name))
                except Exception:
                    pass
            raise
        return {"ok": True, "services": results}

    def _stop_group(self, service: str) -> dict[str, Any]:
        names = tuple(reversed(OWNED_GROUPS[service]))
        return self._stop_names(names)

    def _stop_names(self, names: tuple[str, ...]) -> dict[str, Any]:
        outcomes: list[dict[str, Any]] = []
        errors: list[str] = []
        owned = {item["name"] for item in self.supervisor.identities()}
        for name in names:
            if name not in owned:
                continue
            try:
                outcomes.append(asyncio.run(self.supervisor.stop_service(name)))
            except Exception as exc:
                errors.append(type(exc).__name__)
        return {"ok": not errors, "services": outcomes, "errors": errors}

    def _service_inventory(self) -> dict[str, Any]:
        network = capture_data_plane_network()
        listeners = {item["port"]: item for item in network["listeners"]}
        external = [
            {
                "service_name": name,
                "listener": f"127.0.0.1:{port}",
                "ownership": ownership,
                "listener_observed": port in listeners,
                "health": "NOT_PROBED_BY_SUPERVISOR",
                "pid": listeners.get(port, {}).get("pid"),
            }
            for name, (port, ownership) in EXTERNAL_DEPENDENCIES.items()
        ]
        return {
            "ok": True,
            "owned": self.supervisor.identities(),
            "external_dependencies": external,
            "external_lifecycle_policy": "OBSERVE_ONLY_NEVER_ADOPT_OR_STOP",
            "network_observation_status": network["status"],
        }

    @staticmethod
    def _external_operation_denied(service: Any) -> dict[str, Any]:
        known = service if isinstance(service, str) and service in EXTERNAL_DEPENDENCIES else "unknown"
        return {
            "ok": False,
            "error_type": "OwnershipError",
            "error": "service is not owned by this supervisor",
            "service": known,
        }

    def _respond(self, request: dict[str, Any], response: dict[str, Any], output_stream: TextIO) -> None:
        known_operations = {
            "health", "services", "network_inventory", "start", "stop",
            "start_stack", "stop_stack", "cleanup",
        }
        raw_op = request.get("op")
        op = raw_op if isinstance(raw_op, str) and raw_op in known_operations else "invalid"
        raw_service = request.get("service")
        known_services = set(OWNED_GROUPS) | set(EXTERNAL_DEPENDENCIES)
        service = raw_service if isinstance(raw_service, str) and raw_service in known_services else None
        event = {
            "timestamp": _now(),
            "request_id": uuid.uuid4().hex,
            "operation": op,
            "service": service,
            "ok": bool(response.get("ok")),
            "response": response,
        }
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self.event_log.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
            handle.flush()
        output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        output_stream.flush()


def _parse_args(argv: list[str] | None = None) -> SupervisorConfig:
    parser = argparse.ArgumentParser(description="D4-3B allow-listed persistent stdio supervisor")
    parser.add_argument("--service-root", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--startup-timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[4]
    tools_root = DEFAULT_TOOLS_ROOT.resolve()
    return SupervisorConfig(
        repo_root=repo_root,
        tools_root=tools_root,
        service_root=args.service_root,
        corpus_manifest=args.corpus_manifest,
        backend_python=BACKEND_PYTHON,
        rag_python=RAG_PYTHON,
        startup_timeout_seconds=args.startup_timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    config = _parse_args(argv)
    try:
        profiles = build_service_profiles(config)
        config.service_root.resolve().mkdir(parents=True, exist_ok=True)
    except (LifecycleError, RunnerError, OSError, ValueError) as exc:
        sys.stderr.write(f"D4 supervisor startup failed: {type(exc).__name__}\n")
        return 2
    supervisor = ProcessSupervisor(startup_timeout_seconds=config.startup_timeout_seconds)
    service = JsonlSupervisor(
        profiles=profiles,
        supervisor=supervisor,
        event_log=config.service_root.resolve() / "supervisor-events.jsonl",
    )
    try:
        service.serve()
    except KeyboardInterrupt:
        pass
    finally:
        if not service.stopping:
            asyncio.run(supervisor.close())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
