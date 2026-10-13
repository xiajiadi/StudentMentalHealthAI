from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.assessment.binding import D3_IDENTITY
from smhai_backend.domains.assessment.schemas import AssessmentDto
from smhai_backend.domains.assessment.service import AssessmentService
from smhai_backend.domains.cat_assets.schemas import ActivationListDto
from smhai_backend.domains.cat_assets.service import SchoolCatAssetService
from smhai_backend.domains.models import (
    Actor,
    AssessmentRecord,
    BackendRole,
    SchoolRoleContext,
)
from smhai_backend.integrations.cat import CatStart, HttpCatClient


class _Expr:
    def __and__(self, _other):
        return self


class _Column:
    def __eq__(self, _other):
        return _Expr()


class _Query:
    def __init__(self, model):
        self.model = model

    def where(self, *_args):
        return self

    def with_for_update(self):
        return self


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def scalar(self, query):
        return self.rows.get(query.model)


class _UnitOfWork:
    def __init__(self, rows):
        self.session = _Session(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _TaskBinding:
    school_id = _Column()
    task_id = _Column()


class _SessionBinding:
    school_id = _Column()
    assessment_session_id = _Column()


class _Activation:
    id = _Column()
    school_id = _Column()
    plan_version_id = _Column()


class _PlanVersion:
    id = _Column()
    school_id = _Column()


class _Plan:
    id = _Column()
    school_id = _Column()


class _BankVersion:
    id = _Column()
    school_id = _Column()


class _Bank:
    id = _Column()
    school_id = _Column()


class _AssessmentSession:
    id = _Column()
    assessment_ref = _Column()
    subject_id = _Column()
    task_enrollment_id = _Column()


def _adapter(rows):
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter._db_models = SimpleNamespace(
        SchoolCatTaskBinding=_TaskBinding,
        SchoolCatSessionBinding=_SessionBinding,
        SchoolCatActivation=_Activation,
        SchoolCatPlanVersion=_PlanVersion,
        SchoolCatPlan=_Plan,
        SchoolCatItemBankVersion=_BankVersion,
        SchoolCatItemBank=_Bank,
        AssessmentSession=_AssessmentSession,
    )
    adapter._select = _Query
    adapter._decrypt_school_cat_document = lambda _uow, row, _schema: row.document
    return adapter, _UnitOfWork(rows)


def _task(*, mode="SAVED_VERSION"):
    return SimpleNamespace(
        id=30,
        school_id=7,
        cat_binding_mode=mode,
        instrument_id=(D3_IDENTITY.instrument_id if mode == "FIXTURE" else "SYNTHETIC_CAT"),
        instrument_version=(
            D3_IDENTITY.instrument_version
            if mode == "FIXTURE"
            else "synthetic_item_bank.v1 / demo.v1"
        ),
        item_bank_version="demo.v1" if mode == "SAVED_VERSION" else None,
        config_version="config.synthetic.v3" if mode == "SAVED_VERSION" else None,
    )


def _actor(role: BackendRole):
    context = SchoolRoleContext(
        context_id="ROLECAT_synthetic",
        role=role,
        school_id=7,
        school_ref="SCHOOL_synthetic",
    )
    return Actor(
        user_id="USER_synthetic",
        username="synthetic-user",
        role=role,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=7,
        school_ref="SCHOOL_synthetic",
        school_contexts=(context,),
    )


def _binding_rows(*, session_status="IN_PROGRESS", activation_status="REVOKED"):
    bank_document = {
        "instrument_id": "SYNTHETIC_CAT",
        "version": "demo.v1",
        "metadata": {"instrument_version": "synthetic_item_bank.v1 / demo.v1"},
    }
    config_document = {"config_version": "config.synthetic.v3"}
    task_binding = SimpleNamespace(
        id=40,
        school_id=7,
        task_id=30,
        activation_id=50,
        plan_version_id=60,
    )
    session_binding = SimpleNamespace(
        id=70,
        public_id="synthetic-session-binding",
        school_id=7,
        assessment_session_id=80,
        task_enrollment_id=90,
        subject_id=100,
        task_id=30,
        task_binding_id=40,
        activation_id=50,
        plan_version_id=60,
    )
    activation = SimpleNamespace(
        id=50,
        public_id="synthetic-activation",
        school_id=7,
        plan_version_id=60,
        status=activation_status,
    )
    plan_version = SimpleNamespace(
        id=60,
        public_id="synthetic-plan-version",
        school_id=7,
        plan_id=110,
        bank_version_id=120,
        payload_ciphertext=b"encrypted",
        key_version="key-v1",
        cipher_format_version=1,
        payload_schema_version="school-cat-config.v1",
        document=config_document,
    )
    bank_version = SimpleNamespace(
        id=120,
        public_id="synthetic-bank-version",
        school_id=7,
        bank_id=130,
        payload_ciphertext=b"encrypted",
        key_version="key-v1",
        cipher_format_version=1,
        payload_schema_version="school-cat-bank.v1",
        document=bank_document,
    )
    return {
        _TaskBinding: task_binding,
        _SessionBinding: session_binding,
        _Activation: activation,
        _PlanVersion: plan_version,
        _Plan: SimpleNamespace(id=110, school_id=7, status="ARCHIVED"),
        _BankVersion: bank_version,
        _Bank: SimpleNamespace(id=130, school_id=7, status="ARCHIVED"),
    }, task_binding, session_binding, session_status


def _writer_fixture(*, mode="FIXTURE"):
    task = _task(mode=mode)
    db_record = SimpleNamespace(
        id=80,
        assessment_ref="ASSESS_synthetic_task",
        subject_id=100,
        task_enrollment_id=90,
        status="IN_PROGRESS",
        cat_binding_mode=mode,
    )
    enrollment = SimpleNamespace(id=90, school_id=7, subject_id=100)
    subject = SimpleNamespace(subject_ref="SUBJECT_synthetic")
    rows = {_AssessmentSession: db_record, _TaskBinding: None, _SessionBinding: None}
    saved_binding = saved_bank_document = saved_config_document = None
    if mode == "SAVED_VERSION":
        binding_rows, _task_binding, session_binding, _status = _binding_rows()
        rows.update(binding_rows)
        rows[_AssessmentSession] = db_record
        saved_binding = {
            "binding_ref": f"CSBIND_{session_binding.public_id}",
            "activation_ref": f"CACT_{rows[_Activation].public_id}",
            "plan_version_ref": f"CPVER_{rows[_PlanVersion].public_id}",
            "bank_version_ref": f"CBVER_{rows[_BankVersion].public_id}",
        }
        saved_bank_document = rows[_BankVersion].document
        saved_config_document = rows[_PlanVersion].document

    adapter, uow = _adapter(rows)

    async def get_session(_assessment_id):
        return db_record

    async def active_enrollment(**_kwargs):
        return enrollment

    uow.assessments = SimpleNamespace(get_session=get_session)
    uow.school_operations = SimpleNamespace(active_enrollment_for_assessment=active_enrollment)
    adapter.identity_profile = "school_tenant"
    adapter._db_not_found = LookupError
    adapter._uow = lambda: uow

    async def actor_role(_uow, _actor, role_code, _at, *, lock=False):
        assert role_code == "student" and lock is True
        return 1, 2

    async def lock_scope(_uow, _actor, _account_id, active, *, at):
        return active, task, subject

    saves = []

    async def save(*_args, **_kwargs):
        saves.append("saved")

    adapter._school_actor_role = actor_role
    adapter._lock_school_assessment_write_scope = lock_scope
    adapter._save_assessment_in_uow = save
    record = AssessmentRecord(
        assessment_id="ASSESS_synthetic_task",
        subject_id="SUBJECT_synthetic",
        assessment={
            "instrument": {
                "instrument_id": task.instrument_id,
                "version": task.instrument_version,
            },
            "status": "in_progress",
        },
        task_enrollment_id=90,
        cat_binding_mode=mode,
        cat_item_bank_version=("demo.v1" if mode == "SAVED_VERSION" else None),
        cat_config_version=("config.synthetic.v3" if mode == "SAVED_VERSION" else None),
        saved_binding=saved_binding,
        saved_bank_document=saved_bank_document,
        saved_config_document=saved_config_document,
    )
    return adapter, record, task, db_record, saves


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["task", "session"])
async def test_saved_task_session_binding_missing_fails_closed(missing):
    rows, _task_binding, _session_binding, _status = _binding_rows()
    if missing == "task":
        rows[_TaskBinding] = None
    else:
        rows[_SessionBinding] = None
    adapter, uow = _adapter(rows)

    with pytest.raises(BackendError) as caught:
        await adapter._school_task_assessment_binding(
            uow,
            SimpleNamespace(school_id=7),
            _task(),
            SimpleNamespace(id=90),
            SimpleNamespace(
                id=80,
                subject_id=100,
                status="IN_PROGRESS",
                cat_binding_mode="SAVED_VERSION",
            ),
            at=None,
        )

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_fixture_task_with_unexpected_saved_binding_fails_closed():
    rows, *_rest = _binding_rows()
    rows[_SessionBinding] = None
    adapter, uow = _adapter(rows)

    with pytest.raises(BackendError) as caught:
        await adapter._school_task_assessment_binding(
            uow,
            SimpleNamespace(school_id=7),
            _task(mode="FIXTURE"),
            SimpleNamespace(id=90),
            SimpleNamespace(
                id=80,
                subject_id=100,
                status="IN_PROGRESS",
                cat_binding_mode="FIXTURE",
            ),
            at=None,
        )

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "unexpected_version"),
    [
        ("item_bank_version", "unexpected-bank"),
        ("config_version", "unexpected-config"),
    ],
)
async def test_fixture_task_projection_rejects_pinned_version_columns(
    field_name, unexpected_version
):
    task = _task(mode="FIXTURE")
    setattr(task, field_name, unexpected_version)
    adapter, uow = _adapter({_TaskBinding: None})

    with pytest.raises(BackendError) as caught:
        await adapter._task_cat_binding_fields(uow, SimpleNamespace(school_id=7), task)

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_fixture_write_keeps_cat_runtime_versions_without_binding_them_to_task_columns():
    adapter, record, _task_row, _db_record, saves = _writer_fixture()
    session = CatStart(
        assessment_id=record.assessment_id,
        subject_id=record.subject_id,
        instrument_id=D3_IDENTITY.instrument_id,
        instrument_version=D3_IDENTITY.instrument_version,
        started_at="2026-10-13T00:00:00Z",
        current_item={"item_id": "ITEM_synthetic_2"},
        current_index=1,
        answered_count=1,
        administered_count=1,
        item_bank_version="demo.v1",
        config_version="demo.cat.v1",
        provider_version="synthetic-cat",
        cat_binding_mode="FIXTURE",
    )
    AssessmentService._apply_state(record, session)

    await adapter.school_save_assessment_for_actor(
        _actor(BackendRole.STUDENT),
        record,
        at=None,
        trace_id="TRACE_fixture_save",
    )

    assert record.cat_item_bank_version == "demo.v1"
    assert record.cat_config_version == "demo.cat.v1"
    assert record.cat_provider_version == "synthetic-cat"
    assert saves == ["saved"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", [ErrorCode.FORBIDDEN, ErrorCode.RESOURCE_NOT_FOUND])
async def test_write_scope_lock_failure_is_propagated_without_saving(error_code):
    adapter, record, _task_row, _db_record, saves = _writer_fixture()
    lock_calls = []

    async def reject_scope(*_args, **_kwargs):
        lock_calls.append("called")
        raise BackendError(error_code, detail="synthetic write scope unavailable")

    adapter._lock_school_assessment_write_scope = reject_scope

    with pytest.raises(BackendError) as caught:
        await adapter.school_save_assessment_for_actor(
            _actor(BackendRole.STUDENT),
            record,
            at=None,
            trace_id="TRACE_write_scope_rejected",
        )

    assert caught.value.code is error_code
    assert lock_calls == ["called"]
    assert saves == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "unexpected_version"),
    [
        ("item_bank_version", "unexpected-bank"),
        ("config_version", "unexpected-config"),
    ],
)
async def test_fixture_task_rejects_pinned_database_version_columns(field_name, unexpected_version):
    adapter, record, task, _db_record, saves = _writer_fixture()
    setattr(task, field_name, unexpected_version)

    with pytest.raises(BackendError) as caught:
        await adapter.school_save_assessment_for_actor(
            _actor(BackendRole.STUDENT),
            record,
            at=None,
            trace_id="TRACE_fixture_pinned_version",
        )

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert saves == []


@pytest.mark.asyncio
async def test_saved_version_write_requires_exact_pinned_item_and_config_versions():
    adapter, record, _task_row, _db_record, saves = _writer_fixture(mode="SAVED_VERSION")
    await adapter.school_save_assessment_for_actor(
        _actor(BackendRole.STUDENT),
        record,
        at=None,
        trace_id="TRACE_saved_versions_match",
    )
    assert saves == ["saved"]

    for field_name, wrong_version in (
        ("cat_item_bank_version", "other-bank"),
        ("cat_config_version", "other-config"),
    ):
        adapter, mismatched, _task_row, _db_record, rejected_saves = _writer_fixture(
            mode="SAVED_VERSION"
        )
        setattr(mismatched, field_name, wrong_version)
        with pytest.raises(BackendError) as caught:
            await adapter.school_save_assessment_for_actor(
                _actor(BackendRole.STUDENT),
                mismatched,
                at=None,
                trace_id=f"TRACE_saved_{field_name}",
            )
        assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
        assert rejected_saves == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("saved_bank_document", {"version": "other"}),
        ("saved_config_document", {"config_version": "other"}),
    ],
)
async def test_saved_version_write_rejects_changed_documents_mode_and_unknown_mode(
    field_name, changed_value
):
    adapter, record, _task_row, _db_record, saves = _writer_fixture(mode="SAVED_VERSION")
    setattr(record, field_name, changed_value)
    with pytest.raises(BackendError) as caught:
        await adapter.school_save_assessment_for_actor(
            _actor(BackendRole.STUDENT),
            record,
            at=None,
            trace_id="TRACE_saved_document_changed",
        )
    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert saves == []

    adapter, changed_mode, _task_row, db_record, mode_saves = _writer_fixture(mode="SAVED_VERSION")
    db_record.cat_binding_mode = "FIXTURE"
    with pytest.raises(BackendError) as caught:
        await adapter.school_save_assessment_for_actor(
            _actor(BackendRole.STUDENT),
            changed_mode,
            at=None,
            trace_id="TRACE_saved_mode_changed",
        )
    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert mode_saves == []

    adapter, unknown_mode, _task_row, _db_record, unknown_saves = _writer_fixture(mode="UNKNOWN")
    with pytest.raises(BackendError) as caught:
        await adapter.school_save_assessment_for_actor(
            _actor(BackendRole.STUDENT),
            unknown_mode,
            at=None,
            trace_id="TRACE_unknown_cat_mode",
        )
    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert unknown_saves == []


@pytest.mark.asyncio
async def test_in_progress_session_keeps_exact_binding_when_activation_and_assets_archived():
    rows, task_binding, session_binding, _status = _binding_rows()
    adapter, uow = _adapter(rows)
    actor = SimpleNamespace(school_id=7)
    enrollment = SimpleNamespace(id=90)
    session = SimpleNamespace(
        id=80,
        subject_id=100,
        status="IN_PROGRESS",
        cat_binding_mode="SAVED_VERSION",
    )

    context = await adapter._school_task_assessment_binding(
        uow, actor, _task(), enrollment, session, at=None
    )

    assert context["cat_binding_mode"] == "SAVED_VERSION"
    assert context["saved_binding"] == {
        "binding_ref": f"CSBIND_{session_binding.public_id}",
        "activation_ref": f"CACT_{rows[_Activation].public_id}",
        "plan_version_ref": f"CPVER_{rows[_PlanVersion].public_id}",
        "bank_version_ref": f"CBVER_{rows[_BankVersion].public_id}",
    }
    assert context["saved_bank_document"]["version"] == "demo.v1"
    assert context["saved_binding"] is not None
    assert context["saved_config_document"]["config_version"] == "config.synthetic.v3"
    assert task_binding.id == session_binding.task_binding_id


@pytest.mark.asyncio
async def test_created_session_requires_active_activation_and_asset_parents():
    rows, *_rest = _binding_rows(activation_status="REVOKED")
    adapter, uow = _adapter(rows)
    with pytest.raises(BackendError) as caught:
        await adapter._school_task_assessment_binding(
            uow,
            SimpleNamespace(school_id=7),
            _task(),
            SimpleNamespace(id=90),
            SimpleNamespace(
                id=80,
                subject_id=100,
                status="CREATED",
                cat_binding_mode="SAVED_VERSION",
            ),
            at=None,
        )
    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_saved_task_publish_keeps_instrument_and_item_bank_versions_distinct():
    class SchoolClass:
        id = _Column()
        school_id = _Column()
        class_ref = _Column()

    class Activation:
        id = _Column()
        public_id = _Column()
        school_id = _Column()
        status = _Column()
        plan_version_id = _Column()

    class PlanVersion:
        id = _Column()
        school_id = _Column()
        plan_id = _Column()
        bank_version_id = _Column()

    class Plan:
        id = _Column()
        school_id = _Column()
        status = _Column()

    class BankVersion:
        id = _Column()
        school_id = _Column()
        bank_id = _Column()

    class Bank:
        id = _Column()
        school_id = _Column()
        status = _Column()

    class TaskBinding:
        school_id = _Column()
        task_id = _Column()
        activation_id = _Column()
        plan_version_id = _Column()

        def __init__(self, **values):
            for key, value in values.items():
                setattr(self, key, value)

    now = "2026-10-13T00:00:00Z"
    activation = SimpleNamespace(
        id=50,
        public_id="b" * 36,
        school_id=7,
        status="ACTIVE",
        plan_version_id=60,
    )
    plan_version = SimpleNamespace(
        id=60,
        public_id="c" * 36,
        school_id=7,
        plan_id=110,
        bank_version_id=120,
        version_number=4,
        payload_ciphertext=b"ciphertext",
    )
    bank_document = {
        "instrument_id": "SYNTHETIC_CAT",
        "version": "demo.v1",
        "metadata": {"instrument_version": "synthetic_item_bank.v1 / demo.v1"},
    }
    config_document = {"config_version": "config.v7"}
    bank_version = SimpleNamespace(id=120, school_id=7, bank_id=130, document=bank_document)
    plan_version.document = config_document
    plan = SimpleNamespace(id=110, school_id=7, status="ACTIVE", display_name="Saved plan")
    bank = SimpleNamespace(id=130, school_id=7, status="ACTIVE", display_name="Saved bank")
    school_class = SimpleNamespace(id=20, school_id=7, class_ref="CLASS_synthetic")
    task = SimpleNamespace(
        id=30,
        public_id="d" * 36,
        task_ref="TASK_saved_synthetic",
        status="PUBLISHED",
        opens_at=None,
        due_at=None,
        published_at=now,
        instrument_id=None,
        instrument_version=None,
        item_bank_version=None,
        config_version=None,
    )
    rows = {
        SchoolClass: school_class,
        Activation: activation,
        PlanVersion: plan_version,
        Plan: plan,
        BankVersion: bank_version,
        Bank: bank,
    }
    class PublicationSession:
        def add(self, row):
            if isinstance(row, TaskBinding):
                rows[TaskBinding] = row

        async def scalar(self, query):
            return rows.get(query.model)

        async def flush(self):
            return None

    publication_uows = []

    class PublicationUow:
        def __init__(self):
            self.session = PublicationSession()
            self.audit_records = []
            publication_uows.append(self)

            async def append_audit(**values):
                self.audit_records.append(values)

            self.audit = SimpleNamespace(append=append_audit)

        async def __aenter__(self):
            self.school_operations = SimpleNamespace(
                publish_task_with_snapshot=lambda **kwargs: publish_snapshot(kwargs)
            )
            return self

        async def __aexit__(self, *_args):
            return False

    captured = {}

    async def publish_snapshot(kwargs):
        captured.update(kwargs)
        task.instrument_id = kwargs["instrument_id"]
        task.instrument_version = kwargs["instrument_version"]
        task.item_bank_version = kwargs["item_bank_version"]
        task.config_version = kwargs["config_version"]
        return SimpleNamespace(task=task, enrollment_count=2)

    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter._db_models = SimpleNamespace(
        SchoolClass=SchoolClass,
        SchoolCatActivation=Activation,
        SchoolCatPlanVersion=PlanVersion,
        SchoolCatPlan=Plan,
        SchoolCatItemBankVersion=BankVersion,
        SchoolCatItemBank=Bank,
        MeasurementTask=type("MeasurementTask", (), {}),
        SchoolCatTaskBinding=TaskBinding,
    )
    adapter._select = _Query
    adapter._uow = PublicationUow
    adapter._db_enums = SimpleNamespace(
        AuditResult=SimpleNamespace(SUCCESS="SUCCESS")
    )
    adapter._decrypt_school_cat_document = lambda _uow, row, _schema: row.document

    async def actor_role(_uow, _actor, role, _at):
        assert role == "admin"
        return 1, 2

    async def claim(_uow, _idempotency):
        return SimpleNamespace(replayed=False)

    async def complete(*_args, **_kwargs):
        return None

    adapter._school_actor_role = actor_role
    adapter._school_idempotency_begin = claim
    adapter._school_idempotency_complete = complete
    result = await adapter.school_publish_task(
        _actor(BackendRole.ADMIN),
        "CLASS_synthetic",
        "TASK_saved_synthetic",
        opens_at=None,
        due_at=None,
        at=now,
        activation_ref=f"CACT_{activation.public_id}",
        idempotency=("key", "f" * 64, "scope"),
    )

    expected_instrument_version = "synthetic_item_bank.v1 / demo.v1"
    assert captured["instrument_version"] == expected_instrument_version
    assert captured["item_bank_version"] == "demo.v1"
    assert captured["config_version"] == "config.v7"
    assert task.instrument_version == expected_instrument_version
    assert task.item_bank_version == "demo.v1"
    assert result["instrument_version"] == expected_instrument_version
    assert rows[TaskBinding].activation_id == activation.id
    assert rows[TaskBinding].plan_version_id == plan_version.id
    assert publication_uows[0].audit_records == [
        {
            "action": "school_tasks.task.published",
            "resource_type": "measurement_task",
            "resource_public_id": "TASK_saved_synthetic",
            "result": "SUCCESS",
            "trace_id": publication_uows[0].audit_records[0]["trace_id"],
            "actor_account_id": 1,
            "safe_metadata": {"source": "backend", "state": "PUBLISHED"},
        }
    ]
    assert publication_uows[0].audit_records[0]["trace_id"].startswith("TRACE_")


@pytest.mark.asyncio
async def test_saved_cat_start_posts_exact_binding_and_rejects_binding_mismatch(monkeypatch):
    client = object.__new__(HttpCatClient)
    binding = {
        "binding_ref": "CSBIND_" + "a" * 36,
        "activation_ref": "CACT_" + "b" * 36,
        "plan_version_ref": "CPVER_" + "c" * 36,
        "bank_version_ref": "CBVER_" + "d" * 36,
    }
    bank_document = {
        "instrument_id": "SYNTHETIC_CAT",
        "version": "demo.v1",
        "metadata": {"instrument_version": "synthetic_item_bank.v1 / demo.v1"},
    }
    config_document = {"config_version": "config.v1"}
    sent = {}

    async def post_json(path, body, *, context):
        sent.update(path=path, body=body, context=context)
        return {
            "assessment_id": "ASSESS_synthetic",
            "subject_id": "SUBJECT_synthetic",
            "cat_binding_mode": "SAVED_VERSION",
            "saved_binding": binding,
            "item_bank_version": bank_document["version"],
            "config_version": config_document["config_version"],
        }

    monkeypatch.setattr(client, "post_json", post_json)
    result = await client.start_saved_session(
        assessment_id="ASSESS_synthetic",
        subject_id="SUBJECT_synthetic",
        instrument_id="SYNTHETIC_CAT",
        instrument_version="synthetic_item_bank.v1 / demo.v1",
        binding=binding,
        bank_document=bank_document,
        config_document=config_document,
    )
    assert sent["path"] == "/internal/cat/saved-sessions"
    assert all(sent["body"][key] == value for key, value in binding.items())
    assert sent["body"]["bank_document"] == bank_document
    assert sent["body"]["config_document"] == config_document
    assert sent["body"]["instrument_version"] == "synthetic_item_bank.v1 / demo.v1"
    assert sent["body"]["bank_document"]["version"] == "demo.v1"
    assert result.item_bank_version == "demo.v1"
    assert result.cat_binding_mode == "SAVED_VERSION"
    assert result.saved_binding == binding

    async def mismatched(*_args, **_kwargs):
        return {
            "assessment_id": "ASSESS_synthetic",
            "subject_id": "SUBJECT_synthetic",
            "cat_binding_mode": "SAVED_VERSION",
            "saved_binding": {**binding, "activation_ref": "CACT_" + "e" * 36},
        }

    monkeypatch.setattr(client, "post_json", mismatched)
    with pytest.raises(BackendError) as caught:
        await client.start_saved_session(
            assessment_id="ASSESS_synthetic",
            subject_id="SUBJECT_synthetic",
            instrument_id="SYNTHETIC_CAT",
            instrument_version="synthetic_item_bank.v1 / demo.v1",
            binding=binding,
            bank_document=bank_document,
            config_document=config_document,
        )
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


def test_private_saved_assets_are_not_repr_or_public_assessment_fields():
    marker = "SYNTHETIC_PRIVATE_DOCUMENT_MARKER"
    assessment = {
        "schema_version": "assessment.v1",
        "assessment_id": "ASSESS_synthetic",
        "subject_id": "SUBJECT_synthetic",
        "instrument": {
            "instrument_id": "SYNTHETIC_CAT",
            "version": "synthetic_item_bank.v1 / demo.v1",
        },
        "population_scope": "SYNTHETIC_STUDENT_DEMO",
        "status": "in_progress",
        "dimensions": {},
        "risk": {
            "level": "normal",
            "need_human_review": False,
            "reason_codes": [],
            "ruleset_id": "synthetic-test",
        },
        "response_summary": {"items_answered": 0, "duration_seconds": None},
        "provenance": {
            "source_adapter": "synthetic",
            "adapter_version": "test",
            "cat_engine_version": "test",
            "item_bank_version": "demo.v1",
        },
        "timestamps": {"started_at": "2026-10-13T00:00:00Z", "completed_at": None},
    }
    record = AssessmentRecord(
        assessment_id="ASSESS_synthetic",
        subject_id="SUBJECT_synthetic",
        assessment=assessment,
        cat_binding_mode="SAVED_VERSION",
        saved_binding={"binding_ref": "CSBIND_synthetic"},
        saved_bank_document={"stem": marker},
        saved_config_document={"private": marker},
    )
    assert marker not in repr(record)
    public_dto = AssessmentDto.model_validate(record.assessment).model_dump(mode="json")
    assert marker not in repr(public_dto)
    assert not {"saved_binding", "saved_bank_document", "saved_config_document"} & set(public_dto)

    cat_start = CatStart(
        assessment_id="ASSESS_synthetic",
        subject_id="SUBJECT_synthetic",
        instrument_id="SYNTHETIC_CAT",
        instrument_version="synthetic_item_bank.v1 / demo.v1",
        started_at="2026-10-13T00:00:00Z",
        saved_binding={"binding_ref": marker},
    )
    assert marker not in repr(cat_start)


def test_activation_list_is_metadata_only_and_rejects_document_fields():
    item = {
        "activation_ref": "CACT_" + "a" * 36,
        "plan_version_ref": "CPVER_" + "b" * 36,
        "bank_version_ref": "CBVER_" + "c" * 36,
        "plan_name": "合成方案",
        "plan_version_number": 2,
        "bank_name": "合成题库",
        "bank_version_number": 3,
        "status": "ACTIVE",
        "revision": 1,
        "created_at": "2026-10-13T00:00:00Z",
        "revoked_at": None,
    }
    metadata = ActivationListDto.model_validate(
        {
            "engineering_only": True,
            "psychological_interpretation_allowed": False,
            "items": [item],
            "has_more": False,
        },
        strict=True,
    )
    assert metadata.items[0].status == "ACTIVE"
    assert "bank_document" not in metadata.model_dump(mode="json")["items"][0]

    with pytest.raises(ValidationError):
        ActivationListDto.model_validate(
            {
                "engineering_only": True,
                "psychological_interpretation_allowed": False,
                "items": [{**item, "bank_document": {"stem": "private"}}],
                "has_more": False,
            },
            strict=True,
        )


@pytest.mark.asyncio
async def test_activation_history_filter_is_only_available_to_specialist():
    version_ref = "CPVER_" + "a" * 36
    calls = []

    class Persistence:
        async def school_cat_assets_list_activations(self, actor, **kwargs):
            calls.append((actor.role, kwargs))
            return {"items": [], "has_more": False}

    service = SchoolCatAssetService(persistence=Persistence())
    with pytest.raises(BackendError) as denied:
        await service.list_activations(
            _actor(BackendRole.ADMIN), limit=20, skip=0, plan_version_ref=version_ref
        )
    assert denied.value.code is ErrorCode.VALIDATION_FAILED
    assert calls == []

    await service.list_activations(
        _actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
        limit=20,
        skip=0,
        plan_version_ref=version_ref,
    )
    assert calls == [
        (
            BackendRole.PSYCHOLOGICAL_SPECIALIST,
            {"limit": 20, "skip": 0, "plan_version_ref": version_ref},
        )
    ]


@pytest.mark.asyncio
async def test_cat_404_recovery_restarts_saved_version_and_replays_responses_in_order():
    class CatUnavailable:
        def __init__(self):
            self.states = 0
            self.saved_starts = []
            self.fixture_starts = []
            self.replayed = []

        async def state(self, *_args, **_kwargs):
            self.states += 1
            if self.states == 1:
                raise BackendError(ErrorCode.RESOURCE_NOT_FOUND, detail="session missing")
            next_index = self.states
            return CatStart(
                assessment_id="ASSESS_saved",
                subject_id="SUBJECT_saved",
                instrument_id="SYNTHETIC_CAT",
                instrument_version="synthetic_item_bank.v1 / demo.v1",
                started_at="2026-10-13T00:00:00Z",
                current_item={"item_id": f"ITEM_{next_index}"},
                cat_binding_mode="SAVED_VERSION",
                saved_binding=binding,
            )

        async def start_saved_session(self, **kwargs):
            self.saved_starts.append(kwargs)
            return CatStart(
                assessment_id=kwargs["assessment_id"],
                subject_id=kwargs["subject_id"],
                instrument_id=kwargs["instrument_id"],
                instrument_version=kwargs["instrument_version"],
                started_at="2026-10-13T00:00:00Z",
                current_item={"item_id": "ITEM_1"},
                cat_binding_mode="SAVED_VERSION",
                saved_binding=kwargs["binding"],
            )

        async def start(self, **kwargs):
            self.fixture_starts.append(kwargs)
            raise AssertionError("saved-session recovery must not fall back to fixture CAT")

        async def submit_response(self, _session, *, item_id, response, **_kwargs):
            self.replayed.append((item_id, response))

    binding = {
        "binding_ref": "CSBIND_" + "a" * 36,
        "activation_ref": "CACT_" + "b" * 36,
        "plan_version_ref": "CPVER_" + "c" * 36,
        "bank_version_ref": "CBVER_" + "d" * 36,
    }
    bank_document = {
        "instrument_id": "SYNTHETIC_CAT",
        "version": "demo.v1",
        "metadata": {"instrument_version": "synthetic_item_bank.v1 / demo.v1"},
    }
    config_document = {"config_version": "config.v4"}
    cat = CatUnavailable()
    service = AssessmentService.__new__(AssessmentService)
    service.cat = cat
    service._sessions = {}
    record = AssessmentRecord(
        assessment_id="ASSESS_saved",
        subject_id="SUBJECT_saved",
        assessment={
            "instrument": {
                "instrument_id": "SYNTHETIC_CAT",
                "version": "synthetic_item_bank.v1 / demo.v1",
            },
            "timestamps": {"started_at": "2026-10-13T00:00:00Z"},
        },
        responses={"ITEM_1": "A", "ITEM_2": "B"},
        cat_item_bank_version="demo.v1",
        cat_config_version="config.v4",
        cat_binding_mode="SAVED_VERSION",
        saved_binding=binding,
        saved_bank_document=bank_document,
        saved_config_document=config_document,
    )

    session = await service._cat_session(record, request_id="REQ_test", trace_id="TRACE_test")

    assert cat.fixture_starts == []
    assert cat.replayed == [("ITEM_1", "A"), ("ITEM_2", "B")]
    assert cat.saved_starts[0]["binding"] == binding
    assert cat.saved_starts[0]["bank_document"] == bank_document
    assert cat.saved_starts[0]["config_document"] == config_document
    assert cat.saved_starts[0]["instrument_version"] == "synthetic_item_bank.v1 / demo.v1"
    assert record.cat_item_bank_version == "demo.v1"
    assert session.cat_binding_mode == "SAVED_VERSION"
