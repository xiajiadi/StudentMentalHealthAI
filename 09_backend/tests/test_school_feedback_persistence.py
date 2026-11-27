"""Focused feedback projection and transition checks, without a database."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from smhai_backend.adapters.school_feedback import SchoolFeedbackPersistenceAdapter
from smhai_backend.adapters.school_support import SchoolSupportPersistenceAdapter
from smhai_backend.core.errors import BackendError, ErrorCode


def fixture_adapter():
    protection = SimpleNamespace(cipher_format_version="aes-gcm.v1", decrypt_json=Mock())
    persistence = SimpleNamespace(protection=protection)
    adapter = SchoolFeedbackPersistenceAdapter(persistence)
    row = SimpleNamespace(
        feedback_ref="FEED_synthetic",
        school_id=1,
        review_case_id=2,
        task_id=3,
        class_id=4,
        task_enrollment_id=5,
        subject_id=6,
        assessment_session_id=7,
        synthetic_only=True,
        level="L3",
        payload_schema_version="school_feedback_content.v1",
        cipher_format_version="aes-gcm.v1",
        payload_ciphertext=b"synthetic-encrypted-fixture",
        key_version="test-key",
        content_revision=1,
        state_version=1,
        case_version=3,
        status="PUBLISHED",
        created_at=datetime(2026, 10, 13),
        published_at=datetime(2026, 10, 13),
        revoked_at=None,
    )
    protection.decrypt_json.return_value = {
        "feedback_ref": row.feedback_ref,
        "content_revision": 1,
        "title": "合成反馈",
        "body": "合成工程样例，不含测量结论。",
    }
    case = SimpleNamespace(review_ref="synthetic-case", version=3, status="APPROVED")
    assessment = SimpleNamespace(assessment_ref="ASSESS_synthetic")
    return adapter, row, case, assessment


@pytest.mark.parametrize("status", ["DRAFT", "REVOKED"])
def test_unpublished_student_projection_does_not_decrypt(status):
    pytest.importorskip("database_layer.crypto")
    adapter, row, case, assessment = fixture_adapter()
    row.status = status
    with pytest.raises(BackendError) as raised:
        adapter._projection(row, case, assessment, student=True)
    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND
    adapter.protection.decrypt_json.assert_not_called()


def test_student_projection_omits_case_fields_and_has_exact_authorized_content():
    pytest.importorskip("database_layer.crypto")
    adapter, row, case, assessment = fixture_adapter()
    result = adapter._projection(row, case, assessment, student=True)
    assert set(result) == {
        "feedback_ref",
        "assessment_ref",
        "level",
        "synthetic_only",
        "content_revision",
        "state_version",
        "status",
        "title",
        "body",
        "created_at",
        "published_at",
    }
    assert result["assessment_ref"] == assessment.assessment_ref
    assert result["synthetic_only"] is True
    assert result["title"] == "合成反馈"


@pytest.mark.parametrize(
    "field,value",
    [
        ("feedback_ref", "FEED_other"),
        ("content_revision", True),
        ("content_revision", 2),
        ("title", " "),
        ("body", " "),
        ("body", "诊断"),
        ("title", "clinical score"),
    ],
)
def test_ciphertext_binding_and_content_shape_fail_closed(field, value):
    pytest.importorskip("database_layer.crypto")
    adapter, row, case, assessment = fixture_adapter()
    adapter.protection.decrypt_json.return_value[field] = value
    with pytest.raises(BackendError) as raised:
        adapter._projection(row, case, assessment, student=True)
    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_fresh_scope_precedes_receipt_replay_and_replay_does_not_republish():
    adapter, row, case, assessment = fixture_adapter()
    row.status = "REVOKED"
    row.revoked_at = datetime(2026, 10, 13)
    order = []

    class Uow:
        session = SimpleNamespace(scalar=AsyncMock(return_value=case), flush=AsyncMock())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    async def authorized(*args, **kwargs):
        order.append("actor")
        return 8, 9

    async def scope(*args, **kwargs):
        order.append("scope")
        return case, assessment

    async def feedback(*args, **kwargs):
        order.append("feedback")
        return row

    async def receipt(*args, **kwargs):
        order.append("receipt")
        return SimpleNamespace(replayed=True)

    # Actual models are used solely to build the statement, not as fake
    # authorization evidence. Native tenant/transaction proof is separate.
    models = pytest.importorskip("database_layer.models")
    adapter._directory._persistence._db_models = models
    from sqlalchemy import select

    adapter._directory._persistence._select = select
    adapter._directory._persistence._utc_now = lambda: datetime(2026, 10, 13)
    adapter._directory._persistence._uow = Uow
    adapter._actor = authorized
    adapter._scope = scope
    adapter._feedback = feedback
    adapter._school_idempotency_begin = receipt
    adapter._receipt_resource = AsyncMock(return_value=row.feedback_ref)
    adapter._projection = Mock(return_value={"status": "REVOKED"})
    adapter._replay_projection = AsyncMock(return_value={"status": "PUBLISHED"})
    adapter._append = AsyncMock()
    result = await adapter.school_feedback_publish(
        SimpleNamespace(school_id=1),
        row.feedback_ref,
        expected_case_version=3,
        expected_state_version=1,
        idempotency=("key", "hash", "scope"),
        trace_id="TRACE_synthetic",
    )
    assert result == {"status": "PUBLISHED"}
    assert order == ["actor", "scope", "feedback", "receipt"]
    assert row.status == "REVOKED"
    adapter._replay_projection.assert_awaited_once()
    assert adapter._replay_projection.call_args.args[1:] == (row, case, assessment, "PUBLISHED", 2)
    adapter._append.assert_not_called()


@pytest.mark.asyncio
async def test_feedback_event_uses_real_audit_repository_metadata_allowlist():
    from database_layer import enums, models
    from database_layer.repositories import AuditRepository

    adapter, row, _case, _assessment = fixture_adapter()
    adapter._db_models = models
    adapter._db_enums = enums
    row.id = 10
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    uow = SimpleNamespace(session=session, audit=AuditRepository(session))
    await adapter._append(
        uow, row, 8, 9, "PUBLISHED", "DRAFT", "synthetic-feedback-audit", row.created_at
    )
    records = [call.args[0] for call in session.add.call_args_list]
    assert len(records) == 2
    event, audit = records
    assert event.review_case_id == row.review_case_id
    assert event.content_revision == row.content_revision
    assert audit.safe_metadata == {"source": "school_feedback", "state": "PUBLISHED", "count": 1}
    assert audit.action == "school_feedback.published"
    assert session.flush.await_count == 2


@pytest.mark.parametrize(
    "scenario", ["general", "linked", "different_subject", "unavailable", "revision_changed"]
)
@pytest.mark.asyncio
async def test_support_evidence_binds_current_subject_and_only_audits_metadata(
    scenario, monkeypatch
):
    from database_layer import enums, models
    from database_layer.repositories import AuditRepository
    from sqlalchemy import select
    from sqlalchemy.dialects import mysql

    adapter, row, case, assessment = fixture_adapter()
    adapter._directory._persistence._select = select
    adapter._db_models = models
    adapter._db_enums = enums
    case.subject_id = row.subject_id + int(scenario == "different_subject")
    case.class_id = row.class_id
    support_case = SimpleNamespace(
        subject_id=row.subject_id, class_id=row.class_id, class_student_id=20
    )
    actor = SimpleNamespace(
        school_id=row.school_id, school_ref="PUBLICDEMO_QA", user_id="USER_fixture"
    )
    adapter._case_for_feedback = AsyncMock(return_value=case)
    adapter._scope = AsyncMock(return_value=(case, assessment))
    adapter._feedback = AsyncMock(return_value=row)
    source = (row.feedback_ref, row.content_revision) if scenario != "general" else None
    if scenario == "revision_changed":
        row.content_revision += 1
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=None if scenario == "unavailable" else row.feedback_ref),
        add=Mock(),
        flush=AsyncMock(),
    )
    uow = SimpleNamespace(session=session, audit=AuditRepository(session))
    monkeypatch.setattr(
        "smhai_backend.adapters.school_feedback.get_request_context",
        lambda: SimpleNamespace(trace_id="TRACE_support_evidence_fixture"),
    )
    if scenario == "different_subject":
        with pytest.raises(BackendError) as raised:
            await adapter.assigned_published_feedback_for_support(
                uow, actor, support_case, 8, 9, row.created_at, source=source
            )
        assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND
        adapter.protection.decrypt_json.assert_not_called()
        session.add.assert_not_called()
    else:
        result = await adapter.assigned_published_feedback_for_support(
            uow, actor, support_case, 8, 9, row.created_at, source=source
        )
        if scenario in {"unavailable", "revision_changed"}:
            assert result is None
            adapter.protection.decrypt_json.assert_not_called()
            session.add.assert_not_called()
        else:
            assert result == {
                "title": "合成反馈",
                "body": "合成工程样例，不含测量结论。",
                "published_at": row.published_at,
                "content_revision": 1,
            }
            audit = session.add.call_args.args[0]
            assert audit.action == "school_feedback.support_plan_read"
            assert audit.safe_metadata == {
                "source": "school_feedback", "state": "PUBLISHED", "count": 1
            }
    if scenario == "unavailable":
        adapter._scope.assert_not_called()
    else:
        assert adapter._scope.await_args.kwargs["class_student_id"] == support_case.class_student_id
    query = str(session.scalar.await_args.args[0].compile(
        dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert "JOIN (SELECT DISTINCT" in query
    assert (
        "school_feedback_records.feedback_ref = 'FEED_synthetic'" in query
    ) == (source is not None)
    assert ("school_feedback_records.content_revision = 1" in query) == (source is not None)


@pytest.mark.parametrize(
    ("scenario", "text", "source", "role_id"),
    [
        ("linked", "合成请求", ("FEED_original", 1), 12),
        ("legacy", "请说明测评反馈第 1 版\n反馈编号 FEED_in_text\n\n合成请求", None, 12),
        ("general", "合成请求", None, 12),
        ("other_owner", "合成请求", ("FEED_original", 1), 13),
    ],
)
@pytest.mark.asyncio
async def test_support_plan_reads_only_the_persisted_link_for_the_current_owner(
    scenario, text, source, role_id
):
    uow = object()

    @asynccontextmanager
    async def open_uow():
        yield uow

    lookup = AsyncMock(return_value={"title": "合成反馈"})
    case = SimpleNamespace(
        case_ref="SSC_synthetic", source_type="STUDENT", status="TRIAGED",
        owner_membership_role_id=12,
    )
    now = datetime(2026, 11, 28)
    adapter = SimpleNamespace(
        _utc_now=lambda: now,
        _uow=open_uow,
        _require_actor=AsyncMock(return_value=(8, role_id)),
        _case=AsyncMock(return_value=case),
        _case_content=AsyncMock(
            return_value=SimpleNamespace(source_text=text, feedback_source=source)
        ),
        _reviews=SimpleNamespace(assigned_published_feedback_for_support=lookup),
    )
    actor = object()
    read_evidence = SchoolSupportPersistenceAdapter.support_plan_evidence
    if scenario == "other_owner":
        with pytest.raises(BackendError) as raised:
            await read_evidence(adapter, actor, case.case_ref)
        assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND
        adapter._case_content.assert_not_called()
        lookup.assert_not_called()
        return
    result = await read_evidence(adapter, actor, case.case_ref)
    adapter._case_content.assert_awaited_once_with(uow, actor, case.case_ref)
    if scenario == "legacy":
        assert result == {"feedback": None}
        lookup.assert_not_called()
    else:
        assert result == {"feedback": {"title": "合成反馈"}}
        lookup.assert_awaited_once_with(uow, actor, case, 8, role_id, now, source=source)


@pytest.mark.parametrize(
    ("current_status", "revision", "expected_code"),
    [
        ("PUBLISHED", 1, None),
        ("PUBLISHED", 2, ErrorCode.WORKFLOW_CONFLICT),
        ("REVOKED", 1, ErrorCode.RESOURCE_NOT_FOUND),
    ],
)
@pytest.mark.asyncio
async def test_feedback_question_resolves_published_scope_without_decrypting(
    current_status, revision, expected_code
):
    from database_layer import models
    from sqlalchemy import select

    adapter, row, case, assessment = fixture_adapter()
    adapter._db_models = models
    adapter._directory._persistence._select = select
    row.status = current_status
    case.subject_id = row.subject_id
    case.class_id = row.class_id
    case.task_enrollment_id = row.task_enrollment_id
    adapter._student_feedback_scope = AsyncMock(return_value=(row, case, assessment))
    uow = SimpleNamespace(session=SimpleNamespace(scalar=AsyncMock(return_value=19)))
    actor = SimpleNamespace(school_id=1)
    args = (uow, actor, 8, row.feedback_ref, revision, row.created_at)
    if expected_code:
        with pytest.raises(BackendError) as raised:
            await adapter.student_feedback_support_scope(*args)
        assert raised.value.code is expected_code
        uow.session.scalar.assert_not_awaited()
    else:
        assert await adapter.student_feedback_support_scope(*args) == (6, 4, 19)
    adapter._student_feedback_scope.assert_awaited_once_with(
        uow, actor, 8, row.feedback_ref, row.created_at
    )
    adapter.protection.decrypt_json.assert_not_called()
