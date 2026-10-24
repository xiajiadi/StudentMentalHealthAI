"""Resume first-login acceptance for one isolated synthetic student."""
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
NODE_SCRIPT = Path(__file__).with_name("school_account_lifecycle_first_login_qa.mjs")
ALPHA_SCHOOL_REF = "SYNTHETIC_SCHOOL_SEED_ALPHA_V1"
CLASS_REF = "LCQA-2026-C08"
STUDENT_NUMBER = "LCQA26-C08-023"
DISPLAY_NAME = "LifecycleQA-LCQA26-C08-023"
BACKEND_URL = "http://127.0.0.1:8088"
FRONTEND_URL = "http://127.0.0.1:4178"


class QAError(Exception):
    def __init__(self, stage: str, code: str, status: int | None = None) -> None:
        self.stage = stage
        self.code = code
        self.status = status
        super().__init__(code)


def _data(client: Any, method: str, path: str, *, stage: str, expected: tuple[int, ...] = (200,), body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> tuple[dict[str, Any], Any]:
    try:
        response = client.request(method, path, json=body, headers=headers)
    except Exception as exc:  # noqa: BLE001 - no raw request details.
        raise QAError(stage, type(exc).__name__) from None
    if response.status_code not in expected:
        raise QAError(stage, "UNEXPECTED_HTTP_STATUS", response.status_code)
    try:
        envelope = response.json()
    except ValueError:
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code) from None
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code)
    return data, response


def _headers(origin: str, csrf: str | None = None, key: str | None = None) -> dict[str, str]:
    result = {"Origin": origin, "Accept": "application/json"}
    if csrf is not None:
        result["X-CSRF-Token"] = csrf
    if key is not None:
        result["Idempotency-Key"] = key
    return result


def _safe_result(stdout: str, exit_code: int) -> dict[str, Any]:
    allowed_stages = {
        "admin_login", "admin_workspace", "keyboard_tabs", "first_login_mobile",
        "first_login", "student_login", "role_denied", "viewport_1440", "viewport_1024",
        "viewport_768", "viewport_390", "logout", "credential_replay_rejected",
    }
    allowed_checkpoints = {
        "browser_launch", "login_page", "first_login_mode", "first_login_form",
        "first_login_submit", "first_login_click", "first_login_response", "first_login_result",
        "return_to_login", "student_login",
        "student_home", "role_denial", "responsive_capture", "logout", "credential_replay",
    }
    try:
        value = json.loads(stdout)
    except (ValueError, TypeError):
        return {"status": "FAIL", "failure": {"stage": "browser_runner", "code": "INVALID_RESULT"}}
    if not isinstance(value, dict):
        return {"status": "FAIL", "failure": {"stage": "browser_runner", "code": "INVALID_RESULT"}}
    raw_stages = value.get("stages")
    stages = {
        key: "PASS" if raw_stages.get(key) == "PASS" else "FAIL"
        for key in allowed_stages
    } if isinstance(raw_stages, dict) else {}
    widths: dict[str, int] = {}
    raw_widths = value.get("viewport_widths")
    if isinstance(raw_widths, dict):
        for key in ("1440", "1024", "768", "390"):
            width = raw_widths.get(key)
            if isinstance(width, int) and 0 <= width <= 5000:
                widths[key] = width
    student_widths: dict[str, int] = {}
    raw_student_widths = value.get("student_viewport_widths")
    if isinstance(raw_student_widths, dict):
        for key in ("1440", "1024", "768", "390"):
            width = raw_student_widths.get(key)
            if isinstance(width, int) and 0 <= width <= 5000:
                student_widths[key] = width
    screenshots: dict[str, str] = {}
    raw_screenshots = value.get("screenshots")
    if isinstance(raw_screenshots, dict):
        for key, path in raw_screenshots.items():
            if key in {
                *(f"admin_{width}" for width in (1440, 1024, 768, 390)),
                *(f"student_{width}" for width in (1440, 1024, 768, 390)),
                "first_login_390",
            } and isinstance(path, str):
                candidate = Path(path)
                if key == "first_login_390":
                    expected_name = "account-lifecycle-first-login-390.png"
                else:
                    kind, width = key.split("_", maxsplit=1)
                    expected_name = f"account-lifecycle-{kind}-{width}.png"
                if candidate.name == expected_name:
                    screenshots[key] = str(candidate)
    result: dict[str, Any] = {
        "status": "PASS" if exit_code == 0 and value.get("status") == "PASS" else "FAIL",
        "stages": stages,
        "viewport_widths": widths,
        "student_viewport_widths": student_widths,
        "screenshots": screenshots,
    }
    failure = value.get("failure")
    if isinstance(failure, dict):
        stage, code = failure.get("stage"), failure.get("code")
        if isinstance(stage, str) and (stage in allowed_stages or stage in allowed_checkpoints) and isinstance(code, str) and len(code) <= 64:
            result["failure"] = {"stage": stage, "code": code}
            checkpoint = failure.get("checkpoint")
            if checkpoint in allowed_checkpoints:
                result["failure"]["checkpoint"] = checkpoint
            request_seen = failure.get("request_seen")
            if isinstance(request_seen, bool):
                result["failure"]["request_seen"] = request_seen
            status = failure.get("http_status")
            if isinstance(status, int) and 100 <= status <= 599:
                result["failure"]["http_status"] = status
    return result


def run(workspace_arg: Path, *, backend_port: int = 8088, frontend_port: int = 4178) -> dict[str, Any]:
    try:
        import httpx
        import school_backend
        import school_browser_qa as base_qa
        from private_settings import read_private
        from school_account_lifecycle_browser_qa import (
            _api_headers,
            _login_admin,
            _request_data,
        )
        from school_app_lifecycle import SchoolAppLifecycle
        from smhai_backend.domains.school_directory.service import roster_login_name

        workspace = base_qa.validate_workspace_path(workspace_arg, allow_custom_name=True)
        status = SchoolAppLifecycle(REPO).status(workspace)
        if not base_qa.verify_owned_application_services(
            status, backend_port=backend_port, frontend_port=frontend_port
        ):
            raise QAError("service_gate", "OWNED_PREVIEW_SERVICES_REQUIRED")
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
        try:
            preflight = subprocess.run(
                [node, str(NODE_SCRIPT), "--preflight"],
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=FRONTEND,
                timeout=60,
                check=False,
                shell=False,
                env=node_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QAError("browser_preflight", type(exc).__name__) from None
        try:
            preflight_result = json.loads(preflight.stdout)
        except (ValueError, TypeError):
            preflight_result = None
        if preflight.returncode != 0 or not isinstance(preflight_result, dict) \
            or preflight_result.get("status") != "PASS":
            raise QAError("browser_preflight", "BROWSER_PREFLIGHT_FAILED")
        school_backend.load_runtime(workspace, REPO)
        private = read_private(workspace / base_qa.ACCOUNT_FILE)
        credentials = base_qa.validate_credentials(private)
        admin = credentials["alpha.admin"]
        origin = f"http://127.0.0.1:{frontend_port}"
        api_url = f"http://127.0.0.1:{backend_port}"

        with httpx.Client(base_url=api_url, timeout=30.0, follow_redirects=False) as client:
            csrf, actor = _login_admin(client, admin, origin)
            active = actor.get("active_context")
            if not isinstance(active, dict) or active.get("school_ref") != ALPHA_SCHOOL_REF or active.get("role") != "ADMIN":
                raise QAError("admin_context", "ALPHA_ADMIN_CONTEXT_UNAVAILABLE")

            directory, _response = _request_data(
                client, "GET", "/api/v1/school/admin/directory", stage="directory"
            )
            if directory.get("school", {}).get("school_ref") != ALPHA_SCHOOL_REF:
                raise QAError("directory", "SCHOOL_SCOPE_MISMATCH")
            matching = [
                member for member in directory.get("members", [])
                if isinstance(member, dict) and member.get("display_name") == DISPLAY_NAME
            ]
            if len(matching) != 1:
                raise QAError("student_lookup", "SYNTHETIC_STUDENT_NOT_UNIQUE")
            student = matching[0]
            if student.get("role") != "student" or student.get("account_status") != "ACTIVE" \
                or student.get("provisioning_status") != "ACTIVE" or student.get("class_refs") != [CLASS_REF]:
                raise QAError("student_lookup", "SYNTHETIC_STUDENT_STATE_MISMATCH")

            no_csrf = client.post(
                "/api/v1/school/admin/accounts/credentials/issue",
                json={"user_ids": [student["user_id"]]},
                headers=_headers(origin),
            )
            if no_csrf.status_code != 403:
                raise QAError("csrf_negative", "MISSING_CSRF_NOT_REJECTED", no_csrf.status_code)

            _reauth, _response = _request_data(
                client,
                "POST",
                "/api/v1/auth/reauthenticate",
                stage="admin_reauthentication",
                body={"current_password": admin["password"]},
                headers=_api_headers(origin, csrf),
            )
            issued, _response = _request_data(
                client,
                "POST",
                "/api/v1/school/admin/accounts/credentials/issue",
                stage="credential_reissue",
                expected_status=(201,),
                body={"user_ids": [student["user_id"]]},
                headers=_api_headers(origin, csrf, f"lifecycle-first-login-{uuid.uuid4().hex}"),
            )
            rows = issued.get("credentials")
            if not isinstance(rows, list) or len(rows) != 1:
                raise QAError("credential_reissue", "CREDENTIAL_RESULT_MISMATCH")
            credential = rows[0]
            if credential.get("user_id") != student["user_id"]:
                raise QAError("credential_reissue", "CREDENTIAL_USER_MISMATCH")
            student_username = roster_login_name(ALPHA_SCHOOL_REF, STUDENT_NUMBER)
            if credential.get("login_name") != student_username:
                raise QAError("credential_reissue", "CREDENTIAL_LOGIN_MISMATCH")
            if not isinstance(credential.get("credential"), str) or len(credential["credential"]) < 32:
                raise QAError("credential_reissue", "CREDENTIAL_FORMAT_MISMATCH")
            student_secret = credential["credential"]

    except QAError as exc:
        result: dict[str, Any] = {"status": "FAIL", "failure": {"stage": exc.stage, "code": exc.code}}
        if exc.status is not None:
            result["failure"]["http_status"] = exc.status
        return result
    except Exception as exc:  # noqa: BLE001 - suppress runtime and secret details.
        return {"status": "FAIL", "failure": {"stage": "preflight", "code": type(exc).__name__}}

    try:
        artifact_dir = base_qa.create_artifact_run_dir(workspace)
    except Exception as exc:  # noqa: BLE001 - no local ACL/path diagnostics.
        return {"status": "FAIL", "failure": {"stage": "artifact_directory", "code": type(exc).__name__}}
    payload = {
        "admin": admin,
        "artifact_dir": str(artifact_dir),
        "backend_url": api_url,
        "frontend_url": origin,
        "school_ref": ALPHA_SCHOOL_REF,
        "username": student_username,
        "credential": student_secret,
    }
    try:
        child = subprocess.run(
            [node, str(NODE_SCRIPT)],
            input=json.dumps(payload, separators=(",", ":")),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=FRONTEND,
            timeout=300,
            check=False,
            shell=False,
            env=node_env,
        )
    except subprocess.TimeoutExpired:
        child_result = {"status": "FAIL", "failure": {"stage": "browser_runner", "code": "TIMEOUT"}}
    except OSError as exc:
        child_result = {"status": "FAIL", "failure": {"stage": "browser_runner", "code": type(exc).__name__}}
    else:
        child_result = _safe_result(child.stdout, child.returncode)

    child_result["stages"] = {
        **child_result.get("stages", {}),
        "csrf_missing_rejected": "PASS",
        "credential_reissue": "PASS",
    }
    child_result["counts"] = {"credentials_reissued": 1}
    return base_qa.persist_sanitized_report(artifact_dir, "account-lifecycle-first-login", child_result)


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
    try:
        result = run(args.workspace, backend_port=args.backend_port, frontend_port=args.frontend_port)
    except Exception as exc:  # noqa: BLE001 - fixed safe output only.
        result = {"status": "FAIL", "failure": {"stage": "harness", "code": type(exc).__name__}}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
