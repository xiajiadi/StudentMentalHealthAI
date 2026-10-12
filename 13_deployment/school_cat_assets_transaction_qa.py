"""Verify CAT asset UOW rollback with a process-local audit fault.

This harness is intentionally not run by tests. When invoked manually, it uses
the already-owned synthetic school workspace, authenticates a specialist over
the existing Backend, resolves that same persisted school actor, and calls the
real asset adapter plus CAT validator. It never starts or patches a live
service; AuditRepository.append is patched only in this Python process.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://127.0.0.1:8088"
CAT_ASSETS_URL = "http://127.0.0.1:8180"
SNAPSHOT_TABLES = (
    "school_cat_item_banks",
    "school_cat_item_bank_versions",
    "school_cat_plans",
    "school_cat_plan_versions",
    "idempotency_records",
    "audit_events",
)
STAGE_KEYS = (
    "workspace_and_manifest_gate",
    "runtime_revision_gate",
    "specialist_http_login_and_context",
    "persisted_actor_context_recovery",
    "real_cat_template_and_validation",
    "synthetic_setup_assets",
    "create_bank_audit_rollback",
    "create_bank_version_audit_rollback",
    "create_plan_version_audit_rollback",
    "ciphertext_projection_check",
    "session_cleanup",
)
CHECK_KEYS = STAGE_KEYS
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
    }
)


class QaFailure(RuntimeError):
    """A fixed invariant failure; exception text is never retained."""


class InjectedAuditFailure(RuntimeError):
    """Raised after the original audit append has flushed in this process."""


@dataclass(frozen=True, slots=True)
class TableProjection:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


def _require(condition: bool) -> None:
    if not condition:
        raise QaFailure("transaction invariant failed")


def _safe_error_class(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if name in SAFE_ERROR_CLASSES else "OtherError"


def _safe_result(
    *,
    status: str,
    stage: str,
    checks: dict[str, str],
    row_counts: dict[str, int] | None = None,
    error_class: str | None = None,
) -> dict[str, Any]:
    safe_checks = {
        name: "PASS" if checks.get(name) == "PASS" else "FAIL"
        for name in CHECK_KEYS
    }
    result: dict[str, Any] = {
        "schema_version": "psynova.school-cat-assets-transaction-qa.v1",
        "status": "PASS" if status == "PASS" and all(
            value == "PASS" for value in safe_checks.values()
        ) else "FAIL",
        "stage": stage if stage in STAGE_KEYS or stage == "complete" else "preflight",
        "checks": safe_checks,
    }
    if row_counts is not None:
        result["row_counts"] = {
            table: (
                row_counts[table]
                if type(row_counts.get(table)) is int and row_counts[table] >= 0
                else 0
            )
            for table in SNAPSHOT_TABLES
        }
    if error_class is not None:
        result["error_class"] = (
            error_class if error_class in SAFE_ERROR_CLASSES else "OtherError"
        )
    return result


def _preserve_result_on_evidence_failure(
    result: dict[str, Any], exc: BaseException
) -> dict[str, Any]:
    """Retain the transaction outcome even if its evidence file cannot be written."""
    error_class = _safe_error_class(exc)
    preserved = dict(result)
    if preserved.get("status") == "PASS":
        preserved["status"] = "FAIL"
        preserved["stage"] = "evidence_write"
        preserved["error_class"] = error_class
    else:
        preserved["evidence_write_error_class"] = error_class
    return preserved


def _write_evidence(
    workspace: Path,
    result: dict[str, Any],
    run_id: str,
    *,
    reject_reparse_path: Callable[[Path], None],
) -> Path:
    """Write safely below the verified workspace without replacing evidence."""
    root = workspace.resolve(strict=True)
    logs = workspace / "logs"
    reject_reparse_path(logs)
    logs_root = logs.resolve(strict=True)
    if not logs_root.is_relative_to(root):
        raise QaFailure("evidence directory escaped workspace")
    target = logs_root / f"cat-assets-transaction-qa-{run_id}.json"
    if target.exists():
        raise QaFailure("evidence file already exists")
    candidate = target.resolve(strict=False)
    if not candidate.is_relative_to(logs_root):
        raise QaFailure("evidence path escaped log directory")
    with target.open("x", encoding="utf-8") as stream:
        # The helper requires an existing leaf; check it after exclusive create.
        reject_reparse_path(target)
        resolved_target = target.resolve(strict=True)
        if resolved_target.parent != logs_root:
            raise QaFailure("evidence target changed during creation")
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return target


def _specialist_credentials(private: Any) -> tuple[str, str]:
    if not isinstance(private, dict) or private.get("recipe_version") != "school-contexts-v1":
        raise QaFailure("sealed specialist account unavailable")
    credentials = private.get("credentials")
    pair = credentials.get("alpha.psychological_specialist") if isinstance(credentials, dict) else None
    if not isinstance(pair, (tuple, list)) or len(pair) != 2:
        raise QaFailure("sealed specialist account unavailable")
    username, password = pair
    if (
        not isinstance(username, str)
        or re.fullmatch(r"SYNTHETIC_[A-Za-z0-9_]{1,100}", username) is None
        or not isinstance(password, str)
        or not 16 <= len(password) <= 512
    ):
        raise QaFailure("sealed specialist account unavailable")
    return username, password


def _clear_private(private: Any) -> None:
    if not isinstance(private, dict):
        return
    credentials = private.get("credentials")
    if isinstance(credentials, dict):
        for slot in tuple(credentials):
            credentials[slot] = ("", "")
        credentials.clear()
    private.clear()


def _select_specialist_context(actor_dto: Any, school_ref: str) -> dict[str, Any]:
    if not isinstance(actor_dto, dict) or not isinstance(actor_dto.get("user_id"), str):
        raise QaFailure("authenticated specialist projection unavailable")
    contexts = actor_dto.get("available_contexts")
    if not isinstance(contexts, list):
        raise QaFailure("authenticated specialist contexts unavailable")
    matches = [
        value for value in contexts
        if isinstance(value, dict)
        and value.get("role") == "PSYCHOLOGICAL_SPECIALIST"
        and value.get("school_ref") == school_ref
    ]
    if len(matches) != 1:
        raise QaFailure("active specialist school context unavailable")
    return matches[0]


async def _recover_persisted_actor(
    persistence: Any,
    *,
    username: str,
    expected_user_id: str,
    selected_context: dict[str, Any],
    role: Any,
) -> Any:
    """Resolve the real SyntheticUser actor so its context list is retained."""
    user = await persistence.get_by_username(username)
    _require(user is not None and user.user_id == expected_user_id)
    contexts = [
        context for context in user.school_contexts
        if context.role is role
        and context.school_ref == selected_context["school_ref"]
    ]
    _require(len(contexts) == 1)
    actor = user.actor(contexts[0].context_id)
    _require(
        actor is not None
        and actor.user_id == expected_user_id
        and actor.role is role
        and actor.scope_profile == "school_tenant"
        and actor.school_id == contexts[0].school_id
        and actor.school_ref == selected_context["school_ref"]
        and any(context.context_id == contexts[0].context_id for context in actor.school_contexts)
    )
    return actor


async def _snapshot_tables(persistence: Any) -> dict[str, TableProjection]:
    """Read exact ordered row projections on a fresh pooled connection."""
    await persistence.engine.dispose()
    projections: dict[str, TableProjection] = {}
    async with persistence.engine.connect() as connection:
        for table in SNAPSHOT_TABLES:
            result = await connection.exec_driver_sql(
                f"SELECT * FROM `{table}` ORDER BY id"
            )
            columns = tuple(result.keys())
            rows = tuple(tuple(row) for row in result.fetchall())
            projections[table] = TableProjection(columns=columns, rows=rows)
    return projections


def _row_counts(snapshot: dict[str, TableProjection]) -> dict[str, int]:
    return {table: len(snapshot[table].rows) for table in SNAPSHOT_TABLES}


def _ciphertext_is_nonplaintext(
    snapshot: dict[str, TableProjection], plaintext_markers: tuple[str, ...]
) -> bool:
    version_tables = (
        "school_cat_item_bank_versions",
        "school_cat_plan_versions",
    )
    saw_version = False
    forbidden_columns = {
        "bank_document", "config_document", "item_document", "stem", "parameters"
    }
    for table in version_tables:
        projection = snapshot[table]
        if forbidden_columns.intersection(projection.columns):
            return False
        if not {"payload_ciphertext", "cipher_format_version", "key_version", "payload_schema_version"}.issubset(
            projection.columns
        ):
            return False
        cipher_index = projection.columns.index("payload_ciphertext")
        saw_version = saw_version or bool(projection.rows)
        for row in projection.rows:
            ciphertext = row[cipher_index]
            if not isinstance(ciphertext, bytes) or not ciphertext:
                return False
            if any(marker.encode("utf-8") in ciphertext for marker in plaintext_markers):
                return False
    return saw_version


async def _expect_audit_failure_after_flush(
    audit_repository_type: type,
    *,
    trace_id: str,
    operation: Callable[[], Awaitable[Any]],
) -> None:
    """Patch only this process's audit repository and restore it unconditionally."""
    original_append = audit_repository_type.append
    hit = False

    async def append_then_fail(repository: Any, **kwargs: Any) -> Any:
        nonlocal hit
        record = await original_append(repository, **kwargs)
        if kwargs.get("trace_id") == trace_id:
            hit = True
            raise InjectedAuditFailure("fixed injected audit failure")
        return record

    audit_repository_type.append = append_then_fail
    try:
        try:
            await operation()
        except InjectedAuditFailure:
            _require(hit)
            return
        raise QaFailure("expected post-flush audit failure was not raised")
    finally:
        audit_repository_type.append = original_append


def _idempotency(actor: Any, operation: str, key: str, request: dict[str, Any]):
    from smhai_backend.core.idempotency import fingerprint

    scope = fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": operation,
        }
    )
    return key, fingerprint(request), scope


def _trace(run_id: str, suffix: str) -> str:
    return f"TRACE_CAT_ASSET_QA_{run_id}_{suffix}"


def _clear_runtime_environment() -> None:
    for key in tuple(os.environ):
        if key.upper().startswith(("DB_", "SMHAI_")) or key.upper() in {
            "DATABASE_URL", "DATABASE_KEY_FILE", "MYSQL_PWD",
        }:
            os.environ.pop(key, None)


async def _prepare_document(adapter: Any, actor: Any, bank_document: dict[str, Any], config_document: dict[str, Any] | None):
    validated = await adapter.school_cat_assets_validate(
        actor, bank_document, config_document=config_document
    )
    _require(validated.get("engineering_only") is True)
    _require(validated.get("psychological_interpretation_allowed") is False)
    return validated


async def _prepare_plan_document(
    adapter: Any, actor: Any, bank_version_ref: str, config_document: dict[str, Any]
) -> dict[str, Any]:
    validated = await adapter.school_cat_assets_validate_plan(
        actor, bank_version_ref, config_document
    )
    _require(isinstance(validated.get("config_document"), dict))
    return validated


async def _prepare_plan_documents(
    adapter: Any,
    actor: Any,
    bank_version_ref: str,
    config_documents: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Complete all CAT validation before any rollback baseline is captured."""
    validated: list[dict[str, Any]] = []
    for document in config_documents:
        validated.append(
            await _prepare_plan_document(adapter, actor, bank_version_ref, document)
        )
    return tuple(validated)


async def _inject_create_bank_failure(
    adapter: Any,
    audit_repository_type: type,
    persistence: Any,
    actor: Any,
    *,
    run_id: str,
    display_name: str,
    original_document: dict[str, Any],
    validated_document: dict[str, Any],
    sequence: str,
) -> dict[str, TableProjection]:
    before = await _snapshot_tables(persistence)
    trace_id = _trace(run_id, sequence)
    body = {"display_name": display_name, "bank_document": original_document}
    idem = _idempotency(
        actor, "school_cat_assets:create_bank", f"SYNTHETIC_CAT_ASSET_QA_{run_id}_{sequence}", body
    )

    async def invoke():
        return await adapter.school_cat_assets_create_bank(
            actor,
            display_name,
            validated_document["bank_document"],
            item_count=validated_document["item_count"],
            dimension_count=validated_document["dimension_count"],
            idempotency=idem,
            trace_id=trace_id,
        )

    await _expect_audit_failure_after_flush(
        audit_repository_type, trace_id=trace_id, operation=invoke
    )
    after = await _snapshot_tables(persistence)
    _require(before == after)
    return after


async def _inject_bank_version_failure(
    adapter: Any,
    audit_repository_type: type,
    persistence: Any,
    actor: Any,
    *,
    run_id: str,
    bank_ref: str,
    expected_revision: int,
    original_document: dict[str, Any],
    validated_document: dict[str, Any],
) -> dict[str, TableProjection]:
    before = await _snapshot_tables(persistence)
    trace_id = _trace(run_id, "rollback_bank_version")
    body = {"expected_revision": expected_revision, "bank_document": original_document}
    operation = f"school_cat_assets:create_bank_version:{bank_ref}"
    idem = _idempotency(
        actor, operation, f"SYNTHETIC_CAT_ASSET_QA_{run_id}_rollback_bank_version", body
    )

    async def invoke():
        return await adapter.school_cat_assets_create_bank_version(
            actor,
            bank_ref,
            expected_revision,
            validated_document["bank_document"],
            item_count=validated_document["item_count"],
            dimension_count=validated_document["dimension_count"],
            idempotency=idem,
            trace_id=trace_id,
        )

    await _expect_audit_failure_after_flush(
        audit_repository_type, trace_id=trace_id, operation=invoke
    )
    after = await _snapshot_tables(persistence)
    _require(before == after)
    return after


async def _inject_plan_version_failure(
    adapter: Any,
    audit_repository_type: type,
    persistence: Any,
    actor: Any,
    *,
    run_id: str,
    plan_ref: str,
    bank_version_ref: str,
    expected_revision: int,
    original_config: dict[str, Any],
    validated_config: dict[str, Any],
) -> dict[str, TableProjection]:
    before = await _snapshot_tables(persistence)
    trace_id = _trace(run_id, "rollback_plan_version")
    body = {
        "expected_revision": expected_revision,
        "bank_version_ref": bank_version_ref,
        "config_document": original_config,
    }
    operation = f"school_cat_assets:create_plan_version:{plan_ref}"
    idem = _idempotency(
        actor, operation, f"SYNTHETIC_CAT_ASSET_QA_{run_id}_rollback_plan_version", body
    )

    async def invoke():
        return await adapter.school_cat_assets_create_plan_version(
            actor,
            plan_ref,
            expected_revision,
            bank_version_ref,
            validated_config["config_document"],
            idempotency=idem,
            trace_id=trace_id,
        )

    await _expect_audit_failure_after_flush(
        audit_repository_type, trace_id=trace_id, operation=invoke
    )
    after = await _snapshot_tables(persistence)
    _require(before == after)
    return after


def _make_bank_document(template: dict[str, Any], *, marker: str) -> dict[str, Any]:
    from copy import deepcopy

    document = deepcopy(template)
    document["version"] = f"qa-{marker}"
    items = document.get("items")
    _require(isinstance(items, list) and bool(items))
    for index, item in enumerate(items):
        _require(isinstance(item, dict))
        item["item_id"] = f"ITEM_QA_{marker}_{index + 1}"
        if index == 0:
            item["stem"] = f"Synthetic CAT asset rollback marker {marker}"
    return document


async def _authenticate_specialist(client: Any, username: str, password: str, school_ref: str):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    _require(response.status_code == 200)
    data = response.json().get("data")
    _require(isinstance(data, dict))
    actor_dto = data.get("actor")
    csrf = data.get("csrf_token")
    _require(isinstance(csrf, str) and bool(csrf))
    selected = _select_specialist_context(actor_dto, school_ref)
    active = client.post(
        "/api/v1/auth/active-context",
        json=selected,
        headers={"X-CSRF-Token": csrf},
    )
    _require(active.status_code == 200)
    confirmation = client.get("/api/v1/auth/me")
    _require(confirmation.status_code == 200)
    confirmed = confirmation.json().get("data")
    if isinstance(confirmed, dict):
        confirmed = confirmed.get("actor", confirmed)
    _require(
        isinstance(confirmed, dict)
        and confirmed.get("user_id") == actor_dto.get("user_id")
        and isinstance(confirmed.get("active_context"), dict)
        and confirmed["active_context"].get("school_ref") == school_ref
        and confirmed["active_context"].get("role") == "PSYCHOLOGICAL_SPECIALIST"
    )
    return actor_dto, selected, csrf


async def _run_native_proof(workspace: Path, run_id: str) -> dict[str, Any]:
    checks = {key: "FAIL" for key in STAGE_KEYS}
    stage = STAGE_KEYS[0]
    row_counts: dict[str, int] | None = None
    persistence = None
    cat_client = None
    http_client = None
    csrf: str | None = None
    login_attempted = False
    username = ""
    password = ""
    secret = ""
    private: Any = None
    error_class: str | None = None
    try:
        from database_layer.repositories import AuditRepository
        from smhai_backend.adapters.database import MySqlBackendAdapter
        from smhai_backend.adapters.school_cat_assets import (
            SchoolCatAssetsPersistenceAdapter,
        )
        from smhai_backend.core.config import ModuleClientSettings
        from smhai_backend.domains.models import BackendRole
        from smhai_backend.integrations.cat_assets import HttpCatAssetsClient

        from private_settings import read_private
        from school_backend import load_runtime
        from school_cat_assets_browser_qa import owned_cat

        workspace, _marker = owned_cat.owned_workspace._verified_workspace()
        owned_cat.owned_workspace._inspect_application_listeners(workspace)
        _require(workspace.resolve(strict=True) == workspace)
        runtime = load_runtime(workspace, REPO)
        _require(
            runtime.get("database") == "smhai_school_demo"
            and runtime.get("port") == 3308
            and runtime.get("identity_profile") == "school_tenant"
        )
        checks[STAGE_KEYS[0]] = "PASS"

        stage = STAGE_KEYS[1]
        secret = os.environ.get("SMHAI_SCHOOL_CSRF_SECRET", "")
        _require(isinstance(secret, str) and re.fullmatch(r"[a-f0-9]{64}", secret) is not None)
        private = read_private(workspace / owned_cat.ACCOUNT_FILE)
        username, password = _specialist_credentials(private)
        _clear_private(private)
        private = None
        httpx = __import__("httpx")
        persistence = MySqlBackendAdapter(
            repository_root=REPO,
            identity_profile="school_tenant",
            school_csrf_secret=secret,
        )
        secret = ""
        _clear_runtime_environment()
        await persistence._require_database_revision()
        checks[STAGE_KEYS[1]] = "PASS"

        stage = STAGE_KEYS[2]
        http_client = httpx.Client(base_url=BACKEND_URL, timeout=30, trust_env=False)
        login_attempted = True
        actor_dto, selected_context, csrf = await _authenticate_specialist(
            http_client, username, password, owned_cat.owned_workspace.SCHOOL_REF
        )
        _require(actor_dto.get("username") == username)
        checks[STAGE_KEYS[2]] = "PASS"

        stage = STAGE_KEYS[3]
        actor = await _recover_persisted_actor(
            persistence,
            username=actor_dto["username"],
            expected_user_id=actor_dto["user_id"],
            selected_context=selected_context,
            role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        )
        username = ""
        password = ""
        await persistence._require_database_revision()
        checks[STAGE_KEYS[3]] = "PASS"

        stage = STAGE_KEYS[4]
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
        checks[STAGE_KEYS[4]] = "PASS"

        stage = STAGE_KEYS[5]
        marker_a = f"QA_{run_id[:12]}_A"
        marker_b = f"QA_{run_id[:12]}_B"
        marker_failed_create = f"QA_{run_id[:12]}_FAIL_CREATE"
        marker_failed_version = f"QA_{run_id[:12]}_FAIL_VERSION"
        marker_plan = f"QA_{run_id[:12]}_PLAN"
        original_bank_a = _make_bank_document(template["bank_document"], marker=marker_a)
        original_bank_b = _make_bank_document(template["bank_document"], marker=marker_b)
        original_failed_bank = _make_bank_document(
            template["bank_document"], marker=marker_failed_create
        )
        original_failed_version = _make_bank_document(
            template["bank_document"], marker=marker_failed_version
        )
        validated_bank_a = await _prepare_document(adapter, actor, original_bank_a, None)
        validated_bank_b = await _prepare_document(adapter, actor, original_bank_b, None)
        validated_failed_bank = await _prepare_document(adapter, actor, original_failed_bank, None)
        validated_failed_version = await _prepare_document(
            adapter, actor, original_failed_version, None
        )
        config_one = dict(template["config_document"])
        config_one["config_version"] = f"qa-{marker_plan}-one"
        config_two = dict(template["config_document"])
        config_two["config_version"] = f"qa-{marker_plan}-two"
        display_name = f"Synthetic rollback QA {run_id[:12]}"
        create_bank_body = {"display_name": display_name, "bank_document": original_bank_a}
        create_bank_idem = _idempotency(
            actor,
            "school_cat_assets:create_bank",
            f"SYNTHETIC_CAT_ASSET_QA_{run_id}_prepare_bank",
            create_bank_body,
        )
        bank_created = await adapter.school_cat_assets_create_bank(
            actor,
            display_name,
            validated_bank_a["bank_document"],
            item_count=validated_bank_a["item_count"],
            dimension_count=validated_bank_a["dimension_count"],
            idempotency=create_bank_idem,
            trace_id=_trace(run_id, "prepare_bank"),
        )
        bank_ref = bank_created["bank"]["bank_ref"]
        bank_v2_body = {"expected_revision": 1, "bank_document": original_bank_b}
        bank_v2_idem = _idempotency(
            actor,
            f"school_cat_assets:create_bank_version:{bank_ref}",
            f"SYNTHETIC_CAT_ASSET_QA_{run_id}_prepare_bank_version",
            bank_v2_body,
        )
        bank_v2_created = await adapter.school_cat_assets_create_bank_version(
            actor,
            bank_ref,
            1,
            validated_bank_b["bank_document"],
            item_count=validated_bank_b["item_count"],
            dimension_count=validated_bank_b["dimension_count"],
            idempotency=bank_v2_idem,
            trace_id=_trace(run_id, "prepare_bank_version"),
        )
        bank_v2_ref = bank_v2_created["version_ref"]
        validated_config_one, validated_config_two = await _prepare_plan_documents(
            adapter, actor, bank_v2_ref, (config_one, config_two)
        )
        plan_body = {
            "display_name": display_name,
            "bank_version_ref": bank_v2_ref,
            "config_document": config_one,
        }
        plan_idem = _idempotency(
            actor,
            "school_cat_assets:create_plan",
            f"SYNTHETIC_CAT_ASSET_QA_{run_id}_prepare_plan",
            plan_body,
        )
        plan_created = await adapter.school_cat_assets_create_plan(
            actor,
            display_name,
            bank_v2_ref,
            validated_config_one["config_document"],
            idempotency=plan_idem,
            trace_id=_trace(run_id, "prepare_plan"),
        )
        plan_ref = plan_created["plan"]["plan_ref"]
        checks[STAGE_KEYS[5]] = "PASS"

        stage = STAGE_KEYS[6]
        failed_bank_display_name = f"Synthetic rollback QA failed create {run_id[:12]}"
        bank_failure_snapshot = await _inject_create_bank_failure(
            adapter,
            AuditRepository,
            persistence,
            actor,
            run_id=run_id,
            display_name=failed_bank_display_name,
            original_document=original_failed_bank,
            validated_document=validated_failed_bank,
            sequence="rollback_bank_create",
        )
        row_counts = _row_counts(bank_failure_snapshot)
        checks[STAGE_KEYS[6]] = "PASS"

        stage = STAGE_KEYS[7]
        version_failure_snapshot = await _inject_bank_version_failure(
            adapter,
            AuditRepository,
            persistence,
            actor,
            run_id=run_id,
            bank_ref=bank_ref,
            expected_revision=2,
            original_document=original_failed_version,
            validated_document=validated_failed_version,
        )
        _require(bank_failure_snapshot == version_failure_snapshot)
        row_counts = _row_counts(version_failure_snapshot)
        checks[STAGE_KEYS[7]] = "PASS"

        stage = STAGE_KEYS[8]
        plan_failure_snapshot = await _inject_plan_version_failure(
            adapter,
            AuditRepository,
            persistence,
            actor,
            run_id=run_id,
            plan_ref=plan_ref,
            bank_version_ref=bank_v2_ref,
            expected_revision=1,
            original_config=config_two,
            validated_config=validated_config_two,
        )
        _require(version_failure_snapshot == plan_failure_snapshot)
        row_counts = _row_counts(plan_failure_snapshot)
        checks[STAGE_KEYS[8]] = "PASS"

        stage = STAGE_KEYS[9]
        ciphertext_snapshot = await _snapshot_tables(persistence)
        markers = (marker_a, marker_b, marker_plan)
        _require(_ciphertext_is_nonplaintext(ciphertext_snapshot, markers))
        _require(row_counts == _row_counts(ciphertext_snapshot))
        checks[STAGE_KEYS[9]] = "PASS"
        row_counts = _row_counts(ciphertext_snapshot)
    except Exception as exc:  # noqa: BLE001 - DB/HTTP errors may include private detail.
        error_class = _safe_error_class(exc)
    finally:
        failed_stage = stage
        stage = STAGE_KEYS[10]
        cleanup_failed = False
        if http_client is not None:
            try:
                if csrf is not None:
                    response = http_client.post(
                        "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
                    )
                    cleanup_failed = response.status_code not in {200, 204}
                elif login_attempted:
                    cleanup_failed = True
            except Exception:  # noqa: BLE001 - cleanup details may contain secrets.
                cleanup_failed = True
            try:
                http_client.close()
            except Exception:  # noqa: BLE001 - cleanup details may contain secrets.
                cleanup_failed = True
        if cat_client is not None:
            try:
                await cat_client.close()
            except Exception:  # noqa: BLE001 - cleanup details may contain secrets.
                cleanup_failed = True
        if persistence is not None:
            try:
                await persistence.engine.dispose()
            except Exception:  # noqa: BLE001 - cleanup details may contain secrets.
                cleanup_failed = True
        username = ""
        password = ""
        secret = ""
        csrf = None
        _clear_runtime_environment()
        if private is not None:
            try:
                _clear_private(private)
            except Exception:  # noqa: BLE001 - cleanup details may contain secrets.
                cleanup_failed = True
        checks[STAGE_KEYS[10]] = "FAIL" if cleanup_failed else "PASS"
    passed = error_class is None and all(value == "PASS" for value in checks.values())
    return _safe_result(
        status="PASS" if passed else "FAIL",
        stage="complete" if passed else STAGE_KEYS[10] if cleanup_failed else failed_stage,
        checks=checks,
        row_counts=row_counts,
        error_class=error_class,
    )


def run(workspace_arg: Path) -> dict[str, Any]:
    """Run the explicitly requested native proof; tests never call this."""
    run_id = uuid4().hex
    checks: dict[str, str] = {}
    stage = STAGE_KEYS[0]
    result: dict[str, Any] | None = None
    error_class: str | None = None
    evidence_workspace: Path | None = None
    try:
        for path in (
            REPO / "11_database" / ".venv" / "Lib" / "site-packages",
            REPO / "11_database",
            REPO / "09_backend" / "src",
            REPO / "13_deployment",
        ):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        from school_browser_qa import validate_workspace_path
        from school_cat_assets_browser_qa import owned_cat

        requested = validate_workspace_path(workspace_arg, REPO)
        _require(requested == owned_cat.WORKSPACE.resolve(strict=True))
        verified, _manifest = owned_cat.owned_workspace._verified_workspace()
        _require(verified == requested)
        evidence_workspace = verified
        result = asyncio.run(_run_native_proof(requested, run_id))
    except Exception as exc:  # noqa: BLE001 - native settings and DB diagnostics may be private.
        error_class = _safe_error_class(exc)
        result = _safe_result(
            status="FAIL", stage=stage, checks=checks, error_class=error_class
        )

    try:
        if result is None:
            result = _safe_result(
                status="FAIL", stage=stage, checks=checks, error_class="OtherError"
            )
        # The target is the exact externally-owned workspace verified above.
        if evidence_workspace is None:
            return result
        from school_cat_assets_browser_qa import owned_cat

        target = _write_evidence(
            evidence_workspace,
            result,
            run_id,
            reject_reparse_path=owned_cat.owned_workspace._reject_reparse_path,
        )
        result["evidence_file"] = target.name
    except Exception as exc:  # noqa: BLE001 - never emit filesystem details.
        result = _preserve_result_on_evidence_failure(result or {}, exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.workspace)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
