"""Run an append-only synthetic school-directory API check on loopback."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://127.0.0.1:8088"
QA_STATE_FILE = "school-directory.private.qa.dpapi"
QA_SCHEMA = "psynova.school-directory-http-qa.v1"
LOGIN_PATTERN = re.compile(r"SYNTHETIC_[A-Za-z0-9_]{1,100}\Z")


class QaFailure(RuntimeError):
    """An invariant failed; the exception message is deliberately fixed."""


class SessionCleanupFailure(QaFailure):
    """A bootstrap session could not be confirmed logged out."""


def _require(condition: bool) -> None:
    if not condition:
        raise QaFailure("school directory QA invariant failed")


def _reject_reparse_path(path: Path, *, allow_missing_leaf: bool = False) -> None:
    """Reject Windows reparse points before reading or writing workspace files."""
    if not path.is_absolute() or ".." in path.parts:
        raise QaFailure("workspace path is invalid")
    cursor = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        cursor = cursor / part
        try:
            attributes = getattr(cursor.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            if allow_missing_leaf and index == len(path.parts[1:]) - 1:
                return
            raise QaFailure("workspace path is unavailable") from None
        if attributes & 0x400:
            raise QaFailure("workspace path is invalid")


def _atomic_write_private(
    path: Path, values: dict[str, Any], *, exclusive: bool
) -> None:
    from private_settings import write_private

    _reject_reparse_path(path.parent)
    _reject_reparse_path(path, allow_missing_leaf=not path.exists())
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        _reject_reparse_path(temporary, allow_missing_leaf=True)
        write_private(temporary, values, exclusive=True)
        if exclusive and path.exists():
            raise FileExistsError("QA recovery state already exists")
        _reject_reparse_path(path, allow_missing_leaf=not path.exists())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _validate_state(value: Any, workspace_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != QA_SCHEMA:
        raise QaFailure("QA recovery state is invalid")
    if value.get("workspace_id") != workspace_id:
        raise QaFailure("QA recovery state belongs to another workspace")
    if not isinstance(value.get("run_id"), str) or not re.fullmatch(
        r"[a-f0-9]{32}", value["run_id"]
    ):
        raise QaFailure("QA recovery state is invalid")
    suffix = value["run_id"][:20].upper()
    class_ref = value.get("class_ref")
    if (
        not isinstance(class_ref, str)
        or not re.fullmatch(r"CLASS_DIR_QA_[A-F0-9]{20}", class_ref)
        or class_ref != f"CLASS_DIR_QA_{suffix}"
    ):
        raise QaFailure("QA recovery state is invalid")
    if not isinstance(value.get("original_school_name"), (str, type(None))):
        raise QaFailure("QA recovery state is invalid")
    if (
        not isinstance(value.get("class_name"), str)
        or not isinstance(value.get("school_name"), str)
        or len(value["class_name"]) > 120
        or len(value["school_name"]) > 120
    ):
        raise QaFailure("QA recovery state is invalid")
    if not isinstance(value.get("keys"), dict) or not isinstance(
        value.get("task"), dict
    ):
        raise QaFailure("QA recovery state is invalid")
    keys = value["keys"]
    task = value["task"]
    if (
        set(keys) != {"class", "import"}
        or any(
            not isinstance(item, str) or not re.fullmatch(r"[a-f0-9]{32}", item)
            for item in keys.values()
        )
        or set(task) != {"key", "opens_at", "due_at"}
        or not isinstance(task.get("key"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", task["key"])
        or not all(isinstance(task.get(name), str) for name in ("opens_at", "due_at"))
        or not isinstance(value.get("valid_preview_done"), bool)
        or not isinstance(value.get("import_verified"), bool)
        or not isinstance(value.get("activation_started"), bool)
    ):
        raise QaFailure("QA recovery state is invalid")
    accounts = value.get("accounts")
    if not isinstance(accounts, dict) or set(accounts) != {"student", "teacher"}:
        raise QaFailure("QA recovery state is invalid")
    seen: set[str] = set()
    for role, account in accounts.items():
        if not isinstance(account, dict):
            raise QaFailure("QA recovery state is invalid")
        username, password = account.get("username"), account.get("password")
        if (
            not isinstance(username, str)
            or LOGIN_PATTERN.fullmatch(username) is None
            or username != f"SYNTHETIC_QA_{role.upper()}_{suffix}"
            or username.casefold() in seen
            or not isinstance(password, str)
            or len(password) < 16
            or not isinstance(account.get("display_name"), str)
            or len(account["display_name"]) > 120
            or role not in {"student", "teacher"}
        ):
            raise QaFailure("QA recovery state is invalid")
        seen.add(username.casefold())
    return value


def _new_state(workspace_id: str, original_school_name: str | None) -> dict[str, Any]:
    run_id = uuid4().hex
    suffix = run_id[:20].upper()
    return {
        "schema_version": QA_SCHEMA,
        "workspace_id": workspace_id,
        "run_id": run_id,
        "original_school_name": original_school_name,
        "class_ref": f"CLASS_DIR_QA_{suffix}",
        "class_name": f"目录验收班级 {suffix}",
        "school_name": f"目录验收学校 {suffix}",
        "keys": {"class": uuid4().hex, "import": uuid4().hex},
        "valid_preview_done": False,
        "import_verified": False,
        "activation_started": False,
        "task": {
            "key": uuid4().hex,
            "opens_at": datetime.now(UTC).isoformat(),
            "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
        "accounts": {
            role: {
                "username": f"SYNTHETIC_QA_{role.upper()}_{suffix}",
                "password": secrets.token_urlsafe(24) + "Aa9!",
                "display_name": f"目录验收{'学生' if role == 'student' else '教师'} {suffix}",
            }
            for role in ("student", "teacher")
        },
    }


def _data(response: Any, expected_status: int) -> Any:
    _require(response.status_code == expected_status)
    try:
        body = response.json()
    except ValueError as exc:
        raise QaFailure("invalid HTTP response") from exc
    _require(isinstance(body, dict) and isinstance(body.get("data"), (dict, list)))
    return body["data"]


def _contains_forbidden_fields(value: Any) -> bool:
    forbidden = {
        "password",
        "password_hash",
        "login_name",
        "username",
        "subject_id",
        "assessment_id",
        "responses",
        "report",
    }
    if isinstance(value, dict):
        return any(
            str(key).casefold() in forbidden or _contains_forbidden_fields(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_fields(item) for item in value)
    return False


def _assert_no_echo(response: Any, values: list[str]) -> None:
    body = response.text
    _require(all(value not in body for value in values))


def _login(
    client: Any, username: str, password: str, role: str, school_ref: str | None = None
):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    auth = _data(response, 200)
    _assert_no_echo(response, [password])
    _require(isinstance(auth.get("csrf_token"), str) and bool(auth["csrf_token"]))
    actor = auth.get("actor")
    _require(isinstance(actor, dict))
    contexts = actor.get("available_contexts")
    _require(isinstance(contexts, list))
    candidates = [
        item
        for item in contexts
        if isinstance(item, dict)
        and item.get("role") == role
        and (school_ref is None or item.get("school_ref") == school_ref)
    ]
    _require(bool(candidates))
    selected = candidates[0]
    csrf = auth["csrf_token"]
    context_response = client.post(
        "/api/v1/auth/active-context",
        json=selected,
        headers={"X-CSRF-Token": csrf},
    )
    active_actor = _data(context_response, 200)
    _require(
        isinstance(active_actor.get("active_context"), dict)
        and active_actor["active_context"].get("role") == role
        and active_actor["active_context"].get("school_ref") == selected["school_ref"]
    )
    return {"csrf": csrf, "school_ref": selected["school_ref"]}


def _write(
    client: Any, csrf: str, path: str, body: dict[str, Any], *, key: str | None = None
):
    headers = {"X-CSRF-Token": csrf}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(path, json=body, headers=headers)


def _safe_result(
    run_id: str | None,
    checks: dict[str, str],
    *,
    stage: str,
    status: str,
    http_status: int | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "psynova.school-directory-http-result.v1",
        "status": status,
        "stage": stage,
        "checks": dict(checks),
        "expected_accounts": 2,
    }
    if run_id is not None:
        result["run_id"] = run_id
    if http_status is not None:
        result["http_status"] = http_status
    if error_type is not None:
        result["error_type"] = error_type
    return result


def run(workspace_arg: Path, *, resume: bool = False) -> dict[str, Any]:
    import httpx
    from private_settings import read_private
    from school_backend import load_runtime
    from school_browser_qa import validate_credentials, validate_workspace_path

    _reject_reparse_path(workspace_arg)
    workspace = validate_workspace_path(workspace_arg, REPO)
    _reject_reparse_path(workspace)
    _reject_reparse_path(workspace / "workspace.json")
    from resume_school_workspace import ResumeOperations

    ResumeOperations().verify_acl(workspace)
    marker = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    _require(
        isinstance(marker.get("workspace_id"), str)
        and bool(marker["workspace_id"])
        and marker.get("port") == 3308
        and marker.get("database") == "smhai_school_demo"
    )
    load_runtime(workspace, REPO)

    state_path = workspace / QA_STATE_FILE
    account_file = workspace / "school-accounts.private.dpapi"
    _reject_reparse_path(state_path, allow_missing_leaf=not state_path.exists())
    _reject_reparse_path(account_file)
    if resume:
        state = _validate_state(read_private(state_path), marker["workspace_id"])
    else:
        _require(not state_path.exists())
        stored_accounts = read_private(account_file)
        credentials = validate_credentials(stored_accounts)
        admin_credentials = credentials["alpha.admin"]
        admin = httpx.Client(base_url=BACKEND_URL, timeout=30, trust_env=False)
        admin_auth: dict[str, str] | None = None
        admin_cleanup_failed = False
        try:
            admin_auth = _login(
                admin,
                admin_credentials["username"],
                admin_credentials["password"],
                "ADMIN",
            )
            directory_response = admin.get(
                "/api/v1/school/admin/directory",
                headers={"X-CSRF-Token": admin_auth["csrf"]},
            )
            directory = _data(directory_response, 200)
            _require(isinstance(directory.get("school"), dict))
            state = _new_state(
                marker["workspace_id"], directory["school"].get("display_name")
            )
            _atomic_write_private(state_path, state, exclusive=True)
        finally:
            if admin_auth is not None:
                try:
                    logout = admin.post(
                        "/api/v1/auth/logout",
                        headers={"X-CSRF-Token": admin_auth["csrf"]},
                    )
                    admin_cleanup_failed = logout.status_code not in {200, 204}
                except httpx.HTTPError:
                    admin_cleanup_failed = True
            elif admin.cookies:
                admin_cleanup_failed = True
            try:
                admin.close()
            except (OSError, RuntimeError):
                admin_cleanup_failed = True
            if admin_cleanup_failed:
                raise SessionCleanupFailure("initial admin session cleanup failed")

    state = _validate_state(state, marker["workspace_id"])
    credentials = validate_credentials(read_private(account_file))
    clients: dict[str, Any] = {}
    csrf: dict[str, str] = {}
    checks: dict[str, str] = {}
    stage = "client_setup"
    http_status: int | None = None
    school_changed = False
    restore_ok = True
    result: dict[str, Any] | None = None

    def checked(response: Any, expected: int = 200) -> Any:
        nonlocal http_status
        http_status = response.status_code
        return _data(response, expected)

    try:
        stage = "admin_login"
        clients["admin"] = httpx.Client(
            base_url=BACKEND_URL, timeout=30, trust_env=False
        )
        admin_auth = _login(
            clients["admin"],
            credentials["alpha.admin"]["username"],
            credentials["alpha.admin"]["password"],
            "ADMIN",
        )
        csrf["admin"] = admin_auth["csrf"]
        school_ref = admin_auth["school_ref"]

        stage = "directory_projection"
        directory = checked(
            clients["admin"].get(
                "/api/v1/school/admin/directory",
                headers={"X-CSRF-Token": csrf["admin"]},
            )
        )
        _require(not _contains_forbidden_fields(directory))
        _require(directory["school"]["school_ref"] == school_ref)
        checks["directory_minimum_disclosure"] = "PASS"

        original_name = state.get("original_school_name")
        if original_name is None:
            checks["school_name_roundtrip"] = "SKIPPED_NULL_ORIGINAL_NAME"
        elif isinstance(original_name, str) and original_name.strip():
            stage = "school_name_edit"
            school_changed = True
            response = _write(
                clients["admin"],
                csrf["admin"],
                "/api/v1/school/admin/school/name",
                {"display_name": state["school_name"]},
            )
            edited = checked(response)
            _require(edited.get("display_name") == state["school_name"])
        else:
            raise QaFailure("original school name is invalid")

        stage = "class_create"
        class_body = {"class_ref": state["class_ref"]}
        created_class = checked(
            _write(
                clients["admin"],
                csrf["admin"],
                "/api/v1/school/classes",
                class_body,
                key=state["keys"]["class"],
            ),
            201,
        )
        _require(created_class.get("class_ref") == state["class_ref"])
        replayed_class = checked(
            _write(
                clients["admin"],
                csrf["admin"],
                "/api/v1/school/classes",
                class_body,
                key=state["keys"]["class"],
            ),
            201,
        )
        _require(replayed_class.get("class_ref") == state["class_ref"])
        checks["class_idempotent_replay"] = "PASS"

        stage = "class_name_edit"
        named_class = checked(
            _write(
                clients["admin"],
                csrf["admin"],
                f"/api/v1/school/admin/classes/{state['class_ref']}/name",
                {"display_name": state["class_name"]},
            )
        )
        _require(named_class.get("display_name") == state["class_name"])
        checks["class_name_edit"] = "PASS"

        stage = "invalid_preview"
        invalid_login = f"invalid directory login {state['run_id']}"
        invalid_name = f"DIRECTORY_ECHO_SENTINEL_{state['run_id']}"
        invalid_preview = clients["admin"].post(
            "/api/v1/school/admin/accounts/preview",
            json={
                "class_ref": state["class_ref"],
                "rows": [
                    {
                        "row_no": 1,
                        "login_name": invalid_login,
                        "display_name": invalid_name,
                        "role": "student",
                    },
                    {
                        "row_no": 2,
                        "login_name": invalid_login,
                        "display_name": invalid_name,
                        "role": "teacher",
                    },
                ],
            },
        )
        invalid_result = checked(invalid_preview)
        _assert_no_echo(invalid_preview, [invalid_login, invalid_name])
        error_codes = {item.get("code") for item in invalid_result.get("errors", [])}
        _require(
            invalid_result.get("valid") is False
            and "INVALID_LOGIN_NAME" in error_codes
            and "DUPLICATE_LOGIN_NAME" in error_codes
        )
        checks["invalid_preview_no_echo"] = "PASS"

        rows = [
            {
                "row_no": row_no,
                "login_name": account["username"],
                "display_name": account["display_name"],
                "role": role,
            }
            for row_no, (role, account) in enumerate(state["accounts"].items(), start=1)
        ]
        if not state["valid_preview_done"]:
            stage = "valid_preview"
            preview = checked(
                clients["admin"].post(
                    "/api/v1/school/admin/accounts/preview",
                    json={"class_ref": state["class_ref"], "rows": rows},
                )
            )
            _require(preview.get("valid") is True and preview.get("row_count") == 2)
            state["valid_preview_done"] = True
            _atomic_write_private(state_path, state, exclusive=False)
            checks["valid_preview"] = "PASS"
        else:
            checks["valid_preview"] = "PASS_RESUMED"

        stage = "account_import"
        import_body = {"class_ref": state["class_ref"], "rows": rows}
        _require(not any("password" in key.casefold() for key in import_body))
        imported_response = _write(
            clients["admin"],
            csrf["admin"],
            "/api/v1/school/admin/accounts/import",
            import_body,
            key=state["keys"]["import"],
        )
        imported = checked(imported_response, 201)
        _assert_no_echo(
            imported_response,
            [account["username"] for account in state["accounts"].values()]
            + [account["password"] for account in state["accounts"].values()],
        )
        _require(
            imported.get("created_count") == 2
            and len(imported.get("accounts", [])) == 2
        )
        import_statuses = [item.get("status") for item in imported["accounts"]]
        if not state["import_verified"]:
            _require(import_statuses == ["PENDING_ACTIVATION", "PENDING_ACTIVATION"])

        stage = "import_resource_replay"
        replay_response = _write(
            clients["admin"],
            csrf["admin"],
            "/api/v1/school/admin/accounts/import",
            import_body,
            key=state["keys"]["import"],
        )
        replayed = checked(replay_response, 201)
        _require(
            replayed.get("batch_ref") == imported.get("batch_ref")
            and replayed.get("created_count") == 2
            and replayed.get("accounts") == imported.get("accounts")
        )
        checks["import_replays_same_batch"] = "PASS"
        state["import_verified"] = True
        _atomic_write_private(state_path, state, exclusive=False)

        stage = "member_name_edit"
        for role, item in zip(state["accounts"], imported["accounts"], strict=True):
            response = _write(
                clients["admin"],
                csrf["admin"],
                f"/api/v1/school/admin/members/{item['user_id']}/name",
                {"display_name": state["accounts"][role]["display_name"]},
            )
            name_result = checked(response)
            _require(
                name_result.get("display_name")
                == state["accounts"][role]["display_name"]
            )
        checks["member_name_edit"] = "PASS"

        stage = "activation"
        batch_path = f"/api/v1/school/admin/accounts/batches/{imported['batch_ref']}"
        current_batch = checked(clients["admin"].get(batch_path))
        _require(current_batch.get("created_count") == 2)
        by_row = {
            item.get("row_no"): item for item in current_batch.get("accounts", [])
        }
        _require(set(by_row) == {1, 2})
        for row_no, (_role, account) in enumerate(state["accounts"].items(), start=1):
            item = by_row[row_no]
            if item.get("status") == "PENDING_ACTIVATION":
                state["activation_started"] = True
                _atomic_write_private(state_path, state, exclusive=False)
                activation_response = _write(
                    clients["admin"],
                    csrf["admin"],
                    f"/api/v1/school/admin/accounts/{item['user_id']}/activate",
                    {"new_password": account["password"]},
                )
                activation_result = checked(activation_response, 200)
                _assert_no_echo(activation_response, [account["password"]])
                _require(activation_result.get("status") == "ACTIVE")
            else:
                _require(item.get("status") == "ACTIVE")
            second_activation = _write(
                clients["admin"],
                csrf["admin"],
                f"/api/v1/school/admin/accounts/{item['user_id']}/activate",
                {"new_password": account["password"]},
            )
            http_status = second_activation.status_code
            _assert_no_echo(second_activation, [account["password"]])
            _require(second_activation.status_code == 409)
        checks["activation_one_time"] = "PASS"

        stage = "student_teacher_login"
        for role, account in state["accounts"].items():
            clients[role] = httpx.Client(
                base_url=BACKEND_URL, timeout=30, trust_env=False
            )
            actor = _login(
                clients[role],
                account["username"],
                account["password"],
                role.upper(),
                school_ref,
            )
            csrf[role] = actor["csrf"]
            forbidden = clients[role].get(
                "/api/v1/school/admin/directory",
                headers={"X-CSRF-Token": csrf[role]},
            )
            http_status = forbidden.status_code
            _require(forbidden.status_code == 403)
        checks["new_account_login_and_admin_denial"] = "PASS"

        stage = "cross_school_admin_denial"
        stored_accounts = read_private(account_file)
        raw_credentials = (
            stored_accounts.get("credentials", {})
            if isinstance(stored_accounts, dict)
            else {}
        )
        beta_admin = (
            raw_credentials.get("beta.admin")
            if isinstance(raw_credentials, dict)
            else None
        )
        if isinstance(beta_admin, (list, tuple)) and len(beta_admin) == 2:
            foreign_client = httpx.Client(
                base_url=BACKEND_URL, timeout=30, trust_env=False
            )
            clients["foreign_admin"] = foreign_client
            foreign_auth = _login(foreign_client, beta_admin[0], beta_admin[1], "ADMIN")
            csrf["foreign_admin"] = foreign_auth["csrf"]
            _require(foreign_auth["school_ref"] != school_ref)
            foreign_read = foreign_client.get(
                batch_path, headers={"X-CSRF-Token": foreign_auth["csrf"]}
            )
            http_status = foreign_read.status_code
            _require(foreign_read.status_code == 404)
            checks["cross_school_batch_denial"] = "PASS"
        else:
            checks["cross_school_batch_denial"] = "SKIPPED_NO_FOREIGN_ADMIN_FIXTURE"

        stage = "typed_class_links"
        directory_after_activation = checked(
            clients["admin"].get(
                "/api/v1/school/admin/directory",
                headers={"X-CSRF-Token": csrf["admin"]},
            )
        )
        target_class = next(
            item
            for item in directory_after_activation["classes"]
            if item.get("class_ref") == state["class_ref"]
        )
        _require(
            target_class.get("display_name") == state["class_name"]
            and target_class.get("active_student_count") == 1
            and target_class.get("active_teacher_count") == 1
        )
        checks["typed_class_student_teacher_links"] = "PASS"

        stage = "assigned_workflow"
        task = state["task"]
        task_body = {"opens_at": task["opens_at"], "due_at": task["due_at"]}
        published = checked(
            _write(
                clients["admin"],
                csrf["admin"],
                f"/api/v1/school/classes/{state['class_ref']}/tasks",
                task_body,
                key=task["key"],
            ),
            201,
        )
        task_ref = published.get("task_ref")
        _require(
            isinstance(task_ref, str)
            and published.get("published_enrollment_count") == 1
        )
        student_tasks = checked(
            clients["student"].get(
                "/api/v1/school/tasks/student",
                headers={"X-CSRF-Token": csrf["student"]},
            )
        )
        _require(any(item.get("task_ref") == task_ref for item in student_tasks))
        teacher_progress = checked(
            clients["teacher"].get(
                f"/api/v1/school/classes/{state['class_ref']}/task-progress",
                headers={"X-CSRF-Token": csrf["teacher"]},
            )
        )
        _require(
            len(teacher_progress) == 1
            and teacher_progress[0].get("task_ref") == task_ref
            and not _contains_forbidden_fields(teacher_progress)
        )
        checks["student_assigned_task_and_teacher_aggregate"] = "PASS"

        result = _safe_result(state["run_id"], checks, stage="complete", status="PASS")
    except Exception as exc:  # noqa: BLE001 - exception messages may contain request data.
        result = _safe_result(
            state.get("run_id") if isinstance(state, dict) else None,
            checks,
            stage=stage,
            status="FAIL",
            http_status=http_status,
            error_type=type(exc).__name__,
        )
    finally:
        if school_changed and clients.get("admin") is not None:
            try:
                original_name = state.get("original_school_name")
                response = _write(
                    clients["admin"],
                    csrf["admin"],
                    "/api/v1/school/admin/school/name",
                    {"display_name": original_name},
                )
                restore_ok = response.status_code == 200
                if restore_ok:
                    restored = response.json().get("data", {})
                    restore_ok = restored.get("display_name") == original_name
            except (httpx.HTTPError, ValueError, AttributeError):
                restore_ok = False
            if restore_ok:
                checks["school_name_roundtrip"] = "PASS"
            elif result is not None:
                result["status"] = "FAIL"
                result["stage"] = "school_name_restore"
                result["error_type"] = "RestoreFailed"
        for slot, client in clients.items():
            try:
                if slot in csrf:
                    logout = client.post(
                        "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf[slot]}
                    )
                    logout_ok = logout.status_code in {200, 204}
                else:
                    logout_ok = not bool(client.cookies)
            except httpx.HTTPError:
                logout_ok = False
            try:
                client.close()
            except (OSError, RuntimeError):
                logout_ok = False
            checks[f"{slot}_session_cleanup"] = "PASS" if logout_ok else "FAIL"
            if not logout_ok and result is not None:
                result["status"] = "FAIL"
                result["stage"] = "session_cleanup"
                result["error_type"] = "SessionCleanupFailed"

    if result is None:
        result = _safe_result(
            None, checks, stage=stage, status="FAIL", error_type="UnknownFailure"
        )
    result["checks"] = checks
    try:
        artifact = workspace / f"school-directory-qa-{uuid4().hex}.json"
        _reject_reparse_path(artifact.parent)
        _reject_reparse_path(artifact, allow_missing_leaf=True)
        with artifact.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2))
        result["evidence_file"] = artifact.name
    except Exception as exc:  # noqa: BLE001 - do not emit filesystem detail.
        result["status"] = "FAIL"
        result["stage"] = "evidence_write"
        result["error_type"] = type(exc).__name__
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue the append-only run using the existing DPAPI-sealed QA state.",
    )
    args = parser.parse_args()
    for path in (
        REPO / "11_database" / ".venv" / "Lib" / "site-packages",
        REPO / "11_database",
        REPO / "09_backend" / "src",
        REPO / "13_deployment",
    ):
        sys.path.insert(0, str(path))
    try:
        result = run(args.workspace, resume=args.resume)
    except Exception as exc:  # noqa: BLE001 - emit only a stable safe result.
        result = {
            "schema_version": "psynova.school-directory-http-result.v1",
            "status": "FAIL",
            "stage": "session_cleanup"
            if isinstance(exc, SessionCleanupFailure)
            else "preflight",
            "checks": (
                {"initial_admin_session_cleanup": "FAIL"}
                if isinstance(exc, SessionCleanupFailure)
                else {}
            ),
            "error_type": type(exc).__name__,
        }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
