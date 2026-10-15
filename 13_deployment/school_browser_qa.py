"""Run a synthetic school-role browser check without exposing credentials."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "10_frontend"
NODE_SCRIPT = Path(__file__).with_name("school_browser_qa.mjs")
TASK_NODE_SCRIPT = Path(__file__).with_name("school_task_browser_qa.mjs")
FRONTEND_URL = "http://127.0.0.1:4178"
BACKEND_URL = "http://127.0.0.1:8088"
WORKSPACE_PREFIX = ".StudentMentalHealthAI-school-workspace-20261011"
ACCOUNT_FILE = "school-accounts.private.dpapi"
ACCOUNT_SLOTS: dict[str, tuple[str, str, str]] = {
    "alpha.student": ("STUDENT", "STUDENT", "/student/home"),
    "alpha.teacher": ("TEACHER", "TEACHER", "/teacher/overview"),
    "alpha.psychological_specialist": (
        "PSYCHOLOGICAL_SPECIALIST",
        "PSYCHOLOGICAL_SPECIALIST",
        "/specialist/overview",
    ),
    "alpha.admin": ("SCHOOL_ADMIN", "ADMIN", "/admin/overview"),
}
STAGE_KEYS = (
    "blank_login",
    "real_login",
    "role_route",
    "auth_me",
    "screenshot",
    "forbidden_route",
    "forbidden_api",
    "ui_logout",
    "blank_restore",
)
TASK_STAGE_KEYS = (
    "admin_login",
    "class_created",
    "student_assigned",
    "teacher_assigned",
    "task_published",
    "student_login",
    "cat_started",
    "cat_completed",
    "student_completed_history",
    "teacher_login",
    "teacher_completed_aggregate",
    "admin_revoke",
    "student_revoked_history",
    "result_detail_request_blocked",
    "sessions_cleaned",
    "screenshots",
)
TASK_SCREENSHOTS = (
    "admin-task-published.png",
    "student-completed-history.png",
    "teacher-task-summary.png",
    "admin-task-revoked.png",
    "student-revoked-history.png",
)
FAILURE_SCREENSHOT_NAME = "admin-school-operations-failure.png"
SAFE_FAILURE_CLASSES = {
    "Error", "TimeoutError", "TypeError", "RangeError", "ReferenceError",
    "ProtocolError", "TargetClosedError", "WorkflowResponseError",
}
FAILURE_ROUTE_MODES = {
    "login", "student_home", "student_assessments", "student_assessment_new",
    "student_assessment_session", "student_assessment_result", "teacher_overview",
    "admin_overview", "other",
}
CAT_FAILURE_SUBSTAGES = {
    "task_row", "task_click", "task_route", "question_ready", "progress",
    "submit", "complete",
}
FAILURE_SELECTOR_KEYS = (
    "assessment_page", "assessment_loading", "question_title", "question_card",
    "assessment_complete_card", "assessment_error", "assigned_task",
)
SAFE_DIAGNOSTIC_ENDPOINTS = {
    "/api/v1/school/tasks/{task_ref}/start",
    "/api/v1/assessments/{assessment_id}/state",
    "/api/v1/assessments/{assessment_id}/responses",
    "/api/v1/assessments/{assessment_id}/complete",
}
SAFE_BROWSER_PREREQUISITE_CODES = {
    "READY",
    "CHROMIUM_EXECUTABLE_MISSING",
    "HEADLESS_SHELL_EXECUTABLE_MISSING",
    "BROWSER_LAYOUT_UNRECOGNIZED",
    "INVALID_DIAGNOSTIC",
}


class HarnessError(Exception):
    """Safe, fixed-message wrapper error."""


def validate_workspace_path(
    workspace: Path, repo: Path = REPO, *, allow_custom_name: bool = False,
) -> Path:
    """Require an external synthetic workspace with a valid marker."""
    try:
        resolved = workspace.resolve(strict=True)
        resolved_repo = repo.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HarnessError("InvalidWorkspace") from exc
    if not resolved.is_dir() or (resolved.name != WORKSPACE_PREFIX and not allow_custom_name):
        raise HarnessError("InvalidWorkspace")
    try:
        resolved.relative_to(resolved_repo)
    except ValueError:
        pass
    else:
        raise HarnessError("InvalidWorkspace")
    marker = _read_workspace_marker(resolved)
    if marker is None:
        raise HarnessError("InvalidWorkspace")
    return resolved


def _read_workspace_marker(workspace: Path) -> dict[str, Any] | None:
    try:
        marker = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(marker, dict)
        or marker.get("schema_version") != "psynova.synthetic-workspace.v1"
        or marker.get("project") != "StudentMentalHealthAI"
        or marker.get("synthetic_only") is not True
        or marker.get("state") not in {"READY_FOR_MIGRATION", "READY"}
        or marker.get("host") != "127.0.0.1"
        or marker.get("database") != "smhai_school_demo"
        or type(marker.get("port")) is not int
        or not 1024 <= marker["port"] <= 65535
        or not isinstance(marker.get("workspace_id"), str)
        or not marker["workspace_id"]
    ):
        return None
    return marker


def _loopback_urls(
    workspace: Path, backend_port: int | None, frontend_port: int | None,
) -> tuple[int, int, str, str]:
    custom_workspace = workspace.name != WORKSPACE_PREFIX
    if backend_port is None and frontend_port is None and not custom_workspace:
        backend_port, frontend_port = 8088, 4178
    if type(backend_port) is not int or type(frontend_port) is not int:
        raise HarnessError("ExplicitLoopbackPortsRequired")
    if (
        not 1024 <= backend_port <= 65535
        or not 1024 <= frontend_port <= 65535
        or backend_port == frontend_port
    ):
        raise HarnessError("InvalidLoopbackPortProfile")
    marker = _read_workspace_marker(workspace)
    if marker is None or marker["port"] in {backend_port, frontend_port}:
        raise HarnessError("InvalidLoopbackPortProfile")
    return (
        backend_port,
        frontend_port,
        f"http://127.0.0.1:{frontend_port}",
        f"http://127.0.0.1:{backend_port}",
    )


def verify_owned_application_services(
    status: object, *, backend_port: int, frontend_port: int,
) -> bool:
    if not isinstance(status, dict) or status.get("status") != "RUNNING":
        return False
    if status.get("manifest_is_current_revision") is not True or status.get("database") != "VERIFIED":
        return False
    services = status.get("services")
    if not isinstance(services, dict):
        return False
    for name, port in (("backend", backend_port), ("frontend", frontend_port)):
        item = services.get(name)
        if (
            not isinstance(item, dict)
            or item.get("port") != port
            or item.get("owned_process") is not True
            or item.get("listener") != "OWNED"
            or item.get("ready") is not True
        ):
            return False
    return True


def validate_credentials(private: Any) -> dict[str, dict[str, str]]:
    """Extract only the four registered alpha accounts, in memory."""
    if not isinstance(private, dict) or private.get("recipe_version") != "school-contexts-v1":
        raise HarnessError("CredentialsUnavailable")
    all_credentials = private.get("credentials")
    if not isinstance(all_credentials, dict):
        raise HarnessError("CredentialsUnavailable")
    result: dict[str, dict[str, str]] = {}
    for slot in ACCOUNT_SLOTS:
        value = all_credentials.get(slot)
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise HarnessError("CredentialsUnavailable")
        username, password = value
        if (
            not isinstance(username, str)
            or not username.startswith("SYNTHETIC_")
            or not isinstance(password, str)
            or len(password) < 16
        ):
            raise HarnessError("CredentialsUnavailable")
        result[slot] = {"username": username, "password": password}
    return result


def _result_shell() -> dict[str, Any]:
    return {
        "status": "FAIL",
        "runner_status": "FAIL",
        "slot_count": len(ACCOUNT_SLOTS),
        "pass_count": 0,
        "fail_count": len(ACCOUNT_SLOTS),
        "results": [],
    }


def _node_script_for_workflow(workflow: str) -> Path:
    if workflow == "auth":
        return NODE_SCRIPT
    if workflow == "school-tasks":
        return TASK_NODE_SCRIPT
    raise HarnessError("WorkflowUnavailable")


def _exact_account_results(children: object) -> dict[str, dict[str, Any]] | None:
    """Accept one child result for each registered account and nothing else."""
    if not isinstance(children, list) or len(children) != len(ACCOUNT_SLOTS):
        return None
    by_slot: dict[str, dict[str, Any]] = {}
    for item in children:
        if not isinstance(item, dict):
            return None
        slot = item.get("slot")
        if type(slot) is not str or slot not in ACCOUNT_SLOTS or slot in by_slot:
            return None
        by_slot[slot] = item
    if set(by_slot) != set(ACCOUNT_SLOTS):
        return None
    return by_slot


def _sanitize_browser_prerequisite(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    code = value.get("code")
    if (
        type(status) is not str
        or status not in {"PASS", "FAIL"}
        or type(code) is not str
        or code not in SAFE_BROWSER_PREREQUISITE_CODES
    ):
        return {"status": "FAIL", "code": "INVALID_DIAGNOSTIC"}
    if (status == "PASS") != (code == "READY"):
        return {"status": "FAIL", "code": "INVALID_DIAGNOSTIC"}
    return {"status": status, "code": code}


def sanitize_task_child_output(
    stdout: str,
    *,
    artifact_dir: Path,
    child_exit_code: int,
) -> dict[str, Any]:
    """Allowlist workflow evidence; never forward child paths or free-form text."""
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    child_stages = parsed.get("stages") if isinstance(parsed, dict) else None
    recognized_stages = isinstance(child_stages, dict)
    exact_stage_set = (
        recognized_stages
        and set(child_stages) == set(TASK_STAGE_KEYS)
        and all(value in {"PASS", "FAIL"} for value in child_stages.values())
    )
    safe_stages = {
        key: "PASS" if recognized_stages and child_stages.get(key) == "PASS" else "FAIL"
        for key in TASK_STAGE_KEYS
    }
    children = parsed.get("screenshots") if isinstance(parsed, dict) else None
    valid_screenshots = (
        isinstance(children, list)
        and all(type(name) is str for name in children)
        and len(children) == len(TASK_SCREENSHOTS)
        and set(children) == set(TASK_SCREENSHOTS)
    )
    screenshot_paths = [artifact_dir / name for name in TASK_SCREENSHOTS]
    screenshots_exist = valid_screenshots and all(path.is_file() for path in screenshot_paths)
    runner_ok = type(child_exit_code) is int and child_exit_code == 0
    stages_passed = exact_stage_set and all(value == "PASS" for value in safe_stages.values())
    passed = (
        runner_ok
        and isinstance(parsed, dict)
        and parsed.get("workflow") == "school-tasks"
        and parsed.get("status") == "PASS"
        and stages_passed
        and screenshots_exist
    )
    result: dict[str, Any] = {
        "workflow": "school-tasks",
        "status": "PASS" if passed else "FAIL",
        "runner_status": "PASS" if runner_ok else "FAIL",
        "stages": safe_stages,
    }
    if passed:
        result["screenshots"] = [str(path) for path in screenshot_paths]
    else:
        result["failure_class"] = "BrowserWorkflowFailed"
        child_failure = parsed.get("failure") if isinstance(parsed, dict) else None
        if isinstance(child_failure, dict):
            stage = child_failure.get("stage")
            error_class = child_failure.get("error_class")
            if (
                stage in TASK_STAGE_KEYS
                and safe_stages[stage] == "FAIL"
                and isinstance(error_class, str)
                and error_class in SAFE_FAILURE_CLASSES
            ):
                safe_failure: dict[str, Any] = {"stage": stage, "error_class": error_class}
                if "diagnostics" in child_failure:
                    diagnostics = child_failure.get("diagnostics")
                    if not isinstance(diagnostics, dict):
                        diagnostics = {}
                else:
                    # Compatibility with older Node summaries that flattened
                    # the same allowlisted diagnostics into `failure`.
                    diagnostics = {
                        key: child_failure[key]
                        for key in (
                            "route_mode",
                            "cat_substage",
                            "selectors",
                            "responses",
                        )
                        if key in child_failure
                    }
                if (
                    stage in {"cat_started", "cat_completed"}
                    and isinstance(diagnostics, dict)
                    and isinstance(diagnostics.get("cat_substage"), str)
                    and diagnostics.get("cat_substage") in CAT_FAILURE_SUBSTAGES
                ):
                    safe_failure["cat_substage"] = diagnostics["cat_substage"]
                if child_failure.get("screenshot") == FAILURE_SCREENSHOT_NAME:
                    failure_screenshot = artifact_dir / FAILURE_SCREENSHOT_NAME
                    if failure_screenshot.is_file():
                        safe_failure["screenshot"] = str(failure_screenshot)
                if isinstance(diagnostics, dict):
                    route_mode = diagnostics.get("route_mode")
                    if isinstance(route_mode, str) and route_mode in FAILURE_ROUTE_MODES:
                        safe_failure["route_mode"] = route_mode
                    selectors = diagnostics.get("selectors")
                    if (
                        isinstance(selectors, dict)
                        and set(selectors) == set(FAILURE_SELECTOR_KEYS)
                        and all(type(value) is bool for value in selectors.values())
                    ):
                        safe_failure["selectors"] = {
                            key: selectors[key] for key in FAILURE_SELECTOR_KEYS
                        }
                    responses = diagnostics.get("responses")
                    if isinstance(responses, list):
                        safe_responses = []
                        for item in responses[-12:]:
                            if not isinstance(item, dict):
                                continue
                            method = item.get("method")
                            status = item.get("status")
                            endpoint = item.get("endpoint")
                            if (
                                isinstance(method, str)
                                and method in {"GET", "POST"}
                                and type(status) is int
                                and 100 <= status <= 599
                                and isinstance(endpoint, str)
                                and endpoint in SAFE_DIAGNOSTIC_ENDPOINTS
                            ):
                                safe_responses.append({
                                    "method": method,
                                    "status": status,
                                    "endpoint": endpoint,
                                })
                        safe_failure["responses"] = safe_responses
                result["failure"] = safe_failure
    return result


def sanitize_child_output(
    stdout: str,
    *,
    artifact_dir: Path,
    child_exit_code: int,
) -> dict[str, Any]:
    """Allowlist fixed browser evidence; discard stderr and all free-form text."""
    safe = _result_shell()
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    children = parsed.get("results") if isinstance(parsed, dict) else None
    by_slot = _exact_account_results(children)
    runner_ok = type(child_exit_code) is int and child_exit_code == 0 and by_slot is not None
    safe["runner_status"] = "PASS" if runner_ok else "FAIL"

    for slot, (frontend_role, api_role, expected_path) in ACCOUNT_SLOTS.items():
        child = by_slot.get(slot, {}) if by_slot is not None else {}
        screenshot = artifact_dir / f"{slot.replace('.', '-')}.png"
        child_stages = child.get("stages")
        if not isinstance(child_stages, dict):
            child_stages = {}
        valid_stages = set(child_stages) == set(STAGE_KEYS)
        stages_passed = valid_stages and all(
            child_stages.get(key) == "PASS" for key in STAGE_KEYS
        )
        screenshot_exists = screenshot.is_file()
        passed = (
            runner_ok
            and child.get("status") == "PASS"
            and stages_passed
            and screenshot_exists
        )
        row: dict[str, Any] = {
            "slot": slot,
            "expected_role": frontend_role,
            "expected_api_role": api_role,
            "expected_path": expected_path,
            "status": "PASS" if passed else "FAIL",
            "stages": {
                key: (
                    "PASS"
                    if valid_stages
                    and child_stages.get(key) == "PASS"
                    and (key != "screenshot" or screenshot_exists)
                    else "FAIL"
                )
                for key in STAGE_KEYS
            },
        }
        if passed:
            row["screenshot"] = str(screenshot)
        if not passed:
            # Never forward a child exception name/message; use one fixed label.
            row["failure_class"] = "BrowserCheckFailed"
        safe["results"].append(row)
        if passed:
            safe["pass_count"] += 1
            safe["fail_count"] -= 1
    safe["status"] = "PASS" if safe["pass_count"] == len(ACCOUNT_SLOTS) else "FAIL"
    if isinstance(parsed, dict):
        prerequisite = _sanitize_browser_prerequisite(parsed.get("browser_prerequisite"))
        if prerequisite is not None:
            safe["browser_prerequisite"] = prerequisite
            if prerequisite["status"] != "PASS":
                safe["status"] = "FAIL"
        if "browser_launch_failure_code" in parsed:
            launch_failure = parsed.get("browser_launch_failure_code")
            safe["browser_launch_failure_code"] = (
                launch_failure
                if launch_failure == "BROWSER_LAUNCH_FAILED"
                else "INVALID_DIAGNOSTIC"
            )
            safe["status"] = "FAIL"
    return safe


def persist_sanitized_report(
    artifact_dir: Path, workflow: str, result: dict[str, Any],
) -> dict[str, Any]:
    """Persist only already-sanitized evidence in the exclusive run directory."""
    report_path = artifact_dir / "sanitized-report.json"
    temporary_path = artifact_dir / f".sanitized-report-{uuid.uuid4().hex}.tmp"
    result["evidence_report_status"] = "PERSISTED"
    result["evidence_report_path"] = str(report_path)
    document = {
        "schema_version": "psynova.school-browser-qa-report.v1",
        "workflow": workflow,
        "result": result,
    }
    try:
        encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        descriptor = os.open(
            temporary_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if report_path.exists():
            raise FileExistsError
        os.replace(temporary_path, report_path)
    except (OSError, TypeError, ValueError):
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        result.pop("evidence_report_path", None)
        result["evidence_report_status"] = "UNAVAILABLE"
        result["status"] = "FAIL"
        result["failure_class"] = "SafeReportPersistenceFailed"
    return result


def safe_error_result(stage: str, exc: BaseException) -> dict[str, Any]:
    """Return a fixed classification and intentionally ignore exception text."""
    del exc
    return {
        "status": "FAIL",
        "stage": stage,
        "failure_class": "HarnessError",
        "slot_count": len(ACCOUNT_SLOTS),
        "pass_count": 0,
        "fail_count": len(ACCOUNT_SLOTS),
    }


def safe_node_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Give Node only Windows process essentials, not runtime or user secrets."""
    source = os.environ if source is None else source
    allowed = {
        "path", "systemroot", "windir", "temp", "tmp", "localappdata",
        "userprofile", "appdata", "programfiles", "programfiles(x86)",
        "playwright_browsers_path",
    }
    return {key: value for key, value in source.items() if key.casefold() in allowed}


def create_artifact_run_dir(workspace: Path) -> Path:
    """Create a fresh, exclusive run folder without replacing prior evidence."""
    root = workspace / "browser-qa"
    if root.is_symlink():
        raise HarnessError("ArtifactDirectoryInvalid")
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        resolved_root = root.resolve(strict=True)
        resolved_workspace = workspace.resolve(strict=True)
        resolved_root.relative_to(resolved_workspace)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HarnessError("ArtifactDirectoryInvalid") from exc
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    run_dir = resolved_root / run_id
    try:
        run_dir.mkdir(mode=0o700, exist_ok=False)
    except OSError as exc:
        raise HarnessError("ArtifactRunDirectoryUnavailable") from exc
    return run_dir


def run(
    workspace_arg: Path, workflow: str = "auth", *,
    backend_port: int | None = None, frontend_port: int | None = None,
) -> dict[str, Any]:
    try:
        node_script = _node_script_for_workflow(workflow)
    except HarnessError as exc:
        return safe_error_result("workflow_gate", exc)
    try:
        workspace = validate_workspace_path(
            workspace_arg,
            allow_custom_name=backend_port is not None and frontend_port is not None,
        )
        backend_port, frontend_port, frontend_url, backend_url = _loopback_urls(
            workspace, backend_port, frontend_port
        )
    except Exception as exc:  # noqa: BLE001 - discard raw parse and path details.
        return safe_error_result("workspace_gate", exc)
    # Import only after path validation. This gate rechecks owned process,
    # workspace ACL, sealed runtime settings, database grants and revision.
    for path in (
        REPO / "11_database" / ".venv" / "Lib" / "site-packages",
        REPO / "11_database",
        REPO / "09_backend" / "src",
        REPO / "13_deployment",
    ):
        sys.path.insert(0, str(path))
    from private_settings import read_private
    from school_backend import load_runtime

    try:
        load_runtime(workspace, REPO)
    except Exception as exc:  # noqa: BLE001 - errors may contain SQL or DPAPI details.
        return safe_error_result("runtime_gate", exc)
    try:
        from school_app_lifecycle import LifecycleError, SchoolAppLifecycle

        lifecycle_status = SchoolAppLifecycle(REPO).status(workspace)
        if not verify_owned_application_services(
            lifecycle_status,
            backend_port=backend_port,
            frontend_port=frontend_port,
        ):
            raise HarnessError("LifecycleOwnershipUnavailable")
    except (HarnessError, LifecycleError, OSError, TypeError, ValueError) as exc:
        return safe_error_result("owner_gate", exc)
    try:
        credentials = validate_credentials(read_private(workspace / ACCOUNT_FILE))
    except Exception as exc:  # noqa: BLE001 - credential decoder errors stay private.
        return safe_error_result("account_gate", exc)
    node = shutil.which("node")
    if not node:
        return safe_error_result("browser_runner", HarnessError("NodeUnavailable"))
    try:
        artifact_dir = create_artifact_run_dir(workspace)
    except Exception as exc:  # noqa: BLE001 - file and ACL details stay private.
        return safe_error_result("artifact_target", exc)

    payload = {
        "credentials": credentials,
        "artifact_dir": str(artifact_dir),
        "frontend_url": frontend_url,
        "backend_url": backend_url,
        "accounts": {
            slot: {"role": frontend_role, "api_role": api_role, "path": route}
            for slot, (frontend_role, api_role, route) in ACCOUNT_SLOTS.items()
        },
    }
    serialized = json.dumps(payload, separators=(",", ":"))
    del credentials, payload
    try:
        child = subprocess.run(
            [node, str(node_script)],
            input=serialized,
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=FRONTEND,
            timeout=300,
            check=False,
            shell=False,
            env=safe_node_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        del serialized
        return persist_sanitized_report(
            artifact_dir, workflow, safe_error_result("browser_runner", exc)
        )
    except OSError as exc:
        del serialized
        return persist_sanitized_report(
            artifact_dir, workflow, safe_error_result("browser_runner", exc)
        )
    del serialized
    # Child stdout/stderr are intentionally held only in memory. stdout is
    # parsed through a strict allowlist; stderr is never used or emitted.
    if workflow == "school-tasks":
        result = sanitize_task_child_output(
            child.stdout,
            artifact_dir=artifact_dir,
            child_exit_code=child.returncode,
        )
    else:
        result = sanitize_child_output(
            child.stdout, artifact_dir=artifact_dir, child_exit_code=child.returncode
        )
    return persist_sanitized_report(artifact_dir, workflow, result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--workflow", default="auth")
    parser.add_argument("--backend-port", type=int)
    parser.add_argument("--frontend-port", type=int)
    args = parser.parse_args()
    try:
        result = run(
            args.workspace,
            args.workflow,
            backend_port=args.backend_port,
            frontend_port=args.frontend_port,
        )
    except Exception as exc:  # noqa: BLE001 - SQL/DPAPI/Playwright errors may embed secrets.
        result = safe_error_result("harness", exc)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
