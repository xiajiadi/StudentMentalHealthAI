from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from database_layer.models import SchoolSupportCase
from database_layer.school_support import SchoolSupportError, SchoolSupportRepository


@pytest.mark.parametrize(
    ("source_type", "source"),
    [
        ("STUDENT", ("FEED_original", 2)),
        ("STUDENT", None),
        ("TEACHER", None),
    ],
)
@pytest.mark.asyncio
async def test_support_feedback_source_round_trips_independently_of_user_text(
    source_type, source, protection
):
    def add(record):
        if isinstance(record, SchoolSupportCase):
            record.id = 7
            session.scalar.return_value = record

    session = Mock(add=Mock(side_effect=add), flush=AsyncMock(), scalar=AsyncMock())
    repository = SchoolSupportRepository(session, protection)
    user_text = "请说明测评反馈第 1 版\n反馈编号 FEED_in_text\n\n合成请求"
    case = await repository.create_case(
        school_id=1,
        subject_id=2,
        class_id=3,
        class_student_id=4,
        source_type=source_type,
        source_text=user_text,
        category_code="OTHER",
        created_by_membership_role_id=5,
        trace_id="TRACE_synthetic",
        now=datetime(2026, 11, 28, tzinfo=UTC),
        feedback_source=source,
    )

    stored = session.scalar.return_value
    assert b"FEED_" not in stored.source_ciphertext
    assert stored.source_payload_schema_version == "school-support-case-source.v1"
    result = await repository.get_case_content(school_id=1, case_ref=case.case_ref)
    assert result.source_text == user_text
    assert result.feedback_source == source


@pytest.mark.parametrize(
    ("source_type", "source"),
    [("TEACHER", ("FEED_original", 2)), ("STUDENT", ("FEED_original", True))],
)
@pytest.mark.asyncio
async def test_invalid_feedback_source_never_creates_case(source_type, source, protection):
    session = Mock()
    repository = SchoolSupportRepository(session, protection)
    with pytest.raises(SchoolSupportError):
        await repository.create_case(
            school_id=1,
            subject_id=2,
            class_id=3,
            class_student_id=4,
            source_type=source_type,
            source_text="合成请求",
            category_code="OTHER",
            created_by_membership_role_id=5,
            trace_id="TRACE_synthetic",
            feedback_source=source,
        )
    session.add.assert_not_called()
