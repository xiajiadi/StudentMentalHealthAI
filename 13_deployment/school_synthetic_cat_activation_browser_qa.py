"""Prepare a sanitized four-role saved-CAT activation browser workflow.

The wrapper reuses the owned synthetic workspace/process checks, backend
runtime verification, and sealed alpha-account reader. Only fixed stage names,
HTTP status numbers, and masked screenshot names are written as evidence.
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
NODE_SCRIPT = Path(__file__).with_name("school_synthetic_cat_activation_browser_qa.mjs")
ACCOUNT_FILE = "school-accounts.private.dpapi"
BROWSER_CACHE = owned_workspace.BROWSER_CACHE
BACKEND_URL = owned_workspace.BACKEND_URL
FRONTEND_URL = owned_workspace.FRONTEND_URL
ACCOUNT_ROUTES = {
    "alpha.admin": ("SCHOOL_ADMIN", "ADMIN", "/admin/overview"),
    "alpha.student": ("STUDENT", "STUDENT", "/student/home"),
    "alpha.teacher": ("TEACHER", "TEACHER", "/teacher/overview"),
    "alpha.psychological_specialist": (
        "PSYCHOLOGICAL_SPECIALIST", "PSYCHOLOGICAL_SPECIALIST", "/specialist/overview"
    ),
}
PREFLIGHT_STAGE_KEYS = (
    "workspace_owned", "owned_processes_verified", "backend_runtime_verified", "credentials_loaded", "browser_runner",
)
UI_STAGE_KEYS = (
    "specialist_login",
    "assets_read_200",
    "asset_template_http_200",
    "asset_bank_list_http_200",
    "asset_plan_list_http_200",
    "asset_template_flags_valid",
    "asset_bank_list_flags_valid",
    "asset_plan_list_flags_valid",
    "asset_template_shape_valid",
    "asset_template_metadata_valid",
    "asset_template_status_valid",
    "student_identity_resolved",
    "teacher_identity_resolved",
    "bank_created_201",
    "plan_created_201",
    "history_version_selected",
    "activation_created_201",
    "activation_metadata_matched",
    "specialist_desktop_screenshot",
    "specialist_mobile_screenshot",
    "admin_login",
    "class_created",
    "student_assigned",
    "teacher_assigned",
    "activation_selected",
    "task_published_201",
    "task_activation_matched",
    "admin_metadata_redacted",
    "admin_desktop_screenshot",
    "student_login",
    "cat_started",
    "cat_version_provenance_matched",
    "three_responses_saved",
    "cat_completed",
    "student_completed_history",
    "student_desktop_screenshot",
    "teacher_login",
    "teacher_completion_aggregate",
    "teacher_metadata_redacted",
    "teacher_desktop_screenshot",
    "teacher_mobile_screenshot",
    "sessions_cleaned",
)
STAGE_KEYS = PREFLIGHT_STAGE_KEYS + UI_STAGE_KEYS + ("screenshots",)
SCREENSHOTS = (
    "specialist-activation-desktop.png",
    "specialist-activation-mobile.png",
    "admin-saved-task-desktop.png",
    "student-saved-cat-history.png",
    "teacher-saved-task-desktop.png",
    "teacher-saved-task-mobile.png",
)
SCREENSHOT_STAGES = {
    "specialist-activation-desktop.png": "specialist_desktop_screenshot",
    "specialist-activation-mobile.png": "specialist_mobile_screenshot",
    "admin-saved-task-desktop.png": "admin_desktop_screenshot",
    "student-saved-cat-history.png": "student_desktop_screenshot",
    "teacher-saved-task-desktop.png": "teacher_desktop_screenshot",
    "teacher-saved-task-mobile.png": "teacher_mobile_screenshot",
}
API_STATUS_KEYS = (
    "template_read", "bank_list_specialist", "plan_list_specialist", "bank_create", "plan_create",
    "cat_catalog_reload", "auth_me_student", "auth_me_teacher",
    "plan_version_detail", "bank_version_detail",
    "activation_list_specialist", "activation_create", "activation_list_admin", "class_create",
    "student_assignment", "teacher_assignment", "task_publish", "task_list", "task_start", "assessment_state",
    "response_1", "response_2", "response_3", "assessment_complete", "teacher_progress",
)
SAFE_FAILURE_CLASSES = {
    "Error", "HarnessError", "TimeoutError", "TypeError", "RangeError", "ReferenceError",
    "ProtocolError", "TargetClosedError", "OSError", "PermissionError", "FileNotFoundError",
    "TimeoutExpired", "ImportError", "RuntimeError", "ValueError", "KeyError",
}


class HarnessError(RuntimeError):
    """Fixed safe wrapper error; exception messages are never returned."""


def _empty_stages() -> dict[str, str]:
    return {key: "FAIL" for key in STAGE_KEYS}


def _result(
    stages: dict[str, str] | None = None,
    *,
    runner_status: str = "FAIL",
    artifact_dir: Path | None = None,
    failure: dict[str, str] | None = None,
    api_statuses: dict[str, int] | None = None,
) -> dict[str, Any]:
    safe_stages = {key: "PASS" if stages and stages.get(key) == "PASS" else "FAIL" for key in STAGE_KEYS}
    passed = runner_status == "PASS" and all(value == "PASS" for value in safe_stages.values())
    result: dict[str, Any] = {
        "workflow": "synthetic-cat-activation",
        "status": "PASS" if passed else "FAIL",
        "runner_status": "PASS" if runner_status == "PASS" else "FAIL",
        "stages": safe_stages,
        "screenshots": list(SCREENSHOTS) if passed else [],
        "api_statuses": _safe_api_statuses(api_statuses),
    }
    if artifact_dir is not None:
        result["artifact_dir"] = str(artifact_dir)
    if failure and failure.get("stage") in STAGE_KEYS:
        error_class = failure.get("error_class")
        result["failure"] = {
            "stage": failure["stage"],
            "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    return result


def _safe_api_statuses(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: status for key, status in value.items()
        if key in API_STATUS_KEYS and type(status) is int and 100 <= status <= 599
    }


def _sanitize_child(stdout: str, exit_code: int, artifact_dir: Path) -> dict[str, Any]:
    try:
        child = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        child = None
    raw_stages = child.get("stages") if isinstance(child, dict) else None
    exact_stages = (
        isinstance(raw_stages, dict)
        and set(raw_stages) == set(UI_STAGE_KEYS) | {"screenshots"}
        and all(value in {"PASS", "FAIL"} for value in raw_stages.values())
    )
    stages = {key: "PASS" if exact_stages and raw_stages.get(key) == "PASS" else "FAIL" for key in UI_STAGE_KEYS}
    declared = child.get("screenshots") if isinstance(child, dict) else None
    declared_valid = (
        isinstance(declared, list) and len(declared) == len(SCREENSHOTS)
        and set(declared) == set(SCREENSHOTS)
    )
    for name, stage in SCREENSHOT_STAGES.items():
        if not declared_valid or not (artifact_dir / name).is_file():
            stages[stage] = "FAIL"
    screenshots_valid = declared_valid and all((artifact_dir / name).is_file() for name in SCREENSHOTS)
    child_failure = child.get("failure") if isinstance(child, dict) else None
    failure = None
    if isinstance(child_failure, dict) and child_failure.get("stage") in UI_STAGE_KEYS:
        error_class = child_failure.get("error_class")
        failure = {
            "stage": child_failure["stage"],
            "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    shape_valid = (
        isinstance(child, dict)
        and child.get("workflow") == "synthetic-cat-activation"
        and child.get("status") == "PASS"
        and exact_stages and all(value == "PASS" for value in stages.values())
        and raw_stages.get("screenshots") == "PASS" and screenshots_valid
    )
    runner_ok = type(exit_code) is int and exit_code == 0
    return {
        "runner_status": "PASS" if runner_ok and shape_valid else "FAIL",
        "stages": stages,
        "failure": failure,
        "api_statuses": _safe_api_statuses(child.get("api_statuses") if isinstance(child, dict) else None),
    }


def _safe_node_environment() -> dict[str, str]:
    from school_browser_qa import safe_node_environment

    environment = safe_node_environment()
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_CACHE)
    return environment


def _write_result(artifact_dir: Path | None, result: dict[str, Any]) -> None:
    if artifact_dir is None:
        return
    try:
        (artifact_dir / "external-synthetic-cat-activation-browser-qa.json").write_text(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
        )
    except OSError:
        return


def run() -> dict[str, Any]:
    stages = _empty_stages()
    artifact_dir: Path | None = None
    private: Any = None
    credentials: dict[str, dict[str, str]] | None = None
    serialized = ""
    child_stdout = ""
    failure_stage = "workspace_owned"
    failure: dict[str, str] | None = None
    api_statuses: dict[str, int] = {}
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
        from school_browser_qa import create_artifact_run_dir, validate_credentials

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
        credentials = validate_credentials(private)
        owned_workspace._clear_private_account_material(private)
        private = None
        if set(credentials) != set(ACCOUNT_ROUTES):
            raise HarnessError("SyntheticAccountSetMismatch")
        stages["credentials_loaded"] = "PASS"

        failure_stage = "browser_runner"
        node = shutil.which("node")
        if not node or not NODE_SCRIPT.is_file():
            raise HarnessError("ExistingNodeRuntimeUnavailable")
        artifact_dir = create_artifact_run_dir(workspace)
        payload = {
            "accounts": {
                slot: {"role": role, "api_role": api_role, "path": route}
                for slot, (role, api_role, route) in ACCOUNT_ROUTES.items()
            },
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
            timeout=900,
            check=False,
            shell=False,
            env=_safe_node_environment(),
        )
        child_stdout = child.stdout
        child_code = child.returncode
        del child
        serialized = ""
        child_result = _sanitize_child(child_stdout, child_code, artifact_dir)
        child_stdout = ""
        stages.update({key: child_result["stages"][key] for key in UI_STAGE_KEYS})
        stages["screenshots"] = "PASS" if all(
            stages[name] == "PASS" for name in SCREENSHOT_STAGES.values()
        ) else "FAIL"
        if child_result["runner_status"] == "PASS":
            stages["browser_runner"] = "PASS"
        failure = child_result.get("failure")
        if child_result["runner_status"] != "PASS" and failure is None:
            failure = {"stage": "browser_runner", "error_class": "HarnessError"}
        api_statuses = child_result["api_statuses"]
        result = _result(
            stages,
            runner_status="PASS" if child_result["runner_status"] == "PASS" else "FAIL",
            artifact_dir=artifact_dir,
            failure=failure,
            api_statuses=api_statuses,
        )
    except Exception as error:  # noqa: BLE001 - only a fixed failure class is retained.
        error_class = type(error).__name__
        failure = {
            "stage": failure_stage,
            "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
        }
        result = _result(stages, runner_status="FAIL", artifact_dir=artifact_dir, failure=failure)
    finally:
        serialized = ""
        child_stdout = ""
        owned_workspace._clear_private_account_material(private)
        if credentials is not None:
            for account in credentials.values():
                account["username"] = ""
                account["password"] = ""
            credentials.clear()
    _write_result(artifact_dir, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-cache", type=Path, default=BROWSER_CACHE)
    args = parser.parse_args()
    if args.browser_cache.resolve(strict=False) != BROWSER_CACHE.resolve(strict=False):
        result = _result(_empty_stages(), runner_status="FAIL")
    else:
        result = run()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
