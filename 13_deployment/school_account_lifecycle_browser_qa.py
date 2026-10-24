"""Run the synthetic 200-student roster and first-login browser flow safely."""
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
NODE_SCRIPT = Path(__file__).with_name("school_account_lifecycle_browser_qa.mjs")
ALPHA_SCHOOL_REF = "SYNTHETIC_SCHOOL_SEED_ALPHA_V1"
BACKEND_URL = "http://127.0.0.1:8088"
FRONTEND_URL = "http://127.0.0.1:4178"
CLASS_REFS = tuple(f"LCQA-2026-C{index:02d}" for index in range(1, 9))
ROW_COUNT = 200
ARTIFACT_PREFIX = "account-lifecycle"


class QAError(Exception):
    def __init__(self, stage: str, code: str, status: int | None = None) -> None:
        self.stage = stage
        self.code = code
        self.status = status
        super().__init__(code)


def _request_data(
    client: Any,
    method: str,
    path: str,
    *,
    stage: str,
    expected_status: tuple[int, ...] = (200,),
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], Any]:
    try:
        response = client.request(method, path, json=body, headers=headers)
    except Exception as exc:  # noqa: BLE001 - never emit request or credential details.
        raise QAError(stage, type(exc).__name__) from None
    if response.status_code not in expected_status:
        raise QAError(stage, "UNEXPECTED_HTTP_STATUS", response.status_code)
    try:
        payload = response.json()
    except ValueError:
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code) from None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code)
    return data, response


def _api_headers(origin: str, csrf: str | None = None, key: str | None = None) -> dict[str, str]:
    values = {"Origin": origin, "Accept": "application/json"}
    if csrf is not None:
        values["X-CSRF-Token"] = csrf
    if key is not None:
        values["Idempotency-Key"] = key
    return values


def _login_admin(client: Any, credential: dict[str, str], origin: str) -> tuple[str, dict[str, Any]]:
    result, _response = _request_data(
        client,
        "POST",
        "/api/v1/auth/login",
        stage="admin_login",
        body={"username": credential["username"], "password": credential["password"]},
        headers=_api_headers(origin),
    )
    csrf = result.get("csrf_token")
    actor = result.get("actor")
    if not isinstance(csrf, str) or not isinstance(actor, dict):
        raise QAError("admin_login", "INVALID_LOGIN_RESPONSE")
    active = actor.get("active_context")
    if not isinstance(active, dict) or active.get("school_ref") != ALPHA_SCHOOL_REF or active.get("role") != "ADMIN":
        contexts = actor.get("available_contexts")
        target = next(
            (
                item
                for item in contexts or []
                if isinstance(item, dict)
                and item.get("school_ref") == ALPHA_SCHOOL_REF
                and item.get("role") == "ADMIN"
            ),
            None,
        )
        if target is None:
            raise QAError("admin_context", "ALPHA_ADMIN_CONTEXT_UNAVAILABLE")
        actor, _response = _request_data(
            client,
            "POST",
            "/api/v1/auth/active-context",
            stage="admin_context",
            body={"role": "ADMIN", "school_ref": ALPHA_SCHOOL_REF},
            headers=_api_headers(origin, csrf, f"lifecycle-context-{uuid.uuid4().hex}"),
        )
    active = actor.get("active_context")
    if not isinstance(active, dict) or active.get("school_ref") != ALPHA_SCHOOL_REF or active.get("role") != "ADMIN":
        raise QAError("admin_context", "ALPHA_ADMIN_CONTEXT_UNAVAILABLE")
    return csrf, actor


def _prepare_classes(client: Any, csrf: str, origin: str) -> list[str]:
    directory, _response = _request_data(
        client, "GET", "/api/v1/school/admin/directory", stage="class_directory"
    )
    school = directory.get("school")
    if not isinstance(school, dict) or school.get("school_ref") != ALPHA_SCHOOL_REF:
        raise QAError("class_directory", "ALPHA_SCHOOL_SCOPE_MISMATCH")
    classes = directory.get("classes")
    if not isinstance(classes, list):
        raise QAError("class_directory", "INVALID_CLASS_DIRECTORY")
    existing = {
        row.get("class_ref"): row
        for row in classes
        if isinstance(row, dict) and isinstance(row.get("class_ref"), str)
    }
    for class_ref in CLASS_REFS:
        row = existing.get(class_ref)
        if row is not None:
            if row.get("status") != "ACTIVE":
                raise QAError("class_prepare", "SYNTHETIC_CLASS_NOT_ACTIVE")
            continue
        _request_data(
            client,
            "POST",
            "/api/v1/school/classes",
            stage="class_prepare",
            expected_status=(201,),
            body={"class_ref": class_ref},
            headers=_api_headers(origin, csrf, f"lifecycle-class-{class_ref}"),
        )
    refreshed, _response = _request_data(
        client, "GET", "/api/v1/school/admin/directory", stage="class_verify"
    )
    refreshed_classes = {
        row.get("class_ref"): row
        for row in refreshed.get("classes", [])
        if isinstance(row, dict) and isinstance(row.get("class_ref"), str)
    }
    if any(
        class_ref not in refreshed_classes or refreshed_classes[class_ref].get("status") != "ACTIVE"
        for class_ref in CLASS_REFS
    ):
        raise QAError("class_verify", "SYNTHETIC_CLASS_SET_MISMATCH")
    return list(CLASS_REFS)


def _sanitize_child_output(stdout: str, child_exit_code: int) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        return {"status": "FAIL", "stage": "browser_runner", "failure_code": "INVALID_RESULT"}
    if not isinstance(payload, dict):
        return {"status": "FAIL", "stage": "browser_runner", "failure_code": "INVALID_RESULT"}
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        stages = {}
    allowed = {
        "admin_login", "admin_route", "roster_file", "roster_preview", "roster_import",
        "roster_persisted", "credential_selection", "credential_issue", "encrypted_download",
        "first_login", "credential_replay_rejected", "student_login", "role_denied",
        "viewport_1440", "viewport_1024", "viewport_768", "viewport_390", "logout",
    }
    safe_stages = {
        key: "PASS" if key in allowed and value == "PASS" else "FAIL"
        for key, value in stages.items()
        if key in allowed
    }
    counts = payload.get("counts")
    safe_counts = {}
    if isinstance(counts, dict):
        for name in ("classes", "students", "per_class", "credentials_issued", "credential_file_bytes"):
            value = counts.get(name)
            if isinstance(value, int) and 0 <= value <= 1000:
                safe_counts[name] = value
    viewport_widths = payload.get("viewport_widths")
    safe_widths: dict[str, int] = {}
    if isinstance(viewport_widths, dict):
        for name in ("1440", "1024", "768", "390"):
            value = viewport_widths.get(name)
            if isinstance(value, int) and 0 <= value <= 5000:
                safe_widths[name] = value
    run_ref = payload.get("run_ref")
    safe: dict[str, Any] = {
        "status": "PASS" if child_exit_code == 0 and payload.get("status") == "PASS" else "FAIL",
        "runner_status": "PASS" if child_exit_code == 0 else "FAIL",
        "stages": safe_stages,
        "counts": safe_counts,
        "viewport_widths": safe_widths,
    }
    if isinstance(run_ref, str) and len(run_ref) <= 128 and run_ref.startswith("SROSTER_"):
        safe["run_ref"] = run_ref
    failure = payload.get("failure")
    if isinstance(failure, dict):
        stage = failure.get("stage")
        code = failure.get("code")
        http_status = failure.get("http_status")
        checkpoint = failure.get("checkpoint")
        if isinstance(stage, str) and stage in allowed and isinstance(code, str) and len(code) <= 64:
            safe["failure"] = {"stage": stage, "code": code}
            if isinstance(http_status, int) and 100 <= http_status <= 599:
                safe["failure"]["http_status"] = http_status
            if checkpoint in {
                "browser_launch", "login_page", "login_form", "login_submit",
                "context_choice", "admin_route",
            }:
                safe["failure"]["checkpoint"] = checkpoint
    screenshots = payload.get("screenshots")
    if isinstance(screenshots, dict):
        safe["screenshots"] = {
            key: value for key, value in screenshots.items()
            if key in {"1440", "1024", "768", "390"}
            and isinstance(value, str)
            and Path(value).name.startswith("account-lifecycle-")
            and Path(value).suffix == ".png"
        }
    return safe


def run(workspace_arg: Path, *, backend_port: int, frontend_port: int) -> dict[str, Any]:
    try:
        import httpx
        import school_backend
        import school_browser_qa as base_qa
        from private_settings import read_private
        from school_app_lifecycle import SchoolAppLifecycle

        workspace = base_qa.validate_workspace_path(
            workspace_arg, allow_custom_name=True
        )
        status = SchoolAppLifecycle(REPO).status(workspace)
        if not base_qa.verify_owned_application_services(
            status, backend_port=backend_port, frontend_port=frontend_port
        ):
            raise QAError("service_gate", "OWNED_PREVIEW_SERVICES_REQUIRED")
        school_backend.load_runtime(workspace, REPO)
        credentials = base_qa.validate_credentials(
            read_private(workspace / base_qa.ACCOUNT_FILE)
        )
        admin_credential = credentials["alpha.admin"]
        origin = f"http://127.0.0.1:{frontend_port}"
        api_url = f"http://127.0.0.1:{backend_port}"
        with httpx.Client(base_url=api_url, timeout=30.0, follow_redirects=False) as client:
            csrf, _actor = _login_admin(client, admin_credential, origin)
            class_refs = _prepare_classes(client, csrf, origin)
    except QAError as exc:
        result = {"status": "FAIL", "failure": {"stage": exc.stage, "code": exc.code}}
        if exc.status is not None:
            result["failure"]["http_status"] = exc.status
        return result
    except Exception as exc:  # noqa: BLE001 - omit all runtime and credential details.
        return {"status": "FAIL", "failure": {"stage": "preflight", "code": type(exc).__name__}}

    node = shutil.which("node")
    if not node:
        return {"status": "FAIL", "failure": {"stage": "browser_runner", "code": "NODE_UNAVAILABLE"}}
    try:
        artifact_dir = base_qa.create_artifact_run_dir(workspace)
    except Exception as exc:  # noqa: BLE001 - do not expose paths or ACL details.
        return {"status": "FAIL", "failure": {"stage": "artifact_directory", "code": type(exc).__name__}}
    payload = {
        "admin": admin_credential,
        "artifact_dir": str(artifact_dir),
        "backend_url": api_url,
        "frontend_url": origin,
        "school_ref": ALPHA_SCHOOL_REF,
        "class_refs": class_refs,
        "viewport_widths": [1440, 1024, 768, 390],
    }
    try:
        child = subprocess.run(
            [node, str(NODE_SCRIPT)],
            input=json.dumps(payload, separators=(",", ":")),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=FRONTEND,
            timeout=600,
            check=False,
            shell=False,
            env=base_qa.safe_node_environment(),
        )
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "failure": {"stage": "browser_runner", "code": "TIMEOUT"}}
    except OSError as exc:
        return {"status": "FAIL", "failure": {"stage": "browser_runner", "code": type(exc).__name__}}
    result = _sanitize_child_output(child.stdout, child.returncode)
    return base_qa.persist_sanitized_report(artifact_dir, "account-lifecycle", result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--backend-port", type=int, default=8088)
    parser.add_argument("--frontend-port", type=int, default=4178)
    args = parser.parse_args()
    try:
        sys.path[:0] = [
            str(REPO / "11_database" / ".venv" / "Lib" / "site-packages"),
            str(REPO / "11_database"),
            str(REPO / "09_backend" / "src"),
            str(REPO / "13_deployment"),
        ]
        result = run(
            args.workspace,
            backend_port=args.backend_port,
            frontend_port=args.frontend_port,
        )
    except Exception as exc:  # noqa: BLE001 - no raw errors or local secret material.
        result = {"status": "FAIL", "failure": {"stage": "harness", "code": type(exc).__name__}}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
