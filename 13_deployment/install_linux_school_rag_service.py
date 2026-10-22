"""Safely add the pinned, loopback-only synthetic M0 RAG sidecar to the ECS."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

APP_ROOT = Path("/opt/psynova-school-demo")
BASE_RELEASE = APP_ROOT / "release"
BASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SOURCE_COMMIT = "eaf40f52356587e2b7efb9fc2cb807309c4df7c8"
SERVICE_ROOT = APP_ROOT / "services" / "rag"
UNIT_PATH = Path("/etc/systemd/system/psynova-school-rag.service")
STATE_PATH = Path("/var/lib/psynova-school-demo/rag-install-state.json")
RAG_STATE_DIRECTORY = Path("/var/lib/psynova-school-rag")
LOCK_PATH = Path("/run/lock/psynova-school-rag-install.lock")
BUNDLE_PATH = Path(
    "/home/psynova/apps/psynova/staging/linux-school-demo/"
    "psynova-school-rag-eaf40f5.tar.gz"
)
BUNDLE_SHA256 = "9a53685b9336bd21da72d80fd3b9532723764c23659b67def35a98a2b6fae1c8"
MAX_BUNDLE_SIZE = 5 * 1024 * 1024
MAX_MEMBER_SIZE = 2 * 1024 * 1024
SERVICE_NAME = "psynova-school-rag.service"
HEALTH_URL = "http://127.0.0.1:8170/health/ready"
RETRIEVAL_URL = "http://127.0.0.1:8170/internal/rag/retrievals"


class GateError(RuntimeError):
    def __init__(self, code: str, phase: str) -> None:
        super().__init__(code)
        self.code = code
        self.phase = phase


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(args: list[str], *, phase: str, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GateError("required_command_failed", phase) from None
    if result.returncode != 0:
        raise GateError("required_command_failed", phase)
    return result


def _require_root_snapshot() -> None:
    if os.geteuid() != 0:
        raise GateError("root_required", "startup")
    if Path(__file__).is_symlink():
        raise GateError("root_snapshot_symlink_rejected", "startup")
    _require_root_owned_directory(Path("/opt"), "application_parent_metadata_mismatch")
    _require_root_owned_directory(APP_ROOT, "application_root_metadata_mismatch")
    _require_root_owned_directory(BASE_RELEASE, "base_release_metadata_mismatch")
    script_path = Path(__file__).resolve(strict=True)
    if script_path.parent != APP_ROOT.resolve(strict=True):
        raise GateError("root_snapshot_path_mismatch", "startup")
    metadata = script_path.stat(follow_symlinks=False)
    if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o500:
        raise GateError("root_snapshot_metadata_mismatch", "startup")


def _require_root_owned_directory(path: Path, error_code: str) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError(error_code, "host_preflight") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise GateError(error_code, "host_preflight")


@contextlib.contextmanager
def _deployment_lock():
    import fcntl

    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(LOCK_PATH, flags, 0o600)
        metadata = os.fstat(descriptor)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
            os.close(descriptor)
            raise GateError("deployment_lock_metadata_mismatch", "startup")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise GateError("deployment_already_running", "startup") from None
    except OSError:
        raise GateError("deployment_lock_unavailable", "startup") from None
    try:
        yield
    finally:
        os.close(descriptor)


def _check_systemd() -> None:
    result = _run(["systemd", "--version"], phase="host_preflight")
    first_line = result.stdout.decode("utf-8", errors="replace").splitlines()[0]
    fields = first_line.split()
    if len(fields) < 2 or fields[1] != "255":
        raise GateError("systemd_version_mismatch", "host_preflight")


def _active_unit(name: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", name],
        capture_output=True,
        timeout=15,
        check=False,
    )
    return result.returncode == 0


def _enabled_unit(name: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-enabled", "--quiet", name],
        capture_output=True,
        timeout=15,
        check=False,
    )
    return result.returncode == 0


def _port_8170_listeners() -> list[str]:
    result = _run(["ss", "-ltnH"], phase="listener_check")
    listeners: list[str] = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        columns = line.split()
        if len(columns) >= 4 and columns[3].endswith(":8170"):
            listeners.append(columns[3])
    return listeners


def _bundle_manifest(bundle: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not bundle.is_file() or bundle.is_symlink():
        raise GateError("bundle_missing", "bundle_preflight")
    if bundle.stat().st_size > MAX_BUNDLE_SIZE or _sha256(bundle) != BUNDLE_SHA256:
        raise GateError("bundle_fingerprint_mismatch", "bundle_preflight")

    files: dict[str, bytes] = {}
    try:
        with tarfile.open(bundle, mode="r:gz") as archive:
            for member in archive.getmembers():
                if not _safe_member_name(member.name) or not member.isfile():
                    raise GateError("bundle_member_rejected", "bundle_preflight")
                if member.size < 0 or member.size > MAX_MEMBER_SIZE:
                    raise GateError("bundle_member_size_rejected", "bundle_preflight")
                if member.name in files:
                    raise GateError("bundle_duplicate_member", "bundle_preflight")
                stream = archive.extractfile(member)
                if stream is None:
                    raise GateError("bundle_member_unreadable", "bundle_preflight")
                data = stream.read(MAX_MEMBER_SIZE + 1)
                if len(data) != member.size:
                    raise GateError("bundle_member_size_mismatch", "bundle_preflight")
                files[member.name] = data
    except (tarfile.TarError, OSError):
        raise GateError("bundle_archive_invalid", "bundle_preflight") from None

    manifest_bytes = files.get("PAYLOAD_MANIFEST.json")
    if manifest_bytes is None:
        raise GateError("bundle_manifest_missing", "bundle_preflight")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError):
        raise GateError("bundle_manifest_invalid", "bundle_preflight") from None
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "psynova.school-rag-bundle.v1"
        or manifest.get("source_commit") != SOURCE_COMMIT
        or manifest.get("corpus_kind") != "synthetic-m0-university-student-demo"
        or manifest.get("retrieval_mode") != "bm25"
        or manifest.get("human_curated") is not False
        or type(manifest.get("files")) is not list
    ):
        raise GateError("bundle_manifest_scope_mismatch", "bundle_preflight")

    declared: dict[str, dict[str, Any]] = {}
    for record in manifest["files"]:
        if (
            type(record) is not dict
            or not isinstance(record.get("path"), str)
            or record["path"] in declared
            or not _allowed_payload_path(record["path"])
        ):
            raise GateError("bundle_manifest_entry_rejected", "bundle_preflight")
        declared[record["path"]] = record
    actual = set(files) - {"PAYLOAD_MANIFEST.json"}
    if actual != set(declared):
        raise GateError("bundle_file_inventory_mismatch", "bundle_preflight")
    for name, record in declared.items():
        data = files[name]
        if (
            record.get("size_bytes") != len(data)
            or record.get("sha256") != hashlib.sha256(data).hexdigest()
        ):
            raise GateError("bundle_file_fingerprint_mismatch", "bundle_preflight")
    required = {
        "rag/config/school_m0_demo_bm25.v1.json",
        "rag/data/m0-demo/embedding_ready.jsonl",
        "rag/data/m0-demo/knowledge_documents.jsonl",
        "rag/data/m0-demo/review_queue.jsonl",
        "systemd/psynova-school-rag.service",
    }
    if not required.issubset(actual) or not any(
        name.startswith("rag/src/rag_engine/") and name.endswith(".py")
        for name in actual
    ):
        raise GateError("bundle_required_files_missing", "bundle_preflight")
    return manifest, files


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "" not in path.parts
        and "\\" not in name
    )


def _allowed_payload_path(name: str) -> bool:
    return (
        name.startswith("rag/src/rag_engine/")
        or name in {
            "rag/THIRD_PARTY_NOTICES.md",
            "rag/config/school_m0_demo_bm25.v1.json",
            "rag/data/m0-demo/embedding_ready.jsonl",
            "rag/data/m0-demo/knowledge_documents.jsonl",
            "rag/data/m0-demo/review_queue.jsonl",
            "rag/data/m0-demo/manifest.json",
            "systemd/psynova-school-rag.service",
        }
    )


def _preflight() -> tuple[dict[str, Any], dict[str, bytes]]:
    _require_root_snapshot()
    _check_systemd()
    try:
        base_revision = (BASE_RELEASE / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
    except OSError:
        raise GateError("base_release_revision_unavailable", "host_preflight") from None
    if base_revision != BASE_REVISION:
        raise GateError("base_release_revision_mismatch", "host_preflight")
    revision_path = BASE_RELEASE / "SOURCE_REVISION"
    revision_metadata = revision_path.stat(follow_symlinks=False)
    if revision_path.is_symlink() or revision_metadata.st_uid != 0:
        raise GateError("base_release_revision_metadata_mismatch", "host_preflight")
    _require_root_owned_directory(STATE_PATH.parent, "state_directory_metadata_mismatch")
    _require_root_owned_directory(UNIT_PATH.parent, "systemd_directory_metadata_mismatch")
    if not _active_unit("mysql.service") or not _active_unit("psynova-school-demo.service"):
        raise GateError("required_base_service_inactive", "host_preflight")

    if os.path.lexists(STATE_PATH):
        if STATE_PATH.is_file() and not STATE_PATH.is_symlink():
            state = _read_state()
            if state.get("bundle_sha256") == BUNDLE_SHA256:
                manifest, files = _bundle_manifest(BUNDLE_PATH)
                _verify_completed_install(state, manifest, files)
                return state, files
        raise GateError("uncheckpointed_partial_install", "host_preflight")
    if _has_uncheckpointed_objects():
        raise GateError("uncheckpointed_partial_install", "host_preflight")

    required_package_check = [
        str(APP_ROOT / "venv" / "bin" / "python"),
        "-c",
        "import bm25s, fastapi, numpy, uvicorn, jsonschema, pydantic, httpx",
    ]
    _run(required_package_check, phase="dependency_preflight")
    manifest, files = _bundle_manifest(BUNDLE_PATH)
    return manifest, files


def _has_uncheckpointed_objects() -> bool:
    services_root = SERVICE_ROOT.parent
    if os.path.lexists(services_root) and (
        services_root.is_symlink() or not services_root.is_dir()
    ):
        return True
    pending_paths = (
        list(services_root.glob(".rag-pending-*")) if services_root.is_dir() else []
    )
    return any(
        (
            os.path.lexists(SERVICE_ROOT),
            os.path.lexists(UNIT_PATH),
            os.path.lexists(RAG_STATE_DIRECTORY),
            os.path.lexists(STATE_PATH),
            bool(pending_paths),
            _active_unit(SERVICE_NAME),
            _enabled_unit(SERVICE_NAME),
            bool(_port_8170_listeners()),
        )
    )


def _read_state() -> dict[str, Any]:
    try:
        metadata = STATE_PATH.stat(follow_symlinks=False)
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise GateError("rag_checkpoint_unreadable", "checkpoint_check") from None
    if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600 or type(value) is not dict:
        raise GateError("rag_checkpoint_metadata_mismatch", "checkpoint_check")
    return value


def _verify_completed_install(
    state: dict[str, Any], manifest: dict[str, Any], files: dict[str, bytes]
) -> None:
    if (
        state.get("phase") != "HTTP_VERIFIED"
        or state.get("source_commit") != SOURCE_COMMIT
        or state.get("bundle_sha256") != BUNDLE_SHA256
        or not SERVICE_ROOT.is_dir()
        or SERVICE_ROOT.is_symlink()
        or not UNIT_PATH.is_file()
        or UNIT_PATH.is_symlink()
    ):
        raise GateError("rag_checkpoint_state_mismatch", "checkpoint_check")
    for name, data in files.items():
        if name == "PAYLOAD_MANIFEST.json":
            target = SERVICE_ROOT / name
        elif name.startswith("rag/"):
            target = SERVICE_ROOT / PurePosixPath(name).relative_to("rag")
        elif name == "systemd/psynova-school-rag.service":
            target = UNIT_PATH
        else:
            raise GateError("installed_file_inventory_mismatch", "checkpoint_check")
        try:
            if target.is_symlink():
                raise GateError("installed_file_symlink_rejected", "checkpoint_check")
            if _sha256(target) != hashlib.sha256(data).hexdigest():
                raise GateError("installed_file_fingerprint_mismatch", "checkpoint_check")
        except GateError:
            raise
        except OSError:
            raise GateError("installed_file_missing", "checkpoint_check") from None
    if not _enabled_unit(SERVICE_NAME) or not _active_unit(SERVICE_NAME):
        raise GateError("rag_service_not_active_and_enabled", "checkpoint_check")
    _verify_listener()
    _verify_http_acceptance()


def _verify_listener() -> None:
    listeners = _port_8170_listeners()
    if listeners != ["127.0.0.1:8170"]:
        raise GateError("rag_listener_scope_mismatch", "http_verification")


def _request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise GateError("rag_http_status_mismatch", "http_verification")
            value = json.loads(response.read(1024 * 1024))
    except GateError:
        raise
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        raise GateError("rag_http_request_failed", "http_verification") from None
    if type(value) is not dict:
        raise GateError("rag_http_response_invalid", "http_verification")
    return value


def _retrieval_payload(population: str, suffix: str) -> dict[str, Any]:
    return {
        "assessment": {
            "schema_version": "assessment.v1",
            "assessment_id": f"ASSESS_linux_rag_{suffix}",
            "subject_id": f"SUBJ_synthetic_rag_{suffix}",
            "population_scope": population,
            "status": "completed",
            "dimensions": {"study_planning": {"band": "unknown"}},
            "risk": {"level": "normal", "need_human_review": False},
        },
        "target_role": "student",
        "query": "如何拆分学习任务并安排下一步",
        "top_k": 3,
        "target_population": population,
    }


def _verify_http_acceptance() -> dict[str, int]:
    health = _request_json(HEALTH_URL)
    if (
        health.get("status") != "READY"
        or health.get("retrieval_mode") != "bm25"
        or health.get("synthetic_fixture_only") is not True
        or health.get("eligible_chunk_count") != 3
        or health.get("rerank_enabled") is not False
    ):
        raise GateError("rag_health_contract_mismatch", "http_verification")

    accepted = _request_json(
        RETRIEVAL_URL, _retrieval_payload("university_student", "student")
    ).get("data")
    if type(accepted) is not dict:
        raise GateError("rag_positive_retrieval_invalid", "http_verification")
    chunks = accepted.get("chunks")
    citations = accepted.get("citations", {}).get("citations")
    if (
        type(chunks) is not list
        or not chunks
        or type(citations) is not list
        or not citations
        or any(
            type(item) is not dict
            or
            item.get("rights_status") != "verified"
            or item.get("review_status") != "approved"
            or "university_student" not in item.get("population_scope", [])
            for item in chunks
        )
    ):
        raise GateError("rag_positive_retrieval_scope_mismatch", "http_verification")

    rejected = _request_json(
        RETRIEVAL_URL,
        _retrieval_payload("secondary_school_student", "secondary_scope"),
    ).get("data")
    if (
        type(rejected) is not dict
        or rejected.get("chunks") != []
        or rejected.get("citations", {}).get("citations") != []
    ):
        raise GateError("rag_cross_population_retrieval_not_abstained", "http_verification")
    return {"eligible_chunks": health["eligible_chunk_count"], "retrieved_chunks": len(chunks), "citations": len(citations)}


def _write_file(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(path, 0, 0)
    os.chmod(path, mode)


def _install_payload(files: dict[str, bytes]) -> None:
    services_root = SERVICE_ROOT.parent
    if os.path.lexists(services_root) and (
        not services_root.is_dir() or services_root.is_symlink()
    ):
        raise GateError("service_parent_path_invalid", "install_payload")
    services_root.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chown(services_root, 0, 0)
    os.chmod(services_root, 0o755)
    staging = services_root / f".rag-pending-{BUNDLE_SHA256[:12]}"
    if os.path.lexists(staging):
        raise GateError("rag_staging_path_exists", "install_payload")
    staging.mkdir(mode=0o755)
    os.chown(staging, 0, 0)
    unit_bytes = files["systemd/psynova-school-rag.service"]
    for name, data in files.items():
        if name == "PAYLOAD_MANIFEST.json" or name == "systemd/psynova-school-rag.service":
            continue
        relative = PurePosixPath(name).relative_to("rag")
        target = staging.joinpath(*relative.parts)
        _write_file(target, data, 0o644)
    _write_file(staging / "PAYLOAD_MANIFEST.json", files["PAYLOAD_MANIFEST.json"], 0o644)
    if os.path.lexists(SERVICE_ROOT):
        raise GateError("rag_destination_appeared", "install_payload")
    os.rename(staging, SERVICE_ROOT)
    if os.path.lexists(UNIT_PATH):
        raise GateError("rag_unit_destination_appeared", "install_unit")
    _write_file(UNIT_PATH, unit_bytes, 0o644)


def _write_checkpoint(results: dict[str, int]) -> None:
    if STATE_PATH.exists() or STATE_PATH.is_symlink():
        raise GateError("rag_checkpoint_already_exists", "checkpoint_write")
    state = {
        "schema": "psynova.school-rag-install-state.v1",
        "phase": "HTTP_VERIFIED",
        "source_commit": SOURCE_COMMIT,
        "base_release_revision": BASE_REVISION,
        "bundle_sha256": BUNDLE_SHA256,
        "corpus_kind": "synthetic-m0-university-student-demo",
        "retrieval_mode": "bm25",
        "checks": {
            "service_loopback_only": True,
            "positive_retrieval_and_citations": True,
            "cross_population_abstention": True,
        },
        "counts": results,
        "completed_at_epoch": int(time.time()),
    }
    parent = STATE_PATH.parent
    if not parent.is_dir() or parent.is_symlink():
        raise GateError("state_directory_unavailable", "checkpoint_write")
    data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    _write_file(STATE_PATH, data, 0o600)


def _report(status: str, **fields: Any) -> None:
    print(json.dumps({"rag_service": status, **fields}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    phase = "startup"
    lock_context = None
    lock_entered = False
    try:
        _require_root_snapshot()
        if args.inspect and not os.path.lexists(STATE_PATH):
            if _has_uncheckpointed_objects():
                raise GateError("uncheckpointed_partial_install", "inspect")
            _report("NOT_INSTALLED", phase="inspect", writes=False)
            return 0
        if args.resume:
            lock_context = _deployment_lock()
            lock_context.__enter__()
            lock_entered = True
        manifest, files = _preflight()
        if args.inspect:
            results = _verify_http_acceptance()
            _report(
                "PASS",
                phase="HTTP_VERIFIED",
                source_commit=SOURCE_COMMIT,
                bundle_sha256=BUNDLE_SHA256,
                counts=results,
                service_active=_active_unit(SERVICE_NAME),
                service_enabled=_enabled_unit(SERVICE_NAME),
                listener="127.0.0.1:8170",
                writes=False,
            )
            return 0
        if args.dry_run:
            if STATE_PATH.exists():
                _verify_completed_install(_read_state(), manifest, files)
                _report("PASS", phase="COMPLETE", writes=False, actions=[])
                return 0
            _report(
                "PASS",
                phase="READY",
                writes=False,
                actions=[
                    "install hash-pinned RAG code and synthetic export",
                    "install loopback-only systemd unit",
                    "start and enable psynova-school-rag.service",
                    "verify positive citations and cross-population abstention",
                ],
            )
            return 0

        if STATE_PATH.exists():
            _verify_completed_install(_read_state(), manifest, files)
            _report("PASS", phase="COMPLETE", already_installed=True, writes=False)
            return 0

        phase = "install_payload"
        _install_payload(files)
        phase = "systemd_verify"
        _run(["systemd-analyze", "verify", str(UNIT_PATH)], phase=phase)
        phase = "systemd_start"
        _run(["systemctl", "daemon-reload"], phase=phase)
        _run(["systemctl", "enable", "--now", SERVICE_NAME], phase=phase, timeout=90)
        phase = "http_verification"
        deadline = time.monotonic() + 90
        last_error: GateError | None = None
        results: dict[str, int] | None = None
        while time.monotonic() < deadline:
            try:
                _verify_listener()
                results = _verify_http_acceptance()
                last_error = None
                break
            except GateError as exc:
                last_error = exc
                time.sleep(2)
        if last_error is not None or results is None:
            raise GateError("rag_http_acceptance_failed", phase) from None
        phase = "checkpoint_write"
        _write_checkpoint(results)
        _report(
            "PASS",
            phase="HTTP_VERIFIED",
            source_commit=SOURCE_COMMIT,
            bundle_sha256=BUNDLE_SHA256,
            counts=results,
            service_active=True,
            service_enabled=True,
            listener="127.0.0.1:8170",
            secrets_logged=False,
        )
        return 0
    except GateError as exc:
        _report("BLOCKED", phase=exc.phase or phase, error_code=exc.code)
        return 2
    except Exception:  # noqa: BLE001 - keep raw host errors out of deploy output.
        _report("BLOCKED", phase=phase, error_code="unexpected_failure")
        return 2
    finally:
        if lock_entered and lock_context is not None:
            lock_context.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
