"""Persistent, allow-listed JSONL supervisor for D4 evaluation-owned services.

The parent bootstrap owns a new isolated MySQL instance; JSONL manages only the
allow-listed Backend, fresh RAG service, and observers. CAT, Runtime/Ollama,
Safety, and OPA remain external dependencies and are never adopted or stopped.
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

from .cli import _managed_specs
from .credential_provider import (
    CredentialProviderError,
    DatabaseCredential,
    EvaluationCredentialProvider,
    credential_evidence_metadata,
)
from .environment_profiles import BACKEND_PYTHON, D4_TASK_TOOLS_ROOT, RAG_PYTHON
from .mysql_bootstrap import IsolatedMySqlBootstrap, MySqlBootstrapError
from .manifest import write_json_once
from .network_integrity import capture_data_plane_network
from .process_lifecycle import LifecycleError, ProcessSpec, ProcessSupervisor
from .runner import CanonicalHttpTransport, RunnerError


DEFAULT_TOOLS_ROOT = D4_TASK_TOOLS_ROOT
OWNED_GROUPS = {
    "rag": ("d4-rag",),
    "observers": ("d4-rag-observer", "d4-llm-observer"),
    "backend": ("d4-backend",),
}
START_ORDER = ("d4-backend", "d4-rag", "d4-rag-observer", "d4-llm-observer")
EXTERNAL_DEPENDENCIES = {
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


def build_service_profiles(
    config: SupervisorConfig,
    *,
    database_credential: DatabaseCredential,
    credential_redactions: tuple[str, ...] = (),
) -> dict[str, ProcessSpec]:
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
    if service_root.exists():
        entries = {entry.name for entry in service_root.iterdir()}
        if entries and entries != {"mysql"}:
            raise RunnerError("supervisor output directory must be new or contain only this run's MySQL bootstrap")
        if "mysql" in entries and not (service_root / "mysql" / "data").is_dir():
            raise RunnerError("supervisor MySQL bootstrap directory is incomplete")
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
        database_credential=database_credential,
        credential_redactions=credential_redactions,
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
        login_transport: CanonicalHttpTransport | None = None,
    ) -> None:
        if set(profiles) != set(START_ORDER):
            raise ValueError("supervisor profiles do not match the fixed D4 service allowlist")
        self.profiles = profiles
        self.supervisor = supervisor
        self.event_log = event_log
        self.login_transport = login_transport
        self.login_gate_passed = False
        self.login_gate_failed = False
        self.login_gate_result: dict[str, dict[str, str]] | None = None
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
        if self.login_gate_failed and op in {"start", "start_stack"}:
            return {
                "ok": False,
                "error_type": "CredentialGateError",
                "error": "synthetic login gate failed; cleanup and controller review are required",
            }
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
            try:
                backend = self._start_group("backend")
                if not backend.get("ok"):
                    return backend
                rag = self._start_group("rag")
                if not rag.get("ok"):
                    self._stop_names(("d4-backend",))
                    self.login_gate_passed = False
                    return rag
                observers = self._start_group("observers")
                if not observers.get("ok"):
                    self._stop_names(("d4-rag", "d4-backend"))
                    self.login_gate_passed = False
                    return observers
                return {"ok": True, "services": self.supervisor.identities()}
            except Exception:
                self._stop_names(tuple(reversed(START_ORDER)))
                self.login_gate_passed = False
                self.login_gate_result = None
                raise
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
        if service == "rag" and not self.login_gate_passed:
            return {"ok": False, "error_type": "PreconditionError", "error": "synthetic login gate must pass before RAG"}
        if service == "observers" and not self._is_owned("d4-rag"):
            return {"ok": False, "error_type": "PreconditionError", "error": "RAG must be ready before observers"}
        outcome = self._start_names(OWNED_GROUPS[service])
        if service == "backend":
            try:
                self._run_login_gate()
                outcome["login_gate"] = self.login_gate_result
            except Exception:
                self._stop_names(("d4-backend",))
                self.login_gate_passed = False
                self.login_gate_result = None
                return {
                    "ok": False,
                    "error_type": "CredentialGateError",
                    "error": "synthetic login gate failed; fresh accounts were not modified",
                }
        return outcome

    def _run_login_gate(self) -> None:
        if self.login_gate_passed:
            return
        if self.login_transport is None:
            self.login_gate_failed = True
            raise RunnerError("supervisor has no fixed synthetic login credentials")

        async def verify_and_close() -> dict[str, dict[str, str]]:
            try:
                result = await self.login_transport.login_gate()
                return {username: dict(identity) for username, identity in result.items()}
            finally:
                await self.login_transport.close()

        try:
            result = asyncio.run(verify_and_close())
        except Exception:
            self.login_gate_failed = True
            raise RunnerError("synthetic login gate failed; fresh accounts were not modified") from None
        self.login_gate_result = result
        self.login_gate_passed = True

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
        if service == "backend":
            outcomes = self._stop_names(("d4-llm-observer", "d4-rag-observer", "d4-rag", "d4-backend"))
            self.login_gate_passed = False
            self.login_gate_result = None
            return outcomes
        if service == "rag":
            return self._stop_names(("d4-llm-observer", "d4-rag-observer", "d4-rag"))
        return self._stop_names(tuple(reversed(OWNED_GROUPS[service])))

    def _is_owned(self, name: str) -> bool:
        return any(item["name"] == name for item in self.supervisor.identities())

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
        if "d4-backend" in names and "d4-backend" not in {
            item["name"] for item in self.supervisor.identities()
        }:
            self.login_gate_passed = False
            self.login_gate_result = None
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
    process_supervisor = ProcessSupervisor(startup_timeout_seconds=config.startup_timeout_seconds)
    login_transport: CanonicalHttpTransport | None = None
    database_credential: DatabaseCredential | None = None
    try:
        provider = EvaluationCredentialProvider()
        synthetic_credentials = provider.resolve_frozen_synthetic_credentials(config.repo_root)
        mysql_bootstrap = IsolatedMySqlBootstrap(
            repo_root=config.repo_root,
            run_root=config.service_root,
            backend_python=config.backend_python,
        )
        server_evidence = asyncio.run(mysql_bootstrap.start_server(process_supervisor))
        database_credential = provider.generate_database_credential()
        profiles = build_service_profiles(
            config,
            database_credential=database_credential,
            credential_redactions=synthetic_credentials.secret_values(),
        )
        config.service_root.resolve().mkdir(parents=True, exist_ok=True)
        bootstrap_evidence = mysql_bootstrap.provision_database(database_credential)
        login_transport = CanonicalHttpTransport(
            backend_base_url="http://127.0.0.1:8080",
            observer_urls={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
            rag_observer_events=config.service_root / "events" / "rag.jsonl",
            llm_observer_events=config.service_root / "events" / "llm.jsonl",
            passwords=synthetic_credentials.password_mapping(),
        )
        write_json_once(
            config.service_root / "credential-bootstrap.json",
            {
                "schema_version": "d4-3b-credential-bootstrap.v1",
                "database_credential": credential_evidence_metadata(),
                "fixture_source_verified": synthetic_credentials.source_verified,
                "ignored_credential_manager_target": "IGNORED_UNCLASSIFIED_CREDENTIAL_TARGET",
                "mysql_server": server_evidence,
                "mysql_bootstrap": bootstrap_evidence.as_dict(),
            },
        )
    except (CredentialProviderError, LifecycleError, MySqlBootstrapError, RunnerError, OSError, ValueError) as exc:
        sys.stderr.write(f"D4 supervisor startup failed: {type(exc).__name__}\n")
        asyncio.run(process_supervisor.close())
        if login_transport is not None:
            asyncio.run(login_transport.close())
        return 2
    service = JsonlSupervisor(
        profiles=profiles,
        supervisor=process_supervisor,
        event_log=config.service_root.resolve() / "supervisor-events.jsonl",
        login_transport=login_transport,
    )
    try:
        service.serve()
    except KeyboardInterrupt:
        pass
    finally:
        if not service.stopping:
            asyncio.run(process_supervisor.close())
        if login_transport is not None:
            asyncio.run(login_transport.close())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
