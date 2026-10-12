from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import school_cat_assets_transaction_qa as qa


class FakeRole:
    PSYCHOLOGICAL_SPECIALIST = object()


@dataclass
class FakeContext:
    context_id: str
    role: object
    school_id: int
    school_ref: str


class FakeUser:
    user_id = "USER_synthetic"
    username = "SYNTHETIC_SPECIALIST"
    school_contexts = (FakeContext("ROLECTX_real", FakeRole.PSYCHOLOGICAL_SPECIALIST, 7, "SCHOOL_A"),)

    def __init__(self):
        self.actor_context_ids: list[str | None] = []

    def actor(self, context_id=None):
        self.actor_context_ids.append(context_id)
        active = next((ctx for ctx in self.school_contexts if ctx.context_id == context_id), None)
        return type(
            "ActorProjection",
            (),
            {
                "user_id": self.user_id,
                "role": active.role if active else None,
                "scope_profile": "school_tenant",
                "school_id": active.school_id if active else None,
                "school_ref": active.school_ref if active else None,
                "school_contexts": self.school_contexts,
            },
        )()


def test_result_exposes_only_fixed_stages_counts_and_safe_error_class():
    checks = {key: "PASS" for key in qa.STAGE_KEYS}
    result = qa._safe_result(
        status="PASS",
        stage="complete",
        checks={**checks, "private_payload": "must not appear"},
        row_counts={table: 2 for table in qa.SNAPSHOT_TABLES},
        error_class="private details must not appear",
    )

    assert result["status"] == "PASS"
    assert set(result["checks"]) == set(qa.STAGE_KEYS)
    assert result["error_class"] == "OtherError"
    assert "private_payload" not in repr(result)
    assert "private details" not in repr(result)
    assert set(result["row_counts"]) == set(qa.SNAPSHOT_TABLES)


def test_specialist_secret_projection_and_source_clearing():
    private = {
        "recipe_version": "school-contexts-v1",
        "credentials": {
            "alpha.psychological_specialist": ["SYNTHETIC_SPECIALIST_A", "s" * 24],
            "alpha.admin": ["SYNTHETIC_ADMIN", "a" * 24],
        },
    }

    username, password = qa._specialist_credentials(private)
    qa._clear_private(private)

    assert username == "SYNTHETIC_SPECIALIST_A"
    assert password == "s" * 24
    assert private == {}


def test_specialist_context_selector_requires_exact_role_and_school():
    actor = {
        "user_id": "USER_synthetic",
        "available_contexts": [
            {"role": "ADMIN", "school_ref": "SCHOOL_A"},
            {
                "role": "PSYCHOLOGICAL_SPECIALIST",
                "school_ref": "SCHOOL_A",
            },
        ],
    }

    selected = qa._select_specialist_context(actor, "SCHOOL_A")
    assert selected == {
        "role": "PSYCHOLOGICAL_SPECIALIST",
        "school_ref": "SCHOOL_A",
    }
    assert "context_id" not in selected
    with pytest.raises(qa.QaFailure):
        qa._select_specialist_context(actor, "SCHOOL_B")


def test_actor_recovery_uses_persisted_user_actor_with_selected_context():
    user = FakeUser()

    class Persistence:
        async def get_by_username(self, username):
            assert username == user.username
            return user

    actor = asyncio.run(
        qa._recover_persisted_actor(
            Persistence(),
            username=user.username,
            expected_user_id=user.user_id,
            selected_context={"role": "PSYCHOLOGICAL_SPECIALIST", "school_ref": "SCHOOL_A"},
            role=FakeRole.PSYCHOLOGICAL_SPECIALIST,
        )
    )

    assert actor.school_id == 7
    assert actor.school_ref == "SCHOOL_A"
    assert actor.school_contexts == user.school_contexts
    assert user.actor_context_ids == ["ROLECTX_real"]


def test_evidence_write_uses_existing_leaf_guard_after_exclusive_create(tmp_path):
    workspace = tmp_path / "verified-workspace"
    logs = workspace / "logs"
    logs.mkdir(parents=True)
    checked = []

    def reject_reparse_path(path):
        assert path.exists()
        assert path.resolve().is_relative_to(workspace.resolve())
        checked.append(path)

    target = qa._write_evidence(
        workspace,
        {"status": "FAIL", "stage": "create_bank_audit_rollback"},
        "a" * 32,
        reject_reparse_path=reject_reparse_path,
    )

    assert target.parent == logs
    assert target.exists()
    assert checked == [logs, target]
    assert '"stage": "create_bank_audit_rollback"' in target.read_text(encoding="utf-8")


def test_evidence_write_failure_preserves_original_failure_and_stage(tmp_path):
    workspace = tmp_path / "verified-workspace"
    (workspace / "logs").mkdir(parents=True)

    def reject_with_error(_path):
        raise TypeError("private path diagnostic")

    original = {
        "status": "FAIL",
        "stage": "create_plan_version_audit_rollback",
        "error_class": "InjectedAuditFailure",
        "checks": {"create_plan_version_audit_rollback": "PASS"},
    }
    try:
        qa._write_evidence(
            workspace,
            original,
            "b" * 32,
            reject_reparse_path=reject_with_error,
        )
    except TypeError as exc:
        preserved = qa._preserve_result_on_evidence_failure(original, exc)
    else:
        raise AssertionError("expected safe evidence path check failure")

    assert preserved["stage"] == original["stage"]
    assert preserved["error_class"] == original["error_class"]
    assert preserved["evidence_write_error_class"] == "TypeError"
    assert "private path diagnostic" not in repr(preserved)


@pytest.mark.asyncio
async def test_plan_validations_finish_before_fault_snapshot_and_are_not_repeated(monkeypatch):
    events = []
    projection = {
        table: qa.TableProjection(columns=("id",), rows=())
        for table in qa.SNAPSHOT_TABLES
    }

    async def snapshot(_persistence):
        events.append("snapshot")
        return projection

    class FakeAdapter:
        async def school_cat_assets_validate_plan(self, _actor, _bank_version_ref, config):
            events.append(f"validate:{config['config_version']}")
            return {"config_document": dict(config)}

        async def school_cat_assets_create_plan_version(
            self, _actor, _plan_ref, _revision, _bank_ref, _config, *, trace_id, **_kwargs
        ):
            events.append("write")
            await FakeAuditRepository().append(trace_id=trace_id)

    class FakeAuditRepository:
        async def append(self, **kwargs):
            events.append("audit_append")
            return kwargs

    monkeypatch.setattr(qa, "_snapshot_tables", snapshot)
    monkeypatch.setattr(
        qa, "_idempotency", lambda *_args: ("synthetic-key", "synthetic-body", "synthetic-scope")
    )
    configs = (
        {"config_version": "qa.v1"},
        {"config_version": "qa.v2"},
    )
    validated = await qa._prepare_plan_documents(
        FakeAdapter(), object(), "CBVER_" + "a" * 36, configs
    )
    assert [item["config_document"] for item in validated] == list(configs)

    result = await qa._inject_plan_version_failure(
        FakeAdapter(),
        FakeAuditRepository,
        object(),
        object(),
        run_id="c" * 32,
        plan_ref="CPLAN_" + "b" * 36,
        bank_version_ref="CBVER_" + "a" * 36,
        expected_revision=1,
        original_config=configs[1],
        validated_config=validated[1],
    )

    assert tuple(result) == qa.SNAPSHOT_TABLES
    assert events == [
        "validate:qa.v1",
        "validate:qa.v2",
        "snapshot",
        "write",
        "audit_append",
        "snapshot",
    ]


def test_audit_patch_raises_only_after_original_append_and_restores_method():
    class FakeAuditRepository:
        def __init__(self):
            self.rows = []

        async def append(self, **kwargs):
            self.rows.append(dict(kwargs))
            return self.rows[-1]

    original = FakeAuditRepository.append
    repository = FakeAuditRepository()

    async def invoke():
        await repository.append(trace_id="TRACE_injected")

    asyncio.run(
        qa._expect_audit_failure_after_flush(
            FakeAuditRepository,
            trace_id="TRACE_injected",
            operation=invoke,
        )
    )

    assert repository.rows == [{"trace_id": "TRACE_injected"}]
    assert FakeAuditRepository.append is original


def test_audit_patch_is_restored_when_operation_fails_before_matching_append():
    class FakeAuditRepository:
        async def append(self, **_kwargs):
            raise ValueError("private error text")

    original = FakeAuditRepository.append

    async def invoke():
        await FakeAuditRepository().append(trace_id="TRACE_other")

    with pytest.raises(ValueError):
        asyncio.run(
            qa._expect_audit_failure_after_flush(
                FakeAuditRepository,
                trace_id="TRACE_target",
                operation=invoke,
            )
        )
    assert FakeAuditRepository.append is original


class FakeConnection:
    def __init__(self):
        self.tables = []

    async def exec_driver_sql(self, statement):
        table = statement.split("FROM `", maxsplit=1)[1].split("`", maxsplit=1)[0]
        self.tables.append(table)
        return FakeResult(table)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class FakeResult:
    def __init__(self, table):
        self.table = table

    def keys(self):
        return ("id", "payload_ciphertext") if "versions" in self.table else ("id",)

    def fetchall(self):
        return [(1, b"cipher")] if "versions" in self.table else [(1,)]


class FakeEngine:
    def __init__(self):
        self.disposed = 0
        self.connection = FakeConnection()

    async def dispose(self):
        self.disposed += 1

    def connect(self):
        return self.connection


class FakePersistence:
    def __init__(self):
        self.engine = FakeEngine()


def test_snapshot_reads_all_six_tables_in_allowlisted_order_on_disposed_engine():
    persistence = FakePersistence()
    snapshot = asyncio.run(qa._snapshot_tables(persistence))

    assert persistence.engine.disposed == 1
    assert tuple(snapshot) == qa.SNAPSHOT_TABLES
    assert tuple(persistence.engine.connection.tables) == qa.SNAPSHOT_TABLES
    assert snapshot["school_cat_item_bank_versions"].rows == ((1, b"cipher"),)


def test_ciphertext_check_rejects_plaintext_marker_and_document_columns():
    bank = qa.TableProjection(
        columns=("id", "payload_ciphertext", "cipher_format_version", "key_version", "payload_schema_version"),
        rows=((1, b"random-ciphertext", "f1", "k1", "school_cat_bank_document.v1"),),
    )
    plan = qa.TableProjection(
        columns=("id", "payload_ciphertext", "cipher_format_version", "key_version", "payload_schema_version"),
        rows=((1, b"random-ciphertext", "f1", "k1", "school_cat_config_document.v1"),),
    )
    snapshot = {
        "school_cat_item_bank_versions": bank,
        "school_cat_plan_versions": plan,
    }

    assert qa._ciphertext_is_nonplaintext(snapshot, ("SYNTHETIC_MARKER",))
    plaintext = dict(snapshot)
    plaintext["school_cat_item_bank_versions"] = qa.TableProjection(
        bank.columns,
        ((1, b"SYNTHETIC_MARKER", "f1", "k1", "school_cat_bank_document.v1"),),
    )
    assert not qa._ciphertext_is_nonplaintext(plaintext, ("SYNTHETIC_MARKER",))
