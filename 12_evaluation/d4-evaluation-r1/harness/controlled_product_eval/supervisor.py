"""Persistent, allow-listed JSONL supervisor for the complete D4 evaluation stack."""

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
from typing import Any, Mapping, TextIO

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
from .service_profiles import (
    ExternalProfileSet,
    ServiceProfileError,
    build_external_service_profiles,
    invalidate_current_runtime_pointer,
    preflight_formal_port_owners,
    verify_external_service_readiness,
    verify_runtime_attestation_still_live,
)


DEFAULT_TOOLS_ROOT = D4_TASK_TOOLS_ROOT
OWNED_GROUPS = {
    "mysql": ("d4-mysql",),
    "opa": ("d4-opa",),
    "safety": ("d4-safety",),
    "ollama": ("d4-ollama",),
    "runtime": ("d4-runtime",),
    "cat": ("d4-cat",),
    "external": ("d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat"),
    "rag": ("d4-rag",),
    "observers": ("d4-rag-observer", "d4-llm-observer"),
    "backend": ("d4-backend",),
}
START_ORDER = (
    "d4-mysql", "d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat",
    "d4-backend", "d4-rag", "d4-rag-observer", "d4-llm-observer",
)
EXTERNAL_DEPENDENCIES: dict[str, tuple[int, str]] = {}
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


def build_service_profile_bundle(
    config: SupervisorConfig,
    *,
    database_credential: DatabaseCredential,
    credential_redactions: tuple[str, ...] = (),
    mysql_spec: ProcessSpec | None = None,
    external_profile_set: ExternalProfileSet | None = None,
) -> tuple[dict[str, ProcessSpec], Mapping[str, Mapping[str, Any]], Mapping[str, ProcessSpec]]:
    repo_root = config.repo_root.resolve()
    tools_root = config.tools_root.resolve()
    service_root = config.service_root.resolve()
    corpus_manifest = config.corpus_manifest.resolve()
    if tools_root != DEFAULT_TOOLS_ROOT.resolve():
        raise RunnerError("supervisor task-tools root is pinned and cannot be overridden")
    if repo_root != Path(__file__).resolve().parents[4]:
        raise RunnerError("supervisor repository root must match the checked-out evaluation source")
    if not _within(service_root, tools_root) or service_root == tools_root:
        raise RunnerError("supervisor output must use a new attempt directory under the pinned D4 task-tools root")
    if _within(service_root, repo_root):
        raise RunnerError("supervisor output must stay outside the project checkout")
    if service_root.exists():
        entries = {entry.name for entry in service_root.iterdir()}
        allowed_entries = {"mysql", "profile-sources", "events", "preflight"}
        if not entries <= allowed_entries:
            raise RunnerError("supervisor output contains paths outside the fixed service profile")
        if "mysql" in entries and not (service_root / "mysql" / "data").is_dir():
            raise RunnerError("supervisor MySQL bootstrap directory is incomplete")
        if "profile-sources" in entries and external_profile_set is None:
            raise RunnerError("profile sources already exist but were not supplied to the fixed profile builder")
    if not _within(corpus_manifest, tools_root) or not corpus_manifest.is_file():
        raise RunnerError("supervisor requires an existing approved corpus manifest under the D4 task tools root")

    expected_backend = BACKEND_PYTHON.resolve()
    expected_rag = RAG_PYTHON.resolve()
    if config.backend_python.resolve() != expected_backend:
        raise RunnerError("supervisor Backend interpreter must use the pinned task-local Python 3.12 environment")
    if config.rag_python.resolve() != expected_rag:
        raise RunnerError("supervisor RAG interpreter must use the pinned task-local RAG environment")

    external = external_profile_set or build_external_service_profiles(repo_root, service_root)
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
    mysql = mysql_spec or IsolatedMySqlBootstrap(
        repo_root=repo_root,
        run_root=service_root,
        backend_python=expected_backend,
    ).server_spec()
    profiles = {spec.name: spec for spec in [mysql, *external.profiles.values(), *specs]}
    if set(profiles) != set(START_ORDER):
        raise RunnerError("fixed supervisor profile inventory is incomplete")
    return profiles, external.source_evidence, external.stale_profiles


def build_service_profiles(
    config: SupervisorConfig,
    *,
    database_credential: DatabaseCredential,
    credential_redactions: tuple[str, ...] = (),
    mysql_spec: ProcessSpec | None = None,
    external_profile_set: ExternalProfileSet | None = None,
) -> dict[str, ProcessSpec]:
    """Return only the fixed complete service profile map."""

    profiles, _evidence, _stale_profiles = build_service_profile_bundle(
        config,
        database_credential=database_credential,
        credential_redactions=credential_redactions,
        mysql_spec=mysql_spec,
        external_profile_set=external_profile_set,
    )
    return profiles


class JsonlSupervisor:
    """Serve a bounded JSONL protocol; no request can supply a command or path."""

    def __init__(
        self,
        *,
        profiles: dict[str, ProcessSpec],
        supervisor: ProcessSupervisor,
        event_log: Path,
        login_transport: CanonicalHttpTransport | None = None,
        close_transport_after_login: bool = True,
        profile_source_evidence: Mapping[str, Mapping[str, Any]] | None = None,
        attempt_id: str | None = None,
        service_root: Path | None = None,
        current_runtime_pointer: Path | None = None,
    ) -> None:
        if set(profiles) != set(START_ORDER):
            raise ValueError("supervisor profiles do not match the fixed D4 service allowlist")
        self.profiles = profiles
        self.supervisor = supervisor
        self.event_log = event_log
        self.login_transport = login_transport
        self.close_transport_after_login = close_transport_after_login
        self.profile_source_evidence = profile_source_evidence
        self.attempt_id = attempt_id
        self.service_root = service_root
        self.current_runtime_pointer = current_runtime_pointer
        self.runtime_preflight: dict[str, Any] | None = None
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
            "start_external_stack": {"op"},
            "stop_external_stack": {"op"},
        }
        if op not in allowed_keys or set(request) != allowed_keys[op]:
            return {"ok": False, "error_type": "RequestError", "error": "operation is not allow-listed"}
        if self.login_gate_failed and op in {"start", "start_stack", "start_external_stack"}:
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
            return {"ok": True, "inventory": capture_data_plane_network(owned_pids=self.supervisor.process_tree_pids())}
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
                external = self._start_external_stack()
                if not external.get("ok"):
                    return external
                backend = self._start_group("backend")
                if not backend.get("ok"):
                    self._stop_names(tuple(reversed(START_ORDER[1:])))
                    self.login_gate_passed = False
                    return backend
                rag = self._start_group("rag")
                if not rag.get("ok"):
                    self._stop_names(tuple(reversed(START_ORDER[1:])))
                    self.login_gate_passed = False
                    return rag
                observers = self._start_group("observers")
                if not observers.get("ok"):
                    self._stop_names(tuple(reversed(START_ORDER[1:])))
                    self.login_gate_passed = False
                    return observers
                if self.runtime_preflight is None:
                    return {"ok": False, "error_type": "PreconditionError", "error": "live Runtime attestation is missing"}
                verify_runtime_attestation_still_live(
                    self.runtime_preflight,
                    supervisor=self.supervisor,
                    profiles=self.profiles,
                )
                return {"ok": True, "services": self.supervisor.identities()}
            except Exception:
                self._stop_names(tuple(reversed(START_ORDER)))
                self.login_gate_passed = False
                self.login_gate_result = None
                raise
        if op == "stop_stack":
            return self._stop_names(tuple(reversed(START_ORDER)))
        if op == "start_external_stack":
            return self._start_external_stack()
        if op == "stop_external_stack":
            return self._stop_names(tuple(reversed(START_ORDER[1:])))
        if op == "cleanup":
            result = asyncio.run(self.supervisor.close())
            self.stopping = bool(result["cleanup_verified"])
            self._invalidate_runtime_attestation(
                "supervisor_cleanup_verified" if result["cleanup_verified"] else "supervisor_cleanup_unverified"
            )
            return {
                "ok": result["cleanup_verified"],
                "cleanup": result,
                "shutdown": self.stopping,
            }
        return {"ok": False, "error_type": "RequestError", "error": "operation is not allow-listed"}

    def _start_group(self, service: str) -> dict[str, Any]:
        if service == "external":
            return self._start_external_stack()
        if service == "mysql" and self._is_owned("d4-mysql"):
            return {"ok": True, "services": [row for row in self.supervisor.identities() if row["name"] == "d4-mysql"]}
        prerequisites = {
            "opa": ("d4-mysql",),
            "safety": ("d4-opa",),
            "ollama": ("d4-safety",),
            "runtime": ("d4-ollama",),
            "cat": ("d4-runtime",),
            "backend": ("d4-mysql", "d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat"),
        }
        missing = [name for name in prerequisites.get(service, ()) if not self._is_owned(name)]
        if missing:
            return {
                "ok": False,
                "error_type": "PreconditionError",
                "error": "required earlier fixed services are not supervisor-owned and ready",
                "missing_services": missing,
            }
        if service == "backend":
            if self.runtime_preflight is None:
                return {"ok": False, "error_type": "PreconditionError", "error": "live Runtime attestation must pass before Backend"}
            try:
                verify_runtime_attestation_still_live(
                    self.runtime_preflight,
                    supervisor=self.supervisor,
                    profiles=self.profiles,
                    include_application_stack=False,
                )
            except Exception:
                self._invalidate_runtime_attestation("runtime_identity_changed_before_backend")
                return {"ok": False, "error_type": "PreconditionError", "error": "live Runtime attestation is stale"}
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

    def _start_external_stack(self) -> dict[str, Any]:
        if not self._is_owned("d4-mysql"):
            return {"ok": False, "error_type": "PreconditionError", "error": "fresh isolated MySQL must be ready before external services"}
        if not self.profile_source_evidence or not self.attempt_id or self.service_root is None or self.current_runtime_pointer is None:
            return {"ok": False, "error_type": "PreconditionError", "error": "fixed live Runtime attestation context is unavailable"}
        started = self._start_names(OWNED_GROUPS["external"])
        if not started.get("ok"):
            return started
        try:
            attestation = asyncio.run(
                verify_external_service_readiness(
                    supervisor=self.supervisor,
                    profiles=self.profiles,
                    source_evidence=self.profile_source_evidence,
                    attempt_id=self.attempt_id,
                    run_root=self.service_root,
                    current_pointer=self.current_runtime_pointer,
                )
            )
        except Exception as exc:
            self._stop_names(tuple(reversed(OWNED_GROUPS["external"])))
            return {"ok": False, "error_type": type(exc).__name__, "error": "live Runtime attestation failed"}
        self.runtime_preflight = dict(attestation["preflight"])
        return {
            "ok": True,
            "services": self.supervisor.identities(),
            "runtime_preflight_path": attestation["run_preflight_path"],
            "runtime_preflight_hash": self.runtime_preflight["preflight_hash"],
        }

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
                if self.close_transport_after_login:
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
                if self._is_owned(name):
                    results.append(next(row for row in self.supervisor.identities() if row["name"] == name))
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
        if service == "external":
            return self._stop_names(tuple(reversed(START_ORDER[1:])))
        if service == "mysql":
            return self._stop_names(("d4-llm-observer", "d4-rag-observer", "d4-rag", "d4-backend", "d4-mysql"))
        if service == "opa":
            return self._stop_names(tuple(reversed(START_ORDER[1:])))
        if service == "safety":
            return self._stop_names(("d4-llm-observer", "d4-rag-observer", "d4-rag", "d4-backend", "d4-cat", "d4-runtime", "d4-ollama", "d4-safety"))
        if service == "ollama":
            return self._stop_names(("d4-llm-observer", "d4-rag-observer", "d4-rag", "d4-backend", "d4-cat", "d4-runtime", "d4-ollama"))
        if service == "runtime":
            return self._stop_names(("d4-llm-observer", "d4-rag-observer", "d4-rag", "d4-backend", "d4-cat", "d4-runtime"))
        if service == "cat":
            return self._stop_names(("d4-llm-observer", "d4-rag-observer", "d4-rag", "d4-backend", "d4-cat"))
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
        if any(name in names for name in ("d4-mysql", *OWNED_GROUPS["external"])):
            self._invalidate_runtime_attestation("supervisor_owned_runtime_dependency_stopped")
        return {"ok": not errors, "services": outcomes, "errors": errors}

    def _invalidate_runtime_attestation(self, reason: str) -> bool:
        invalidated = False
        if self.current_runtime_pointer is not None and self.attempt_id:
            invalidated = invalidate_current_runtime_pointer(
                self.current_runtime_pointer,
                attempt_id=self.attempt_id,
                reason=reason,
            )
        self.runtime_preflight = None
        return invalidated

    def _service_inventory(self) -> dict[str, Any]:
        network = capture_data_plane_network(owned_pids=self.supervisor.process_tree_pids())
        return {
            "ok": True,
            "owned": self.supervisor.identities(),
            "fixed_profile_services": sorted(OWNED_GROUPS),
            "external_dependencies": [],
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
            "start_stack", "stop_stack", "cleanup", "start_external_stack", "stop_external_stack",
        }
        raw_op = request.get("op")
        op = raw_op if isinstance(raw_op, str) and raw_op in known_operations else "invalid"
        raw_service = request.get("service")
        known_services = set(OWNED_GROUPS) | set(EXTERNAL_DEPENDENCIES)
        service = raw_service if isinstance(raw_service, str) and raw_service in known_services else None
        self._record_event(request, response, op, service)
        output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        output_stream.flush()

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        """Run and audit one fixed operation for an in-process evaluation attempt."""

        try:
            response = self.dispatch(request)
        except Exception as exc:
            response = {"ok": False, "error_type": type(exc).__name__, "error": "operation failed"}
        known_operations = {
            "health", "services", "network_inventory", "start", "stop",
            "start_stack", "stop_stack", "cleanup", "start_external_stack", "stop_external_stack",
        }
        raw_op = request.get("op")
        op = raw_op if isinstance(raw_op, str) and raw_op in known_operations else "invalid"
        raw_service = request.get("service")
        known_services = set(OWNED_GROUPS) | set(EXTERNAL_DEPENDENCIES)
        service = raw_service if isinstance(raw_service, str) and raw_service in known_services else None
        self._record_event(request, response, op, service)
        return response

    def _record_event(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        op: str,
        service: str | None,
    ) -> None:
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
    service: JsonlSupervisor | None = None
    attempt_id = f"D4SUP-{uuid.uuid4().hex}"
    current_runtime_pointer = D4_TASK_TOOLS_ROOT / "runtime-preflight-current.json"
    try:
        provider = EvaluationCredentialProvider()
        synthetic_credentials = provider.resolve_frozen_synthetic_credentials(config.repo_root)
        mysql_bootstrap = IsolatedMySqlBootstrap(
            repo_root=config.repo_root,
            run_root=config.service_root,
            backend_python=config.backend_python,
        )
        external_profiles = build_external_service_profiles(config.repo_root, config.service_root)
        mysql_spec = mysql_bootstrap.server_spec()
        port_preflight = preflight_formal_port_owners(
            profiles={**external_profiles.profiles, mysql_spec.name: mysql_spec},
            stale_profiles=external_profiles.stale_profiles,
            evidence_path=config.service_root / "preflight" / "formal-port-inventory.json",
        )
        write_json_once(
            config.service_root / "preflight" / "profile-source-identities.json",
            {
                "schema_version": "d4-service-profile-identities.v1",
                "attempt_id": attempt_id,
                "accepted_source_commit": "f11f72795f2a7f2b01a62f57187e26c38628c4a0",
                "formal_port_preflight_status": port_preflight["status"],
                "services": {key: dict(value) for key, value in external_profiles.source_evidence.items()},
            },
        )
        server_evidence = asyncio.run(mysql_bootstrap.start_server(process_supervisor))
        database_credential = provider.generate_database_credential()
        profiles, source_evidence, _stale_profiles = build_service_profile_bundle(
            config,
            database_credential=database_credential,
            credential_redactions=synthetic_credentials.secret_values(),
            mysql_spec=mysql_spec,
            external_profile_set=external_profiles,
        )
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
        service = JsonlSupervisor(
            profiles=profiles,
            supervisor=process_supervisor,
            event_log=config.service_root.resolve() / "supervisor-events.jsonl",
            login_transport=login_transport,
            profile_source_evidence=source_evidence,
            attempt_id=attempt_id,
            service_root=config.service_root.resolve(),
            current_runtime_pointer=current_runtime_pointer,
        )
    except (CredentialProviderError, LifecycleError, MySqlBootstrapError, RunnerError, ServiceProfileError, OSError, ValueError) as exc:
        sys.stderr.write(f"D4 supervisor startup failed: {type(exc).__name__}\n")
        asyncio.run(process_supervisor.close())
        invalidate_current_runtime_pointer(current_runtime_pointer, attempt_id=attempt_id, reason="supervisor_startup_failed")
        if login_transport is not None:
            asyncio.run(login_transport.close())
        return 2
    try:
        service.serve()
    except KeyboardInterrupt:
        pass
    finally:
        if not service.stopping:
            asyncio.run(process_supervisor.close())
        service._invalidate_runtime_attestation(
            "supervisor_cleanup_verified" if process_supervisor._closed else "supervisor_cleanup_unverified"
        )
        if login_transport is not None:
            asyncio.run(login_transport.close())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
