from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "11_database"))
sys.path.insert(0, str(REPO / "09_backend" / "src"))
import school_cat_binding_transaction_qa as qa
from smhai_backend.adapters.database import MySqlBackendAdapter


def test_safe_result_contains_only_fixed_aggregate_stages_and_error_classes():
    checks = {key: "PASS" for key in qa.CHECK_KEYS}
    result = qa._safe_result(
        status="PASS",
        stage="complete",
        checks={**checks, "private_payload": "must not appear"},
        error_class="private exception text",
    )

    assert result["status"] == "PASS"
    assert set(result["checks"]) == set(qa.CHECK_KEYS)
    assert result["error_class"] == "OtherError"
    assert "private_payload" not in repr(result)
    assert "private exception text" not in repr(result)


def test_missing_task_or_session_audit_call_is_detected_from_executable_ast():
    assert not qa._source_mentions_audit(
        "async def write():\n    await save_binding()\n"
    )
    assert qa._source_mentions_audit(
        "async def write():\n    await uow.audit.append(trace_id=trace_id)\n"
    )
    assert not qa._source_mentions_audit("async def write(:\n")


@pytest.mark.parametrize(
    "method_name",
    ["school_publish_task", "school_prepare_task_session"],
)
def test_actual_backend_write_methods_expose_uow_audit_append(method_name):
    method = getattr(MySqlBackendAdapter, method_name)

    assert qa._source_has_audit_hook(method)


def test_activation_rollback_diagnostics_allow_only_two_named_preflight_audits():
    audit_columns = (
        "id",
        "action",
        "trace_id",
        "result",
        "resource_type",
        "resource_public_id",
        "safe_metadata",
    )
    old_audit = (1, "old.action", "TRACE_OLD", "SUCCESS", "resource", None, {})
    before = {
        "school_cat_activations": (("id", "status"), ((1, "REVOKED"),)),
        "idempotency_records": (("id", "state"), ((4, "COMPLETED"),)),
        "audit_events": (audit_columns, (old_audit,)),
    }
    expected_audits = (
        (2, "school_cat_assets.activation_preflight", "TRACE_PREFLIGHT", "SUCCESS", "school_cat_assets", None, json.dumps({"source": "school_cat_assets", "state": "READ"})),
        (3, "school_cat_assets.activation_assets_validated", "TRACE_PREFLIGHT", "SUCCESS", "school_cat_assets", None, json.dumps({"source": "school_cat_assets", "state": "SUCCESS"})),
    )
    after = {
        **before,
        "audit_events": (audit_columns, (old_audit, *expected_audits)),
    }

    diagnostics = qa._activation_rollback_diagnostics(
        before,
        after,
        preflight_trace_id="TRACE_PREFLIGHT",
        transaction_trace_id="TRACE_TRANSACTION",
    )

    assert set(diagnostics) == {
        "activation_preflight_read_audit",
        "activation_preflight_network_audit",
        "activation_rows_unchanged",
        "activation_receipt_unchanged",
        "activation_transaction_audit_rollback",
    }
    assert set(diagnostics.values()) == {"PASS"}


def test_activation_rollback_diagnostics_reject_extra_audit_or_business_delta():
    audit_columns = (
        "id",
        "action",
        "trace_id",
        "result",
        "resource_type",
        "resource_public_id",
        "safe_metadata",
    )
    before = {
        "school_cat_activations": (("id",), ()),
        "idempotency_records": (("id",), ()),
        "audit_events": (audit_columns, ()),
    }
    after = {
        "school_cat_activations": (("id",), ((10,),)),
        "idempotency_records": (("id",), ()),
        "audit_events": (
            audit_columns,
            (
                (1, "school_cat_assets.activation_preflight", "TRACE_PREFLIGHT", "SUCCESS", "school_cat_assets", None, {"source": "school_cat_assets", "state": "READ"}),
                (2, "school_cat_assets.activation_assets_validated", "TRACE_PREFLIGHT", "SUCCESS", "school_cat_assets", None, {"source": "school_cat_assets", "state": "SUCCESS"}),
                (3, "school_cat_assets.activation_created", "TRACE_TRANSACTION", "SUCCESS", "school_cat_activation", "CACT_synthetic", {"source": "school_cat_assets", "state": "SUCCESS"}),
            ),
        ),
    }

    diagnostics = qa._activation_rollback_diagnostics(
        before,
        after,
        preflight_trace_id="TRACE_PREFLIGHT",
        transaction_trace_id="TRACE_TRANSACTION",
    )

    assert diagnostics["activation_rows_unchanged"] == "FAIL"
    assert diagnostics["activation_transaction_audit_rollback"] == "FAIL"


def test_audit_metadata_comparison_accepts_driver_json_without_emitting_it():
    read_metadata = {"source": "school_cat_assets", "state": "READ"}

    assert qa._audit_metadata_is(read_metadata, state="READ")
    assert qa._audit_metadata_is(json.dumps(read_metadata), state="READ")
    assert qa._audit_metadata_is(json.dumps(read_metadata).encode(), state="READ")
    assert not qa._audit_metadata_is(json.dumps(read_metadata), state="SUCCESS")


def test_audit_failure_is_injected_after_original_append_and_always_restored():
    class AuditRepository:
        def __init__(self):
            self.rows = []

        async def append(self, **kwargs):
            self.rows.append(dict(kwargs))
            return self.rows[-1]

    original = AuditRepository.append
    repository = AuditRepository()

    async def invoke():
        await repository.append(
            trace_id="TRACE_QA", action="school_cat_assets.activation_created"
        )

    asyncio.run(
        qa._expect_audit_failure(
            AuditRepository,
            trace_id="TRACE_QA",
            expected_action="school_cat_assets.activation_created",
            operation=invoke,
        )
    )

    assert repository.rows == [
        {"trace_id": "TRACE_QA", "action": "school_cat_assets.activation_created"}
    ]
    assert AuditRepository.append is original


def test_task_audit_injection_can_scope_to_one_operation_call():
    class AuditRepository:
        def __init__(self):
            self.rows = []

        async def append(self, **kwargs):
            self.rows.append(dict(kwargs))
            return self.rows[-1]

    repository = AuditRepository()

    async def invoke():
        await repository.append(
            trace_id="TRACE_TASK_STAGE", action="school_tasks.task.published"
        )

    asyncio.run(
        qa._expect_audit_failure(
            AuditRepository,
            trace_id="TRACE_TASK_STAGE",
            expected_action="school_tasks.task.published",
            operation=invoke,
        )
    )

    assert repository.rows == [
        {"trace_id": "TRACE_TASK_STAGE", "action": "school_tasks.task.published"}
    ]


def test_activation_concurrency_requires_exactly_one_success_and_one_conflict():
    class BackendError(Exception):
        code = object()

    conflict = BackendError()
    assert qa._activation_race_outcome([{"status": "ACTIVE"}, conflict], BackendError.code)
    assert not qa._activation_race_outcome([{"status": "ACTIVE"}, {"status": "ACTIVE"}], BackendError.code)
    assert not qa._activation_race_outcome([conflict, conflict], BackendError.code)


@pytest.mark.asyncio
async def test_audit_rollback_helper_does_not_accept_an_unhit_failpoint():
    class AuditRepository:
        async def append(self, **kwargs):
            return kwargs

    async def operation_without_audit():
        return None

    with pytest.raises(qa.QaFailure):
        await qa._expect_audit_failure(
            AuditRepository,
            trace_id="TRACE_NOT_REACHED",
            expected_action="school_tasks.assessment_session.prepared",
            operation=operation_without_audit,
        )
    assert AuditRepository.append.__name__ == "append"
