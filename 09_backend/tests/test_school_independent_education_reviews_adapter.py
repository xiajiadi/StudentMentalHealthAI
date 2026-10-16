from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from database_layer import enums as db_enums
from database_layer.models import (
    Account,
    AccountSchoolMembership,
    MembershipRole,
    School,
    Subject,
    SubjectAccessGrant,
)
from sqlalchemy.dialects import sqlite

from smhai_backend.adapters.school_independent_education_reviews import (
    SchoolIndependentEducationReviewsPersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationSourceCard,
)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.rows)


def _adapter(*, valid_through: datetime | None = None):
    persistence = SimpleNamespace(
        _db_models=SimpleNamespace(
            SubjectAccessGrant=SubjectAccessGrant,
            Subject=Subject,
            Account=Account,
            AccountSchoolMembership=AccountSchoolMembership,
            MembershipRole=MembershipRole,
            School=School,
        ),
        _db_enums=db_enums,
    )
    return SchoolIndependentEducationReviewsPersistenceAdapter(
        persistence,
        expected_school_id=1,
        source_study_ref="school-study-r1",
        source_package_ref="student-package-r3",
        source_manifest_sha256="a" * 64,
        prompt_id="PROMPT_research_student",
        prompt_version="1.4.0",
        valid_through=valid_through or datetime(2027, 6, 30, tzinfo=UTC),
        source_cards={
            "CHUNK_SCHOOL_RESEARCH_RECORD_1": ResearchGeneralEducationSourceCard(
                chunk_id="CHUNK_SCHOOL_RESEARCH_RECORD_1",
                record_id="record-1",
                source_id="source-1",
                title="Source title",
                organization="Source organization",
                canonical_url="https://example.edu/source",
                record_locator="Abstract",
                source_population_scope="Secondary school students",
                source_language="en",
                license="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                attribution="Source organization",
                excerpt_sha256="a" * 64,
                excerpt_text="Source excerpt.",
                consumer_age_min=14,
                consumer_age_max=17,
            )
        },
    )


@pytest.mark.asyncio
async def test_reviewer_self_scope_requires_one_current_active_student_grant() -> None:
    adapter = _adapter()
    row = SimpleNamespace(subject_id=13, school_id=1)
    now = datetime(2026, 10, 16, tzinfo=UTC)

    session = _Session([(3,)])
    await adapter._require_current_owner_self(SimpleNamespace(session=session), row, now)
    sql = str(session.statement.compile(dialect=sqlite.dialect()))
    assert "subject_access_grants.relationship_type = ?" in sql
    assert "subject_access_grants.revoked_at IS NULL" in sql
    assert "subjects.status = ?" in sql
    assert "accounts.status = ?" in sql
    assert "account_school_memberships.status = ?" in sql
    assert "membership_roles.role_code = ?" in sql
    assert "membership_roles.revoked_at IS NULL" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [(3,), (4,)]])
async def test_reviewer_self_scope_fails_closed_when_grant_is_missing_or_ambiguous(rows) -> None:
    adapter = _adapter()
    session = _Session(rows)

    with pytest.raises(BackendError) as raised:
        await adapter._require_current_owner_self(
            SimpleNamespace(session=session),
            SimpleNamespace(subject_id=13, school_id=1),
            datetime(2026, 10, 16, tzinfo=UTC),
        )

    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND


def test_source_expiry_treats_naive_database_clock_as_utc() -> None:
    naive_now = datetime(2026, 10, 16, 1, 0)
    valid = _adapter(valid_through=datetime(2026, 10, 16, 2, 0, tzinfo=UTC))
    expired = _adapter(valid_through=datetime(2026, 10, 15, 20, 0, tzinfo=UTC))
    valid._conversations._utc_now = lambda: naive_now
    expired._conversations._utc_now = lambda: naive_now

    valid._require_source_current()
    with pytest.raises(BackendError):
        expired._require_source_current()
