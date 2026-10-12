"""Prove school directory import rollback against the isolated MySQL workspace.

This harness creates only two uniquely named synthetic accounts in a single
request, injects a fixed audit failure after the import rows and idempotency
receipt have been flushed, then checks committed state through a fresh SQL
connection. It never starts or mutates the running HTTP service.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://127.0.0.1:8088"
RESULT_PREFIX = "school-directory-transaction-qa-"
RUN_PATTERN = re.compile(r"[a-f0-9]{32}\Z")


class QaFailure(RuntimeError):
    """An invariant failed; exception text is never written to evidence."""


class InjectedAuditFailure(RuntimeError):
    """Fixed fault injected at the school-directory audit boundary."""


def _require(condition: bool) -> None:
    if not condition:
        raise QaFailure("transaction invariant failed")


def _reject_reparse_path(path: Path, *, allow_missing_leaf: bool = False) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise QaFailure("external workspace path is invalid")
    cursor = Path(path.anchor)
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            attributes = getattr(cursor.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            raise QaFailure("external workspace path is unavailable") from None
        if attributes & 0x400:
            raise QaFailure("external workspace path is invalid")


def _safe_result(
    *,
    status: str,
    stage: str,
    checks: dict[str, str],
    counts: dict[str, int] | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "psynova.school-directory-transaction-qa.v1",
        "status": status,
        "stage": stage,
        "checks": dict(checks),
        "rows_attempted": 2,
    }
    if counts is not None:
        result["residual_counts"] = dict(counts)
    if error_type is not None:
        result["error_type"] = error_type
    return result


def _credentials(workspace: Path) -> tuple[str, str]:
    from private_settings import read_private

    account_file = workspace / "school-accounts.private.dpapi"
    _reject_reparse_path(account_file)
    stored = read_private(account_file)
    credentials = stored.get("credentials") if isinstance(stored, dict) else None
    admin = credentials.get("alpha.admin") if isinstance(credentials, dict) else None
    _require(isinstance(admin, (list, tuple)) and len(admin) == 2)
    username, password = admin
    _require(
        isinstance(username, str)
        and username.startswith("SYNTHETIC_")
        and isinstance(password, str)
        and len(password) >= 16
    )
    return username, password


def _post_login(
    client: Any, username: str, password: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
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
    admin_contexts = [
        item
        for item in contexts
        if isinstance(item, dict) and item.get("role") == "ADMIN"
    ]
    _require(len(admin_contexts) == 1)
    active = client.post(
        "/api/v1/auth/active-context",
        json=admin_contexts[0],
        headers={"X-CSRF-Token": csrf},
    )
    _require(active.status_code == 200)
    active_actor = active.json().get("data")
    _require(
        isinstance(active_actor, dict)
        and active_actor.get("user_id") == actor_dto.get("user_id")
        and active_actor.get("active_context") == admin_contexts[0]
    )
    return actor_dto, admin_contexts[0], csrf


async def _domain_actor(
    persistence: Any, actor_dto: dict[str, Any], selected_context: dict[str, Any]
) -> Any:
    from smhai_backend.domains.models import BackendRole

    user = await persistence.get_by_username(actor_dto["username"])
    _require(user is not None and user.user_id == actor_dto.get("user_id"))
    contexts = [
        context
        for context in user.school_contexts
        if context.role is BackendRole.ADMIN
        and context.school_ref == selected_context.get("school_ref")
    ]
    _require(len(contexts) == 1)
    actor = user.actor(contexts[0].context_id)
    _require(
        actor is not None
        and actor.scope_profile == "school_tenant"
        and actor.role is BackendRole.ADMIN
        and actor.school_id == contexts[0].school_id
        and actor.school_ref == contexts[0].school_ref
    )
    return actor


async def _inspect_committed_state(
    persistence: Any,
    *,
    usernames: list[str],
    batch_ref: str | None,
    idempotency_scope: str,
    idempotency_key: str,
) -> dict[str, int]:
    from sqlalchemy import func, select

    m = persistence._db_models
    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).digest()
    # Dispose pooled connections so this read necessarily checks out a new
    # physical connection after the import UOW has exited.
    await persistence.engine.dispose()
    async with persistence.session_factory() as session:
        account_count = await session.scalar(
            select(func.count(m.Account.id)).where(m.Account.login_name.in_(usernames))
        )
        batch_count = 0
        provision_count = await session.scalar(
            select(func.count(m.SchoolAccountProvision.id))
            .join(m.Account, m.Account.id == m.SchoolAccountProvision.account_id)
            .where(m.Account.login_name.in_(usernames))
        )
        membership_count = await session.scalar(
            select(func.count(m.AccountSchoolMembership.id))
            .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
            .where(m.Account.login_name.in_(usernames))
        )
        role_count = await session.scalar(
            select(func.count(m.MembershipRole.id))
            .join(
                m.AccountSchoolMembership,
                m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
            )
            .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
            .where(m.Account.login_name.in_(usernames))
        )
        if batch_ref is not None:
            batch_count = await session.scalar(
                select(func.count(m.SchoolAccountBatch.id)).where(
                    m.SchoolAccountBatch.batch_ref == batch_ref
                )
            )
        receipt_count = await session.scalar(
            select(func.count(m.IdempotencyRecord.id)).where(
                m.IdempotencyRecord.scope == idempotency_scope,
                m.IdempotencyRecord.key_hash == key_hash,
            )
        )
        audit_count = 0
        if batch_ref is not None:
            audit_count = await session.scalar(
                select(func.count(m.AuditEvent.id)).where(
                    m.AuditEvent.action == "school_directory.import_accounts",
                    m.AuditEvent.resource_public_id == batch_ref,
                )
            )
        return {
            "accounts": int(account_count or 0),
            "memberships": int(membership_count or 0),
            "membership_roles": int(role_count or 0),
            "batches": int(batch_count or 0),
            "provisions": int(provision_count or 0),
            "idempotency_receipts": int(receipt_count or 0),
            "import_audit_events": int(audit_count or 0),
        }


async def run(workspace_arg: Path) -> dict[str, Any]:
    import httpx
    from school_backend import load_runtime
    from school_browser_qa import validate_workspace_path
    from smhai_backend.adapters.database import MySqlBackendAdapter
    from smhai_backend.adapters.school_directory import (
        SchoolDirectoryPersistenceAdapter,
    )
    from smhai_backend.core.idempotency import fingerprint
    from smhai_backend.domains.school_directory.schemas import AccountImportRow
    from sqlalchemy.exc import SQLAlchemyError

    workspace = validate_workspace_path(workspace_arg, REPO)
    _reject_reparse_path(workspace_arg)
    _reject_reparse_path(workspace)
    _reject_reparse_path(workspace / "workspace.json")
    # load_runtime validates workspace ownership, private ACL, process identity,
    # schema revision and sealed runtime settings, then loads DB config to RAM.
    ready = load_runtime(workspace, REPO)
    _require(
        ready.get("database") == "smhai_school_demo"
        and ready.get("port") == 3308
        and ready.get("identity_profile") == "school_tenant"
    )
    csrf_secret = os.environ.get("SMHAI_SCHOOL_CSRF_SECRET")
    _require(
        isinstance(csrf_secret, str) and re.fullmatch(r"[a-f0-9]{64}", csrf_secret)
    )

    persistence = None
    client = None
    login_csrf: str | None = None
    login_attempted = False
    directory: SchoolDirectoryPersistenceAdapter | None = None
    original_audit = None
    captured: dict[str, str | None] = {"batch_ref": None}
    checks: dict[str, str] = {}
    stage = "runtime_ready"
    counts: dict[str, int] | None = None
    result: dict[str, Any] | None = None
    run_id = uuid4().hex
    usernames = [
        f"SYNTHETIC_TXN_STUDENT_{run_id[:16].upper()}",
        f"SYNTHETIC_TXN_TEACHER_{run_id[:16].upper()}",
    ]
    idem_key = f"SYNTHETIC_TXN_{run_id}"

    try:
        stage = "admin_http_auth"
        credentials = _credentials(workspace)
        client = httpx.Client(base_url=BACKEND_URL, timeout=30, trust_env=False)
        login_attempted = True
        actor_dto, selected_context, login_csrf = _post_login(client, *credentials)

        stage = "adapter_setup"
        persistence = MySqlBackendAdapter(
            repository_root=REPO,
            identity_profile="school_tenant",
            school_csrf_secret=csrf_secret,
        )
        del csrf_secret, credentials
        domain_actor = await _domain_actor(persistence, actor_dto, selected_context)
        _require(domain_actor.school_ref == selected_context["school_ref"])
        checks["http_and_persisted_admin_same_school"] = "PASS"

        stage = "baseline_absence"
        directory = SchoolDirectoryPersistenceAdapter(persistence)
        payload_rows = [
            {
                "row_no": 1,
                "login_name": usernames[0],
                "display_name": f"Txn Student {run_id[:8]}",
                "role": "student",
            },
            {
                "row_no": 2,
                "login_name": usernames[1],
                "display_name": f"Txn Teacher {run_id[:8]}",
                "role": "teacher",
            },
        ]
        rows = [AccountImportRow.model_validate(item) for item in payload_rows]
        request_payload = {"class_ref": None, "rows": payload_rows}
        idempotency_scope = fingerprint(
            {
                "actor": domain_actor.user_id,
                "school_id": domain_actor.school_id,
                "school_ref": domain_actor.school_ref,
                "role": domain_actor.role.value,
                "operation": "school_directory:account_import",
            }
        )
        idem_tuple = (idem_key, fingerprint(request_payload), idempotency_scope)
        counts = await _inspect_committed_state(
            persistence,
            usernames=usernames,
            batch_ref=None,
            idempotency_scope=idempotency_scope,
            idempotency_key=idem_key,
        )
        _require(all(value == 0 for value in counts.values()))
        checks["unique_synthetic_rows_absent_before_import"] = "PASS"

        stage = "inject_audit_failure"
        original_audit = directory._school_directory_audit

        async def fail_audit(
            uow,
            *,
            actor_account_id: int,
            action: str,
            resource_type: str,
            resource_public_id: str | None,
            trace_id: str,
            count: int = 1,
        ) -> None:
            del uow, actor_account_id, action, resource_type, trace_id, count
            captured["batch_ref"] = resource_public_id
            raise InjectedAuditFailure("injected fixed audit failure")

        directory._school_directory_audit = fail_audit
        try:
            await directory.school_directory_import_accounts(
                domain_actor,
                None,
                rows,
                idempotency=idem_tuple,
                trace_id=f"TRACE_{run_id}",
            )
        except InjectedAuditFailure:
            checks["audit_failure_injected_after_import_flush"] = "PASS"
        else:
            raise QaFailure("audit failure did not propagate")
        finally:
            directory._school_directory_audit = original_audit
            original_audit = None
        batch_ref = captured["batch_ref"]
        _require(
            isinstance(batch_ref, str)
            and re.fullmatch(r"BATCH_[a-f0-9]{32}", batch_ref)
        )

        stage = "fresh_connection_rollback_check"
        counts = await _inspect_committed_state(
            persistence,
            usernames=usernames,
            batch_ref=batch_ref,
            idempotency_scope=idempotency_scope,
            idempotency_key=idem_key,
        )
        _require(all(value == 0 for value in counts.values()))
        checks["business_rows_audit_and_receipt_rolled_back"] = "PASS"
        result = _safe_result(
            status="PASS", stage="complete", checks=checks, counts=counts
        )
    except Exception as exc:  # noqa: BLE001 - only stable class names are retained.
        result = _safe_result(
            status="FAIL",
            stage=stage,
            checks=checks,
            counts=counts,
            error_type=type(exc).__name__,
        )
    finally:
        if directory is not None and original_audit is not None:
            directory._school_directory_audit = original_audit
        cleanup_failed = False
        if client is not None:
            try:
                if login_csrf is not None:
                    logout = client.post(
                        "/api/v1/auth/logout",
                        headers={"X-CSRF-Token": login_csrf},
                    )
                    cleanup_failed = logout.status_code not in {200, 204}
                elif login_attempted:
                    cleanup_failed = True
            except (httpx.HTTPError, OSError, RuntimeError):
                cleanup_failed = True
            finally:
                try:
                    client.close()
                except (OSError, RuntimeError):
                    cleanup_failed = True
        if persistence is not None:
            try:
                await persistence.engine.dispose()
            except (SQLAlchemyError, OSError, RuntimeError):
                cleanup_failed = True
        if cleanup_failed and result is not None:
            result["status"] = "FAIL"
            result["stage"] = "cleanup"
            result["checks"]["session_cleanup"] = "FAIL"

    if result is None:
        result = _safe_result(
            status="FAIL",
            stage=stage,
            checks=checks,
            counts=counts,
            error_type="UnknownFailure",
        )
    if "session_cleanup" not in result["checks"]:
        result["checks"]["session_cleanup"] = (
            "SKIPPED_NO_SESSION" if client is None and not login_attempted else "PASS"
        )
    try:
        artifact = workspace / f"{RESULT_PREFIX}{run_id}.json"
        result["evidence_file"] = artifact.name
        _reject_reparse_path(artifact.parent)
        _reject_reparse_path(artifact, allow_missing_leaf=True)
        with artifact.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:  # noqa: BLE001 - filesystem details are not exposed.
        result["status"] = "FAIL"
        result["stage"] = "evidence_write"
        result["error_type"] = type(exc).__name__
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        REPO / "11_database" / ".venv" / "Lib" / "site-packages",
        REPO / "11_database",
        REPO / "09_backend" / "src",
        REPO / "13_deployment",
    ):
        sys.path.insert(0, str(path))
    try:
        result = asyncio.run(run(args.workspace))
    except Exception as exc:  # noqa: BLE001 - preflight details may contain private config.
        result = _safe_result(
            status="FAIL",
            stage="preflight",
            checks={},
            error_type=type(exc).__name__,
        )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
