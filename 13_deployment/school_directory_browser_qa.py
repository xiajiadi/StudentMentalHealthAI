"""Prepare a sanitized real-browser school-directory check.

This wrapper validates the exact synthetic workspace and its owned processes,
then passes only the existing admin login to the Node runner over stdin. It
does not print credentials, HTTP bodies, browser diagnostics, or free-form
child output.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "10_frontend"
NODE_SCRIPT = Path(__file__).with_name("school_directory_browser_qa.mjs")
WORKSPACE = Path(r"D:\Projects\.StudentMentalHealthAI-school-workspace-20261011")
WORKSPACE_ID = "310c6ddbed2c9f6985feb95c3ae28919"
DATABASE = "smhai_school_demo"
DATABASE_PORT = 3308
BACKEND_PORT = 8088
FRONTEND_PORT = 4178
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"
ACCOUNT_FILE = "school-accounts.private.dpapi"
BROWSER_CACHE = Path(r"D:\Dev\caches\ms-playwright")
SCHOOL_REF = "SYNTHETIC_SCHOOL_SEED_ALPHA_V1"
STAGE_KEYS = (
    "admin_login",
    "directory_open",
    "school_name_configure",
    "school_name_restore",
    "csv_select",
    "csv_preview",
    "csv_import",
    "directory_screenshot",
    "student_cancel_clears_password",
    "student_activate",
    "teacher_activate",
    "student_login",
    "student_role_ui",
    "teacher_login",
    "teacher_role_ui",
    "session_cleanup",
    "screenshots",
)
SCREENSHOTS = (
    "school-directory-import.png",
    "new-student-home.png",
    "new-teacher-overview.png",
)


class HarnessError(RuntimeError):
    """Fixed safe harness error; callers never expose its message."""


def _result(stages: dict[str, str] | None = None) -> dict[str, Any]:
    safe_stages = {
        key: "PASS" if stages and stages.get(key) == "PASS" else "FAIL"
        for key in STAGE_KEYS
    }
    return {
        "workflow": "school-directory",
        "status": "PASS" if all(value == "PASS" for value in safe_stages.values()) else "FAIL",
        "runner_status": "FAIL",
        "stages": safe_stages,
        "screenshots": list(SCREENSHOTS)
        if safe_stages["screenshots"] == "PASS"
        else [],
    }


def _reject_reparse_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise HarnessError("InvalidWorkspacePath")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        try:
            attributes = getattr(cursor.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            raise HarnessError("WorkspacePathMissing") from None
        if attributes & 0x400:
            raise HarnessError("WorkspaceReparsePath")


def _verified_workspace() -> tuple[Path, dict[str, Any]]:
    if os.name != "nt":
        raise HarnessError("WindowsWorkspaceRequired")
    _reject_reparse_path(WORKSPACE)
    _reject_reparse_path(WORKSPACE / "workspace.json")
    if WORKSPACE.name != ".StudentMentalHealthAI-school-workspace-20261011":
        raise HarnessError("ExactWorkspaceRequired")

    for path in (
        REPO / "11_database" / ".venv" / "Lib" / "site-packages",
        REPO / "11_database",
        REPO / "09_backend" / "src",
        REPO / "13_deployment",
    ):
        sys.path.insert(0, str(path))
    from prepare_school_runtime import PreparationError, validate_marker
    from resume_school_workspace import ResumeError, ResumeOperations, _process_matches

    try:
        resolved = WORKSPACE.resolve(strict=True)
        if resolved != WORKSPACE or resolved.is_relative_to(REPO.resolve(strict=True)):
            raise HarnessError("ExactWorkspaceRequired")
        marker = validate_marker(resolved, REPO)
    except HarnessError:
        raise
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, PreparationError):
        raise HarnessError("WorkspaceMarkerInvalid") from None
    if (
        marker.get("workspace_id") != WORKSPACE_ID
        or marker.get("database") != DATABASE
        or marker.get("port") != DATABASE_PORT
        or marker.get("host") != "127.0.0.1"
        or marker.get("synthetic_only") is not True
    ):
        raise HarnessError("WorkspaceMarkerMismatch")

    try:
        process = ResumeOperations().inspect_process(marker["parent_pid"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, subprocess.SubprocessError, ResumeError):
        raise HarnessError("WorkspaceProcessUnavailable") from None
    if not process or not _process_matches(process, marker):
        raise HarnessError("WorkspaceProcessMismatch")

    return resolved, marker


def _inspect_application_listeners(workspace: Path) -> None:
    """Match the two listeners to the exact identities in the external manifest."""
    from resume_school_workspace import (
        ResumeError,
        ResumeOperations,
        _command_arguments,
        _utc_timestamp,
    )

    manifest_path = workspace / "school-processes.json"
    _reject_reparse_path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise HarnessError("ApplicationManifestUnavailable") from None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "psynova.owned-processes.v1"
        or manifest.get("project") != "StudentMentalHealthAI"
        or manifest.get("repository") != str(REPO)
        or manifest.get("shared_modules_owned") is not False
        or not isinstance(manifest.get("services"), list)
    ):
        raise HarnessError("ApplicationManifestMismatch")
    by_port: dict[int, dict[str, Any]] = {}
    for item in manifest["services"]:
        if not isinstance(item, dict) or item.get("port") not in {BACKEND_PORT, FRONTEND_PORT}:
            continue
        port = item["port"]
        if port in by_port:
            raise HarnessError("ApplicationManifestDuplicateService")
        by_port[port] = item
    if set(by_port) != {BACKEND_PORT, FRONTEND_PORT}:
        raise HarnessError("ApplicationManifestIncomplete")

    script = r"""
$ports = @([int]$env:PSYNOVA_QA_BACKEND_PORT, [int]$env:PSYNOVA_QA_FRONTEND_PORT)
$result = foreach ($port in $ports) {
  $connections = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
  foreach ($connection in $connections) {
    $owner = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $connection.OwningProcess)
    if ($null -ne $owner) {
      [pscustomobject]@{
        port = $port; address = $connection.LocalAddress; pid = $owner.ProcessId
      }
    }
  }
}
ConvertTo-Json -InputObject @($result) -Depth 3 -Compress
"""
    environment = dict(os.environ)
    environment["PSYNOVA_QA_BACKEND_PORT"] = str(BACKEND_PORT)
    environment["PSYNOVA_QA_FRONTEND_PORT"] = str(FRONTEND_PORT)
    try:
        probe = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=True,
            shell=False,
        )
        records = json.loads(probe.stdout)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, subprocess.SubprocessError):
        raise HarnessError("ApplicationProcessInspectionFailed") from None
    finally:
        if "probe" in locals():
            del probe
        environment.clear()

    if not isinstance(records, list):
        raise HarnessError("ApplicationProcessInspectionFailed")
    listener_by_port: dict[int, list[dict[str, Any]]] = {
        BACKEND_PORT: [], FRONTEND_PORT: [],
    }
    for item in records:
        if isinstance(item, dict) and item.get("port") in listener_by_port:
            listener_by_port[item["port"]].append(item)
    for port in (BACKEND_PORT, FRONTEND_PORT):
        expected_name = f"School owned CPU service {port}"
        identity = by_port[port]
        listeners = listener_by_port[port]
        if (
            identity.get("name") != expected_name
            or identity.get("local_address") != "127.0.0.1"
            or type(identity.get("pid")) is not int
            or not isinstance(identity.get("executable"), str)
            or not isinstance(identity.get("creation_time"), str)
            or not isinstance(identity.get("command_line"), str)
            or len(listeners) != 1
            or listeners[0].get("address") != identity.get("local_address")
            or listeners[0].get("pid") != identity.get("pid")
        ):
            raise HarnessError("ApplicationListenerOwnershipMismatch")
        try:
            current = ResumeOperations().inspect_process(identity["pid"])
            expected_executable = Path(identity["executable"]).resolve(strict=True)
            actual_executable = Path(str(current.get("ExecutablePath", ""))).resolve(strict=True) if current else None
            expected_creation = _utc_timestamp(identity["creation_time"])
            actual_creation = _utc_timestamp(str(current.get("CreationUtc", ""))) if current else ""
            expected_argv = _command_arguments(identity["command_line"])
            actual_argv = _command_arguments(str(current.get("CommandLine", ""))) if current else []

            def normalize(argument: str) -> str:
                return argument.replace("/", "\\").casefold()

            exact_identity = (
                current is not None
                and int(current.get("ProcessId", -1)) == identity["pid"]
                and actual_executable == expected_executable
                and bool(expected_creation)
                and actual_creation == expected_creation
                and [normalize(argument) for argument in actual_argv]
                == [normalize(argument) for argument in expected_argv]
            )
        except (OSError, ResumeError, ValueError, TypeError, KeyError):
            exact_identity = False
        if not exact_identity:
            raise HarnessError("ApplicationProcessIdentityMismatch")


def _admin_credential(private: Any) -> dict[str, str]:
    if not isinstance(private, dict) or private.get("recipe_version") != "school-contexts-v1":
        raise HarnessError("AdminAccountUnavailable")
    all_credentials = private.get("credentials")
    value = all_credentials.get("alpha.admin") if isinstance(all_credentials, dict) else None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise HarnessError("AdminAccountUnavailable")
    username, password = value
    if (
        not isinstance(username, str)
        or not username.startswith("SYNTHETIC_")
        or not all(char.isascii() and (char.isalnum() or char == "_") for char in username)
        or not isinstance(password, str)
        or len(password) < 16
    ):
        raise HarnessError("AdminAccountUnavailable")
    return {"username": username, "password": password}


def _clear_private_account_material(private: Any) -> None:
    if not isinstance(private, dict):
        return
    credentials = private.get("credentials")
    if isinstance(credentials, dict):
        for slot in tuple(credentials):
            credentials[slot] = ("", "")
        credentials.clear()
    private.clear()


def _sanitize_child(stdout: str, exit_code: int, artifact_dir: Path) -> dict[str, Any]:
    try:
        child = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        child = None
    raw_stages = child.get("stages") if isinstance(child, dict) else None
    valid_stages = (
        isinstance(raw_stages, dict)
        and set(raw_stages) == set(STAGE_KEYS)
        and all(value in {"PASS", "FAIL", "SKIPPED_NULL_ORIGINAL"} for value in raw_stages.values())
    )
    stages = {
        stage: raw_stages[stage] if valid_stages else "FAIL"
        for stage in STAGE_KEYS
    }
    declared_screenshots = child.get("screenshots") if isinstance(child, dict) else None
    declared_ok = (
        isinstance(declared_screenshots, list)
        and len(declared_screenshots) == len(SCREENSHOTS)
        and set(declared_screenshots) == set(SCREENSHOTS)
    )
    screenshot_ok = declared_ok and all((artifact_dir / name).is_file() for name in SCREENSHOTS)
    if not screenshot_ok:
        stages["screenshots"] = "FAIL"
    runner_ok = type(exit_code) is int and exit_code == 0
    no_failures = all(value != "FAIL" for value in stages.values())
    skipped = {stage for stage, value in stages.items() if value == "SKIPPED_NULL_ORIGINAL"}
    partial_shape = skipped == {"school_name_restore"} and stages["school_name_configure"] == "PASS"
    passed = (
        runner_ok
        and isinstance(child, dict)
        and child.get("workflow") == "school-directory"
        and child.get("status") == "PASS"
        and all(value == "PASS" for value in stages.values())
        and screenshot_ok
    )
    partial = (
        runner_ok
        and isinstance(child, dict)
        and child.get("workflow") == "school-directory"
        and child.get("status") == "PARTIAL"
        and no_failures
        and partial_shape
        and screenshot_ok
    )
    return {
        "workflow": "school-directory",
        "status": "PASS" if passed else "PARTIAL" if partial else "FAIL",
        "runner_status": "PASS" if runner_ok else "FAIL",
        "stages": stages,
        "screenshots": list(SCREENSHOTS) if passed or partial else [],
    }


def _safe_node_environment() -> dict[str, str]:
    from school_browser_qa import safe_node_environment

    environment = safe_node_environment()
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_CACHE)
    return environment


def run() -> dict[str, Any]:
    artifact_dir: Path | None = None
    serialized = ""
    child_stdout = ""
    private: Any = None
    admin: dict[str, str] | None = None
    try:
        workspace, marker = _verified_workspace()
        _inspect_application_listeners(workspace)

        # Runtime preflight rechecks the database guardian, schema revision,
        # and grants using DPAPI. Secrets remain in this process memory only.
        for module_path in (
            REPO / "11_database" / ".venv" / "Lib" / "site-packages",
            REPO / "11_database",
            REPO / "09_backend" / "src",
            REPO / "13_deployment",
        ):
            sys.path.insert(0, str(module_path))
        from private_settings import read_private
        from school_backend import load_runtime
        from school_browser_qa import create_artifact_run_dir

        load_runtime(workspace, REPO)
        for key in tuple(os.environ):
            if key.upper().startswith(("DB_", "SMHAI_")) or key.upper() in {
                "DATABASE_URL", "DATABASE_KEY_FILE", "MYSQL_PWD",
            }:
                os.environ.pop(key, None)

        if not BROWSER_CACHE.is_dir():
            raise HarnessError("ExistingBrowserCacheUnavailable")
        _reject_reparse_path(BROWSER_CACHE)
        account_path = workspace / ACCOUNT_FILE
        _reject_reparse_path(account_path)
        private = read_private(account_path)
        admin = _admin_credential(private)
        _clear_private_account_material(private)
        private = None

        node = shutil.which("node")
        if not node or not NODE_SCRIPT.is_file():
            admin["password"] = ""
            raise HarnessError("ExistingNodeRuntimeUnavailable")
        artifact_dir = create_artifact_run_dir(workspace)
        payload = {
            "admin": admin,
            "artifact_dir": str(artifact_dir),
            "frontend_url": FRONTEND_URL,
            "backend_url": BACKEND_URL,
        }
        serialized = json.dumps(payload, separators=(",", ":"))
        admin["password"] = ""
        admin["username"] = ""
        admin = None
        del payload, marker

        child = subprocess.run(
            [node, str(NODE_SCRIPT)],
            input=serialized,
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=FRONTEND,
            timeout=360,
            check=False,
            shell=False,
            env=_safe_node_environment(),
        )
        child_stdout = child.stdout
        child_return_code = child.returncode
        del child
        serialized = ""
        result = _sanitize_child(child_stdout, child_return_code, artifact_dir)
        child_stdout = ""
        result["artifact_dir"] = str(artifact_dir)
        safe_path = artifact_dir / "externalbrowserqa.json"
        safe_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        return result
    except Exception:  # noqa: BLE001 - runtime, DPAPI, and driver errors may carry secrets; return only fixed failure state.
        return _result()
    finally:
        serialized = ""
        child_stdout = ""
        _clear_private_account_material(private)
        if admin is not None:
            admin["username"] = ""
            admin["password"] = ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-cache", type=Path, default=BROWSER_CACHE)
    args = parser.parse_args()
    if args.browser_cache.resolve(strict=False) != BROWSER_CACHE.resolve(strict=False):
        result = _result()
    else:
        result = run()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
