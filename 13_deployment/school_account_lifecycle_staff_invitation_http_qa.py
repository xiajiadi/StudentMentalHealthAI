"""Verify real local MySQL-backed staff invitation flows with synthetic accounts."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ALPHA_SCHOOL_REF = "SYNTHETIC_SCHOOL_SEED_ALPHA_V1"
CLASS_REF = "LCQA-2026-C01"
BACKEND_URL = "http://127.0.0.1:8088"
FRONTEND_URL = "http://127.0.0.1:4178"


class QAError(Exception):
    def __init__(self, stage: str, code: str, status: int | None = None) -> None:
        self.stage = stage
        self.code = code
        self.status = status
        super().__init__(code)


def _headers(
    origin: str, csrf: str | None = None, key: str | None = None
) -> dict[str, str]:
    result = {"Origin": origin, "Accept": "application/json"}
    if csrf is not None:
        result["X-CSRF-Token"] = csrf
    if key is not None:
        result["Idempotency-Key"] = key
    return result


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
    except Exception as exc:  # noqa: BLE001 - suppress all request details.
        raise QAError(stage, type(exc).__name__) from None
    if response.status_code not in expected:
        error_code = None
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            candidate = error.get("code") if isinstance(error, dict) else None
            if (
                isinstance(candidate, str)
                and candidate.replace("_", "").isalnum()
                and len(candidate) <= 64
            ):
                error_code = candidate.upper()
        except ValueError:
            pass
        raise QAError(
            stage,
            f"API_{error_code}" if error_code else "UNEXPECTED_HTTP_STATUS",
            response.status_code,
        )
    try:
        envelope = response.json()
    except ValueError:
        raise QAError(
            stage, "INVALID_RESPONSE_ENVELOPE", response.status_code
        ) from None
    result = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(result, dict):
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code)
    return result, response


def _login_role(
    client: Any, origin: str, username: str, password: str, role: str
) -> tuple[str, dict[str, Any]]:
    result, _response = _data(
        client,
        "POST",
        "/api/v1/auth/login",
        stage=f"{role.lower()}_login",
        body={"username": username, "password": password},
        headers=_headers(origin),
    )
    actor = result.get("actor")
    csrf = result.get("csrf_token")
    if not isinstance(actor, dict) or not isinstance(csrf, str) or not csrf:
        raise QAError(f"{role.lower()}_login", "INVALID_LOGIN_RESPONSE")
    active = actor.get("active_context")
    if (
        not isinstance(active, dict)
        or active.get("role") != role
        or active.get("school_ref") != ALPHA_SCHOOL_REF
    ):
        contexts = actor.get("available_contexts")
        target = next(
            (
                item
                for item in contexts or []
                if isinstance(item, dict)
                and item.get("role") == role
                and item.get("school_ref") == ALPHA_SCHOOL_REF
            ),
            None,
        )
        if target is None:
            raise QAError(f"{role.lower()}_login", "EXPECTED_ROLE_CONTEXT_UNAVAILABLE")
        actor, _response = _data(
            client,
            "POST",
            "/api/v1/auth/active-context",
            stage=f"{role.lower()}_context",
            body={"role": role, "school_ref": ALPHA_SCHOOL_REF},
            headers=_headers(origin, csrf, f"lcqa-context-{uuid.uuid4().hex}"),
        )
        active = actor.get("active_context")
    if (
        not isinstance(active, dict)
        or active.get("role") != role
        or active.get("school_ref") != ALPHA_SCHOOL_REF
    ):
        raise QAError(f"{role.lower()}_login", "ACTIVE_ROLE_CONTEXT_MISMATCH")
    return csrf, actor


def run(
    workspace_arg: Path, *, backend_port: int = 8088, frontend_port: int = 4178
) -> dict[str, Any]:
    try:
        import httpx
        import school_backend
        import school_browser_qa as base_qa
        from private_settings import read_private
        from school_account_lifecycle_browser_qa import _api_headers, _login_admin
        from school_app_lifecycle import SchoolAppLifecycle

        workspace = base_qa.validate_workspace_path(
            workspace_arg, allow_custom_name=True
        )
        lifecycle_status = SchoolAppLifecycle(REPO).status(workspace)
        if not base_qa.verify_owned_application_services(
            lifecycle_status, backend_port=backend_port, frontend_port=frontend_port
        ):
            raise QAError("service_gate", "OWNED_PREVIEW_SERVICES_REQUIRED")
        school_backend.load_runtime(workspace, REPO)
        accounts = base_qa.validate_credentials(
            read_private(workspace / base_qa.ACCOUNT_FILE)
        )
        admin = accounts["alpha.admin"]
        origin = f"http://127.0.0.1:{frontend_port}"
        api_url = f"http://127.0.0.1:{backend_port}"
        result = {
            "status": "FAIL",
            "stages": {
                "admin_login": "FAIL",
                "admin_reauthentication": "FAIL",
                "teacher_invitation": "FAIL",
                "teacher_acceptance": "FAIL",
                "teacher_role": "FAIL",
                "teacher_class_scope": "FAIL",
                "psychological_specialist_invitation": "FAIL",
                "psychological_specialist_acceptance": "FAIL",
                "psychological_specialist_role": "FAIL",
                "specialist_no_class_scope": "FAIL",
                "admin_api_denied": "FAIL",
                "credential_replay_rejected": "FAIL",
                "logout_revoked": "FAIL",
                "staff_recovery_issued": "FAIL",
                "staff_recovery_session_revoked": "FAIL",
                "staff_recovery_completed": "FAIL",
                "staff_recovery_replay_rejected": "FAIL",
                "staff_recovery_login": "FAIL",
                "qa_accounts_disabled": "FAIL",
            },
            "counts": {
                "invitations_created": 0,
                "invitations_accepted": 0,
                "qa_accounts_disabled": 0,
            },
        }

        with httpx.Client(
            base_url=api_url, timeout=30.0, follow_redirects=False
        ) as admin_client:
            csrf, admin_actor = _login_admin(admin_client, admin, origin)
            active = admin_actor.get("active_context")
            if (
                not isinstance(active, dict)
                or active.get("role") != "ADMIN"
                or active.get("school_ref") != ALPHA_SCHOOL_REF
            ):
                raise QAError("admin_login", "ALPHA_ADMIN_CONTEXT_UNAVAILABLE")
            result["stages"]["admin_login"] = "PASS"
            _data(
                admin_client,
                "POST",
                "/api/v1/auth/reauthenticate",
                stage="admin_reauthentication",
                body={"current_password": admin["password"]},
                headers=_api_headers(origin, csrf),
            )
            result["stages"]["admin_reauthentication"] = "PASS"

            directory, _response = _data(
                admin_client,
                "GET",
                "/api/v1/school/admin/directory",
                stage="class_directory",
            )
            classes = directory.get("classes")
            if not isinstance(classes, list) or not any(
                isinstance(item, dict)
                and item.get("class_ref") == CLASS_REF
                and item.get("status") == "ACTIVE"
                for item in classes
            ):
                raise QAError("class_directory", "SYNTHETIC_CLASS_UNAVAILABLE")

            accepted_staff: list[dict[str, str]] = []
            invitations: list[dict[str, Any]] = []
            suffix = uuid.uuid4().hex[:12].upper()
            definitions = [
                (
                    "teacher",
                    "TEACHER",
                    f"LCQA-TEACHER-{suffix}",
                    f"LifecycleQA教师{suffix}",
                    [CLASS_REF],
                ),
                (
                    "psychological_specialist",
                    "PSYCHOLOGICAL_SPECIALIST",
                    f"LCQA-PSYCH-{suffix}",
                    f"LifecycleQA心理老师{suffix}",
                    [],
                ),
            ]
            for (
                invitation_role,
                auth_role,
                employee_ref,
                display_name,
                class_refs,
            ) in definitions:
                invitation, _response = _data(
                    admin_client,
                    "POST",
                    "/api/v1/school/admin/staff/invitations",
                    stage=f"{invitation_role}_invitation",
                    expected=(201,),
                    body={
                        "employee_ref": employee_ref,
                        "display_name": display_name,
                        "role": invitation_role,
                        "work_contact": f"{employee_ref.lower()}@example.test",
                        "verified": True,
                        "class_refs": class_refs,
                        "delivery_channel": "MANUAL",
                    },
                    headers=_api_headers(
                        origin, csrf, f"lcqa-invitation-{uuid.uuid4().hex}"
                    ),
                )
                if (
                    invitation.get("status") != "ISSUED"
                    or invitation.get("delivery_channel") != "MANUAL_HANDOFF_REQUIRED"
                ):
                    raise QAError(
                        f"{invitation_role}_invitation", "INVITATION_RESULT_MISMATCH"
                    )
                login_name = invitation.get("login_name")
                invitation_ref = invitation.get("invitation_ref")
                raw_credential = invitation.get("credential")
                user_id = invitation.get("user_id")
                if not all(
                    isinstance(value, str) and value
                    for value in (login_name, invitation_ref, raw_credential, user_id)
                ):
                    raise QAError(
                        f"{invitation_role}_invitation",
                        "INVITATION_SECRET_RESULT_INVALID",
                    )
                invitations.append(
                    {
                        "role": invitation_role,
                        "auth_role": auth_role,
                        "user_id": user_id,
                        "invitation_ref": invitation_ref,
                        "login_name": login_name,
                        "credential": raw_credential,
                    }
                )
                result["stages"][f"{invitation_role}_invitation"] = "PASS"
                result["counts"]["invitations_created"] += 1

            for invitation in invitations:
                new_password = f"{uuid.uuid4().hex}Aa1!"
                _data(
                    admin_client,
                    "POST",
                    "/api/v1/auth/staff-invitations/accept",
                    stage=f"{invitation['role']}_acceptance",
                    body={
                        "invitation_ref": invitation["invitation_ref"],
                        "credential": invitation["credential"],
                        "new_password": new_password,
                        "confirm_password": new_password,
                    },
                    headers=_headers(origin),
                )
                result["stages"][f"{invitation['role']}_acceptance"] = "PASS"
                result["counts"]["invitations_accepted"] += 1
                accepted_staff.append(
                    {
                        "role": invitation["role"],
                        "auth_role": invitation["auth_role"],
                        "user_id": invitation["user_id"],
                        "login_name": invitation["login_name"],
                        "password": new_password,
                        "invitation_ref": invitation["invitation_ref"],
                        "credential": invitation["credential"],
                    }
                )

                with httpx.Client(
                    base_url=api_url, timeout=30.0, follow_redirects=False
                ) as staff_client:
                    staff_csrf, _actor = _login_role(
                        staff_client,
                        origin,
                        invitation["login_name"],
                        new_password,
                        invitation["auth_role"],
                    )
                    result["stages"][f"{invitation['role']}_role"] = "PASS"
                    forbidden = staff_client.get(
                        "/api/v1/school/admin/accounts/summary",
                        headers={"Origin": origin, "Accept": "application/json"},
                    )
                    if forbidden.status_code != 403:
                        raise QAError(
                            "admin_api_denied",
                            "STAFF_ADMIN_API_NOT_FORBIDDEN",
                            forbidden.status_code,
                        )
                    result["stages"]["admin_api_denied"] = "PASS"
                    replay = staff_client.post(
                        "/api/v1/auth/staff-invitations/accept",
                        json={
                            "invitation_ref": invitation["invitation_ref"],
                            "credential": invitation["credential"],
                            "new_password": new_password,
                            "confirm_password": new_password,
                        },
                        headers=_headers(origin),
                    )
                    if replay.status_code not in (401, 409):
                        raise QAError(
                            "credential_replay",
                            "ACCEPTED_INVITATION_REPLAY_NOT_REJECTED",
                            replay.status_code,
                        )
                    result["stages"]["credential_replay_rejected"] = "PASS"
                    logout = staff_client.post(
                        "/api/v1/auth/logout",
                        headers=_headers(
                            origin, staff_csrf, f"lcqa-logout-{uuid.uuid4().hex}"
                        ),
                    )
                    if logout.status_code != 200:
                        raise QAError(
                            "logout", "LOGOUT_NOT_CONFIRMED", logout.status_code
                        )
                    after = staff_client.get(
                        "/api/v1/auth/me",
                        headers={"Origin": origin, "Accept": "application/json"},
                    )
                    if after.status_code != 401:
                        raise QAError(
                            "logout", "SESSION_REMAINS_AUTHORIZED", after.status_code
                        )
                    result["stages"]["logout_revoked"] = "PASS"

            refreshed, _response = _data(
                admin_client,
                "GET",
                "/api/v1/school/admin/directory",
                stage="teacher_scope",
            )
            members = refreshed.get("members")
            teacher = next(
                (
                    item
                    for item in members or []
                    if isinstance(item, dict)
                    and item.get("user_id") == accepted_staff[0]["user_id"]
                ),
                None,
            )
            if not isinstance(teacher, dict) or teacher.get("class_refs") != [
                CLASS_REF
            ]:
                raise QAError("teacher_scope", "TEACHER_CLASS_SCOPE_MISMATCH")
            result["stages"]["teacher_class_scope"] = "PASS"

            ledger = admin_client.get(
                "/api/v1/school/admin/staff/invitations",
                headers={"Origin": origin, "Accept": "application/json"},
            )
            ledger_body = ledger.json() if ledger.status_code == 200 else None
            ledger_data = (
                ledger_body.get("data") if isinstance(ledger_body, dict) else None
            )
            specialist_ref = next(
                (
                    item["invitation_ref"]
                    for item in invitations
                    if item["role"] == "psychological_specialist"
                ),
                None,
            )
            specialist_row = next(
                (
                    item
                    for item in ledger_data or []
                    if isinstance(item, dict)
                    and item.get("invitation_ref") == specialist_ref
                ),
                None,
            )
            if (
                not isinstance(specialist_row, dict)
                or specialist_row.get("status") != "ACCEPTED"
                or specialist_row.get("class_refs") != []
                or "credential" in specialist_row
            ):
                raise QAError("specialist_scope", "SPECIALIST_SCOPE_OR_LEDGER_MISMATCH")
            result["stages"]["specialist_no_class_scope"] = "PASS"

            teacher = accepted_staff[0]
            with httpx.Client(
                base_url=api_url, timeout=30.0, follow_redirects=False
            ) as teacher_client:
                _teacher_csrf, _actor = _login_role(
                    teacher_client,
                    origin,
                    teacher["login_name"],
                    teacher["password"],
                    "TEACHER",
                )
                _data(
                    admin_client,
                    "POST",
                    "/api/v1/auth/reauthenticate",
                    stage="admin_reauthentication_staff_recovery",
                    body={"current_password": admin["password"]},
                    headers=_api_headers(origin, csrf),
                )
                reset, _response = _data(
                    admin_client,
                    "POST",
                    f"/api/v1/school/admin/staff/{teacher['user_id']}/recovery-credential",
                    stage="staff_recovery_issue",
                    expected=(200,),
                    body={
                        "reason_code": "CREDENTIAL_LOST",
                        "verification_method": "IN_PERSON",
                        "identity_verified": True,
                    },
                    headers=_api_headers(
                        origin, csrf, f"lcqa-staff-reset-{uuid.uuid4().hex}"
                    ),
                )
                if (
                    reset.get("status") != "ISSUED"
                    or reset.get("delivery_channel") != "MANUAL_HANDOFF_REQUIRED"
                    or not isinstance(reset.get("credential"), str)
                ):
                    raise QAError(
                        "staff_recovery_issue", "RESET_CREDENTIAL_RESULT_MISMATCH"
                    )
                result["stages"]["staff_recovery_issued"] = "PASS"
                after_issue = teacher_client.get(
                    "/api/v1/auth/me",
                    headers={"Origin": origin, "Accept": "application/json"},
                )
                if after_issue.status_code != 401:
                    raise QAError(
                        "staff_recovery_session",
                        "OLD_STAFF_SESSION_NOT_REVOKED",
                        after_issue.status_code,
                    )
                result["stages"]["staff_recovery_session_revoked"] = "PASS"

                staff_password = f"{uuid.uuid4().hex}Cc3!"
                reset_body = {
                    "school_ref": ALPHA_SCHOOL_REF,
                    "username": teacher["login_name"],
                    "credential": reset["credential"],
                    "new_password": staff_password,
                    "confirm_password": staff_password,
                }
                with httpx.Client(
                    base_url=api_url, timeout=30.0, follow_redirects=False
                ) as public_client:
                    _data(
                        public_client,
                        "POST",
                        "/api/v1/auth/password/reset/complete",
                        stage="staff_recovery_complete",
                        body=reset_body,
                        headers=_headers(origin),
                    )
                    result["stages"]["staff_recovery_completed"] = "PASS"
                    replay = public_client.post(
                        "/api/v1/auth/password/reset/complete",
                        json=reset_body,
                        headers=_headers(origin),
                    )
                    if replay.status_code not in (401, 409):
                        raise QAError(
                            "staff_recovery_replay",
                            "CONSUMED_RESET_NOT_REJECTED",
                            replay.status_code,
                        )
                    result["stages"]["staff_recovery_replay_rejected"] = "PASS"
                _staff_csrf, _actor = _login_role(
                    teacher_client,
                    origin,
                    teacher["login_name"],
                    staff_password,
                    "TEACHER",
                )
                result["stages"]["staff_recovery_login"] = "PASS"

            _data(
                admin_client,
                "POST",
                "/api/v1/auth/reauthenticate",
                stage="admin_reauthentication_cleanup",
                body={"current_password": admin["password"]},
                headers=_api_headers(origin, csrf),
            )
            for invitation in invitations:
                disabled, _response = _data(
                    admin_client,
                    "POST",
                    f"/api/v1/school/admin/accounts/{invitation['user_id']}/status",
                    stage="qa_account_cleanup",
                    body={"status": "DISABLED", "reason_code": "QA_CLEANUP"},
                    headers=_api_headers(
                        origin, csrf, f"lcqa-disable-{uuid.uuid4().hex}"
                    ),
                )
                if disabled.get("status") != "DISABLED":
                    raise QAError("qa_account_cleanup", "TEST_ACCOUNT_NOT_DISABLED")
                result["counts"]["qa_accounts_disabled"] += 1
            result["stages"]["qa_accounts_disabled"] = "PASS"

        result["status"] = (
            "PASS"
            if all(value == "PASS" for value in result["stages"].values())
            else "FAIL"
        )
        return result
    except QAError as exc:
        result = {"status": "FAIL", "failure": {"stage": exc.stage, "code": exc.code}}
        if exc.status is not None:
            result["failure"]["http_status"] = exc.status
        return result
    except Exception as exc:  # noqa: BLE001 - no raw SQL, URL or secret details.
        return {
            "status": "FAIL",
            "failure": {"stage": "harness", "code": type(exc).__name__},
        }


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
    result = run(
        args.workspace, backend_port=args.backend_port, frontend_port=args.frontend_port
    )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
