"""Verify four restored school roles using sealed credentials over stdin only."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from private_settings import read_private
from resume_school_workspace import (
    ResumeOperations,
    _process_matches,
    _reject_reparse_path,
)
from school_backend import load_runtime
from school_browser_qa import (
    ACCOUNT_FILE,
    ACCOUNT_SLOTS,
    FRONTEND,
    NODE_SCRIPT,
    REPO,
    create_artifact_run_dir,
    safe_node_environment,
    sanitize_child_output,
    validate_credentials,
)

SOURCE = Path(r"D:\Projects\.StudentMentalHealthAI-school-workspace-20261011")
TARGET = Path(r"D:\Projects\.StudentMentalHealthAI-school-restore-20261012-a")


def validate_restore_profile(state: dict, source_marker: dict, target_marker: dict) -> None:
    if (
        state.get("phase") != "DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER"
        or state.get("source_workspace_id") != source_marker.get("workspace_id")
        or state.get("workspace_id") != target_marker.get("workspace_id")
        or target_marker.get("port") != 3309
        or not source_marker.get("workspace_id")
        or not target_marker.get("workspace_id")
        or source_marker.get("workspace_id") == target_marker.get("workspace_id")
    ):
        raise ValueError("Verified isolated restoration required")


def run(browser_cache: Path | None = None) -> dict:
    for root in (SOURCE, TARGET):
        _reject_reparse_path(root)
        _reject_reparse_path(root / "workspace.json")
    _reject_reparse_path(TARGET / "restore-state.json")
    state = json.loads((TARGET / "restore-state.json").read_text(encoding="utf-8"))
    source_marker = json.loads((SOURCE / "workspace.json").read_text(encoding="utf-8"))
    target_marker = json.loads((TARGET / "workspace.json").read_text(encoding="utf-8"))
    validate_restore_profile(state, source_marker, target_marker)
    process = ResumeOperations().inspect_process(target_marker["parent_pid"])
    if process is None or not _process_matches(process, target_marker):
        raise ValueError("Restored guardian identity changed")
    load_runtime(TARGET, REPO)
    _reject_reparse_path(SOURCE / ACCOUNT_FILE)
    credentials = validate_credentials(read_private(SOURCE / ACCOUNT_FILE))
    artifact_dir = create_artifact_run_dir(TARGET)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Existing Node runtime unavailable")
    payload = {
        "credentials": credentials, "artifact_dir": str(artifact_dir),
        "frontend_url": "http://127.0.0.1:4179", "backend_url": "http://127.0.0.1:8089",
        "accounts": {slot: {"role": frontend_role, "api_role": api_role, "path": route}
                     for slot, (frontend_role, api_role, route) in ACCOUNT_SLOTS.items()},
    }
    environment = safe_node_environment()
    if browser_cache is not None:
        _reject_reparse_path(browser_cache)
        if not browser_cache.is_dir():
            raise ValueError("Existing browser cache directory required")
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    child = subprocess.run(
        [node, str(NODE_SCRIPT)], input=json.dumps(payload), text=True, encoding="utf-8",
        capture_output=True, cwd=FRONTEND, timeout=300, check=False, shell=False,
        env=environment,
    )
    del credentials, payload
    result = sanitize_child_output(child.stdout, artifact_dir=artifact_dir,
                                   child_exit_code=child.returncode)
    result["restored_workspace"] = True
    result["artifact_dir"] = str(artifact_dir)
    # Child stderr/unsanitized stdout and browser storage never become artifacts.
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-cache", type=Path)
    args = parser.parse_args()
    for path in (REPO / "11_database", REPO / "09_backend" / "src"):
        sys.path.insert(0, str(path))
    try:
        result = run(args.browser_cache)
        print(json.dumps(result))
        sys.exit(0 if result.get("status") == "PASS" else 2)
    except Exception as exc:  # noqa: BLE001 - emit no credentials, candidate content or driver details.
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}))
        sys.exit(2)
