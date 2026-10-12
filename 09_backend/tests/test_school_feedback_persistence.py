"""Focused feedback projection and transition checks, without a database."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from smhai_backend.adapters.school_feedback import SchoolFeedbackPersistenceAdapter
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
