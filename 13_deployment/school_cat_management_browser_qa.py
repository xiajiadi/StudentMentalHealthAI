"""Run the synthetic CAT management specialist workflow in a real browser.

The wrapper rechecks the owned synthetic workspace and current application
processes, then sends only the specialist demo credential to the Node runner
over stdin. Response bodies, credentials, browser diagnostics, and exception
messages are never persisted.
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

import school_directory_browser_qa as owned_workspace

REPO = owned_workspace.REPO
FRONTEND = owned_workspace.FRONTEND
WORKSPACE = owned_workspace.WORKSPACE
NODE_SCRIPT = Path(__file__).with_name("school_cat_management_browser_qa.mjs")
ACCOUNT_FILE = "school-accounts.private.dpapi"
BROWSER_CACHE = owned_workspace.BROWSER_CACHE
BACKEND_URL = owned_workspace.BACKEND_URL
FRONTEND_URL = owned_workspace.FRONTEND_URL
SPECIALIST_SLOT = "alpha.psychological_specialist"
UI_STAGE_KEYS = (
    "specialist_login",
    "catalog_read_verified",
    "simulation100_verified",
    "ui_aggregates_matched_api",
    "repeat_simulation_verified",
    "desktop_screenshot",
    "mobile_screenshot",
    "session_cleanup",
)
PREFLIGHT_STAGE_KEYS = (
    "workspace_owned",
    "owned_processes_verified",
    "backend_runtime_verified",
    "credentials_loaded",
    "browser_runner",
)
STAGE_KEYS = PREFLIGHT_STAGE_KEYS + UI_STAGE_KEYS + ("screenshots",)
SCREENSHOTS = (
    "specialist-cat-management-desktop.png",
    "specialist-cat-management-mobile.png",
)
SCREENSHOT_STAGES = {
    SCREENSHOTS[0]: "desktop_screenshot",
    SCREENSHOTS[1]: "mobile_screenshot",
}
SAFE_FAILURE_CLASSES = {
    "Error", "HarnessError", "AssertionError", "OSError", "PermissionError",
    "FileNotFoundError", "ValueError", "TypeError", "KeyError", "TimeoutExpired",
    "TimeoutError", "ImportError", "TargetClosedError", "ProtocolError", "RangeError",
    "ReferenceError",
}


class HarnessError(RuntimeError):
    """Fixed safe failure; callers never return an exception message."""


def _result(
    stages: dict[str, str] | None = None,
    *,
    runner_status: str = "FAIL",
    failure: dict[str, str] | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    safe_stages = {
        key: "PASS" if stages and stages.get(key) == "PASS" else "FAIL"
        for key in STAGE_KEYS
    }
    passed = runner_status == "PASS" and all(value == "PASS" for value in safe_stages.values())
    result: dict[str, Any] = {
        "workflow": "school-cat-management",
        "status": "PASS" if passed else "FAIL",
        "runner_status": "PASS" if runner_status == "PASS" else "FAIL",
        "stages": safe_stages,
        "screenshots": list(SCREENSHOTS) if passed else [],
    }
    if failure and failure.get("stage") in STAGE_KEYS:
        error_class = failure.get("error_class")
        result["failure"] = {
            "stage": failure["stage"],
            "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    if artifact_dir is not None:
        result["artifact_dir"] = str(artifact_dir)
    return result


def _specialist_credentials(private: Any) -> dict[str, dict[str, str]]:
    if not isinstance(private, dict) or private.get("recipe_version") != "school-contexts-v1":
        raise HarnessError("SpecialistAccountUnavailable")
    all_credentials = private.get("credentials")
    pair = all_credentials.get(SPECIALIST_SLOT) if isinstance(all_credentials, dict) else None
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise HarnessError("SpecialistAccountUnavailable")
    username, password = pair
    if (
        not isinstance(username, str)
        or not username.startswith("SYNTHETIC_")
        or not username.isascii()
        or not all(character.isalnum() or character == "_" for character in username)
        or not isinstance(password, str)
        or not 16 <= len(password) <= 512
    ):
        raise HarnessError("SpecialistAccountUnavailable")
    return {SPECIALIST_SLOT: {"username": username, "password": password}}


def _clear_private(private: Any) -> None:
    owned_workspace._clear_private_account_material(private)


def _sanitize_child(stdout: str, exit_code: int, artifact_dir: Path) -> dict[str, Any]:
    try:
        child = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        child = None
    raw_stages = child.get("stages") if isinstance(child, dict) else None
    stages_valid = (
        isinstance(raw_stages, dict)
        and set(raw_stages) == set(UI_STAGE_KEYS)
        and all(value in {"PASS", "FAIL"} for value in raw_stages.values())
    )
    stages = {
        key: "PASS" if stages_valid and raw_stages.get(key) == "PASS" else "FAIL"
        for key in UI_STAGE_KEYS
    }
    declared = child.get("screenshots") if isinstance(child, dict) else None
    declared_valid = (
        isinstance(declared, list)
        and len(declared) == len(SCREENSHOTS)
        and set(declared) == set(SCREENSHOTS)
    )
    files_valid = {
        name: bool(declared_valid and name in declared and (artifact_dir / name).is_file())
        for name in SCREENSHOTS
    }
    for name, stage in SCREENSHOT_STAGES.items():
        if not files_valid[name]:
            stages[stage] = "FAIL"
    screenshot_valid = declared_valid and all(files_valid.values())
    raw_failure = child.get("failure") if isinstance(child, dict) else None
    failure = None
    if isinstance(raw_failure, dict) and raw_failure.get("stage") in UI_STAGE_KEYS:
        name = raw_failure.get("error_class")
        failure = {
            "stage": raw_failure["stage"],
            "error_class": name if name in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    shape_valid = (
        isinstance(child, dict)
        and child.get("workflow") == "school-cat-management"
        and child.get("status") == "PASS"
        and stages_valid
        and all(value == "PASS" for value in stages.values())
        and screenshot_valid
    )
    runner_ok = type(exit_code) is int and exit_code == 0
    return _result(
        stages,
        runner_status="PASS" if runner_ok and shape_valid else "FAIL",
        failure=failure,
        artifact_dir=artifact_dir,
    )


def _safe_node_environment() -> dict[str, str]:
    environment = owned_workspace._safe_node_environment()
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_CACHE)
    return environment


def _write_result(artifact_dir: Path | None, result: dict[str, Any]) -> None:
    if artifact_dir is None:
        return
    try:
        (artifact_dir / "externalcatmanagementbrowserqa.json").write_text(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def run() -> dict[str, Any]:
    artifact_dir: Path | None = None
    private: Any = None
    credentials: dict[str, dict[str, str]] | None = None
    serialized = ""
    child_stdout = ""
    stages = {key: "FAIL" for key in STAGE_KEYS}
    failure_stage = "workspace_owned"
    failure: dict[str, str] | None = None
    try:
        workspace, marker = owned_workspace._verified_workspace()
        stages["workspace_owned"] = "PASS"

        failure_stage = "owned_processes_verified"
        owned_workspace._inspect_application_listeners(workspace)
        stages["owned_processes_verified"] = "PASS"

        failure_stage = "backend_runtime_verified"
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
        stages["backend_runtime_verified"] = "PASS"

        failure_stage = "credentials_loaded"
        if not BROWSER_CACHE.is_dir():
            raise HarnessError("ExistingBrowserCacheUnavailable")
        owned_workspace._reject_reparse_path(BROWSER_CACHE)
        account_path = workspace / ACCOUNT_FILE
        owned_workspace._reject_reparse_path(account_path)
        private = read_private(account_path)
        credentials = _specialist_credentials(private)
        _clear_private(private)
        private = None
        stages["credentials_loaded"] = "PASS"

        failure_stage = "browser_runner"
        node = shutil.which("node")
        if not node or not NODE_SCRIPT.is_file():
            raise HarnessError("ExistingNodeRuntimeUnavailable")
        artifact_dir = create_artifact_run_dir(workspace)
        payload = {
            "credentials": credentials,
            "artifact_dir": str(artifact_dir),
            "frontend_url": FRONTEND_URL,
            "backend_url": BACKEND_URL,
        }
        serialized = json.dumps(payload, separators=(",", ":"))
        for account in credentials.values():
            account["username"] = ""
            account["password"] = ""
        credentials.clear()
        credentials = None
        del payload, marker

        child = subprocess.run(
            [node, str(NODE_SCRIPT)],
            input=serialized,
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=FRONTEND,
            timeout=660,
            check=False,
            shell=False,
            env=_safe_node_environment(),
        )
        child_stdout = child.stdout
        exit_code = child.returncode
        del child
        serialized = ""
        child_result = _sanitize_child(child_stdout, exit_code, artifact_dir)
        child_stdout = ""
        stages.update({key: child_result["stages"][key] for key in UI_STAGE_KEYS})
        stages["screenshots"] = (
            "PASS" if all(stages[stage] == "PASS" for stage in SCREENSHOT_STAGES.values()) else "FAIL"
        )
        if child_result["runner_status"] == "PASS":
            stages["browser_runner"] = "PASS"
        failure = child_result.get("failure")
        if child_result["runner_status"] != "PASS" and failure is None:
            failure = {"stage": "browser_runner", "error_class": "HarnessError"}
        result = _result(
            stages,
            runner_status=child_result["runner_status"],
            failure=failure,
            artifact_dir=artifact_dir,
        )
    except Exception as error:  # noqa: BLE001 - DPAPI, driver, and runtime details may contain secrets.
        error_class = type(error).__name__
        failure = {
            "stage": failure_stage,
            "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
        }
        result = _result(stages, failure=failure, artifact_dir=artifact_dir)
    finally:
        serialized = ""
        child_stdout = ""
        _clear_private(private)
        if credentials is not None:
            for account in credentials.values():
                account["username"] = ""
                account["password"] = ""
            credentials.clear()
    _write_result(artifact_dir, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = run()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
