from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_feedback import (
    SchoolResearchFeedbackPersistenceAdapter,
    _repo_call,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUsePolicy,
)

from .test_school_research_education_candidates_service import candidate_payload

_PROFILE_SHA = "1" * 64
_MANIFEST_SHA = "2" * 64
_CROSSWALK_SHA = "3" * 64


def _policy() -> ResearchStudyUsePolicy:
    return ResearchStudyUsePolicy(
        study_ref="study_synthetic",
        school_id=17,
        institution="Synthetic School",
        use_scope="ISOLATED_HISTORICAL_REPLAY",
        noncommercial=True,
        historical_replay_only=True,
        english_unchanged=True,
        starts_at=datetime(2026, 10, 1, tzinfo=UTC),
        ends_at=datetime(2026, 10, 31, tzinfo=UTC),
        profiles=(
            ResearchStudyProfilePin(
                profile_ref="PROMIS_SYNTHETIC",
                profile_sha256=_PROFILE_SHA,
                manifest_sha256=_MANIFEST_SHA,
                published_crosswalk_sha256=_CROSSWALK_SHA,
            ),
        ),
        rights_basis="verified public research source for an isolated synthetic replay",
        rights_source_urls=("https://example.org/research-terms",),
        recorded_by="synthetic_operator",
        recorded_at=datetime(2026, 10, 14, tzinfo=UTC),
        operator_declaration="synthetic-only test fixture",
        source_rights_verified=True,
    )


def _profile():
    return SimpleNamespace(
        school_id=17,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_id=91,
        version_number=3,
        profile_sha256=_PROFILE_SHA,
        manifest_sha256=_MANIFEST_SHA,
        published_parameter_crosswalk_sha256=_CROSSWALK_SHA,
        rights_status="VERIFIED",
        execution_status="SIMULATION_ENABLED",
        rights_revoked_at=None,
        research_only=True,
        human_curated=False,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
    )


def _binding():
    return SimpleNamespace(
        school_id=17,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_id=91,
        profile_version_number=3,
        profile_sha256=_PROFILE_SHA,
        task_id=21,
        class_id=31,
        status="ACTIVE",
        revoked_at=None,
        research_only=True,
        cohort_id=None,
    )


def _task(*, due_at):
    return SimpleNamespace(
        id=21,
        class_id=31,
        opens_at=datetime(2026, 10, 2),
        due_at=due_at,
    )


def test_completed_session_review_stays_in_policy_scope_after_task_due_date():
    adapter = SchoolResearchFeedbackPersistenceAdapter(None, study_use_policy=_policy())

    pin = adapter._policy_pin(
        profile=_profile(),
        binding=_binding(),
        task=_task(due_at=datetime(2026, 10, 10)),
        at=datetime(2026, 10, 14, tzinfo=UTC),
    )

    assert pin.profile_ref == "PROMIS_SYNTHETIC"
    assert pin.published_crosswalk_sha256 == _CROSSWALK_SHA


def test_task_window_must_still_be_contained_in_study_policy():
    adapter = SchoolResearchFeedbackPersistenceAdapter(None, study_use_policy=_policy())

    with pytest.raises(BackendError):
        adapter._policy_pin(
            profile=_profile(),
            binding=_binding(),
            task=_task(due_at=datetime(2026, 11, 1)),
            at=datetime(2026, 10, 14, tzinfo=UTC),
        )


async def test_repository_conflict_is_safe_and_does_not_echo_storage_details(monkeypatch):
    class OptimisticConcurrencyConflict(Exception):
        pass

    class ResearchReviewFeedbackError(Exception):
        pass

    package = ModuleType("database_layer")
    package.__path__ = []
    errors_module = ModuleType("database_layer.errors")
    for name in (
        "DatabaseUnavailable",
        "EncryptionKeyUnavailable",
        "ForeignKeyConflict",
        "NotFound",
        "UniqueConflict",
    ):
        setattr(errors_module, name, type(name, (Exception,), {}))
    errors_module.OptimisticConcurrencyConflict = OptimisticConcurrencyConflict
    repo_module = ModuleType("database_layer.school_research_review_feedback")
    repo_module.ResearchReviewFeedbackError = ResearchReviewFeedbackError
    monkeypatch.setitem(sys.modules, "database_layer", package)
    monkeypatch.setitem(sys.modules, "database_layer.errors", errors_module)
    monkeypatch.setitem(
        sys.modules, "database_layer.school_research_review_feedback", repo_module
    )

    async def conflict():
        raise OptimisticConcurrencyConflict("internal row details")

    with pytest.raises(BackendError) as raised:
        await _repo_call(conflict())

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert "internal row details" not in str(raised.value)


async def test_case_and_student_list_candidates_exclude_revoked_scopes():
    sqlalchemy = pytest.importorskip("sqlalchemy")
    from database_layer import models
    from sqlalchemy.dialects import mysql, sqlite

    scope = SimpleNamespace(research_session_id=500)

    class Result:
        def all(self):
            return [(case_model.id, case_model.review_ref, "RSESS_active", case_model.created_at)]

    class Session:
        last_statement = None

        async def scalar(self, statement):
            return 1

        async def execute(self, statement):
            self.last_statement = statement
            return Result()

    class ResearchReviews:
        async def get_case(self, *, school_id, research_session_id):
            return SimpleNamespace(
                review_ref="SRV_active",
                purpose="RESEARCH_SIMULATION",
                research_only=True,
                publication_status="not_approved_for_publication_or_operational_use",
                status="OPEN",
                version=1,
                created_at=datetime(2026, 10, 14, tzinfo=UTC),
                updated_at=datetime(2026, 10, 14, tzinfo=UTC),
                case_note_ciphertext=None,
                case_note_cipher_format_version=None,
                case_note_key_version=None,
                case_note_payload_schema_version=None,
                scope=scope,
            )

    class UnitOfWork:
        def __init__(self):
            self.session = Session()
            self.research_reviews = ResearchReviews()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Adapter(SchoolResearchFeedbackPersistenceAdapter):
        def _utc_now(self):
            return datetime(2026, 10, 14, tzinfo=UTC)

        async def _require_actor(self, *args):
            return (100, 200)

        async def _task(self, *args, **kwargs):
            return SimpleNamespace(id=300, class_id=400)

        async def _active_assignment(self, *args, **kwargs):
            return None

        async def _require_task_study_scope(self, *args, **kwargs):
            return None

        async def _current_scope(self, *args, **kwargs):
            return (scope, None, None, None, None)

    adapter = Adapter(None)
    adapter._select = sqlalchemy.select
    adapter._db_models = models
    adapter._db_enums = SimpleNamespace(
        SubjectStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC")),
        AccountStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
    )
    unit_of_work = UnitOfWork()
    adapter._uow = lambda: unit_of_work
    case_model = SimpleNamespace(
        id=600,
        review_ref="SRV_active",
        created_at=datetime(2026, 10, 14, tzinfo=UTC),
    )
    result = await adapter.school_research_feedback_list_cases(
        SimpleNamespace(school_id=17), "TASK_synthetic", status=None, offset=0, limit=20
    )

    assert result["total"] == 1
    assert len(result["items"]) == 1
    sql = str(unit_of_work.session.last_statement.compile(dialect=sqlite.dialect()))
    assert "school_class_students.status" in sql
    assert "school_class_students.revoked_at IS NULL" in sql
    assert "subject_access_grants.status" in sql
    assert "subject_access_grants.revoked_at IS NULL" in sql

    student_query = adapter._student_candidate_query(
        SimpleNamespace(school_id=17),
        501,
        datetime(2026, 10, 14, tzinfo=UTC),
    )
    assert [column.key for column in student_query.selected_columns] == [
        "feedback_ref",
        "created_at",
    ]
    assert student_query._distinct is True
    student_mysql = str(
        student_query.order_by(
            models.SchoolResearchFeedbackRecord.created_at.desc(),
            models.SchoolResearchFeedbackRecord.feedback_ref.asc(),
        ).compile(dialect=mysql.dialect())
    )
    assert "SELECT DISTINCT" in student_mysql
    assert "school_research_feedback_records.created_at DESC" in student_mysql
    assert "school_research_feedback_records.feedback_ref ASC" in student_mysql
    student_sql = str(student_query.compile(dialect=sqlite.dialect()))
    assert "task_enrollments.revoked_at IS NULL" in student_sql
    assert "school_class_students.revoked_at IS NULL" in student_sql
    assert "subject_access_grants.revoked_at IS NULL" in student_sql
    assert "account_school_memberships.revoked_at IS NULL" in student_sql
    assert "membership_roles.revoked_at IS NULL" in student_sql


def _feedback_row(
    *, schema, payload_value, source_candidate_id=None, source_candidate_revision=None
):
    import json

    return SimpleNamespace(
        feedback_ref="RFEED_synthetic",
        content_revision=1,
        title="人工修订标题",
        body="人工修订后的教育支持正文。",
        status="DRAFT",
        feedback_kind="GENERAL_EDUCATIONAL_SUPPORT",
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
        case_version=2,
        state_version=1,
        created_at=datetime(2026, 10, 14, tzinfo=UTC),
        published_at=None,
        revoked_at=None,
        cipher_format_version="enc.v1",
        key_version="key-v1",
        payload_schema_version=schema,
        payload_ciphertext=json.dumps(payload_value, ensure_ascii=False).encode(),
        source_candidate_id=source_candidate_id,
        source_candidate_revision=source_candidate_revision,
    )


def _install_feedback_decrypt(monkeypatch, adapter, clear_value):
    class EncryptedPayload:
        def __init__(
            self, *, ciphertext, key_version, cipher_format_version, payload_schema_version
        ):
            self.ciphertext = ciphertext
            self.key_version = key_version
            self.cipher_format_version = cipher_format_version
            self.payload_schema_version = payload_schema_version

    crypto_module = ModuleType("database_layer.crypto")
    crypto_module.EncryptedPayload = EncryptedPayload
    monkeypatch.setitem(sys.modules, "database_layer.crypto", crypto_module)
    adapter.protection = SimpleNamespace(decrypt_json=lambda _encrypted: clear_value)


def test_feedback_v1_payload_remains_readable_with_empty_source_projection(monkeypatch):
    clear = {
        "feedback_ref": "RFEED_synthetic",
        "content_revision": 1,
        "title": "人工修订标题",
        "body": "人工修订后的教育支持正文。",
    }
    adapter = SchoolResearchFeedbackPersistenceAdapter(None)
    _install_feedback_decrypt(monkeypatch, adapter, clear)
    row = _feedback_row(
        schema="school_research_feedback_content.v1", payload_value=clear
    )

    result = adapter._feedback_content(row)

    assert result == {
        "title": clear["title"],
        "body": clear["body"],
        "citations": [],
        "source_cards": [],
        "source_manifest_sha256": None,
    }


def test_feedback_v2_payload_keeps_reviewed_text_and_exact_candidate_sources(monkeypatch):
    payload = candidate_payload()
    clear = {
        "feedback_ref": "RFEED_synthetic",
        "content_revision": 1,
        "title": "人工修订标题",
        "body": "人工修订后的教育支持正文。",
        "source_candidate_ref": "REEDUC_synthetic",
        "source_candidate_revision": 1,
        "source_manifest_sha256": payload.provenance.source_manifest_sha256,
        "source_provenance": payload.provenance.model_dump(mode="json"),
        "citations": [item.model_dump(mode="json") for item in payload.citations],
        "source_cards": [item.model_dump(mode="json") for item in payload.source_cards],
    }
    adapter = SchoolResearchFeedbackPersistenceAdapter(None)
    _install_feedback_decrypt(monkeypatch, adapter, clear)
    row = _feedback_row(
        schema="school_research_feedback_content.v2",
        payload_value=clear,
        source_candidate_id=71,
        source_candidate_revision=1,
    )

    result = adapter._feedback_content(
        row, candidate_ref="REEDUC_synthetic", candidate_payload=payload
    )

    assert result["title"] == "人工修订标题"
    assert result["body"] == "人工修订后的教育支持正文。"
    assert result["citations"] == [
        item.model_dump(mode="python") for item in payload.citations
    ]
    assert result["source_cards"] == [
        item.model_dump(mode="python") for item in payload.source_cards
    ]
    assert result["source_manifest_sha256"] == payload.provenance.source_manifest_sha256
    assert "content" not in result
    assert "candidate_payload" not in result

    with pytest.raises(BackendError) as raised:
        adapter._feedback_content(row, candidate_ref="REEDUC_other", candidate_payload=payload)
    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


async def test_feedback_candidate_lookup_requires_exact_session_scope_before_validation():
    from database_layer import models

    expected_scope = SimpleNamespace(
        research_session_id=11,
        school_id=17,
        task_id=21,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
    )
    row = SimpleNamespace(
        id=91,
        candidate_ref="REEDUC_synthetic",
        scope=SimpleNamespace(**vars(expected_scope)),
        status="ADOPTED",
        content_revision=1,
    )

    class CandidateRepository:
        async def get_for_task(self, *, school_id, task_id, candidate_ref):
            assert (school_id, task_id, candidate_ref) == (
                expected_scope.school_id,
                expected_scope.task_id,
                row.candidate_ref,
            )
            return row

    class UnitOfWork:
        research_education_candidates = CandidateRepository()

    payload = candidate_payload()
    validated = []
    adapter = SchoolResearchFeedbackPersistenceAdapter(
        None,
        education_candidate_validator=lambda candidate, scope: validated.append(
            (candidate, scope)
        )
        or payload,
    )
    adapter._db_models = models

    candidate, result = await adapter._candidate_for_feedback(
        UnitOfWork(),
        actor=SimpleNamespace(school_id=expected_scope.school_id),
        task=SimpleNamespace(id=expected_scope.task_id),
        scope=expected_scope,
        candidate_ref=row.candidate_ref,
    )

    assert candidate is row
    assert result is payload
    assert validated == [(row, expected_scope)]


async def test_feedback_candidate_from_another_session_is_not_used():
    from database_layer import models

    expected_scope = SimpleNamespace(
        research_session_id=11,
        school_id=17,
        task_id=21,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
    )
    wrong_scope = SimpleNamespace(**vars(expected_scope))
    wrong_scope.research_session_id = 12
    row = SimpleNamespace(
        id=91,
        candidate_ref="REEDUC_other_session",
        scope=wrong_scope,
        status="ADOPTED",
        content_revision=1,
    )

    class CandidateRepository:
        async def get_for_task(self, **_kwargs):
            return row

    adapter = SchoolResearchFeedbackPersistenceAdapter(
        None,
        education_candidate_validator=lambda *_args: pytest.fail(
            "candidate payload validator must not run for a foreign session"
        ),
    )
    adapter._db_models = models

    with pytest.raises(BackendError) as raised:
        await adapter._candidate_for_feedback(
            SimpleNamespace(research_education_candidates=CandidateRepository()),
            actor=SimpleNamespace(school_id=expected_scope.school_id),
            task=SimpleNamespace(id=expected_scope.task_id),
            scope=expected_scope,
            candidate_ref=row.candidate_ref,
        )

    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND
