"""Verify a synthetic student password recovery through real local HTTP services."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ALPHA_SCHOOL_REF = "SYNTHETIC_SCHOOL_SEED_ALPHA_V1"
CLASS_REF = "LCQA-2026-C01"


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


def _request_data(
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
    except Exception as exc:  # noqa: BLE001 - suppress URL, body and credential details.
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
            stage, error_code or "UNEXPECTED_HTTP_STATUS", response.status_code
        )
    try:
        envelope = response.json()
    except ValueError:
        raise QAError(
            stage, "INVALID_RESPONSE_ENVELOPE", response.status_code
        ) from None
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        raise QAError(stage, "INVALID_RESPONSE_ENVELOPE", response.status_code)
    return data, response


async def _select_synthetic_student() -> tuple[str, str | None]:
    from database_layer import create_engine, create_session_factory
    from database_layer import models as m
    from database_layer.config import DatabaseSettings
    from sqlalchemy import exists, select

    engine = create_engine(DatabaseSettings.from_env())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            has_recovery_history = exists(
                select(m.SchoolPasswordRecoveryTicket.id).where(
                    m.SchoolPasswordRecoveryTicket.account_id == m.Account.id,
                    m.SchoolPasswordRecoveryTicket.school_id == m.School.id,
                )
            )

            def student_query(columns: Any):
                return (
                    select(*columns)
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .join(
                        m.SubjectAccessGrant,
                        (m.SubjectAccessGrant.principal_account_id == m.Account.id)
                        & (m.SubjectAccessGrant.school_id == m.School.id),
                    )
                    .join(
                        m.SchoolClassStudent,
                        (
                            m.SchoolClassStudent.subject_id
                            == m.SubjectAccessGrant.subject_id
                        )
                        & (m.SchoolClassStudent.school_id == m.School.id),
                    )
                    .join(
                        m.SchoolClass,
                        (m.SchoolClass.id == m.SchoolClassStudent.class_id)
                        & (m.SchoolClass.school_id == m.School.id),
                    )
                    .where(
                        m.School.school_ref == ALPHA_SCHOOL_REF,
                        m.School.data_origin == "SYNTHETIC",
                        m.SchoolClass.class_ref == CLASS_REF,
                        m.SchoolClass.status == "ACTIVE",
                        m.SchoolClassStudent.status == "ACTIVE",
                        m.SubjectAccessGrant.relationship_type == "SELF",
                        m.SubjectAccessGrant.status == "ACTIVE",
                        m.MembershipRole.role_code == "student",
                        m.MembershipRole.status == "ACTIVE",
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.Account.status == "ACTIVE",
                        m.Account.login_name.like("SYNTHETIC_ROSTER_%"),
                    )
                    .order_by(m.Account.id)
                    .limit(1)
                )

            pending_ticket_query = (
                student_query(
                    (
                        m.Account.login_name,
                        m.SchoolPasswordRecoveryTicket.ticket_ref,
                    )
                )
                .join(
                    m.SchoolPasswordRecoveryTicket,
                    (m.SchoolPasswordRecoveryTicket.account_id == m.Account.id)
                    & (m.SchoolPasswordRecoveryTicket.school_id == m.School.id),
                )
                .where(m.SchoolPasswordRecoveryTicket.status == "REQUESTED")
                .order_by(m.SchoolPasswordRecoveryTicket.created_at.desc())
            )
            pending_ticket = (await session.execute(pending_ticket_query)).first()
            if pending_ticket is not None:
                return str(pending_ticket[0]), str(pending_ticket[1])

            fresh_student = await session.scalar(
                student_query((m.Account.login_name,)).where(~has_recovery_history)
            )
            if not isinstance(fresh_student, str):
                raise QAError(
                    "student_selection", "FRESH_SYNTHETIC_STUDENT_UNAVAILABLE"
                )
            return fresh_student, None
    finally:
        await engine.dispose()


def _login_role(
    client: Any, origin: str, username: str, password: str, role: str
) -> str:
    result, _response = _request_data(
        client,
        "POST",
        "/api/v1/auth/login",
        stage=f"{role.lower()}_login",
        body={"username": username, "password": password},
        headers=_headers(origin),
    )
    csrf = result.get("csrf_token")
    actor = result.get("actor")
    active = actor.get("active_context") if isinstance(actor, dict) else None
    if not isinstance(csrf, str) or not isinstance(actor, dict):
        raise QAError(f"{role.lower()}_login", "INVALID_LOGIN_RESPONSE")
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
        actor, _response = _request_data(
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
        raise QAError(f"{role.lower()}_login", "EXPECTED_ROLE_CONTEXT_UNAVAILABLE")
    return csrf


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
        student_username, pending_ticket_ref = asyncio.run(_select_synthetic_student())
        origin = f"http://127.0.0.1:{frontend_port}"
        api_url = f"http://127.0.0.1:{backend_port}"
        result: dict[str, Any] = {
            "status": "FAIL",
            "stages": {
                "admin_login": "FAIL",
                "admin_reauthentication": "FAIL",
                "student_recovery_request": "FAIL",
                "teacher_class_scope": "FAIL",
                "teacher_verification": "FAIL",
                "admin_approval": "FAIL",
                "reset_completion": "FAIL",
                "reset_replay_rejected": "FAIL",
                "student_login": "FAIL",
                "logout_revoked": "FAIL",
                "qa_teacher_disabled": "FAIL",
            },
            "counts": {"recovery_completed": 0},
        }

        with httpx.Client(
            base_url=api_url, timeout=30.0, follow_redirects=False
        ) as admin_client:
            csrf, _actor = _login_admin(admin_client, admin, origin)
            result["stages"]["admin_login"] = "PASS"
            _request_data(
                admin_client,
                "POST",
                "/api/v1/auth/reauthenticate",
                stage="admin_reauthentication",
                body={"current_password": admin["password"]},
                headers=_api_headers(origin, csrf),
            )
            result["stages"]["admin_reauthentication"] = "PASS"

            invitation, _response = _request_data(
                admin_client,
                "POST",
                "/api/v1/school/admin/staff/invitations",
                stage="teacher_invitation",
                expected=(201,),
                body={
                    "employee_ref": f"LCQA-RECOVERY-TEACHER-{uuid.uuid4().hex[:12]}",
                    "display_name": "恢复流程核验教师",
                    "role": "teacher",
                    "work_contact": f"lcqa-{uuid.uuid4().hex}@example.test",
                    "verified": True,
                    "class_refs": [CLASS_REF],
                    "delivery_channel": "MANUAL",
                },
                headers=_api_headers(
                    origin, csrf, f"lcqa-recovery-invite-{uuid.uuid4().hex}"
                ),
            )
            if not all(
                isinstance(invitation.get(name), str) and invitation[name]
                for name in ("invitation_ref", "credential", "login_name")
            ):
                raise QAError("teacher_invitation", "INVITATION_RESULT_INVALID")
            teacher_password = f"{uuid.uuid4().hex}Aa1!"
            with httpx.Client(
                base_url=api_url, timeout=30.0, follow_redirects=False
            ) as public_client:
                _request_data(
                    public_client,
                    "POST",
                    "/api/v1/auth/staff-invitations/accept",
                    stage="teacher_invitation_acceptance",
                    body={
                        "invitation_ref": invitation["invitation_ref"],
                        "credential": invitation["credential"],
                        "new_password": teacher_password,
                        "confirm_password": teacher_password,
                    },
                    headers=_headers(origin),
                )
            if pending_ticket_ref is None:
                with httpx.Client(
                    base_url=api_url, timeout=30.0, follow_redirects=False
                ) as public_client:
                    request, _response = _request_data(
                        public_client,
                        "POST",
                        "/api/v1/auth/recovery-requests",
                        stage="student_recovery_request",
                        body={
                            "school_ref": ALPHA_SCHOOL_REF,
                            "username": student_username,
                            "class_ref": CLASS_REF,
                            "reason_code": "CREDENTIAL_LOST",
                        },
                        headers=_headers(origin),
                    )
                if request.get("status") != "REQUEST_RECEIVED":
                    raise QAError(
                        "student_recovery_request", "GENERIC_REQUEST_RESPONSE_MISMATCH"
                    )
            result["stages"]["student_recovery_request"] = "PASS"
            result["stages"]["student_recovery_request"] = "PASS"

            queue_response = admin_client.get(
                "/api/v1/school/admin/recovery-requests",
                headers={"Origin": origin, "Accept": "application/json"},
            )
            try:
                queue_envelope = queue_response.json()
            except ValueError:
                raise QAError(
                    "recovery_queue",
                    "INVALID_RESPONSE_ENVELOPE",
                    queue_response.status_code,
                ) from None
            queue = (
                queue_envelope.get("data") if isinstance(queue_envelope, dict) else None
            )
            ticket = next(
                (
                    item
                    for item in queue or []
                    if isinstance(item, dict)
                    and item.get("username") == student_username
                    and item.get("class_ref") == CLASS_REF
                    and item.get("status") == "REQUESTED"
                ),
                None,
            )
            if queue_response.status_code != 200 or not isinstance(ticket, dict):
                raise QAError(
                    "recovery_queue",
                    "REQUESTED_TICKET_UNAVAILABLE",
                    queue_response.status_code,
                )
            ticket_ref = pending_ticket_ref or ticket.get("ticket_ref")
            if not isinstance(ticket_ref, str) or not ticket_ref:
                raise QAError("recovery_queue", "TICKET_REFERENCE_UNAVAILABLE")

            wrong_role = admin_client.post(
                f"/api/v1/school/teacher/recovery-requests/{ticket_ref}/verify",
                json={"reason_code": "IDENTITY_CHECKED"},
                headers=_api_headers(
                    origin, csrf, f"lcqa-wrong-role-{uuid.uuid4().hex}"
                ),
            )
            if wrong_role.status_code != 403:
                raise QAError(
                    "teacher_role_boundary",
                    "ADMIN_VERIFICATION_NOT_FORBIDDEN",
                    wrong_role.status_code,
                )

            with httpx.Client(
                base_url=api_url, timeout=30.0, follow_redirects=False
            ) as teacher_client:
                teacher_csrf = _login_role(
                    teacher_client,
                    origin,
                    invitation["login_name"],
                    teacher_password,
                    "TEACHER",
                )
                _request_data(
                    teacher_client,
                    "GET",
                    "/api/v1/auth/me",
                    stage="teacher_session",
                )
                _request_data(
                    teacher_client,
                    "POST",
                    f"/api/v1/school/teacher/recovery-requests/{ticket_ref}/verify",
                    stage="teacher_verification",
                    body={"reason_code": "IDENTITY_CHECKED"},
                    headers=_headers(
                        origin, teacher_csrf, f"lcqa-verify-{uuid.uuid4().hex}"
                    ),
                )
            result["stages"]["teacher_verification"] = "PASS"

            _request_data(
                admin_client,
                "POST",
                "/api/v1/auth/reauthenticate",
                stage="admin_reauthentication",
                body={"current_password": admin["password"]},
                headers=_api_headers(origin, csrf),
            )
            result["stages"]["admin_reauthentication"] = "PASS"
            reset, _response = _request_data(
                admin_client,
                "POST",
                f"/api/v1/school/admin/recovery-requests/{ticket_ref}/approve",
                stage="admin_approval",
                body={"reason_code": "IDENTITY_CONFIRMED"},
                headers=_api_headers(origin, csrf, f"lcqa-approve-{uuid.uuid4().hex}"),
            )
            if reset.get("status") != "APPROVED" or not isinstance(
                reset.get("credential"), str
            ):
                raise QAError("admin_approval", "RESET_CREDENTIAL_UNAVAILABLE")
            result["stages"]["admin_approval"] = "PASS"
            result["stages"]["teacher_class_scope"] = "PASS"

            student_password = f"{uuid.uuid4().hex}Bb2!"
            reset_body = {
                "school_ref": ALPHA_SCHOOL_REF,
                "username": student_username,
                "credential": reset["credential"],
                "new_password": student_password,
                "confirm_password": student_password,
            }
            with httpx.Client(
                base_url=api_url, timeout=30.0, follow_redirects=False
            ) as reset_client:
                _request_data(
                    reset_client,
                    "POST",
                    "/api/v1/auth/password/reset/complete",
                    stage="reset_completion",
                    body=reset_body,
                    headers=_headers(origin),
                )
                result["stages"]["reset_completion"] = "PASS"
                replay = reset_client.post(
                    "/api/v1/auth/password/reset/complete",
                    json=reset_body,
                    headers=_headers(origin),
                )
                if replay.status_code not in (401, 409):
                    raise QAError(
                        "reset_replay",
                        "CONSUMED_RESET_CREDENTIAL_NOT_REJECTED",
                        replay.status_code,
                    )
                result["stages"]["reset_replay_rejected"] = "PASS"

            with httpx.Client(
                base_url=api_url, timeout=30.0, follow_redirects=False
            ) as student_client:
                student_csrf = _login_role(
                    student_client,
                    origin,
                    student_username,
                    student_password,
                    "STUDENT",
                )
                result["stages"]["student_login"] = "PASS"
                _request_data(
                    student_client,
                    "POST",
                    "/api/v1/auth/logout",
                    stage="logout",
                    headers=_headers(
                        origin, student_csrf, f"lcqa-reset-logout-{uuid.uuid4().hex}"
                    ),
                )
                after = student_client.get(
                    "/api/v1/auth/me",
                    headers={"Origin": origin, "Accept": "application/json"},
                )
                if after.status_code != 401:
                    raise QAError(
                        "logout", "SESSION_REMAINS_AUTHORIZED", after.status_code
                    )
                result["stages"]["logout_revoked"] = "PASS"

            _request_data(
                admin_client,
                "POST",
                "/api/v1/auth/reauthenticate",
                stage="admin_reauthentication_cleanup",
                body={"current_password": admin["password"]},
                headers=_api_headers(origin, csrf),
            )
            disabled, _response = _request_data(
                admin_client,
                "POST",
                f"/api/v1/school/admin/accounts/{invitation['user_id']}/status",
                stage="qa_teacher_cleanup",
                body={"status": "DISABLED", "reason_code": "QA_CLEANUP"},
                headers=_api_headers(origin, csrf, f"lcqa-disable-{uuid.uuid4().hex}"),
            )
            if disabled.get("status") != "DISABLED":
                raise QAError("qa_teacher_cleanup", "TEST_ACCOUNT_NOT_DISABLED")
            result["stages"]["qa_teacher_disabled"] = "PASS"
            result["counts"]["recovery_completed"] = 1

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
    except Exception as exc:  # noqa: BLE001 - never emit URLs, SQL or credential details.
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
