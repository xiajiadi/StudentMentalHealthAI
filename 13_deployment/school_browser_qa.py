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


class HarnessError(Exception):
    """Safe, fixed-message wrapper error."""


def validate_workspace_path(workspace: Path, repo: Path = REPO) -> Path:
    """Require the owned external school workspace; never accept a repo path."""
    try:
        resolved = workspace.resolve(strict=True)
        resolved_repo = repo.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HarnessError("InvalidWorkspace") from exc
    if not resolved.is_dir() or resolved.name != WORKSPACE_PREFIX:
        raise HarnessError("InvalidWorkspace")
    try:
        resolved.relative_to(resolved_repo)
    except ValueError:
        pass
    else:
        raise HarnessError("InvalidWorkspace")
    return resolved


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
    by_slot = {
        item.get("slot"): item
        for item in children
        if isinstance(item, dict) and item.get("slot") in ACCOUNT_SLOTS
    } if isinstance(children, list) else {}
    runner_ok = type(child_exit_code) is int and child_exit_code == 0
    safe["runner_status"] = "PASS" if runner_ok else "FAIL"

    for slot, (frontend_role, api_role, expected_path) in ACCOUNT_SLOTS.items():
        child = by_slot.get(slot, {})
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
    return safe


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


def run(workspace_arg: Path) -> dict[str, Any]:
    try:
        workspace = validate_workspace_path(workspace_arg)
    except Exception as exc:
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
    from school_backend import load_runtime
    from private_settings import read_private

    try:
        load_runtime(workspace, REPO)
    except Exception as exc:
        return safe_error_result("runtime_gate", exc)
    try:
        credentials = validate_credentials(read_private(workspace / ACCOUNT_FILE))
    except Exception as exc:
        return safe_error_result("account_gate", exc)
    node = shutil.which("node")
    if not node:
        return safe_error_result("browser_runner", HarnessError("NodeUnavailable"))
    try:
        artifact_dir = create_artifact_run_dir(workspace)
    except Exception as exc:
        return safe_error_result("artifact_target", exc)

    payload = {
        "credentials": credentials,
        "artifact_dir": str(artifact_dir),
        "frontend_url": FRONTEND_URL,
        "backend_url": BACKEND_URL,
        "accounts": {
            slot: {"role": frontend_role, "api_role": api_role, "path": route}
            for slot, (frontend_role, api_role, route) in ACCOUNT_SLOTS.items()
        },
    }
    serialized = json.dumps(payload, separators=(",", ":"))
    del credentials, payload
    try:
        child = subprocess.run(
            [node, str(NODE_SCRIPT)],
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
        return safe_error_result("browser_runner", exc)
    except OSError as exc:
        del serialized
        return safe_error_result("browser_runner", exc)
    del serialized
    # Child stdout/stderr are intentionally held only in memory. stdout is
    # parsed through a strict allowlist; stderr is never used or emitted.
    return sanitize_child_output(
        child.stdout,
        artifact_dir=artifact_dir,
        child_exit_code=child.returncode,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.workspace)
    except Exception as exc:  # SQL/DPAPI/Playwright errors may embed secrets.
        result = safe_error_result("harness", exc)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
