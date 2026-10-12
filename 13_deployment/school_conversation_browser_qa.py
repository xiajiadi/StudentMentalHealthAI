"""Run a sanitized student education-support browser workflow.

The existing synthetic school workspace and owned application listeners are
validated before the registered student credential is read. The credential is
sent only to the Node Playwright runner over stdin. Child output and failures
are allowlisted; request bodies, credentials, and raw exceptions are discarded.
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
NODE_SCRIPT = Path(__file__).with_name("school_conversation_browser_qa.mjs")
WORKSPACE = owned_workspace.WORKSPACE
ACCOUNT_FILE = "school-accounts.private.dpapi"
BROWSER_CACHE = owned_workspace.BROWSER_CACHE
SCHOOL_REF = owned_workspace.SCHOOL_REF
SCREENSHOTS = (
    "student-independent-conversation-desktop.png",
    "student-independent-conversation-mobile.png",
)
SCREENSHOT_STAGES = {
    "student-independent-conversation-desktop.png": "desktop_screenshot",
    "student-independent-conversation-mobile.png": "mobile_screenshot",
}
PREFLIGHT_STAGE_KEYS = (
    "workspace_owned",
    "owned_processes_verified",
    "backend_runtime_verified",
    "student_credential_loaded",
    "browser_runner",
)
UI_STAGE_KEYS = (
    "safety_ready",
    "rag_ready",
    "browser_start",
    "student_login",
    "support_open",
    "conversation_created",
    "message_sent",
    "abstention_body_verified",
    "citations_absent",
    "reload_history_verified",
    "first_logout",
    "fresh_student_login",
    "fresh_support_open",
    "fresh_login_history_verified",
    "desktop_screenshot",
    "mobile_screenshot",
    "logout",
)
STAGE_KEYS = PREFLIGHT_STAGE_KEYS + UI_STAGE_KEYS + ("screenshots",)
SAFE_FAILURE_CLASSES = {
    "HarnessError",
    "OSError",
    "PermissionError",
    "FileNotFoundError",
    "ValueError",
    "TypeError",
    "KeyError",
    "TimeoutExpired",
    "TimeoutError",
    "ImportError",
    "Error",
    "AssertionError",
    "TargetClosedError",
    "ProtocolError",
    "RangeError",
    "ReferenceError",
    "WorkflowResponseError",
}


class HarnessError(RuntimeError):
    """Fixed safe harness error; callers never expose its message."""


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
    payload: dict[str, Any] = {
        "workflow": "school-independent-conversation",
        "status": "PASS" if passed else "FAIL",
        "runner_status": "PASS" if runner_status == "PASS" else "FAIL",
        "stages": safe_stages,
        "screenshots": list(SCREENSHOTS) if passed else [],
    }
    if failure and failure.get("stage") in STAGE_KEYS:
        error_class = failure.get("error_class")
        payload["failure"] = {
            "stage": failure["stage"],
            "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    if artifact_dir is not None:
        payload["artifact_dir"] = str(artifact_dir)
    return payload


def _student_credential(private: Any) -> dict[str, str]:
    if not isinstance(private, dict) or private.get("recipe_version") != "school-contexts-v1":
        raise HarnessError("StudentAccountUnavailable")
    accounts = private.get("credentials")
    value = accounts.get("alpha.student") if isinstance(accounts, dict) else None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise HarnessError("StudentAccountUnavailable")
    username, password = value
    if (
        not isinstance(username, str)
        or not username.startswith("SYNTHETIC_")
        or not all(char.isascii() and (char.isalnum() or char == "_") for char in username)
        or not isinstance(password, str)
        or len(password) < 16
    ):
        raise HarnessError("StudentAccountUnavailable")
    return {"username": username, "password": password}


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
    stages = {key: "PASS" if stages_valid and raw_stages.get(key) == "PASS" else "FAIL" for key in UI_STAGE_KEYS}

    declared = child.get("screenshots") if isinstance(child, dict) else None
    declared_valid = isinstance(declared, list) and len(declared) == len(SCREENSHOTS) and set(declared) == set(SCREENSHOTS)
    screenshot_files_valid = {
        name: isinstance(declared, list)
        and declared_valid
        and name in declared
        and (artifact_dir / name).is_file()
        for name in SCREENSHOTS
    }
    for name, stage in SCREENSHOT_STAGES.items():
        if not screenshot_files_valid[name]:
            stages[stage] = "FAIL"
    screenshot_valid = declared_valid and all(screenshot_files_valid.values())

    child_failure = child.get("failure") if isinstance(child, dict) else None
    failure = None
    if isinstance(child_failure, dict):
        stage = child_failure.get("stage")
        error_class = child_failure.get("error_class")
        if stage in UI_STAGE_KEYS:
            failure = {
                "stage": stage,
                "error_class": error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError",
            }

    runner_ok = type(exit_code) is int and exit_code == 0
    shape_ok = (
        isinstance(child, dict)
        and child.get("workflow") == "school-independent-conversation"
        and child.get("status") == "PASS"
        and stages_valid
        and all(value == "PASS" for value in stages.values())
        and screenshot_valid
    )
    return _result(
        stages,
        runner_status="PASS" if runner_ok and shape_ok else "FAIL",
        failure=failure,
        artifact_dir=artifact_dir,
    )


def _safe_node_environment() -> dict[str, str]:
    environment = owned_workspace._safe_node_environment()
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_CACHE)
    return environment


def _write_safe_result(artifact_dir: Path | None, result: dict[str, Any]) -> None:
    if artifact_dir is None:
        return
    try:
        (artifact_dir / "externalbrowserqa.json").write_text(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except OSError:
        # The stdout result remains sanitized even when evidence cannot be saved.
        return


def run() -> dict[str, Any]:
    artifact_dir: Path | None = None
    private: Any = None
    student: dict[str, str] | None = None
    serialized = ""
    child_stdout = ""
    stages = {key: "FAIL" for key in STAGE_KEYS}
    failure_stage = "workspace_owned"
    try:
        workspace, _marker = owned_workspace._verified_workspace()
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
        for name in tuple(os.environ):
            if name.upper().startswith(("DB_", "SMHAI_")) or name.upper() in {
                "DATABASE_URL",
                "DATABASE_KEY_FILE",
                "MYSQL_PWD",
            }:
                os.environ.pop(name, None)
        stages["backend_runtime_verified"] = "PASS"

        failure_stage = "student_credential_loaded"
        if not BROWSER_CACHE.is_dir():
            raise HarnessError("ExistingBrowserCacheUnavailable")
        owned_workspace._reject_reparse_path(BROWSER_CACHE)
        account_path = workspace / ACCOUNT_FILE
        owned_workspace._reject_reparse_path(account_path)
        private = read_private(account_path)
        student = _student_credential(private)
        _clear_private(private)
        private = None
        stages["student_credential_loaded"] = "PASS"

        failure_stage = "student_credential_loaded"
        node = shutil.which("node")
        if not node or not NODE_SCRIPT.is_file():
            raise HarnessError("ExistingNodeRuntimeUnavailable")
        artifact_dir = create_artifact_run_dir(workspace)
        payload = {
            "student": student,
            "artifact_dir": str(artifact_dir),
            "frontend_url": owned_workspace.FRONTEND_URL,
            "backend_url": owned_workspace.BACKEND_URL,
            "school_ref": SCHOOL_REF,
        }
        serialized = json.dumps(payload, separators=(",", ":"))
        student["username"] = ""
        student["password"] = ""
        student = None
        del payload, _marker

        failure_stage = "browser_runner"
        child = subprocess.run(
            [node, str(NODE_SCRIPT)],
            input=serialized,
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=FRONTEND,
            timeout=420,
            check=False,
            shell=False,
            env=_safe_node_environment(),
        )
        child_stdout = child.stdout
        child_return_code = child.returncode
        del child
        serialized = ""
        child_result = _sanitize_child(child_stdout, child_return_code, artifact_dir)
        child_stdout = ""
        stages.update({key: child_result["stages"][key] for key in UI_STAGE_KEYS})
        if all(stages[stage] == "PASS" for stage in SCREENSHOT_STAGES.values()):
            stages["screenshots"] = "PASS"
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
        _write_safe_result(artifact_dir, result)
        return result
    except Exception as exc:  # noqa: BLE001 - exception text may contain credentials or request details.
        safe_class = type(exc).__name__ if type(exc).__name__ in SAFE_FAILURE_CLASSES else "HarnessError"
        result = _result(stages, failure={"stage": failure_stage, "error_class": safe_class}, artifact_dir=artifact_dir)
        _write_safe_result(artifact_dir, result)
        return result
    finally:
        serialized = ""
        child_stdout = ""
        _clear_private(private)
        if student is not None:
            student["username"] = ""
            student["password"] = ""


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
