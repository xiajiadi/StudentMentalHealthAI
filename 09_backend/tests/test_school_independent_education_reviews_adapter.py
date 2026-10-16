from __future__ import annotations

from contextlib import asynccontextmanager
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
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.independent_education_reviews.schemas import (
    IndependentEducationDraftPayload,
    publish_material_sha256,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationSourceCard,
)
from smhai_backend.domains.support.schemas import SupportCitation


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


@pytest.mark.asyncio
async def test_staff_list_checks_current_owner_before_projecting_review_metadata(
    monkeypatch,
) -> None:
    adapter = _adapter()
    now = datetime(2026, 10, 16, tzinfo=UTC)
    row = SimpleNamespace(
        review_ref="EDUREV_" + "a" * 32,
        status="SHARED",
        state_version=2,
        created_at=now,
        updated_at=now,
        subject_id=13,
        school_id=1,
    )

    class _Reviews:
        async def list_for_reviewer(self, **_kwargs):
            return [{"review_ref": row.review_ref}]

        async def count_for_reviewer(self, **_kwargs):
            return 1

        async def get(self, **_kwargs):
            return row

    class _Uow:
        independent_education_reviews = _Reviews()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

    @asynccontextmanager
    async def uow():
        yield _Uow()

    async def reviewer_scope(*_args):
        return (21, 34)

    async def owner_revoked(*_args):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review was not found")

    adapter._conversations._uow = uow
    adapter._conversations._utc_now = lambda: now
    monkeypatch.setattr(adapter, "_reviewer_scope", reviewer_scope)
    monkeypatch.setattr(adapter, "_require_current_owner_self", owner_revoked)

    with pytest.raises(BackendError) as raised:
        await adapter.staff_list(SimpleNamespace(school_id=1), offset=0, limit=10)

    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize("replayed", [False, True])
async def test_publish_adapter_returns_bound_content_on_success_and_idempotent_replay(
    monkeypatch, replayed
) -> None:
    adapter = _adapter()
    now = datetime(2026, 10, 16, tzinfo=UTC)
    card = adapter.source_cards["CHUNK_SCHOOL_RESEARCH_RECORD_1"]
    locator = (
        f"{card.record_locator}; source population: {card.source_population_scope}; "
        f"source: {card.canonical_url}; license: {card.license} ({card.license_url}); "
        f"attribution: {card.attribution}"
    )
    citation = SupportCitation.model_validate(
        {
            "citation_id": "CITATION_test_1",
            "chunk_id": card.chunk_id,
            "document_id": "DOC_test_1",
            "title": card.title,
            "organization": card.organization,
            "locator": locator,
            "rank": 1,
            "source_version": "knowledge.v1",
            "source_hash": "sha256:" + card.excerpt_sha256,
        },
        strict=True,
    )
    draft = IndependentEducationDraftPayload(
        schema_version="independent-research-education-reviewed-draft.v1",
        title="Reviewed education summary",
        body="A source-grounded reviewed summary.",
        citations=[citation],
        source_cards=[card],
        candidate_content_sha256="a" * 64,
        source_manifest_sha256=adapter.source_manifest_sha256,
    )
    candidate = SimpleNamespace(citations=[citation], source_cards=[card])
    public_candidate = {
        "schema_version": "independent-research-education-candidate.v1",
        "content": {
            "summary": "General education information.",
            "observations": [],
            "suggestions": [{"text": "Review the source.", "source_chunk_ids": [card.chunk_id]}],
            "disclaimer": "Engineering research simulation only.",
        },
        "citations": [citation.model_dump(mode="json")],
        "source_cards": [card.model_dump(mode="json")],
        "provenance": {
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "source_study_ref": adapter.source_study_ref,
            "source_package_ref": adapter.source_package_ref,
            "source_manifest_sha256": adapter.source_manifest_sha256,
            "retrieval_id": "RETR_adapter_publish",
            "retrieval_bundle_sha256": "b" * 64,
            "prompt_id": adapter.prompt_id,
            "prompt_version": adapter.prompt_version,
            "prompt_sha256": None,
            "model_id": "MODEL_fixture",
            "logical_model_id": "model-fixture",
            "model_version": "fixture-v1",
            "model_digest_sha256": "c" * 64,
            "runtime_version": "fixture-runtime",
            "trace_id": "TRACE_adapter_publish",
            "input_safety_action": "PROCEED",
            "input_safety_reason_codes": ["SYNTHETIC_TEST"],
            "retrieval_safety_action": "PROCEED",
            "retrieval_safety_reason_codes": ["SYNTHETIC_TEST"],
            "output_safety_action": "PROCEED",
            "output_safety_reason_codes": ["SYNTHETIC_TEST"],
            "claim_boundary_status": "ACCEPTED",
            "citation_binding_status": "BOUND",
        },
    }
    public_draft = {
        "title": draft.title,
        "body": draft.body,
        "content_revision": 2,
        "citations": [citation.model_dump(mode="json")],
        "source_cards": [card.model_dump(mode="json")],
        "updated_at": "2026-10-16T00:00:00.000Z",
    }
    material_hash = publish_material_sha256(public_candidate, public_draft)
    row = SimpleNamespace(
        review_ref="EDUREV_" + "b" * 32,
        status="PUBLISHED" if replayed else "DRAFT",
        state_version=4 if replayed else 3,
        created_at=now,
        updated_at=now,
        reviewed_at=now,
        published_at=now if replayed else None,
        content_revision=2,
        candidate_content_sha256="a" * 64,
        source_manifest_sha256=adapter.source_manifest_sha256,
    )

    class _Repo:
        async def get_candidate_payload(self, _row):
            return {"unused": "candidate parsing is stubbed for this adapter seam test"}

        async def get_reviewed_payload(self, _row):
            return draft.model_dump(mode="json")

        async def transition(self, *, row, **kwargs):
            assert kwargs["to_status"] == "PUBLISHED"
            row.status = "PUBLISHED"
            row.state_version += 1
            row.published_at = kwargs["now"]
            return row

    class _Uow:
        independent_education_reviews = _Repo()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

    @asynccontextmanager
    async def uow():
        yield _Uow()

    class _Claim:
        pass

    claim = _Claim()
    claim.replayed = replayed

    async def locked_staff_review(*_args):
        return (21, 34, row)

    async def write_claim(*_args):
        return claim

    async def complete_write(*_args):
        return None

    async def audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(adapter, "_locked_staff_review", locked_staff_review)
    monkeypatch.setattr(adapter, "_write_claim", write_claim)
    monkeypatch.setattr(adapter, "_complete_write", complete_write)
    monkeypatch.setattr(adapter, "_candidate", lambda *_args: candidate)
    monkeypatch.setattr(
        adapter,
        "_candidate_projection",
        lambda _candidate: SimpleNamespace(model_dump=lambda **_kwargs: public_candidate),
    )
    adapter._conversations._uow = uow
    adapter._conversations._utc_now = lambda: now
    adapter._conversations._audit = audit

    result = await adapter.publish(
        SimpleNamespace(school_id=1),
        row.review_ref,
        expected_version=3,
        safety_material_sha256=material_hash,
        publish_safety_check={
            "operation": "OUTPUT",
            "action": "PROCEED",
            "reason_codes": ["SYNTHETIC_TEST"],
            "requires_human": False,
            "decision_id": "DEC_test_publish",
            "trace_id": "TRACE_test_publish",
            "checked_material_sha256": material_hash,
        },
        idempotency=("key-test", "c" * 64),
        trace_id="TRACE_test_publish",
    )

    assert result["status"] == "PUBLISHED"
    assert result["published_content"] == {
        "title": draft.title,
        "body": draft.body,
        "citations": [citation.model_dump(mode="json")],
        "source_cards": [card.model_dump(mode="json")],
        "published_at": "2026-10-16T00:00:00.000Z",
    }


@pytest.mark.asyncio
async def test_save_draft_adapter_response_has_no_published_content(monkeypatch) -> None:
    adapter = _adapter()
    now = datetime(2026, 10, 16, tzinfo=UTC)
    card = adapter.source_cards["CHUNK_SCHOOL_RESEARCH_RECORD_1"]
    citation = SupportCitation.model_validate(
        {
            "citation_id": "CITATION_test_1",
            "chunk_id": card.chunk_id,
            "document_id": "DOC_test_1",
            "title": card.title,
            "organization": card.organization,
            "locator": "Abstract",
            "rank": 1,
            "source_version": "knowledge.v1",
            "source_hash": "sha256:" + card.excerpt_sha256,
        },
        strict=True,
    )
    row = SimpleNamespace(
        review_ref="EDUREV_" + "c" * 32,
        status="SHARED",
        state_version=2,
        created_at=now,
        updated_at=now,
        candidate_content_sha256="a" * 64,
        source_manifest_sha256=adapter.source_manifest_sha256,
        content_revision=0,
    )
    candidate = SimpleNamespace(citations=[citation], source_cards=[card])

    class _Repo:
        async def get_candidate_payload(self, _row):
            return None

        async def transition(self, *, row, **kwargs):
            assert kwargs["to_status"] == "DRAFT"
            row.status = "DRAFT"
            row.state_version += 1
            return row

    class _Uow:
        independent_education_reviews = _Repo()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

    @asynccontextmanager
    async def uow():
        yield _Uow()

    class _Claim:
        replayed = False

    async def locked_staff_review(*_args):
        return (21, 34, row)

    async def write_claim(*_args):
        return _Claim()

    async def complete_write(*_args):
        return None

    async def audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(adapter, "_locked_staff_review", locked_staff_review)
    monkeypatch.setattr(adapter, "_write_claim", write_claim)
    monkeypatch.setattr(adapter, "_complete_write", complete_write)
    monkeypatch.setattr(adapter, "_candidate", lambda *_args: candidate)
    adapter._conversations._uow = uow
    adapter._conversations._utc_now = lambda: now
    adapter._conversations._audit = audit

    result = await adapter.save_draft(
        SimpleNamespace(school_id=1),
        row.review_ref,
        expected_version=2,
        title="Reviewed title",
        body="Reviewed body.",
        idempotency=("draft-key", "d" * 64),
        trace_id="TRACE_draft_save",
    )

    assert result["status"] == "DRAFT"
    assert result["published_content"] is None


@pytest.mark.asyncio
async def test_share_idempotency_replay_returns_current_published_projection(monkeypatch) -> None:
    adapter = _adapter()
    now = datetime(2026, 10, 16, tzinfo=UTC)
    row = SimpleNamespace(
        review_ref="EDUREV_" + "d" * 32,
        status="PUBLISHED",
        state_version=5,
        created_at=now,
        updated_at=now,
    )
    projection = {"title": "Published title", "body": "Published body."}

    class _Uow:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

    @asynccontextmanager
    async def uow():
        yield _Uow()

    class _Claim:
        replayed = True

    async def load_student_review(*_args):
        return (11, 12, SimpleNamespace(), SimpleNamespace(), row, object())

    async def write_claim(*_args):
        return _Claim()

    async def published_for_student(*_args):
        return projection

    async def public_reviewer_id(*_args):
        return "00000000-0000-4000-8000-000000000099"

    monkeypatch.setattr(adapter, "_load_student_review", load_student_review)
    monkeypatch.setattr(adapter, "_write_claim", write_claim)
    monkeypatch.setattr(adapter, "_published_for_student", published_for_student)
    monkeypatch.setattr(adapter, "_public_reviewer_id", public_reviewer_id)
    adapter._conversations._uow = uow
    adapter._conversations._utc_now = lambda: now

    result = await adapter.share(
        SimpleNamespace(school_id=1),
        "CONV_test",
        row.review_ref,
        expected_version=2,
        reviewer_ref="ROLE_00000000-0000-4000-8000-000000000001",
        consent=True,
        idempotency=("share-key", "e" * 64),
        trace_id="TRACE_share_replay",
    )

    assert result["status"] == "PUBLISHED"
    assert result["published_content"] == projection


@pytest.mark.asyncio
async def test_revoke_idempotency_replay_can_read_revoked_metadata_only(monkeypatch) -> None:
    adapter = _adapter()
    now = datetime(2026, 10, 16, tzinfo=UTC)
    row = SimpleNamespace(
        review_ref="EDUREV_" + "f" * 32,
        status="REVOKED",
        state_version=6,
        created_at=now,
        updated_at=now,
        reviewer_membership_role_id=34,
        subject_id=13,
        school_id=1,
    )

    class _Repo:
        async def get_for_update(self, **_kwargs):
            return row

    class _Uow:
        independent_education_reviews = _Repo()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

    @asynccontextmanager
    async def uow():
        yield _Uow()

    class _Claim:
        replayed = True

    async def reviewer_scope(*_args):
        return (21, 34)

    async def write_claim(*_args):
        return _Claim()

    async def owner_current(*_args):
        return None

    monkeypatch.setattr(adapter, "_reviewer_scope", reviewer_scope)
    monkeypatch.setattr(adapter, "_write_claim", write_claim)
    monkeypatch.setattr(adapter, "_require_current_owner_self", owner_current)
    monkeypatch.setattr(adapter, "_require_source_current", lambda *_args: None)
    adapter._conversations._uow = uow
    adapter._conversations._utc_now = lambda: now

    result = await adapter.revoke(
        SimpleNamespace(school_id=1),
        row.review_ref,
        expected_version=5,
        idempotency=("revoke-key", "f" * 64),
        trace_id="TRACE_revoke_replay",
    )

    assert result["status"] == "REVOKED"
    assert result["published_content"] is None
    with pytest.raises(BackendError) as raised:
        await adapter._locked_staff_review(
            _Uow(), SimpleNamespace(school_id=1), row.review_ref, now
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
