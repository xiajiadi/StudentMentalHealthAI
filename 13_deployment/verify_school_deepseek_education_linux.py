"""Run one idempotent Synthetic Demo education turn through the real Backend path."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
BACKEND = "http://127.0.0.1:8088"
LLM = "http://127.0.0.1:8160"
ACCOUNT_CREDENTIAL = Path("/etc/credstore.encrypted/psynova-school-seed-accounts.cred")
ACCOUNT_CREDENTIAL_NAME = "school-seed-accounts.json"
STATE_PATH = Path("/var/lib/psynova-school-demo/deepseek-generation-state.json")
LOCK_PATH = Path("/run/lock/psynova-school-deepseek-generation.lock")
BACKEND_HTTP_VERIFIER = RELEASE_ROOT / "13_deployment" / "verify_school_http_linux.py"
BACKEND_HTTP_VERIFIER_SHA256 = "da6325afd3230656f7423617b19fd6b94d70da8a20ced6bffb72859b9c22fa46"
BACKEND_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
OPERATION_ID = "synthetic-student-education-turn-v1"
CONVERSATION_KEY = "psynova-synthetic-deepseek-conversation-v1"
MESSAGE_KEY = "psynova-synthetic-deepseek-education-turn-v1"
EXPECTED_MODEL_ID = "MODEL_deepseek_flash_education_support"
QUESTION = (
    "我想更有条理地完成一周的学习任务。请基于可用资料，给我一个简短的一周学习计划，"
    "包含每天一个可执行步骤和每周复盘方法；这是一般学习支持，不要诊断或推断个人心理状态。"
)
ALLOWED_SAFETY_ACTIONS = {"PROCEED", "PROCEED_WITH_BOUNDARY"}
PHASES = (
    "INITIALIZED",
    "CONVERSATION_CREATE_PENDING",
    "CONVERSATION_CREATED",
    "GENERATION_REQUEST_PENDING",
    "VERIFIED",
)


class GateError(RuntimeError):
    def __init__(self, code: str, phase: str) -> None:
        super().__init__(code)
        self.code = code
        self.phase = phase


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_root_file(path: Path, *, mode: int) -> os.stat_result:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError("required_file_unavailable", "preflight") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise GateError("required_file_metadata_mismatch", "preflight")
    return metadata


def _require_root_snapshot() -> None:
    if os.geteuid() != 0:
        raise GateError("root_required", "startup")
    snapshot = Path(__file__)
    if snapshot.is_symlink():
        raise GateError("snapshot_symlink_rejected", "startup")
    try:
        resolved = snapshot.resolve(strict=True)
        metadata = resolved.stat(follow_symlinks=False)
        app_root = APP_ROOT.resolve(strict=True)
        root_metadata = app_root.stat(follow_symlinks=False)
    except OSError:
        raise GateError("snapshot_unavailable", "startup") from None
    suffix = resolved.stem.removeprefix("verify_school_deepseek_education_")
    if (
        resolved.parent != app_root
        or not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != 0
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
        or len(suffix) != 64
        or any(char not in "0123456789abcdef" for char in suffix)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o500
        or _sha256_file(resolved) != suffix
    ):
        raise GateError("snapshot_fingerprint_mismatch", "startup")


@contextmanager
def _lock() -> Iterator[None]:
    import fcntl

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(LOCK_PATH, flags, 0o600)
        metadata = os.fstat(descriptor)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
            os.close(descriptor)
            raise GateError("lock_metadata_mismatch", "startup")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except GateError:
        raise
    except BlockingIOError:
        raise GateError("generation_check_already_running", "startup") from None
    except OSError:
        raise GateError("generation_lock_unavailable", "startup") from None
    try:
        yield
    finally:
        os.close(descriptor)


def _read_state() -> dict[str, Any] | None:
    if not os.path.lexists(STATE_PATH):
        return None
    metadata = _require_root_file(STATE_PATH, mode=0o600)
    try:
        state = json.loads(STATE_PATH.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise GateError("generation_checkpoint_unreadable", "checkpoint_read") from None
    if (
        type(state) is not dict
        or state.get("schema") != "psynova.school-deepseek-generation-state.v1"
        or state.get("operation_id") != OPERATION_ID
        or state.get("backend_revision") != BACKEND_REVISION
        or state.get("phase") not in PHASES
        or type(state.get("checks")) is not dict
        or metadata.st_size > 32 * 1024
    ):
        raise GateError("generation_checkpoint_mismatch", "checkpoint_read")
    return state


def _write_state(state: dict[str, Any]) -> None:
    if not STATE_PATH.parent.is_dir() or STATE_PATH.parent.is_symlink():
        raise GateError("checkpoint_parent_unavailable", "checkpoint_write")
    parent = STATE_PATH.parent.stat(follow_symlinks=False)
    if parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) != 0o700:
        raise GateError("checkpoint_parent_metadata_mismatch", "checkpoint_write")
    state["updated_at_epoch"] = int(time.time())
    data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = STATE_PATH.parent / f".{STATE_PATH.name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, 0o600)
        os.replace(temporary, STATE_PATH)
    except FileExistsError:
        raise GateError("checkpoint_temporary_file_exists", "checkpoint_write") from None
    except OSError:
        raise GateError("checkpoint_write_failed", "checkpoint_write") from None


def _new_state() -> dict[str, Any]:
    return {
        "schema": "psynova.school-deepseek-generation-state.v1",
        "operation_id": OPERATION_ID,
        "backend_revision": BACKEND_REVISION,
        "phase": "INITIALIZED",
        "conversation_id": None,
        "turn_id": None,
        "checks": {},
    }


def _checkpoint(state: dict[str, Any], phase: str, **updates: Any) -> None:
    state["phase"] = phase
    state.update(updates)
    _write_state(state)


def _data(response: Any) -> dict[str, Any]:
    try:
        value = response.json()
        data = value["data"]
    except (KeyError, TypeError, ValueError):
        raise GateError("backend_response_contract_mismatch", "http_verification") from None
    if not isinstance(data, dict):
        raise GateError("backend_response_contract_mismatch", "http_verification")
    return data


def _safe_http_error_code(response: Any) -> str | None:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None
    if type(payload) is not dict:
        return None
    error_value = payload.get("error")
    if type(error_value) is not dict:
        return None
    code = error_value.get("code")
    if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
        return code
    return None


def _validate_completed_turn(turn: dict[str, Any]) -> dict[str, Any]:
    metadata = turn.get("safe_metadata")
    citations = turn.get("citations")
    content = turn.get("content")
    if (
        turn.get("status") != "completed"
        or type(metadata) is not dict
        or metadata.get("stage") != "completed"
        or metadata.get("model_id") != EXPECTED_MODEL_ID
        or metadata.get("attempt_count") != 1
        or type(metadata.get("evidence_count")) is not int
        or metadata.get("evidence_count", 0) < 1
        or type(metadata.get("attempt_count")) is not int
        or metadata.get("input_safety_action") not in ALLOWED_SAFETY_ACTIONS
        or metadata.get("retrieval_safety_action") not in ALLOWED_SAFETY_ACTIONS
        or metadata.get("output_safety_action") not in ALLOWED_SAFETY_ACTIONS
        or not isinstance(citations, list)
        or not citations
        or type(content) is not dict
    ):
        raise GateError("deepseek_education_turn_contract_failed", "http_verification")
    if (
        not isinstance(content.get("summary"), str)
        or not content["summary"].strip()
        or not isinstance(content.get("observations"), list)
        or not isinstance(content.get("suggestions"), list)
        or not content["suggestions"]
        or not isinstance(content.get("disclaimer"), str)
        or not content["disclaimer"].strip()
    ):
        raise GateError("deepseek_education_content_invalid", "http_verification")
    for citation in citations:
        if type(citation) is not dict:
            raise GateError("deepseek_citation_binding_failed", "http_verification")
        citation_id = citation.get("citation_id")
        chunk_id = citation.get("chunk_id")
        source_hash = citation.get("source_hash")
        if (
            not isinstance(citation_id, str)
            or not isinstance(chunk_id, str)
            or not isinstance(source_hash, str)
            or not source_hash.startswith("sha256:")
        ):
            raise GateError("deepseek_citation_binding_failed", "http_verification")
    return {
        "status": "PASS",
        "model_id": EXPECTED_MODEL_ID,
        "attempt_count": 1,
        "evidence_count": metadata["evidence_count"],
        "citation_count": len(citations),
        "input_safety": metadata["input_safety_action"],
        "retrieval_safety": metadata["retrieval_safety_action"],
        "output_safety": metadata["output_safety_action"],
        "answer_text_logged": False,
    }


def _preflight(httpx: Any) -> None:
    try:
        listener_result = subprocess.run(
            ["ss", "-lntH"], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        raise GateError("listener_preflight_unavailable", "preflight") from None
    if listener_result.returncode != 0:
        raise GateError("listener_preflight_failed", "preflight")
    expected = {"8088": "127.0.0.1:8088", "8160": "127.0.0.1:8160"}
    seen: set[str] = set()
    for line in listener_result.stdout.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        local_address = fields[3]
        port = local_address.rsplit(":", 1)[-1]
        if port in expected:
            if local_address != expected[port]:
                raise GateError("service_listener_not_loopback", "preflight")
            seen.add(port)
    if seen != set(expected):
        raise GateError("required_loopback_listener_missing", "preflight")
    for url in (f"{BACKEND}/health/ready", f"{LLM}/health/ready"):
        try:
            response = httpx.get(url, timeout=10, trust_env=False)
        except httpx.HTTPError:
            raise GateError("required_service_unavailable", "preflight") from None
        if response.status_code != 200:
            raise GateError("required_service_not_ready", "preflight")
    _require_root_file(ACCOUNT_CREDENTIAL, mode=0o600)
    _require_root_file(BACKEND_HTTP_VERIFIER, mode=0o644)
    if _sha256_file(BACKEND_HTTP_VERIFIER) != BACKEND_HTTP_VERIFIER_SHA256:
        raise GateError("account_verifier_fingerprint_mismatch", "preflight")


def _resume(state: dict[str, Any] | None) -> dict[str, Any]:
    sys.path.insert(0, str(RELEASE_ROOT / "13_deployment"))
    httpx: Any = importlib.import_module("httpx")
    verifier: Any = importlib.import_module("verify_school_http_linux")
    verifier_data = verifier._data
    login = verifier._login
    read_accounts = verifier._read_accounts

    _preflight(httpx)
    if state is None:
        state = _new_state()
        _write_state(state)
    if state["phase"] == "VERIFIED":
        return {"status": "PASS", **state["checks"], "replayed": True}

    try:
        accounts = read_accounts()
    except Exception:  # noqa: BLE001 - redact credential verifier exceptions
        raise GateError("synthetic_account_credential_unavailable", "authentication") from None
    account = accounts.get("alpha.student")
    if account is None:
        raise GateError("synthetic_student_account_missing", "authentication")
    try:
        session = login(httpx, "alpha.student", account)
    except Exception:  # noqa: BLE001 - redact account authentication errors
        raise GateError("synthetic_student_authentication_failed", "authentication") from None
    client = session["client"]
    csrf = session["csrf"]
    try:
        conversation_id = state.get("conversation_id")
        if conversation_id is None:
            _checkpoint(state, "CONVERSATION_CREATE_PENDING")
            response = client.post(
                "/api/v1/student/conversations",
                json={},
                headers={
                    "Origin": "http://127.0.0.1:4178",
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": CONVERSATION_KEY,
                    "Accept": "application/json",
                },
            )
            if response.status_code != 201:
                raise GateError("conversation_creation_failed", "conversation_create")
            created = verifier_data(response)
            conversation_id = created.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id.startswith("CONV_"):
                raise GateError("conversation_creation_contract_failed", "conversation_create")
            _checkpoint(state, "CONVERSATION_CREATED", conversation_id=conversation_id)

        checks = state.setdefault("checks", {})
        checks.pop("last_http_status", None)
        checks.pop("last_backend_error_code", None)
        _checkpoint(state, "GENERATION_REQUEST_PENDING", conversation_id=conversation_id)
        response = client.post(
            f"/api/v1/student/conversations/{conversation_id}/messages",
            json={"text": QUESTION},
            headers={
                "Origin": "http://127.0.0.1:4178",
                "X-CSRF-Token": csrf,
                "Idempotency-Key": MESSAGE_KEY,
                "Accept": "application/json",
            },
        )
        if response.status_code not in {200, 202}:
            state.setdefault("checks", {})["last_http_status"] = response.status_code
            error_code = _safe_http_error_code(response)
            if error_code is not None:
                state["checks"]["last_backend_error_code"] = error_code
            _write_state(state)
            raise GateError(
                f"deepseek_education_request_http_{response.status_code}", "generation"
            )
        turn = verifier_data(response)
        turn_id = turn.get("turn_id")
        if isinstance(turn_id, str):
            state["turn_id"] = turn_id
            _write_state(state)
        deadline = time.monotonic() + 90
        while turn.get("status") == "requested" and isinstance(turn_id, str):
            if time.monotonic() >= deadline:
                raise GateError("deepseek_education_request_pending", "generation")
            time.sleep(1)
            detail_response = client.get(
                f"/api/v1/student/conversations/{conversation_id}",
                headers={"Accept": "application/json"},
            )
            if detail_response.status_code != 200:
                raise GateError("conversation_persistence_read_failed", "persistence_verify")
            detail = verifier_data(detail_response)
            turns = detail.get("turns")
            if not isinstance(turns, list):
                raise GateError("conversation_persistence_contract_failed", "persistence_verify")
            turn = next(
                (item for item in turns if type(item) is dict and item.get("turn_id") == turn_id),
                turn,
            )

        result = _validate_completed_turn(turn)
        if not isinstance(turn_id, str):
            raise GateError("deepseek_turn_id_missing", "http_verification")
        persisted_response = client.get(
            f"/api/v1/student/conversations/{conversation_id}",
            headers={"Accept": "application/json"},
        )
        if persisted_response.status_code != 200:
            raise GateError("conversation_persistence_read_failed", "persistence_verify")
        persisted = verifier_data(persisted_response)
        persisted_turns = persisted.get("turns")
        if not isinstance(persisted_turns, list):
            raise GateError("conversation_persistence_contract_failed", "persistence_verify")
        stored = next(
            (
                item
                for item in persisted_turns
                if type(item) is dict and item.get("turn_id") == turn_id
            ),
            None,
        )
        if (
            type(stored) is not dict
            or stored.get("status") != "completed"
            or stored.get("safe_metadata") != turn.get("safe_metadata")
            or stored.get("citations") != turn.get("citations")
        ):
            raise GateError("deepseek_persistence_verification_failed", "persistence_verify")
        result["database_persistence"] = "PASS"
        result["cross_component_path"] = "BACKEND_SAFETY_RAG_DEEPSEEK_OUTPUT_SAFETY"
        _checkpoint(
            state,
            "VERIFIED",
            conversation_id=conversation_id,
            turn_id=turn_id,
            checks=result,
        )
        return {"status": "PASS", **result, "replayed": False}
    finally:
        client.close()


def _inspect(state: dict[str, Any] | None) -> int:
    if state is None:
        print(json.dumps({"generation": "NOT_STARTED", "writes": False}, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "generation": "PASS" if state["phase"] == "VERIFIED" else "PARTIAL",
                    "phase": state["phase"],
                    "checks": state.get("checks", {}),
                    "writes": False,
                },
                sort_keys=True,
            )
        )
    return 0


def _dry_run(state: dict[str, Any] | None) -> int:
    httpx: Any = importlib.import_module("httpx")

    _preflight(httpx)
    print(
        json.dumps(
            {
                "generation": "READY_TO_RESUME",
                "phase": "NOT_STARTED" if state is None else state["phase"],
                "one_generation_call_max": True,
                "idempotency_enabled": True,
                "writes": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        _require_root_snapshot()
        with _lock():
            state = _read_state()
            if args.inspect:
                return _inspect(state)
            if args.dry_run:
                return _dry_run(state)
            result = _resume(state)
            print(json.dumps(result, sort_keys=True))
            return 0
    except GateError as exc:
        print(json.dumps({"error_code": exc.code, "phase": exc.phase, "generation": "BLOCKED"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
