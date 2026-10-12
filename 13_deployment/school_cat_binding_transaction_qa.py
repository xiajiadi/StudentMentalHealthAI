"""Verify synthetic CAT activation rollback and uniqueness on the owned MySQL workspace.

Task publication and session creation run only when their persistence methods
include an audit append in the same UOW. This prevents a missing fault hook from
committing QA task/session rows while claiming rollback evidence.
The harness reuses the CAT asset transaction QA's workspace, credential,
authentication, actor-recovery, idempotency, and evidence helpers.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://127.0.0.1:8088"
CAT_ASSETS_URL = "http://127.0.0.1:8180"
TABLES = (
    "school_cat_activations",
    "idempotency_records",
    "audit_events",
)
STAGE_KEYS = (
    "workspace_runtime_and_revision_gate",
    "specialist_login_and_persisted_actor",
    "synthetic_cat_assets_prepared",
    "activation_audit_failure_rollback",
    "activation_concurrent_uniqueness",
    "task_publish_audit_hook",
    "session_start_audit_hook",
    "session_cleanup",
)
DETAIL_KEYS = (
    "activation_preflight_read_audit",
    "activation_preflight_network_audit",
    "activation_fault_hook",
    "activation_rows_unchanged",
    "activation_receipt_unchanged",
    "activation_transaction_audit_rollback",
)
CHECK_KEYS = STAGE_KEYS + DETAIL_KEYS
SAFE_ERROR_CLASSES = frozenset(
    {
        "AssertionError",
        "ConnectionError",
        "InjectedAuditFailure",
        "IntegrityError",
        "OperationalError",
        "OSError",
        "QaFailure",
        "ReadTimeout",
        "RuntimeError",
        "TimeoutException",
        "TypeError",
        "ValueError",
        "MissingAuditHook",
        "BackendError",
    }
)


class QaFailure(RuntimeError):
    """Fixed safe failure; exception messages are never emitted."""


class InjectedAuditFailure(RuntimeError):
    """Raised after the original audit append has flushed in this process."""


def _require(condition: bool) -> None:
    if not condition:
        raise QaFailure("transaction invariant failed")


def _safe_error_class(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if name in SAFE_ERROR_CLASSES else "OtherError"


def _safe_result(
    *, status: str, stage: str, checks: dict[str, str], error_class: str | None = None
) -> dict[str, Any]:
    safe_checks = {key: "PASS" if checks.get(key) == "PASS" else "FAIL" for key in CHECK_KEYS}
    result: dict[str, Any] = {
        "schema_version": "psynova.school-cat-binding-transaction-qa.v1",
        "status": "PASS"
        if status == "PASS" and all(value == "PASS" for value in safe_checks.values())
        else "FAIL",
        "stage": stage if stage in STAGE_KEYS or stage == "complete" else "preflight",
        "checks": safe_checks,
    }
    if error_class is not None:
        result["error_class"] = (
            error_class if error_class in SAFE_ERROR_CLASSES else "OtherError"
        )
    return result


def _activation_race_outcome(results: list[Any], workflow_conflict: Any) -> bool:
    successes = [item for item in results if isinstance(item, dict)]
    conflicts = [
        item for item in results
        if isinstance(item, BaseException) and getattr(item, "code", None) is workflow_conflict
    ]
    return len(results) == 2 and len(successes) == 1 and len(conflicts) == 1


async def _snapshot(
    persistence: Any, tables: tuple[str, ...] = TABLES
) -> dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]]:
    """Capture exact ordered projections for rollback comparison, never output rows."""
    await persistence.engine.dispose()
    values = {}
    async with persistence.engine.connect() as connection:
        for table in tables:
            result = await connection.exec_driver_sql(f"SELECT * FROM `{table}` ORDER BY id")
            values[table] = (tuple(result.keys()), tuple(tuple(row) for row in result.fetchall()))
    return values


def _activation_rollback_diagnostics(
    before: dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]],
    after: dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]],
    *,
    preflight_trace_id: str,
    transaction_trace_id: str,
) -> dict[str, str]:
    """Allow only the two precisely identified, committed preflight audit rows."""
    activation_unchanged = before["school_cat_activations"] == after["school_cat_activations"]
    receipt_unchanged = before["idempotency_records"] == after["idempotency_records"]
    before_columns, before_rows = before["audit_events"]
    after_columns, after_rows = after["audit_events"]
    required_columns = {
        "id",
        "action",
        "trace_id",
        "result",
        "resource_type",
        "resource_public_id",
        "safe_metadata",
    }
    audit_schema_same = before_columns == after_columns and required_columns.issubset(
        after_columns
    )
    existing_audit_unchanged = False
    added_rows: list[tuple[Any, ...]] = []
    preflight_read_count = 0
    preflight_network_count = 0
    transaction_audit_count = 0
    if audit_schema_same:
        id_index = after_columns.index("id")
        before_by_id = {row[id_index]: row for row in before_rows}
        after_by_id = {row[id_index]: row for row in after_rows}
        existing_audit_unchanged = all(
            after_by_id.get(row_id) == row for row_id, row in before_by_id.items()
        )
        added_rows = [row for row in after_rows if row[id_index] not in before_by_id]
        action_index = after_columns.index("action")
        trace_index = after_columns.index("trace_id")
        result_index = after_columns.index("result")
        resource_type_index = after_columns.index("resource_type")
        resource_ref_index = after_columns.index("resource_public_id")
        metadata_index = after_columns.index("safe_metadata")
        for row in added_rows:
            action = row[action_index]
            trace_id = row[trace_index]
            expected = (
                trace_id == preflight_trace_id
                and row[result_index] == "SUCCESS"
                and row[resource_type_index] == "school_cat_assets"
                and row[resource_ref_index] is None
            )
            if action == "school_cat_assets.activation_preflight":
                preflight_read_count += int(
                    expected
                    and _audit_metadata_is(
                        row[metadata_index], state="READ"
                    )
                )
            elif action == "school_cat_assets.activation_assets_validated":
                preflight_network_count += int(
                    expected
                    and _audit_metadata_is(row[metadata_index], state="SUCCESS")
                )
            if (
                action == "school_cat_assets.activation_created"
                and trace_id == transaction_trace_id
            ):
                transaction_audit_count += 1
    only_expected_preflight_rows = len(added_rows) == 2 and (
        preflight_read_count == 1 and preflight_network_count == 1
    )
    return {
        "activation_preflight_read_audit": (
            "PASS" if audit_schema_same and existing_audit_unchanged and preflight_read_count == 1 else "FAIL"
        ),
        "activation_preflight_network_audit": (
            "PASS" if audit_schema_same and existing_audit_unchanged and preflight_network_count == 1 else "FAIL"
        ),
        "activation_rows_unchanged": "PASS" if activation_unchanged else "FAIL",
        "activation_receipt_unchanged": "PASS" if receipt_unchanged else "FAIL",
        "activation_transaction_audit_rollback": (
            "PASS"
            if audit_schema_same
            and existing_audit_unchanged
            and only_expected_preflight_rows
            and transaction_audit_count == 0
            else "FAIL"
        ),
    }


def _audit_metadata_is(value: Any, *, state: str) -> bool:
    expected = {"source": "school_cat_assets", "state": state}
    if isinstance(value, dict):
        return value == expected
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            return json.loads(value) == expected
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return False


async def _expect_audit_failure(
    audit_repository_type: type,
    *,
    trace_id: str,
    operation: Callable[[], Awaitable[Any]],
    expected_action: str,
) -> dict[str, Any]:
    original_append = audit_repository_type.append
    hit = False

    async def append_then_fail(repository: Any, **kwargs: Any) -> Any:
        nonlocal hit
        record = await original_append(repository, **kwargs)
        if kwargs.get("trace_id") == trace_id and kwargs.get("action") == expected_action:
            hit = True
            raise InjectedAuditFailure("fixed injected audit failure")
        return record

    audit_repository_type.append = append_then_fail
    try:
        try:
            await operation()
        except InjectedAuditFailure:
            _require(hit)
            return {"hit": True, "action_matched": True}
        raise QaFailure("expected post-flush audit failure was not raised")
    finally:
        audit_repository_type.append = original_append


def _source_has_audit_hook(method: Callable[..., Any]) -> bool:
    import inspect

    try:
        source = inspect.getsource(method)
    except (OSError, TypeError, SyntaxError):
        return False
    return _source_mentions_audit(source)


async def _login_and_recover_actor(
    client: Any,
    persistence: Any,
    *,
    username: str,
    password: str,
    role_name: str,
    role: Any,
    school_ref: str,
) -> tuple[Any, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    _require(response.status_code == 200)
    data = response.json().get("data")
    _require(isinstance(data, dict))
    actor_dto = data.get("actor")
    csrf = data.get("csrf_token")
    _require(isinstance(actor_dto, dict) and isinstance(csrf, str) and bool(csrf))
    contexts = actor_dto.get("available_contexts")
    _require(isinstance(contexts, list))
    matches = [
        item for item in contexts
        if isinstance(item, dict)
        and item.get("role") == role_name
        and item.get("school_ref") == school_ref
    ]
    _require(len(matches) == 1)
    selected = matches[0]
    active = client.post(
        "/api/v1/auth/active-context", json=selected, headers={"X-CSRF-Token": csrf}
    )
    _require(active.status_code == 200)
    confirmed = client.get("/api/v1/auth/me")
    _require(confirmed.status_code == 200)
    projection = confirmed.json().get("data")
    if isinstance(projection, dict):
        projection = projection.get("actor", projection)
    _require(
        isinstance(projection, dict)
        and projection.get("user_id") == actor_dto.get("user_id")
        and isinstance(projection.get("active_context"), dict)
        and projection["active_context"].get("school_ref") == school_ref
        and projection["active_context"].get("role") == role_name
    )
    actor = await _recover_actor(
        persistence,
        username=actor_dto["username"],
        user_id=actor_dto["user_id"],
        selected_context=selected,
        role=role,
    )
    return actor, csrf


async def _recover_actor(
    persistence: Any, *, username: str, user_id: str, selected_context: dict[str, Any], role: Any
) -> Any:
    import school_cat_assets_transaction_qa as asset_qa

    return await asset_qa._recover_persisted_actor(
        persistence,
        username=username,
        expected_user_id=user_id,
        selected_context=selected_context,
        role=role,
    )


def _source_mentions_audit(source: str) -> bool:
    import textwrap

    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = ast.unparse(node.func).lower()
        if "audit" in target and target.endswith(".append"):
            return True
    return False


async def _run_native(workspace: Path, run_id: str) -> dict[str, Any]:
    checks = {key: "FAIL" for key in CHECK_KEYS}
    stage = STAGE_KEYS[0]
    error_class: str | None = None
    persistence = cat_client = http_client = None
    private = None
    username = password = secret = ""
    admin_username = admin_password = student_username = student_password = ""
    csrf = None
    login_attempted = False
    cleanup_failed = False
    try:
        import httpx
        import school_cat_assets_transaction_qa as asset_qa
        from database_layer.repositories import AuditRepository
        from private_settings import read_private
        from school_backend import load_runtime
        from school_browser_qa import validate_credentials
        from school_cat_assets_browser_qa import owned_cat
        from smhai_backend.adapters.database import MySqlBackendAdapter
        from smhai_backend.adapters.school_cat_assets import (
            SchoolCatAssetsPersistenceAdapter,
        )
        from smhai_backend.core.config import ModuleClientSettings
        from smhai_backend.core.errors import ErrorCode
        from smhai_backend.core.request_context import RequestContext, bound_context
        from smhai_backend.domains.models import BackendRole
        from smhai_backend.integrations.cat_assets import HttpCatAssetsClient

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
        credentials = validate_credentials(private)
        username = credentials["alpha.psychological_specialist"]["username"]
        password = credentials["alpha.psychological_specialist"]["password"]
        admin_username = credentials["alpha.admin"]["username"]
        admin_password = credentials["alpha.admin"]["password"]
        student_username = credentials["alpha.student"]["username"]
        student_password = credentials["alpha.student"]["password"]
        for credential in credentials.values():
            credential["username"] = ""
            credential["password"] = ""
        credentials.clear()
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
        checks[STAGE_KEYS[0]] = "PASS"

        stage = STAGE_KEYS[1]
        http_client = httpx.Client(base_url=BACKEND_URL, timeout=30, trust_env=False)
        login_attempted = True
        actor_dto, selected_context, csrf = await asset_qa._authenticate_specialist(
            http_client, username, password, owned_cat.owned_workspace.SCHOOL_REF
        )
        actor = await asset_qa._recover_persisted_actor(
            persistence,
            username=actor_dto["username"],
            expected_user_id=actor_dto["user_id"],
            selected_context=selected_context,
            role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        )
        username = password = ""
        await persistence._require_database_revision()
        checks[STAGE_KEYS[1]] = "PASS"

        stage = STAGE_KEYS[2]
        cat_client = HttpCatAssetsClient(
            ModuleClientSettings(mode="http", base_url=CAT_ASSETS_URL)
        )
        adapter = SchoolCatAssetsPersistenceAdapter(persistence, cat_client)
        template = await adapter.school_cat_assets_template(actor)
        _require(
            template.get("engineering_only") is True
            and template.get("psychological_interpretation_allowed") is False
            and isinstance(template.get("bank_document"), dict)
            and isinstance(template.get("config_document"), dict)
        )
        marker = f"BIND_QA_{run_id[:12]}"
        bank_document = asset_qa._make_bank_document(template["bank_document"], marker=marker)
        validated_bank = await asset_qa._prepare_document(adapter, actor, bank_document, None)
        display_name = f"Synthetic binding QA {run_id[:12]}"
        bank_body = {"display_name": display_name, "bank_document": bank_document}
        bank_created = await adapter.school_cat_assets_create_bank(
            actor,
            display_name,
            validated_bank["bank_document"],
            item_count=validated_bank["item_count"],
            dimension_count=validated_bank["dimension_count"],
            idempotency=asset_qa._idempotency(
                actor, "school_cat_assets:create_bank", f"SYNTHETIC_BIND_QA_{run_id}_bank", bank_body
            ),
            trace_id=asset_qa._trace(run_id, "setup_bank"),
        )
        bank_ref = bank_created["version_ref"]
        config_document = dict(template["config_document"])
        config_document["config_version"] = f"qa-{marker}"
        validated_plan = await asset_qa._prepare_plan_document(
            adapter, actor, bank_ref, config_document
        )
        plan_body = {"display_name": display_name, "bank_version_ref": bank_ref, "config_document": config_document}
        plan_created = await adapter.school_cat_assets_create_plan(
            actor,
            display_name,
            bank_ref,
            validated_plan["config_document"],
            idempotency=asset_qa._idempotency(
                actor, "school_cat_assets:create_plan", f"SYNTHETIC_BIND_QA_{run_id}_plan", plan_body
            ),
            trace_id=asset_qa._trace(run_id, "setup_plan"),
        )
        plan_version_ref = plan_created["version_ref"]
        checks[STAGE_KEYS[2]] = "PASS"

        stage = STAGE_KEYS[3]
        before = await _snapshot(persistence)
        trace = asset_qa._trace(run_id, "activation_rollback")
        preflight_trace = asset_qa._trace(run_id, "activation_preflight")
        activation_body = {"plan_version_ref": plan_version_ref}
        activation_idem = asset_qa._idempotency(
            actor,
            f"school_cat_assets:create_activation:{plan_version_ref}",
            f"SYNTHETIC_BIND_QA_{run_id}_activation_rollback",
            activation_body,
        )
        async def create_then_fail_activation():
            with bound_context(
                RequestContext(
                    request_id=asset_qa._trace(run_id, "activation_request"),
                    trace_id=preflight_trace,
                )
            ):
                await adapter.school_cat_assets_create_activation(
                    actor, plan_version_ref, idempotency=activation_idem, trace_id=trace
                )

        fault_evidence = await _expect_audit_failure(
            AuditRepository,
            trace_id=trace,
            expected_action="school_cat_assets.activation_created",
            operation=create_then_fail_activation,
        )
        checks["activation_fault_hook"] = (
            "PASS"
            if fault_evidence.get("hit") is True
            and fault_evidence.get("action_matched") is True
            else "FAIL"
        )
        after = await _snapshot(persistence)
        diagnostics = _activation_rollback_diagnostics(
            before,
            after,
            preflight_trace_id=preflight_trace,
            transaction_trace_id=trace,
        )
        checks.update(diagnostics)
        _require(all(diagnostics[key] == "PASS" for key in diagnostics))
        checks[STAGE_KEYS[3]] = "PASS"

        stage = STAGE_KEYS[4]
        async def create_activation(index: int):
            idem = asset_qa._idempotency(
                actor,
                f"school_cat_assets:create_activation:{plan_version_ref}",
                f"SYNTHETIC_BIND_QA_{run_id}_race_{index}",
                activation_body,
            )
            return await adapter.school_cat_assets_create_activation(
                actor,
                plan_version_ref,
                idempotency=idem,
                trace_id=asset_qa._trace(run_id, f"race_{index}"),
            )

        import asyncio as _asyncio

        race = await _asyncio.gather(
            create_activation(1), create_activation(2), return_exceptions=True
        )
        _require(_activation_race_outcome(race, ErrorCode.WORKFLOW_CONFLICT))
        activation_response = next(item for item in race if isinstance(item, dict))
        active_count = await _active_activation_count(persistence, actor.school_id, plan_version_ref)
        _require(active_count == 1)
        checks[STAGE_KEYS[4]] = "PASS"

        stage = STAGE_KEYS[5]
        task_hook = _source_has_audit_hook(MySqlBackendAdapter.school_publish_task)
        stage = STAGE_KEYS[6]
        session_hook = _source_has_audit_hook(MySqlBackendAdapter.school_prepare_task_session)
        if not task_hook or not session_hook:
            checks[STAGE_KEYS[5]] = "PASS" if task_hook else "FAIL"
            checks[STAGE_KEYS[6]] = "PASS" if session_hook else "FAIL"
            error_class = "MissingAuditHook"
        else:
            from datetime import UTC, datetime, timedelta

            from smhai_backend.core.request_context import RequestContext, bound_context
            from smhai_backend.domains.school_tasks.service import (
                task_ref_for_idempotency,
            )

            _require(csrf is not None)
            specialist_logout = http_client.post(
                "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
            )
            _require(specialist_logout.status_code in {200, 204})
            csrf = None
            admin_actor, admin_csrf = await _login_and_recover_actor(
                http_client,
                persistence,
                username=admin_username,
                password=admin_password,
                role_name="ADMIN",
                role=BackendRole.ADMIN,
                school_ref=owned_cat.owned_workspace.SCHOOL_REF,
            )
            csrf = admin_csrf
            admin_username = admin_password = ""
            now = datetime.now(UTC).replace(tzinfo=None)
            class_ref = f"CLASS_BIND_QA_{run_id[:20]}"
            class_key = f"SYNTHETIC_BIND_QA_{run_id}_class"
            await persistence.school_create_class(
                admin_actor,
                class_ref,
                at=now,
                idempotency=asset_qa._idempotency(
                    admin_actor,
                    "class:create",
                    class_key,
                    {"class_ref": class_ref},
                ),
            )
            logout_current = http_client.post(
                "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
            )
            _require(logout_current.status_code in {200, 204})
            csrf = None

            student_actor, student_csrf = await _login_and_recover_actor(
                http_client,
                persistence,
                username=student_username,
                password=student_password,
                role_name="STUDENT",
                role=BackendRole.STUDENT,
                school_ref=owned_cat.owned_workspace.SCHOOL_REF,
            )
            csrf = student_csrf
            student_username = student_password = ""
            roster_key = f"SYNTHETIC_BIND_QA_{run_id}_roster"
            await persistence.school_assign_student(
                admin_actor,
                class_ref,
                student_actor.user_id,
                at=now,
                idempotency=asset_qa._idempotency(
                    admin_actor,
                    f"class:{class_ref}:student",
                    roster_key,
                    {"student_user_id": student_actor.user_id},
                ),
            )
            opens_at = now - timedelta(minutes=1)
            due_at = now + timedelta(days=1)

            def publish_idempotency(key: str):
                body = {
                    "opens_at": opens_at.isoformat(),
                    "due_at": due_at.isoformat(),
                    "activation_ref": activation_response["activation"]["activation_ref"],
                }
                return asset_qa._idempotency(
                    admin_actor,
                    f"class:{class_ref}:task:publish",
                    key,
                    body,
                )

            async def publish_task(key: str, trace_id: str) -> str:
                task_ref = task_ref_for_idempotency(admin_actor, class_ref, key)
                context = RequestContext(
                    request_id=f"REQ_{run_id}_{key[-8:]}", trace_id=trace_id
                )
                with bound_context(context):
                    await persistence.school_publish_task(
                        admin_actor,
                        class_ref,
                        task_ref,
                        opens_at=opens_at,
                        due_at=due_at,
                        activation_ref=activation_response["activation"]["activation_ref"],
                        at=now,
                        idempotency=publish_idempotency(key),
                    )
                return task_ref

            stage = STAGE_KEYS[5]
            task_trace = asset_qa._trace(run_id, "task_publish_rollback")
            task_before = await _snapshot(persistence, _task_tables())
            task_key = f"SYNTHETIC_BIND_QA_{run_id}_task_rollback"
            await _expect_audit_failure(
                AuditRepository,
                trace_id=task_trace,
                expected_action="school_tasks.task.published",
                operation=lambda: publish_task(task_key, task_trace),
            )
            task_after = await _snapshot(persistence, _task_tables())
            _require(task_before == task_after)
            checks[STAGE_KEYS[5]] = "PASS"

            setup_task_key = f"SYNTHETIC_BIND_QA_{run_id}_task_setup"
            task_ref = await publish_task(
                setup_task_key, asset_qa._trace(run_id, "task_setup")
            )

            stage = STAGE_KEYS[6]
            session_trace = asset_qa._trace(run_id, "session_start_rollback")
            session_key = f"SYNTHETIC_BIND_QA_{run_id}_session_rollback"
            session_idem = asset_qa._idempotency(
                student_actor,
                f"task:{task_ref}:start",
                session_key,
                {"task_ref": task_ref},
            )
            session_before = await _snapshot(persistence, _session_tables())
            await _expect_audit_failure(
                AuditRepository,
                trace_id=session_trace,
                expected_action="school_tasks.assessment_session.prepared",
                operation=lambda: persistence.school_prepare_task_session(
                    student_actor,
                    task_ref,
                    f"ASSESS_{run_id}",
                    at=now,
                    trace_id=session_trace,
                    idempotency=session_idem,
                ),
            )
            session_after = await _snapshot(persistence, _session_tables())
            _require(session_before == session_after)
            checks[STAGE_KEYS[6]] = "PASS"
    except Exception as exc:  # noqa: BLE001 - details may include private runtime state.
        error_class = _safe_error_class(exc)
    finally:
        if http_client is not None:
            try:
                if csrf is not None:
                    response = http_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
                    cleanup_failed = response.status_code not in {200, 204}
                elif login_attempted:
                    cleanup_failed = True
            except Exception:  # noqa: BLE001 - never retain response details.
                cleanup_failed = True
            try:
                http_client.close()
            except Exception:  # noqa: BLE001
                cleanup_failed = True
        if cat_client is not None:
            try:
                await cat_client.close()
            except Exception:  # noqa: BLE001
                cleanup_failed = True
        if persistence is not None:
            try:
                await persistence.engine.dispose()
            except Exception:  # noqa: BLE001
                cleanup_failed = True
        username = password = secret = ""
        admin_username = admin_password = student_username = student_password = ""
        csrf = None
        try:
            for key in tuple(os.environ):
                if key.upper().startswith(("DB_", "SMHAI_")) or key.upper() in {
                    "DATABASE_URL", "DATABASE_KEY_FILE", "MYSQL_PWD"
                }:
                    os.environ.pop(key, None)
        except Exception:  # noqa: BLE001
            cleanup_failed = True
        if private is not None:
            try:
                import school_cat_assets_transaction_qa as asset_qa

                asset_qa._clear_private(private)
            except Exception:  # noqa: BLE001
                cleanup_failed = True
        checks["session_cleanup"] = "FAIL" if cleanup_failed else "PASS"
    passed = error_class is None and all(value == "PASS" for value in checks.values())
    return _safe_result(
        status="PASS" if passed else "FAIL",
        stage="complete" if passed else stage,
        checks=checks,
        error_class=error_class,
    )


async def _active_activation_count(persistence: Any, school_id: int, version_ref: str) -> int:
    from database_layer.models import SchoolCatActivation, SchoolCatPlanVersion

    public_id = version_ref.removeprefix("CPVER_")
    async with persistence.engine.connect() as connection:
        result = await connection.execute(
            persistence._select(SchoolCatActivation.id)
            .join(
                SchoolCatPlanVersion,
                SchoolCatPlanVersion.id == SchoolCatActivation.plan_version_id,
            )
            .where(
                SchoolCatActivation.school_id == school_id,
                SchoolCatActivation.status == "ACTIVE",
                SchoolCatPlanVersion.public_id == public_id,
            )
        )
        return len(result.all())


def _task_tables() -> tuple[str, ...]:
    return (
        "measurement_tasks",
        "task_enrollments",
        "school_cat_task_bindings",
        "idempotency_records",
        "audit_events",
    )


def _session_tables() -> tuple[str, ...]:
    return (
        "assessment_sessions",
        "school_cat_session_bindings",
        "idempotency_records",
        "audit_events",
    )


def run(workspace_arg: Path) -> dict[str, Any]:
    """Run only when explicitly invoked by the Controller against its owned workspace."""
    for path in (
        REPO / "11_database" / ".venv" / "Lib" / "site-packages",
        REPO / "11_database",
        REPO / "09_backend" / "src",
        REPO / "13_deployment",
    ):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    run_id = uuid4().hex
    stage = STAGE_KEYS[0]
    checks: dict[str, str] = {}
    try:
        from school_browser_qa import validate_workspace_path
        from school_cat_assets_browser_qa import owned_cat

        requested = validate_workspace_path(workspace_arg, REPO)
        _require(requested == owned_cat.WORKSPACE.resolve(strict=True))
        verified, _marker = owned_cat.owned_workspace._verified_workspace()
        _require(verified == requested)
        return asyncio.run(_run_native(requested, run_id))
    except Exception as exc:  # noqa: BLE001 - only safe class is returned.
        return _safe_result(
            status="FAIL",
            stage=stage,
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
