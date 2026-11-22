"""Single-entry launcher for the isolated PsyNova synthetic school demo.

This module orchestrates the already-reviewed workspace, migration, runtime,
import, and application lifecycle tools. It never prints credentials and never
resets an existing workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DB_ROOT = REPO / "11_database"
BACKEND_ROOT = REPO / "09_backend"
DB_PYTHON = DB_ROOT / ".venv" / "Scripts" / "python.exe"
BACKEND_PYTHON = BACKEND_ROOT / ".venv" / "Scripts" / "python.exe"
CAT_ROOT = REPO / "01_cat-engine"
CAT_PYTHON = CAT_ROOT / ".venv" / "Scripts" / "python.exe"
DEFAULT_FRONTEND_EDITION = "vue"
FRONTEND_ROOTS = {"vue": REPO / "10_frontend", "react": REPO / "10_frontend_react"}
DEMO_PLAN_NAME = "school-demo.v1.json"
IMPORT_PLAN_NAME = "school-demo-import-plan.json"
DEFAULT_WORKSPACE = Path(os.environ.get("PSYNOVA_WORKSPACE", r"D:\PsyNova"))
DEFAULT_DB_PORT = 3344
DEFAULT_BACKEND_PORT = 8088
DEFAULT_FRONTEND_PORT = 4178
DEFAULT_STANDARD_CAT_PORT = 8180
MYSQL_CANDIDATES = (
    Path(os.environ["PSYNOVA_MYSQL_BIN"]) if os.environ.get("PSYNOVA_MYSQL_BIN") else None,
    Path(r"D:\Software\MySQLServer8.4\bin"),
    Path(r"C:\Program Files\MySQL\MySQL Server 8.4\bin"),
    Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin"),
)


class LauncherError(RuntimeError):
    """A fixed, non-sensitive failure code."""

    def __init__(self, code: str, stage: str, detail: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.detail = detail or {}


def _json_output(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _env() -> dict[str, str]:
    result = dict(os.environ)
    paths = [
        str(REPO / "13_deployment"),
        str(DB_ROOT),
        str(BACKEND_ROOT / "src"),
        str(DB_ROOT / ".venv" / "Lib" / "site-packages"),
    ]
    existing = result.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    result["PYTHONPATH"] = ";".join(paths)
    result["PYTHONUTF8"] = "1"
    result.pop("PYTHONHOME", None)
    return result


def _run(
    argv: list[str],
    *,
    timeout: int = 900,
    stage: str,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=REPO,
            env=_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LauncherError("COMMAND_START_FAILED", stage, {"type": type(exc).__name__}) from None
    output = completed.stdout.strip()
    parsed: dict[str, Any] = {}
    if output:
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                parsed = value
                break
    if completed.returncode != 0:
        code = str(parsed.get("code") or parsed.get("error_code") or "COMMAND_FAILED")
        raise LauncherError(code, stage, {"exit_code": completed.returncode, "result": parsed})
    return parsed


def _python(launcher: Path, stage: str) -> Path:
    if not launcher.is_file():
        raise LauncherError("PYTHON_ENV_MISSING", stage, {"expected": str(launcher)})
    return launcher


def _mysql_bin(value: Path | None) -> Path:
    candidates = ([value] if value else []) + [item for item in MYSQL_CANDIDATES if item]
    for candidate in candidates:
        if candidate and (candidate / "mysqld.exe").is_file():
            return candidate.resolve()
    raise LauncherError("MYSQL_BIN_UNAVAILABLE", "doctor")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _marker(workspace: Path) -> dict[str, Any] | None:
    path = workspace / "workspace.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise LauncherError("WORKSPACE_MARKER_INVALID", "workspace") from None
    if not isinstance(value, dict):
        raise LauncherError("WORKSPACE_MARKER_INVALID", "workspace")
    return value


def _doctor(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str | None = None, required: bool = True) -> None:
        checks.append({"name": name, "ok": bool(ok), "required": required, "detail": detail})

    check("windows", os.name == "nt", "Windows current-user DPAPI is required")
    check("database_python", DB_PYTHON.is_file(), str(DB_PYTHON))
    check("backend_python", BACKEND_PYTHON.is_file(), str(BACKEND_PYTHON))
    check("cat_python", CAT_PYTHON.is_file(), str(CAT_PYTHON))
    frontend_root = FRONTEND_ROOTS[getattr(args, "frontend_edition", None) or DEFAULT_FRONTEND_EDITION]
    check("frontend_vite", (frontend_root / "node_modules" / "vite" / "bin" / "vite.js").is_file())
    check("node", shutil.which("node") is not None, shutil.which("node"))
    try:
        mysql = _mysql_bin(args.mysql_bin)
        check("mysql_bin", True, str(mysql))
    except LauncherError:
        check("mysql_bin", False, "Set --mysql-bin or PSYNOVA_MYSQL_BIN")
    marker = _marker(args.workspace) if args.workspace.exists() else None
    check("workspace", marker is not None or not args.workspace.exists(), str(args.workspace))
    if marker is not None:
        check("workspace_synthetic", marker.get("synthetic_only") is True, marker.get("workspace_id"))
        check("workspace_database", marker.get("database") == "smhai_school_demo")
    for name, port in (
        ("backend_port", args.backend_port),
        ("frontend_port", args.frontend_port),
        ("standard_cat_port", getattr(args, "standard_cat_port", DEFAULT_STANDARD_CAT_PORT)),
    ):
        check(name, _port_free(port) or marker is not None, str(port), required=False)
    required_ok = all(item["ok"] for item in checks if item["required"])
    return {
        "status": "READY" if required_ok else "BLOCKED",
        "checks": checks,
        "workspace": str(args.workspace),
    }


def _ensure_workspace(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    marker = _marker(args.workspace)
    if marker is not None:
        if (
            marker.get("schema_version") != "psynova.synthetic-workspace.v1"
            or marker.get("project") != "StudentMentalHealthAI"
            or marker.get("synthetic_only") is not True
            or marker.get("database") != "smhai_school_demo"
        ):
            raise LauncherError("WORKSPACE_UNSUPPORTED", "workspace")
        return marker, False
    if args.workspace.exists():
        raise LauncherError("WORKSPACE_PATH_NOT_EMPTY", "workspace")
    mysql = _mysql_bin(args.mysql_bin)
    db_python = _python(DB_PYTHON, "workspace")
    result = _run(
        [
            str(db_python),
            str(REPO / "13_deployment" / "create_school_workspace.py"),
            "--workspace",
            str(args.workspace),
            "--mysql-bin",
            str(mysql),
            "--port",
            str(args.database_port),
        ],
        stage="workspace",
    )
    if result.get("state") != "READY_FOR_MIGRATION":
        raise LauncherError("WORKSPACE_CREATE_UNEXPECTED", "workspace", result)
    marker = _marker(args.workspace)
    if marker is None:
        raise LauncherError("WORKSPACE_MARKER_MISSING", "workspace")
    return marker, True


def _migrate(args: argparse.Namespace, marker: dict[str, Any]) -> dict[str, Any]:
    db_python = _python(DB_PYTHON, "migration")
    return _run(
        [
            str(db_python),
            str(REPO / "13_deployment" / "migrate_school_workspace.py"),
            "upgrade",
            "--workspace",
            str(args.workspace),
            "--expected-port",
            str(marker["port"]),
            "--workspace-id",
            str(marker["workspace_id"]),
        ],
        stage="migration",
    )


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    if (args.workspace / "runtime-ready.json").is_file():
        return {"runtime_identity": "EXISTING"}
    db_python = _python(DB_PYTHON, "runtime")
    return _run(
        [
            str(db_python),
            str(REPO / "13_deployment" / "prepare_school_runtime.py"),
            "--workspace",
            str(args.workspace),
        ],
        stage="runtime",
    )


def _generate_demo(args: argparse.Namespace) -> dict[str, Any]:
    plan = args.workspace / DEMO_PLAN_NAME
    if plan.is_file():
        return {"status": "EXISTING", "source": str(plan)}
    python = _python(BACKEND_PYTHON, "demo")
    return _run(
        [
            str(python),
            str(REPO / "15_demo" / "school_demo_generator.py"),
            "--output",
            str(plan),
        ],
        stage="demo",
    )


def _plan_demo(args: argparse.Namespace) -> dict[str, Any]:
    source = args.workspace / DEMO_PLAN_NAME
    plan = args.workspace / IMPORT_PLAN_NAME
    if plan.is_file():
        return {"status": "EXISTING", "import_plan": str(plan)}
    python = _python(BACKEND_PYTHON, "demo")
    return _run(
        [
            str(python),
            str(REPO / "15_demo" / "school_demo_importer.py"),
            "plan",
            "--input",
            str(source),
            "--output",
            str(plan),
        ],
        stage="demo",
    )


def _apply_demo(args: argparse.Namespace, marker: dict[str, Any]) -> dict[str, Any]:
    source = args.workspace / DEMO_PLAN_NAME
    plan_path = args.workspace / IMPORT_PLAN_NAME
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        confirmation = plan["apply_contract"]["confirmation"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        raise LauncherError("IMPORT_PLAN_INVALID", "demo") from None
    python = _python(BACKEND_PYTHON, "demo")
    result = _run(
        [
            str(python),
            str(REPO / "15_demo" / "school_demo_importer.py"),
            "apply",
            "--input",
            str(source),
            "--import-plan",
            str(plan_path),
            "--workspace",
            str(args.workspace),
            "--workspace-id",
            str(marker["workspace_id"]),
            "--confirm",
            confirmation,
        ],
        stage="demo",
        timeout=1200,
    )
    if result.get("status") not in {"APPLIED", "VERIFIED", "ALREADY_APPLIED"}:
        raise LauncherError("DEMO_IMPORT_UNEXPECTED", "demo", {"status": result.get("status")})
    return result


def _verify_demo(args: argparse.Namespace, marker: dict[str, Any]) -> dict[str, Any]:
    python = _python(BACKEND_PYTHON, "verify")
    return _run(
        [
            str(python),
            str(REPO / "15_demo" / "school_demo_importer.py"),
            "verify",
            "--input",
            str(args.workspace / DEMO_PLAN_NAME),
            "--import-plan",
            str(args.workspace / IMPORT_PLAN_NAME),
            "--workspace",
            str(args.workspace),
            "--workspace-id",
            str(marker["workspace_id"]),
        ],
        stage="verify",
        timeout=300,
    )


def _lifecycle(argv: list[str], stage: str) -> dict[str, Any]:
    db_python = _python(DB_PYTHON, stage)
    return _run(
        [str(db_python), str(REPO / "13_deployment" / "school_app_lifecycle.py"), *argv],
        stage=stage,
        timeout=240,
    )


def _resume_database_if_stopped(workspace: Path, marker: dict[str, Any]) -> None:
    port = marker.get("port")
    workspace_id = marker.get("workspace_id")
    if (
        marker.get("schema_version") != "psynova.synthetic-workspace.v1"
        or marker.get("project") != "StudentMentalHealthAI"
        or marker.get("synthetic_only") is not True
        or marker.get("database") != "smhai_school_demo"
        or type(port) is not int
        or not 3308 <= port <= 3399
        or not isinstance(workspace_id, str)
    ):
        raise LauncherError("WORKSPACE_UNSUPPORTED", "database_resume")
    if not _port_free(port):
        return
    _run(
        [
            str(_python(DB_PYTHON, "database_resume")),
            str(REPO / "13_deployment" / "resume_school_workspace.py"),
            "--prepared-install-mode",
            "--workspace",
            str(workspace.absolute()),
            "--port",
            str(port),
            "--expected-workspace-id",
            workspace_id,
        ],
        stage="database_resume",
        timeout=90,
    )


def _start(args: argparse.Namespace, marker: dict[str, Any]) -> dict[str, Any]:
    try:
        status = _lifecycle(["status", "--workspace", str(args.workspace)], "lifecycle")
    except LauncherError:
        status = {}
    requested_edition = getattr(args, "frontend_edition", None)
    running_edition = status.get("frontend_edition", DEFAULT_FRONTEND_EDITION)
    requested_profile = getattr(args, "llm_profile", None)
    running_profile = status.get("llm_profile") or "default"
    if _application_ready(status):
        if requested_edition and requested_edition != running_edition:
            raise LauncherError("FRONTEND_EDITION_ALREADY_RUNNING", "lifecycle")
        if requested_profile and requested_profile != running_profile:
            raise LauncherError("LLM_PROFILE_ALREADY_RUNNING", "lifecycle")
        return status
    edition = requested_edition or running_edition
    if status.get("status") == "RUNNING":
        _lifecycle(["stop", "--workspace", str(args.workspace)], "lifecycle")
    return _lifecycle(
        [
            "start",
            "--workspace",
            str(args.workspace),
            "--backend-port",
            str(args.backend_port),
            "--frontend-port",
            str(args.frontend_port),
            "--frontend-mode",
            args.frontend_mode,
            "--frontend-edition",
            edition,
            "--llm-profile",
            requested_profile or running_profile,
            "--enable-standard-cat",
            "--standard-cat-port",
            str(getattr(args, "standard_cat_port", DEFAULT_STANDARD_CAT_PORT)),
            "--timeout",
            "90",
        ],
        "lifecycle",
    )


def _application_ready(status: dict[str, Any]) -> bool:
    if status.get("status") != "RUNNING":
        return False
    services = status.get("services")
    if not isinstance(services, dict):
        return False
    for name in ("backend", "frontend"):
        service = services.get(name)
        if (
            not isinstance(service, dict)
            or service.get("ready") is not True
            or service.get("owned_process") is not True
        ):
            return False
    standard_cat = status.get("standard_cat")
    if isinstance(standard_cat, dict) and standard_cat.get("enabled") is True:
        return standard_cat.get("readiness") == "READY"
    return True


def _stop(args: argparse.Namespace) -> dict[str, Any]:
    manifest = args.workspace / "school-app-lifecycle.json"
    if not manifest.is_file():
        return {"status": "STOPPED", "services": []}
    return _lifecycle(["stop", "--workspace", str(args.workspace)], "lifecycle")


def _install(args: argparse.Namespace) -> dict[str, Any]:
    doctor = _doctor(args)
    if doctor["status"] != "READY":
        raise LauncherError("PREREQUISITES_INCOMPLETE", "doctor", {"checks": doctor["checks"]})
    marker, created = _ensure_workspace(args)
    args.database_port = int(marker["port"])
    migration = _migrate(args, marker)
    runtime = _prepare(args)
    if getattr(args, "demo_profile", None) == "school-empty":
        setup = _run(
            [
                str(_python(BACKEND_PYTHON, "school_setup")),
                str(REPO / "13_deployment" / "school_empty_bootstrap.py"),
                "--workspace", str(args.workspace),
            ],
            stage="school_setup",
        )
        if setup.get("status") not in {"INITIALIZED", "ALREADY_INITIALIZED"}:
            raise LauncherError("LOCAL_SCHOOL_SETUP_UNVERIFIED", "school_setup")
        application = _start(args, marker)
        if not _application_ready(application):
            raise LauncherError("LOCAL_SCHOOL_APPLICATION_NOT_READY", "lifecycle")
        return {
            "status": "READY", "workspace": str(args.workspace), "edition": "local-school",
            "initial_admin": setup["status"], "url": f"http://127.0.0.1:{args.frontend_port}/login",
        }
    if getattr(args, "demo_profile", "school-800") == "school-workflow":
        seed = _run(
            [
                str(_python(BACKEND_PYTHON, "seed")),
                str(REPO / "13_deployment" / "seed_school_workspace.py"),
                "--workspace",
                str(args.workspace),
            ],
            stage="seed",
            timeout=180,
        )
        if seed.get("recipe") != "school-contexts-v1" or seed.get("role_accounts") != 8:
            raise LauncherError("SCHOOL_WORKFLOW_SEED_UNVERIFIED", "seed")
        application = _start(args, marker)
        return {
            "status": "READY",
            "workspace": str(args.workspace),
            "workspace_id": marker["workspace_id"],
            "created_workspace": created,
            "database_port": marker["port"],
            "backend_port": args.backend_port,
            "frontend_port": args.frontend_port,
            "frontend_edition": application.get("frontend_edition", DEFAULT_FRONTEND_EDITION),
            "migration": migration.get("status"),
            "runtime": runtime.get("runtime_identity"),
            "demo": "SCHOOL_WORKFLOW",
            "school_role_accounts": seed["role_accounts"],
            "application": application.get("status"),
            "url": f"http://127.0.0.1:{args.frontend_port}",
        }
    _generate_demo(args)
    _plan_demo(args)
    try:
        imported = _apply_demo(args, marker)
    except LauncherError as exc:
        if (
            exc.code == "workspace_tenant_conflict"
            and (args.workspace / "school-demo-accounts.private.dpapi").is_file()
        ):
            imported = {"status": "EXISTING_MODIFIED"}
        else:
            raise
    try:
        verified = _verify_demo(args, marker)
    except LauncherError:
        verified = {"status": "MODIFIED", "counts": None}
    application = _start(args, marker)
    return {
        "status": "READY",
        "workspace": str(args.workspace),
        "workspace_id": marker["workspace_id"],
        "created_workspace": created,
        "database_port": marker["port"],
        "backend_port": args.backend_port,
        "frontend_port": args.frontend_port,
        "frontend_edition": application.get("frontend_edition", DEFAULT_FRONTEND_EDITION),
        "migration": migration.get("status"),
        "runtime": runtime.get("runtime_identity"),
        "demo": (
            "APPLIED"
            if imported.get("status") in {"APPLIED", "ALREADY_APPLIED"}
            else imported.get("status", "INSTALLED")
        ),
        "counts": verified.get("counts"),
        "application": application.get("status"),
        "url": f"http://127.0.0.1:{args.frontend_port}",
    }


def _status(args: argparse.Namespace) -> dict[str, Any]:
    marker = _marker(args.workspace)
    if marker is None:
        return {"status": "NOT_INSTALLED", "workspace": str(args.workspace)}
    try:
        application = _lifecycle(["status", "--workspace", str(args.workspace)], "lifecycle")
    except LauncherError as exc:
        application = {"status": "STOPPED", "code": exc.code}
    verification: dict[str, Any] = {}
    if (args.workspace / IMPORT_PLAN_NAME).is_file():
        try:
            verification = _verify_demo(args, marker)
        except LauncherError:
            verification = {"status": "INSTALLED_OR_MODIFIED", "counts": None}
    services = application.get("services")
    if not isinstance(services, dict):
        services = {}
    return {
        "status": application.get("status", "UNKNOWN"),
        "workspace": str(args.workspace),
        "workspace_id": marker.get("workspace_id"),
        "database_port": marker.get("port"),
        "backend_port": (
            application.get("backend_port")
            or application.get("application", {}).get("backend_port")
            or services.get("backend", {}).get("port")
        ),
        "frontend_port": (
            application.get("frontend_port")
            or application.get("application", {}).get("frontend_port")
            or services.get("frontend", {}).get("port")
        ),
        "demo": verification.get("status", "INSTALLED_OR_MODIFIED"),
        "frontend_edition": application.get("frontend_edition"),
        "counts": verification.get("counts"),
        "application": application,
    }


def _backup(args: argparse.Namespace) -> dict[str, Any]:
    db_python = _python(DB_PYTHON, "backup")
    return _run(
        [
            str(db_python),
            str(REPO / "13_deployment" / "school_backup.py"),
            "--workspace",
            str(args.workspace),
        ],
        stage="backup",
        timeout=900,
    )


def _accounts(args: argparse.Namespace) -> dict[str, Any]:
    path = args.workspace / "school-demo-accounts.private.dpapi"
    if not path.is_file():
        raise LauncherError("DEMO_ACCOUNTS_MISSING", "accounts")
    try:
        from private_settings import read_private

        payload = read_private(path)
        slots = payload["slots"]
    except Exception:  # noqa: BLE001 - DPAPI details stay local and non-sensitive.
        raise LauncherError("DEMO_ACCOUNTS_UNREADABLE", "accounts") from None
    if not isinstance(slots, dict) or set(slots) != {"student", "teacher", "specialist", "grade_lead"}:
        raise LauncherError("DEMO_ACCOUNTS_INVALID", "accounts")
    print("SYNTHETIC_DEMO local-only credentials. Do not screenshot or share.")
    print("slot\trole\tusername\tpassword")
    for slot in ("student", "teacher", "specialist", "grade_lead"):
        value = slots[slot]
        print(
            f"{slot}\t{value.get('role_code')}\t"
            f"{value.get('login_name')}\t{value.get('password')}"
        )
    return {"status": "DISPLAYED_LOCAL_ONLY", "workspace": str(args.workspace)}


def _uninstall(args: argparse.Namespace) -> dict[str, Any]:
    stopped = _stop(args)
    if not args.purge_data:
        return {"status": "STOPPED_DATA_RETAINED", "workspace": str(args.workspace), "application": stopped}
    marker = _marker(args.workspace)
    if marker is None or args.confirm_purge != f"PURGE_{marker.get('workspace_id')}":
        raise LauncherError("PURGE_CONFIRMATION_REQUIRED", "uninstall")
    target = args.workspace.resolve(strict=True)
    repo = REPO.resolve(strict=True)
    if target == repo or repo in target.parents or target.anchor != "D:\\":
        raise LauncherError("PURGE_PATH_REJECTED", "uninstall")
    shutil.rmtree(target)
    return {"status": "PURGED", "workspace": str(target)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser, *, workspace_required: bool = False) -> None:
        sub.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE, required=workspace_required)

    doctor = commands.add_parser("doctor")
    common(doctor)
    doctor.add_argument("--mysql-bin", type=Path)
    doctor.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    doctor.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    doctor.add_argument("--standard-cat-port", type=int, default=DEFAULT_STANDARD_CAT_PORT)
    doctor.add_argument("--frontend-edition", choices=("vue", "react"), default=DEFAULT_FRONTEND_EDITION)

    install = commands.add_parser("install")
    common(install)
    install.add_argument("--mysql-bin", type=Path)
    install.add_argument("--database-port", type=int, default=DEFAULT_DB_PORT)
    install.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    install.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    install.add_argument("--standard-cat-port", type=int, default=DEFAULT_STANDARD_CAT_PORT)
    install.add_argument("--frontend-mode", choices=("dev", "preview"), default="preview")
    install.add_argument("--frontend-edition", choices=("vue", "react"), default=DEFAULT_FRONTEND_EDITION)
    install.add_argument("--llm-profile", choices=("default", "school-gpu-7b"))
    install.add_argument(
        "--demo-profile", choices=("school-800", "school-workflow", "school-empty"), default="school-800",
    )

    for name in ("start", "stop", "status", "backup", "accounts"):
        sub = commands.add_parser(name)
        common(sub)
    start = commands.choices["start"] if hasattr(commands, "choices") else None
    if start is not None:
        start.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
        start.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
        start.add_argument("--standard-cat-port", type=int, default=DEFAULT_STANDARD_CAT_PORT)
        start.add_argument("--frontend-mode", choices=("dev", "preview"), default="preview")
        start.add_argument("--frontend-edition", choices=("vue", "react"), default=DEFAULT_FRONTEND_EDITION)
        start.add_argument("--llm-profile", choices=("default", "school-gpu-7b"))

    uninstall = commands.add_parser("uninstall")
    common(uninstall)
    uninstall.add_argument("--purge-data", action="store_true")
    uninstall.add_argument("--confirm-purge")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = _doctor(args)
        elif args.command == "install":
            result = _install(args)
        elif args.command == "start":
            marker = _marker(args.workspace)
            if marker is None:
                raise LauncherError("NOT_INSTALLED", "start")
            _resume_database_if_stopped(args.workspace, marker)
            result = _start(args, marker)
        elif args.command == "stop":
            result = _stop(args)
        elif args.command == "status":
            result = _status(args)
        elif args.command == "backup":
            result = _backup(args)
        elif args.command == "accounts":
            result = _accounts(args)
        elif args.command == "uninstall":
            result = _uninstall(args)
        else:
            raise LauncherError("COMMAND_UNSUPPORTED", "cli")
    except LauncherError as exc:
        _json_output(
            {
                "status": "BLOCKED",
                "stage": exc.stage,
                "code": exc.code,
                **exc.detail,
            }
        )
        return 2
    _json_output(result)
    return 0 if result.get("status") not in {"BLOCKED", "NOT_INSTALLED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
