"""Run a focused real-browser check of saved CAT-version simulation."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import school_directory_browser_qa as owned_workspace

REPO = owned_workspace.REPO
FRONTEND = owned_workspace.FRONTEND
WORKSPACE = owned_workspace.WORKSPACE
NODE_SCRIPT = Path(__file__).with_name("school_saved_cat_simulation_browser_qa.mjs")
ACCOUNT_FILE = "school-accounts.private.dpapi"
BROWSER_CACHE = owned_workspace.BROWSER_CACHE
BACKEND_URL = owned_workspace.BACKEND_URL
FRONTEND_URL = owned_workspace.FRONTEND_URL
SPECIALIST_SLOT = "alpha.psychological_specialist"
UI_STAGE_KEYS = (
    "specialist_login",
    "synthetic_assets_prepared",
    "saved_version_selected",
    "simulation100_verified",
    "ui_aggregates_matched_api",
    "repeat_simulation_verified",
    "unsaved_config_ignored",
    "history_switch_clears_result",
    "desktop_screenshot",
    "mobile_screenshot",
    "session_cleanup",
)
SETUP_SUBSTAGES = (
    "template_read", "template_shape",
    "bank_create", "bank_create_shape",
    "plan_create", "plan_create_shape",
    "plan_version_create", "plan_version_create_shape",
    "bank_version_read", "bank_version_shape",
    "plan_version1_read", "plan_version1_shape",
    "plan_version2_read", "plan_version2_shape",
)
SELECTION_SUBSTAGES = (
    "route_heading", "assets_panel_open", "template_response", "plan_tab_open",
    "plan_row_visible", "plan_detail_response", "history_versions_verified",
    "history_row_visible", "version_responses", "binding_label",
)
AGGREGATE_SUBSTAGES = (
    "result_visible", "metric_snapshot", "metric_shape", "metric_values",
    "stop_distribution", "binding_labels", "opaque_reference_check",
)
AGGREGATE_DIAGNOSTIC_STAGES = (
    "ui_aggregates_matched_api", "repeat_simulation_verified", "unsaved_config_ignored",
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
    "specialist-saved-cat-simulation-desktop.png",
    "specialist-saved-cat-simulation-mobile.png",
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
SAFE_FAILURE_CLASSES.add("SyntaxError")


class HarnessError(RuntimeError):
    """Fixed failure; free-form details are never returned."""


def _result(
    stages: dict[str, str] | None = None,
    *,
    runner_status: str = "FAIL",
    failure: dict[str, str] | None = None,
    diagnostics: dict[str, Any] | None = None,
    runner_diagnostics: dict[str, Any] | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    safe_stages = {
        key: "PASS" if stages and stages.get(key) == "PASS" else "FAIL"
        for key in STAGE_KEYS
    }
    passed = runner_status == "PASS" and all(value == "PASS" for value in safe_stages.values())
    result: dict[str, Any] = {
        "workflow": "school-saved-cat-simulation",
        "status": "PASS" if passed else "FAIL",
        "runner_status": "PASS" if runner_status == "PASS" else "FAIL",
        "stages": safe_stages,
        "screenshots": list(SCREENSHOTS) if passed else [],
    }
    if failure and failure.get("stage") in STAGE_KEYS:
        name = failure.get("error_class")
        result["failure"] = {
            "stage": failure["stage"],
            "error_class": name if name in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    if (
        isinstance(diagnostics, dict)
        and set(diagnostics) == {"stage", "substage", "http_status"}
        and (
            diagnostics.get("stage") == "synthetic_assets_prepared"
            and diagnostics.get("substage") in SETUP_SUBSTAGES
            or diagnostics.get("stage") == "saved_version_selected"
            and diagnostics.get("substage") in SELECTION_SUBSTAGES
        )
        and type(diagnostics.get("http_status")) is int
        and 0 <= diagnostics["http_status"] <= 599
    ):
        result["diagnostics"] = {
            "stage": diagnostics["stage"],
            "substage": diagnostics["substage"],
            "http_status": diagnostics["http_status"],
        }
    elif (
        isinstance(diagnostics, dict)
        and set(diagnostics) == {"stage", "substage"}
        and diagnostics.get("stage") in AGGREGATE_DIAGNOSTIC_STAGES
        and diagnostics.get("substage") in AGGREGATE_SUBSTAGES
    ):
        result["diagnostics"] = {"stage": diagnostics["stage"], "substage": diagnostics["substage"]}
    if (
        isinstance(runner_diagnostics, dict)
        and set(runner_diagnostics) == {"exit_code", "stderr_class"}
        and (
            runner_diagnostics.get("exit_code") is None
            or type(runner_diagnostics.get("exit_code")) is int
            and -255 <= runner_diagnostics["exit_code"] <= 255
        )
        and runner_diagnostics.get("stderr_class") in SAFE_FAILURE_CLASSES | {"Unknown"}
    ):
        result["runner_diagnostics"] = {
            "exit_code": runner_diagnostics["exit_code"],
            "stderr_class": runner_diagnostics["stderr_class"],
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


def _stderr_error_class(stderr: str) -> str:
    if not isinstance(stderr, str):
        return "Unknown"
    pattern = re.compile(
        r"(?m)^(Error|HarnessError|AssertionError|OSError|PermissionError|"
        r"FileNotFoundError|ValueError|TypeError|KeyError|TimeoutExpired|"
        r"TimeoutError|ImportError|TargetClosedError|ProtocolError|RangeError|"
        r"ReferenceError|SyntaxError)(?::|$)"
    )
    match = pattern.search(stderr)
    return match.group(1) if match else "Unknown"


def _sanitize_child(stdout: str, exit_code: int, artifact_dir: Path, stderr: str = "") -> dict[str, Any]:
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
    raw_diagnostics = child.get("diagnostics") if isinstance(child, dict) else None
    diagnostics = None
    if (
        isinstance(raw_diagnostics, dict)
        and set(raw_diagnostics) == {"stage", "substage", "http_status"}
        and (
            raw_diagnostics.get("stage") == "synthetic_assets_prepared"
            and raw_diagnostics.get("substage") in SETUP_SUBSTAGES
            or raw_diagnostics.get("stage") == "saved_version_selected"
            and raw_diagnostics.get("substage") in SELECTION_SUBSTAGES
        )
        and type(raw_diagnostics.get("http_status")) is int
        and 0 <= raw_diagnostics["http_status"] <= 599
        and isinstance(raw_failure, dict)
        and raw_failure.get("stage") == raw_diagnostics.get("stage")
    ):
        diagnostics = {
            "stage": raw_diagnostics["stage"],
            "substage": raw_diagnostics["substage"],
            "http_status": raw_diagnostics["http_status"],
        }
    elif (
        isinstance(raw_diagnostics, dict)
        and set(raw_diagnostics) == {"stage", "substage"}
        and raw_diagnostics.get("stage") in AGGREGATE_DIAGNOSTIC_STAGES
        and raw_diagnostics.get("substage") in AGGREGATE_SUBSTAGES
        and isinstance(raw_failure, dict)
        and raw_failure.get("stage") == raw_diagnostics.get("stage")
    ):
        diagnostics = {"stage": raw_diagnostics["stage"], "substage": raw_diagnostics["substage"]}
    shape_valid = (
        isinstance(child, dict)
        and child.get("workflow") == "school-saved-cat-simulation"
        and child.get("status") == "PASS"
        and stages_valid
        and all(value == "PASS" for value in stages.values())
        and screenshot_valid
    )
    runner_ok = type(exit_code) is int and exit_code == 0
    runner_diagnostics = None
    if not runner_ok or not shape_valid:
        safe_exit_code = exit_code if type(exit_code) is int and -255 <= exit_code <= 255 else None
        runner_diagnostics = {
            "exit_code": safe_exit_code,
            "stderr_class": _stderr_error_class(stderr),
        }
    return _result(
        stages,
        runner_status="PASS" if runner_ok and shape_valid else "FAIL",
        failure=failure,
        diagnostics=diagnostics,
        runner_diagnostics=runner_diagnostics,
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
        (artifact_dir / "externalsavedcatsimulationbrowserqa.json").write_text(
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
    child_stderr = ""
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
        child_stderr = child.stderr
        exit_code = child.returncode
        del child
        serialized = ""
        child_result = _sanitize_child(child_stdout, exit_code, artifact_dir, child_stderr)
        child_stdout = ""
        child_stderr = ""
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
            diagnostics=child_result.get("diagnostics"),
            runner_diagnostics=child_result.get("runner_diagnostics"),
            artifact_dir=artifact_dir,
        )
    except Exception as error:  # noqa: BLE001 - exception details may include private runtime data.
        error_class = type(error).__name__
        failure = {
            "stage": failure_stage,
            "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
        }
        runner_diagnostics = None
        if failure_stage == "browser_runner":
            runner_diagnostics = {"exit_code": None, "stderr_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError"}
        result = _result(stages, failure=failure, runner_diagnostics=runner_diagnostics, artifact_dir=artifact_dir)
    finally:
        serialized = ""
        child_stdout = ""
        child_stderr = ""
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
