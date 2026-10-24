"""Verify administrator-driven staff recovery through the real local browser UI."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "10_frontend"
NODE_SCRIPT = Path(__file__).with_name("school_account_lifecycle_staff_recovery_browser_qa.mjs")
ALPHA_SCHOOL_REF = "SYNTHETIC_SCHOOL_SEED_ALPHA_V1"
CLASS_REF = "LCQA-2026-C01"
BACKEND_URL = "http://127.0.0.1:8088"
FRONTEND_URL = "http://127.0.0.1:4178"
NODE_STAGES = (
    "admin_login",
    "admin_route",
    "staff_row",
    "recovery_dialog",
    "recovery_dialog_mobile",
    "recovery_issued",
    "secret_not_rendered",
    "handoff_mobile",
    "encrypted_download",
    "reset_completed",
    "replay_rejected",
    "staff_login",
    "logout",
)
STAGES = (
    "admin_login",
    "staff_invitation",
    "staff_acceptance",
    *NODE_STAGES[1:],
    "qa_account_disabled",
)


class QAError(Exception):
    def __init__(self, stage: str, code: str, status: int | None = None) -> None:
        self.stage = stage
        self.code = code
        self.status = status
        super().__init__(code)


def _safe_child_result(stdout: str, exit_code: int) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        return {"status": "FAIL", "failure": {"stage": "browser_runner", "code": "INVALID_RESULT"}}
    if not isinstance(payload, dict):
        return {"status": "FAIL", "failure": {"stage": "browser_runner", "code": "INVALID_RESULT"}}
    raw_stages = payload.get("stages")
    stages = {
        stage: "PASS" if isinstance(raw_stages, dict) and raw_stages.get(stage) == "PASS" else "FAIL"
        for stage in NODE_STAGES
    }
    result: dict[str, Any] = {
        "status": "PASS" if exit_code == 0 and payload.get("status") == "PASS" else "FAIL",
        "stages": stages,
    }
    failure = payload.get("failure")
    if isinstance(failure, dict):
        stage, code = failure.get("stage"), failure.get("code")
        if stage in {*STAGES[:-1], "browser_launch", "login_page", "login_submit", "staff_reset", "reset_complete"} and isinstance(code, str) and code.replace("_", "").isalnum() and len(code) <= 64:
            result["failure"] = {"stage": stage, "code": code}
            status = failure.get("http_status")
            if isinstance(status, int) and 100 <= status <= 599:
                result["failure"]["http_status"] = status
    return result


def _headers(origin: str, csrf: str | None = None, key: str | None = None) -> dict[str, str]:
    values = {"Origin": origin, "Accept": "application/json"}
    if csrf is not None:
        values["X-CSRF-Token"] = csrf
    if key is not None:
        values["Idempotency-Key"] = key
    return values


def _data(
    client: Any,
    method: str,
    path: str,
    *,
    stage: str,
    expected: tuple[int, ...] = (200,),
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], Any]:
    try:
        response = client.request(method, path, json=body, headers=headers)
    except Exception as exc:  # noqa: BLE001 - request errors can contain sensitive data.
        raise QAError(stage, type(exc).__name__) from None
    if response.status_code not in expected:
        raise QAError(stage, "UNEXPECTED_HTTP_STATUS", response.status_code)
    try:
        envelope = response.json()
    except ValueError:
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code) from None
    payload = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(payload, dict):
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code)
    return payload, response


def run(workspace_arg: Path, *, backend_port: int = 8088, frontend_port: int = 4178) -> dict[str, Any]:
    admin_client = None
    csrf: str | None = None
    admin: dict[str, str] | None = None
    staff_user_id: str | None = None
    origin = f"http://127.0.0.1:{frontend_port}"
    api_url = f"http://127.0.0.1:{backend_port}"
    result: dict[str, Any] = {
        "status": "FAIL",
        "stages": {stage: "FAIL" for stage in STAGES},
    }
    try:
        import httpx
        import school_backend
        import school_browser_qa as base_qa
        from private_settings import read_private
        from school_account_lifecycle_browser_qa import _login_admin
        from school_app_lifecycle import SchoolAppLifecycle

        workspace = base_qa.validate_workspace_path(workspace_arg, allow_custom_name=True)
        status = SchoolAppLifecycle(REPO).status(workspace)
        if not base_qa.verify_owned_application_services(
            status, backend_port=backend_port, frontend_port=frontend_port
        ):
            raise QAError("service_gate", "OWNED_PREVIEW_SERVICES_REQUIRED")
        school_backend.load_runtime(workspace, REPO)
        credentials = base_qa.validate_credentials(
            read_private(workspace / base_qa.ACCOUNT_FILE)
        )
        admin = credentials["alpha.admin"]
        node = shutil.which("node")
        if not node:
            raise QAError("browser_preflight", "NODE_UNAVAILABLE")
        node_env = base_qa.safe_node_environment()
        if not any(key.casefold() == "playwright_browsers_path" for key in node_env):
            browser_candidates = (
                Path("D:/Dev/tools/playwright-browsers"),
                Path.home() / "AppData/Local/ms-playwright",
            )
            browser_cache = next((path for path in browser_candidates if path.is_dir()), None)
            if browser_cache is not None:
                node_env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)

        admin_client = httpx.Client(base_url=api_url, timeout=30.0, follow_redirects=False)
        csrf, actor = _login_admin(admin_client, admin, origin)
        active = actor.get("active_context")
        if (
            not isinstance(active, dict)
            or active.get("role") != "ADMIN"
            or active.get("school_ref") != ALPHA_SCHOOL_REF
        ):
            raise QAError("admin_login", "ALPHA_ADMIN_CONTEXT_UNAVAILABLE")
        result["stages"]["admin_login"] = "PASS"
        directory, _ = _data(
            admin_client, "GET", "/api/v1/school/admin/directory", stage="class_directory"
        )
        classes = directory.get("classes")
        if not isinstance(classes, list) or not any(
            isinstance(item, dict)
            and item.get("class_ref") == CLASS_REF
            and item.get("status") == "ACTIVE"
            for item in classes
        ):
            raise QAError("class_directory", "SYNTHETIC_CLASS_UNAVAILABLE")

        suffix = uuid.uuid4().hex[:12].upper()
        employee_ref = f"LCQA-UI-RESET-{suffix}"
        _data(
            admin_client,
            "POST",
            "/api/v1/auth/reauthenticate",
            stage="admin_reauthentication",
            body={"current_password": admin["password"]},
            headers=_headers(origin, csrf),
        )
        invitation, _ = _data(
            admin_client,
            "POST",
            "/api/v1/school/admin/staff/invitations",
            stage="staff_invitation",
            expected=(201,),
            body={
                "employee_ref": employee_ref,
                "display_name": f"LifecycleQA教师{suffix}",
                "role": "teacher",
                "work_contact": f"{employee_ref.lower()}@example.test",
                "verified": True,
                "class_refs": [CLASS_REF],
                "delivery_channel": "MANUAL",
            },
            headers=_headers(origin, csrf, f"lcqa-ui-invitation-{uuid.uuid4().hex}"),
        )
        raw_credential = invitation.get("credential")
        staff_user_id = invitation.get("user_id") if isinstance(invitation.get("user_id"), str) else None
        staff_login_name = invitation.get("login_name")
        invitation_ref = invitation.get("invitation_ref")
        if (
            not staff_user_id
            or not isinstance(staff_login_name, str)
            or not isinstance(invitation_ref, str)
            or not isinstance(raw_credential, str)
            or invitation.get("delivery_channel") != "MANUAL_HANDOFF_REQUIRED"
        ):
            raise QAError("staff_invitation", "INVITATION_RESULT_INVALID")
        result["stages"]["staff_invitation"] = "PASS"
        initial_password = f"{uuid.uuid4().hex}Aa8!"
        _data(
            admin_client,
            "POST",
            "/api/v1/auth/staff-invitations/accept",
            stage="staff_acceptance",
            body={
                "invitation_ref": invitation_ref,
                "credential": raw_credential,
                "new_password": initial_password,
                "confirm_password": initial_password,
            },
            headers={"Origin": origin, "Accept": "application/json"},
        )
        initial_password = ""
        raw_credential = ""
        result["stages"]["staff_acceptance"] = "PASS"

        artifact_dir = base_qa.create_artifact_run_dir(workspace)
        node_payload = {
            "admin": admin,
            "artifact_dir": str(artifact_dir),
            "backend_url": api_url,
            "employee_ref": employee_ref,
            "frontend_url": origin,
            "school_ref": ALPHA_SCHOOL_REF,
            "staff_login_name": staff_login_name,
            "staff_user_id": staff_user_id,
        }
        child = subprocess.run(
            [node, str(NODE_SCRIPT)],
            input=json.dumps(node_payload, separators=(",", ":")),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=FRONTEND,
            timeout=180,
            check=False,
            shell=False,
            env=node_env,
        )
        child_result = _safe_child_result(child.stdout, child.returncode)
        result["stages"].update(child_result.get("stages", {}))
        if child_result.get("status") != "PASS":
            result["failure"] = child_result.get(
                "failure", {"stage": "browser_runner", "code": "BROWSER_FLOW_FAILED"}
            )
    except QAError as exc:
        result["failure"] = {"stage": exc.stage, "code": exc.code}
        if exc.status is not None:
            result["failure"]["http_status"] = exc.status
    except Exception as exc:  # noqa: BLE001 - never expose runtime or credential details.
        result["failure"] = {"stage": "harness", "code": type(exc).__name__}
    finally:
        if admin_client is not None and admin is not None and csrf is not None and staff_user_id is not None:
            try:
                _data(
                    admin_client,
                    "POST",
                    "/api/v1/auth/reauthenticate",
                    stage="qa_cleanup_reauthentication",
                    body={"current_password": admin["password"]},
                    headers=_headers(origin, csrf),
                )
                cleanup, _ = _data(
                    admin_client,
                    "POST",
                    f"/api/v1/school/admin/accounts/{staff_user_id}/status",
                    stage="qa_cleanup",
                    body={"status": "DISABLED", "reason_code": "QA_CLEANUP"},
                    headers=_headers(origin, csrf, f"lcqa-ui-cleanup-{uuid.uuid4().hex}"),
                )
                if cleanup.get("status") == "DISABLED":
                    result["stages"]["qa_account_disabled"] = "PASS"
                else:
                    result["failure"] = {"stage": "qa_cleanup", "code": "ACCOUNT_NOT_DISABLED"}
            except QAError as exc:
                result["failure"] = {"stage": "qa_cleanup", "code": exc.code}
                if exc.status is not None:
                    result["failure"]["http_status"] = exc.status
            except Exception as exc:  # noqa: BLE001 - do not include exception text.
                result["failure"] = {"stage": "qa_cleanup", "code": type(exc).__name__}
        if admin_client is not None:
            admin_client.close()
    result["status"] = "PASS" if all(value == "PASS" for value in result["stages"].values()) else "FAIL"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--backend-port", type=int, default=8088)
    parser.add_argument("--frontend-port", type=int, default=4178)
    args = parser.parse_args()
    sys.path[:0] = [
        str(REPO / "11_database" / ".venv" / "Lib" / "site-packages"),
        str(REPO / "11_database"),
        str(REPO / "09_backend" / "src"),
        str(REPO / "13_deployment"),
    ]
    result = run(args.workspace, backend_port=args.backend_port, frontend_port=args.frontend_port)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
