"""Exercise task-start authorization ordering against enrollment revocation.

This bounded QA uses only the owned synthetic school workspace. It creates one
synthetic class with two saved-CAT tasks and never emits identities, request
bodies, database rows, credentials, or exception messages.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://127.0.0.1:8088"
TABLES = (
    "assessment_sessions",
    "school_cat_session_bindings",
    "idempotency_records",
    "audit_events",
)
STAGES = (
    "owned_runtime_and_revision_gate",
    "admin_eligible_activation_metadata",
    "synthetic_task_setup",
    "revoke_commits_before_start",
    "start_scope_lock_blocks_revoke",
    "post_revoke_assessment_read_denied",
    "sessions_logged_out",
)
SAFE_ERRORS = frozenset(
    {
        "AssertionError",
        "AttributeError",
        "BackendError",
        "ConnectionError",
        "IntegrityError",
        "OperationalError",
        "OSError",
        "QaFailure",
        "ReadTimeout",
        "RuntimeError",
        "TimeoutError",
        "TimeoutException",
        "TypeError",
        "ValueError",
    }
)


class QaFailure(RuntimeError):
    """Fixed diagnostic; callers only expose this class name."""


def _require(condition: bool) -> None:
    if not condition:
        raise QaFailure("start/revocation invariant failed")


def _safe_result(
    *, status: str, stage: str, checks: dict[str, str], error_class: str | None = None
) -> dict[str, Any]:
    values = {key: "PASS" if checks.get(key) == "PASS" else "FAIL" for key in STAGES}
    result: dict[str, Any] = {
        "schema_version": "psynova.school-cat-start-revocation-qa.v1",
        "status": "PASS"
        if status == "PASS" and all(v == "PASS" for v in values.values())
        else "FAIL",
        "stage": stage if stage in STAGES or stage == "complete" else STAGES[0],
        "checks": values,
    }
    if error_class is not None:
        result["error_class"] = (
            error_class if error_class in SAFE_ERRORS else "OtherError"
        )
    return result


def _safe_error_class(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if name in SAFE_ERRORS else "OtherError"


async def _snapshot(
    persistence: Any,
) -> dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]]:
    """Exact, ordered projections for equality checks; never serialize rows."""
    await persistence.engine.dispose()
    output = {}
    async with persistence.engine.connect() as connection:
        for table in TABLES:
            result = await connection.exec_driver_sql(
                f"SELECT * FROM `{table}` ORDER BY id"
            )
            output[table] = (
                tuple(result.keys()),
                tuple(tuple(row) for row in result.fetchall()),
            )
    return output


def _contains_exact_reference(
    snapshot: dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]],
    table: str,
    column: str,
    value: str,
) -> bool:
    columns, rows = snapshot[table]
    if column not in columns:
        return False
    index = columns.index(column)
    return any(row[index] == value for row in rows)


def _has_prepared_audit(
    snapshot: dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]],
    *,
    assessment_ref: str,
    trace_id: str,
) -> bool:
    columns, rows = snapshot["audit_events"]
    required = {"action", "trace_id", "resource_type", "resource_public_id", "result"}
    if not required.issubset(columns):
        return False
    indexes = {key: columns.index(key) for key in required}
    return any(
        row[indexes["action"]] == "school_tasks.assessment_session.prepared"
        and row[indexes["trace_id"]] == trace_id
        and row[indexes["resource_type"]] == "assessment_session"
        and row[indexes["resource_public_id"]] == assessment_ref
        and row[indexes["result"]] == "SUCCESS"
        for row in rows
    )


def _eligible_activation_ref_from_client(client: Any) -> str:
    """Choose an eligible activation from the authenticated admin API list."""
    response = client.get(
        "/api/v1/school/cat-assets/activations",
        params={"limit": 100, "skip": 0},
    )
    _require(response.status_code == 200)
    envelope = response.json()
    payload = envelope.get("data") if isinstance(envelope, dict) else None
    rows = payload.get("items") if isinstance(payload, dict) else None
    eligible = [
        row
        for row in rows or []
        if isinstance(row, dict) and row.get("status") == "ACTIVE"
    ]
    _require(
        isinstance(payload, dict)
        and payload.get("engineering_only") is True
        and payload.get("psychological_interpretation_allowed") is False
        and bool(eligible)
        and isinstance(eligible[0].get("activation_ref"), str)
        and re.fullmatch(r"CACT_[A-Za-z0-9-]{36}", eligible[0]["activation_ref"])
        is not None
    )
    return eligible[0]["activation_ref"]


async def _run_start_then_revoke(
    start_operation,
    revoke_operation,
    *,
    lock_acquired: asyncio.Event,
    release_lock: asyncio.Event,
    revoke_entered: asyncio.Event,
    timeout_seconds: float = 25.0,
    blocked_window_seconds: float = 0.35,
) -> tuple[Any, Any]:
    """Hold the real scope guard, prove revoke waits, and always release it."""
    start_task = asyncio.create_task(start_operation())
    revoke_task: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(lock_acquired.wait(), timeout=timeout_seconds)

        async def marked_revoke():
            revoke_entered.set()
            return await revoke_operation()

        revoke_task = asyncio.create_task(marked_revoke())
        await asyncio.wait_for(revoke_entered.wait(), timeout=timeout_seconds)
        try:
            await asyncio.wait_for(
                asyncio.shield(revoke_task), timeout=blocked_window_seconds
            )
        except TimeoutError:
            pass
        else:
            raise QaFailure("revoke completed while the start scope lock was held")
    except BaseException:
        release_lock.set()
        for task in (start_task, revoke_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (start_task, revoke_task) if task is not None),
            return_exceptions=True,
        )
        raise
    finally:
        release_lock.set()
    start_result = await asyncio.wait_for(start_task, timeout=timeout_seconds)
    if revoke_task is None:
        raise QaFailure("revoke operation did not start")
    revoke_result = await asyncio.wait_for(revoke_task, timeout=timeout_seconds)
    return start_result, revoke_result


def _guard_instance_after_lock(
    persistence: Any,
    *,
    acquired: asyncio.Event,
    release: asyncio.Event,
    timeout: float = 25.0,
):
    """Wrap only this QA adapter instance; pause after the real DB locks are acquired."""
    original = persistence._lock_school_assessment_write_scope

    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        acquired.set()
        await asyncio.wait_for(release.wait(), timeout=timeout)
        return result

    persistence._lock_school_assessment_write_scope = gated

    def restore() -> None:
        persistence._lock_school_assessment_write_scope = original

    return restore


async def _login_and_recover(
    client: Any,
    persistence: Any,
    *,
    username: str,
    password: str,
    role_name: str,
    role: Any,
    school_ref: str,
) -> tuple[Any, str, str]:
    csrf: str | None = None
    try:
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        _require(response.status_code == 200)
        data = response.json().get("data")
        _require(isinstance(data, dict))
        projection = data.get("actor")
        csrf = data.get("csrf_token")
        _require(isinstance(projection, dict) and isinstance(csrf, str) and csrf)
        contexts = projection.get("available_contexts")
        _require(isinstance(contexts, list))
        matches = [
            row
            for row in contexts
            if isinstance(row, dict)
            and row.get("role") == role_name
            and row.get("school_ref") == school_ref
        ]
        _require(len(matches) == 1)
        selected = matches[0]
        active = client.post(
            "/api/v1/auth/active-context", json=selected, headers={"X-CSRF-Token": csrf}
        )
        _require(active.status_code == 200)
        current = client.get("/api/v1/auth/me")
        _require(current.status_code == 200)
        confirmed = current.json().get("data")
        if isinstance(confirmed, dict):
            confirmed = confirmed.get("actor", confirmed)
        _require(
            isinstance(confirmed, dict)
            and confirmed.get("user_id") == projection.get("user_id")
            and isinstance(confirmed.get("active_context"), dict)
            and confirmed["active_context"].get("role") == role_name
            and confirmed["active_context"].get("school_ref") == school_ref
        )
        import school_cat_assets_transaction_qa as asset_qa

        actor = await asset_qa._recover_persisted_actor(
            persistence,
            username=projection["username"],
            expected_user_id=projection["user_id"],
            selected_context=selected,
            role=role,
        )
        return actor, csrf, projection["user_id"]
    except BaseException:
        if csrf:
            try:
                client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
            except Exception:  # noqa: BLE001, S110 - never expose login cleanup details.
                pass
        raise


async def _logout(client: Any, csrf: str | None) -> None:
    if csrf:
        response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        _require(response.status_code in {200, 204})


async def _run_native(workspace: Path, run_id: str) -> dict[str, Any]:
    checks: dict[str, str] = {}
    stage = STAGES[0]
    error_class: str | None = None
    persistence = None
    http_clients: list[Any] = []
    admin_client = student_client = None
    private = None
    csrf_tokens: list[tuple[Any, str | None]] = []
    release_lock: asyncio.Event | None = None
    restore_guard = None
    secret = ""
    credentials: dict[str, Any] = {}
    try:
        import httpx
        import school_cat_assets_transaction_qa as asset_qa
        from private_settings import read_private
        from school_backend import load_runtime
        from school_browser_qa import validate_credentials
        from school_cat_assets_browser_qa import owned_cat
        from smhai_backend.adapters.database import MySqlBackendAdapter
        from smhai_backend.core.request_context import RequestContext, bound_context
        from smhai_backend.domains.models import BackendRole
        from smhai_backend.domains.school_tasks.service import task_ref_for_idempotency

        workspace, _marker = owned_cat.owned_workspace._verified_workspace()
        owned_cat.owned_workspace._inspect_application_listeners(workspace)
        _require(workspace.resolve(strict=True) == workspace)
        runtime = load_runtime(workspace, REPO)
        _require(
            runtime.get("database") == "smhai_school_demo"
            and runtime.get("port") == 3308
            and runtime.get("identity_profile") == "school_tenant"
        )
        secret = os.environ.get("SMHAI_SCHOOL_CSRF_SECRET", "")
        _require(re.fullmatch(r"[a-f0-9]{64}", secret) is not None)
        private = read_private(workspace / owned_cat.ACCOUNT_FILE)
        creds = validate_credentials(private)
        credentials = {
            key: dict(creds[key])
            for key in (
                "alpha.admin",
                "alpha.student",
            )
        }
        for item in creds.values():
            item["username"] = ""
            item["password"] = ""
        creds.clear()
        asset_qa._clear_private(private)
        private = None
        persistence = MySqlBackendAdapter(
            repository_root=REPO,
            identity_profile="school_tenant",
            school_csrf_secret=secret,
        )
        secret = ""
        asset_qa._clear_runtime_environment()
        await persistence._require_database_revision()
        checks[STAGES[0]] = "PASS"

        stage = STAGES[1]
        admin_client = httpx.Client(base_url=BACKEND_URL, timeout=30, trust_env=False)
        http_clients.append(admin_client)
        admin, admin_csrf, _ = await _login_and_recover(
            admin_client,
            persistence,
            username=credentials["alpha.admin"]["username"],
            password=credentials["alpha.admin"]["password"],
            role_name="ADMIN",
            role=BackendRole.ADMIN,
            school_ref=owned_cat.owned_workspace.SCHOOL_REF,
        )
        csrf_tokens.append((admin_client, admin_csrf))
        # The admin projection contains only activations whose parent bank and
        # plan remain eligible; an ACTIVE historical row alone is insufficient.
        # The admin API projection excludes activations whose parent bank or
        # plan is archived; an ACTIVE historical row alone is insufficient.
        activation_ref = _eligible_activation_ref_from_client(admin_client)
        checks[STAGES[1]] = "PASS"
        student_client = httpx.Client(base_url=BACKEND_URL, timeout=30, trust_env=False)
        http_clients.append(student_client)
        student, student_csrf, student_user_id = await _login_and_recover(
            student_client,
            persistence,
            username=credentials["alpha.student"]["username"],
            password=credentials["alpha.student"]["password"],
            role_name="STUDENT",
            role=BackendRole.STUDENT,
            school_ref=owned_cat.owned_workspace.SCHOOL_REF,
        )
        csrf_tokens.append((student_client, student_csrf))
        stage = STAGES[2]
        now = datetime.now(UTC).replace(tzinfo=None)
        class_ref = f"CLASS_START_REVOKE_QA_{run_id[:20]}"
        class_key = f"SYNTHETIC_START_REVOKE_QA_{run_id}_class"
        with bound_context(
            RequestContext(
                request_id=f"REQ_{run_id}_class", trace_id=f"TRACE_{run_id}_class"
            )
        ):
            await persistence.school_create_class(
                admin,
                class_ref,
                at=now,
                idempotency=asset_qa._idempotency(
                    admin, "class:create", class_key, {"class_ref": class_ref}
                ),
            )
        roster_key = f"SYNTHETIC_START_REVOKE_QA_{run_id}_roster"
        with bound_context(
            RequestContext(
                request_id=f"REQ_{run_id}_roster", trace_id=f"TRACE_{run_id}_roster"
            )
        ):
            await persistence.school_assign_student(
                admin,
                class_ref,
                student_user_id,
                at=now,
                idempotency=asset_qa._idempotency(
                    admin,
                    f"class:{class_ref}:student",
                    roster_key,
                    {"student_user_id": student_user_id},
                ),
            )

        opens_at = now - timedelta(minutes=1)
        due_at = now + timedelta(days=1)

        async def publish(label: str) -> tuple[str, str]:
            key = f"SYNTHETIC_START_REVOKE_QA_{run_id}_task_{label}"
            body = {
                "opens_at": opens_at.isoformat(),
                "due_at": due_at.isoformat(),
                "activation_ref": activation_ref,
            }
            idem = asset_qa._idempotency(
                admin, f"class:{class_ref}:task:publish", key, body
            )
            task_ref = task_ref_for_idempotency(admin, class_ref, key)
            trace = f"TRACE_{run_id}_publish_{label}"
            with bound_context(
                RequestContext(request_id=f"REQ_{run_id}_{label}", trace_id=trace)
            ):
                await persistence.school_publish_task(
                    admin,
                    class_ref,
                    task_ref,
                    opens_at=opens_at,
                    due_at=due_at,
                    activation_ref=activation_ref,
                    at=now,
                    idempotency=idem,
                )
            enrollments = await persistence.school_list_task_enrollments(
                admin, task_ref, at=now
            )
            _require(len(enrollments) == 1 and enrollments[0].get("status") == "ACTIVE")
            return task_ref, enrollments[0]["enrollment_ref"]

        task_a, enrollment_a = await publish("revoke_first")
        task_b, enrollment_b = await publish("start_first")
        checks[STAGES[2]] = "PASS"

        stage = STAGES[3]
        revoke_key_a = f"SYNTHETIC_START_REVOKE_QA_{run_id}_revoke_first"
        revoke_response = admin_client.post(
            f"/api/v1/school/tasks/{task_a}/enrollments/{enrollment_a}/revoke",
            headers={"X-CSRF-Token": admin_csrf, "Idempotency-Key": revoke_key_a},
        )
        _require(revoke_response.status_code == 200)
        before_denied_start = await _snapshot(persistence)
        denied_response = student_client.post(
            f"/api/v1/school/tasks/{task_a}/start",
            json={},
            headers={
                "X-CSRF-Token": student_csrf,
                "Idempotency-Key": f"SYNTHETIC_START_REVOKE_QA_{run_id}_revoked_start",
            },
        )
        _require(denied_response.status_code == 404)
        after_denied_start = await _snapshot(persistence)
        _require(before_denied_start == after_denied_start)
        checks[STAGES[3]] = "PASS"

        stage = STAGES[4]
        lock_acquired, revoke_entered = asyncio.Event(), asyncio.Event()
        release_lock = asyncio.Event()
        restore_guard = _guard_instance_after_lock(
            persistence, acquired=lock_acquired, release=release_lock
        )
        trace_b = f"TRACE_{run_id}_start_first"
        start_key_b = f"SYNTHETIC_START_REVOKE_QA_{run_id}_start_first"
        start_idem_b = asset_qa._idempotency(
            student, f"task:{task_b}:start", start_key_b, {"task_ref": task_b}
        )

        async def guarded_start():
            with bound_context(
                RequestContext(request_id=f"REQ_{run_id}_start_first", trace_id=trace_b)
            ):
                return await persistence.school_prepare_task_session(
                    student,
                    task_b,
                    f"ASSESS_{run_id}",
                    at=datetime.now(UTC).replace(tzinfo=None),
                    trace_id=trace_b,
                    idempotency=start_idem_b,
                )

        async def concurrent_revoke():
            return await persistence.school_revoke_enrollment(
                admin,
                task_b,
                enrollment_b,
                at=datetime.now(UTC).replace(tzinfo=None),
                idempotency=asset_qa._idempotency(
                    admin,
                    f"task:{task_b}:enrollment:{enrollment_b}:revoke",
                    f"SYNTHETIC_START_REVOKE_QA_{run_id}_revoke_after_start",
                    {"task_ref": task_b, "enrollment_ref": enrollment_b},
                ),
            )

        start_result, revoke_result = await _run_start_then_revoke(
            guarded_start,
            concurrent_revoke,
            lock_acquired=lock_acquired,
            release_lock=release_lock,
            revoke_entered=revoke_entered,
        )
        restore_guard()
        restore_guard = None
        _require(isinstance(start_result.get("assessment_id"), str))
        _require(revoke_result.get("status") == "REVOKED")
        _require(
            await persistence.school_list_task_enrollments(
                admin, task_b, at=datetime.now(UTC).replace(tzinfo=None)
            )
            == [{"enrollment_ref": enrollment_b, "status": "REVOKED"}]
        )
        committed = await _snapshot(persistence)
        assessment_ref = start_result["assessment_id"]
        _require(assessment_ref == f"ASSESS_{run_id}")
        _require(
            _contains_exact_reference(
                committed, "assessment_sessions", "assessment_ref", assessment_ref
            )
        )
        session_id = _session_id_from_snapshot(committed, assessment_ref)
        _require(session_id is not None)
        _require(
            _contains_exact_reference(
                committed,
                "school_cat_session_bindings",
                "assessment_session_id",
                session_id,
            )
        )
        _require(
            _contains_exact_reference(
                committed, "idempotency_records", "result_public_id", assessment_ref
            )
        )
        _require(
            _has_prepared_audit(
                committed, assessment_ref=assessment_ref, trace_id=trace_b
            )
        )
        checks[STAGES[4]] = "PASS"

        stage = STAGES[5]
        post_revoke = await persistence.school_get_assessment_for_actor(
            student, assessment_ref, at=datetime.now(UTC).replace(tzinfo=None)
        )
        _require(post_revoke is None)
        checks[STAGES[5]] = "PASS"

    except Exception as exc:  # noqa: BLE001 - only allowlisted class is exposed.
        error_class = _safe_error_class(exc)
    finally:
        result_stage = stage
        stage = STAGES[6]
        if release_lock is not None:
            release_lock.set()
        if restore_guard is not None:
            restore_guard()
        cleanup_ok = True
        for client, token in reversed(csrf_tokens):
            try:
                if token:
                    await _logout(client, token)
            except Exception:  # noqa: BLE001 - cleanup outcome only.
                cleanup_ok = False
        for client in http_clients:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - cleanup outcome only.
                cleanup_ok = False
        if persistence is not None:
            try:
                await persistence.engine.dispose()
            except Exception:  # noqa: BLE001 - cleanup outcome only.
                cleanup_ok = False
        if private is not None:
            try:
                import school_cat_assets_transaction_qa as asset_qa

                asset_qa._clear_private(private)
            except Exception:  # noqa: BLE001 - cleanup outcome only.
                cleanup_ok = False
        for value in credentials.values():
            value["username"] = ""
            value["password"] = ""
        credentials.clear()
        secret = ""
        if cleanup_ok:
            checks[STAGES[6]] = "PASS"
        elif error_class is None:
            error_class = "QaFailure"
    return _safe_result(
        status="PASS"
        if error_class is None and all(checks.get(key) == "PASS" for key in STAGES)
        else "FAIL",
        stage="complete" if error_class is None else result_stage,
        checks=checks,
        error_class=error_class,
    )


def _session_id_from_snapshot(
    snapshot: dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]],
    assessment_ref: str,
) -> int | None:
    columns, rows = snapshot["assessment_sessions"]
    if "assessment_ref" not in columns or "id" not in columns:
        return None
    ref_index, id_index = columns.index("assessment_ref"), columns.index("id")
    matches = [row[id_index] for row in rows if row[ref_index] == assessment_ref]
    return matches[0] if len(matches) == 1 else None


def run(workspace_arg: Path) -> dict[str, Any]:
    for path in (
        REPO / "11_database" / ".venv" / "Lib" / "site-packages",
        REPO / "11_database",
        REPO / "09_backend" / "src",
        REPO / "13_deployment",
    ):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    checks: dict[str, str] = {}
    try:
        from school_browser_qa import validate_workspace_path
        from school_cat_assets_browser_qa import owned_cat

        requested = validate_workspace_path(workspace_arg, REPO)
        _require(requested == owned_cat.WORKSPACE.resolve(strict=True))
        verified, _marker = owned_cat.owned_workspace._verified_workspace()
        _require(verified == requested)
        return asyncio.run(_run_native(requested, uuid4().hex))
    except Exception as exc:  # noqa: BLE001 - no raw diagnostic leaves this boundary.
        return _safe_result(
            status="FAIL",
            stage=STAGES[0],
            checks=checks,
            error_class=_safe_error_class(exc),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    result = run(parser.parse_args().workspace)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
