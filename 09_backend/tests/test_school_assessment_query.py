from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.school_tasks.schemas import StudentAssessmentMetadataDto


class _Expression:
    def __init__(self, fields=()):
        self.fields = set(fields)

    def __and__(self, _other):
        return _Expression(self.fields | _other.fields)

    def __or__(self, _other):
        return _Expression(self.fields | _other.fields)

class _Column:
    def __init__(self, name=""):
        self.name = name

    def __eq__(self, _other):
        return _Expression({self.name})

    def __le__(self, _other):
        return _Expression({self.name})

    def __ge__(self, _other):
        return _Expression({self.name})

    def is_(self, _other):
        return _Expression({self.name})

    def is_not(self, _other):
        return _Expression({self.name})

    def in_(self, _other):
        return _Expression({self.name})

    def desc(self):
        return self


class _Query:
    def __init__(self, selected):
        self.selected = selected
        self.ordering = None
        self.is_distinct = False
        self.offset_value = None
        self.limit_value = None
        self.where_fields = set()
        self.events = []

    def join(self, *_args):
        return self

    def outerjoin(self, *_args):
        return self

    def where(self, *_args):
        for arg in _args:
            self.where_fields.update(arg.fields)
        self.events.append("where")
        return self

    def distinct(self):
        self.is_distinct = True
        return self

    def order_by(self, *ordering):
        self.ordering = ordering
        return self

    def offset(self, skip):
        self.offset_value = skip
        self.events.append("offset")
        return self

    def limit(self, limit):
        self.limit_value = limit
        self.events.append("limit")
        return self

    def scalar_subquery(self):
        return self


class _Session:
    def __init__(self):
        self.statement = None
        self.rows = []

    async def scalars(self, statement):
        self.statement = statement
        return SimpleNamespace(all=lambda: [])

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(all=lambda: self.rows)


class _UnitOfWork:
    def __init__(self):
        self.session = _Session()

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


def _model(*names):
    return SimpleNamespace(**{name: _Column(name) for name in names})


def _combine(*conditions):
    return _Expression(set().union(*(condition.fields for condition in conditions)))


@pytest.mark.asyncio
async def test_school_assessment_distinct_projection_includes_ordered_started_at(monkeypatch):
    sqlalchemy = ModuleType("sqlalchemy")
    sqlalchemy.and_ = _combine
    sqlalchemy.or_ = _combine
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy)

    models = SimpleNamespace(
        AssessmentSession=_model(
            "assessment_ref", "started_at", "subject_id", "task_enrollment_id", "status"
        ),
        Subject=_model("id", "school_id", "subject_ref", "status", "data_origin"),
        TaskEnrollment=_model(
            "id", "subject_id", "class_student_id", "class_id", "school_id", "task_id", "status"
        ),
        SchoolClassStudent=_model(
            "id",
            "subject_id",
            "class_id",
            "school_id",
            "status",
            "revoked_at",
            "valid_from",
            "valid_until",
        ),
        SchoolClass=_model("id", "school_id", "status"),
        MeasurementTask=_model("id", "school_id", "class_id", "status", "opens_at", "due_at"),
        SubjectAccessGrant=_model(
            "subject_id",
            "school_id",
            "principal_account_id",
            "relationship_type",
            "status",
            "revoked_at",
            "valid_from",
            "valid_until",
        ),
        AccountSchoolMembership=_model(
            "id", "account_id", "school_id", "status", "revoked_at", "valid_from", "valid_until"
        ),
        MembershipRole=_model(
            "membership_id",
            "id",
            "school_id",
            "role_code",
            "status",
            "revoked_at",
            "valid_from",
            "valid_until",
        ),
    )
    uow = _UnitOfWork()
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter._db_models = models
    adapter._db_enums = SimpleNamespace(
        SubjectStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC")),
    )
    adapter._utc_now = lambda: datetime(2026, 10, 11, tzinfo=UTC)
    adapter._uow = lambda: uow
    adapter._select = lambda *selected: _Query(selected)

    async def resolve_actor(_uow, _actor, _role, _at):
        return 12, 34

    adapter._school_actor_role = resolve_actor
    actor = SimpleNamespace(
        scope_profile="school_tenant",
        role=BackendRole.STUDENT,
        school_id=8,
        school_ref="SCHOOL_SYNTHETIC",
    )

    result = await adapter.school_list_assessments_for_actor(
        actor, {"SUBJECT_SYNTHETIC"}, limit=20, skip=0
    )

    statement = uow.session.statement
    assert result == []
    assert statement.selected == (
        models.AssessmentSession.assessment_ref,
        models.AssessmentSession.started_at,
    )
    assert statement.is_distinct is True
    assert len(statement.ordering) == 2


@pytest.mark.asyncio
async def test_school_assessment_metadata_projects_null_timestamps_without_decryption(monkeypatch):
    sqlalchemy = ModuleType("sqlalchemy")
    sqlalchemy.and_ = _combine
    sqlalchemy.or_ = _combine
    sqlalchemy.func = SimpleNamespace(count=lambda column: ("count", column))
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy)

    models = SimpleNamespace(
        AssessmentSession=_model(
            "id", "assessment_ref", "started_at", "completed_at", "subject_id",
            "task_enrollment_id", "status",
        ),
        AssessmentResponse=_model("id", "assessment_session_id"),
        Subject=_model("id", "school_id", "subject_ref", "status", "data_origin"),
        TaskEnrollment=_model(
            "id", "subject_id", "class_student_id", "class_id", "school_id", "task_id", "status"
        ),
        SchoolClassStudent=_model(
            "id", "subject_id", "class_id", "school_id", "status", "revoked_at",
            "valid_from", "valid_until",
        ),
        SchoolClass=_model("id", "school_id", "status"),
        MeasurementTask=_model("id", "school_id", "class_id", "status", "opens_at", "due_at"),
        SubjectAccessGrant=_model(
            "subject_id", "school_id", "principal_account_id", "relationship_type", "status",
            "revoked_at", "valid_from", "valid_until",
        ),
        AccountSchoolMembership=_model(
            "id", "account_id", "school_id", "status", "revoked_at", "valid_from", "valid_until"
        ),
        MembershipRole=_model(
            "membership_id", "id", "school_id", "role_code", "status", "revoked_at",
            "valid_from", "valid_until",
        ),
    )
    uow = _UnitOfWork()
    uow.session.rows = [
        (
            "ASSESS_SYNTHETIC_STARTED",
            "IN_PROGRESS",
            2,
            datetime(2026, 10, 11, 12, 30, 45),
            datetime(2026, 10, 11, 13, 0, 0),
        )
    ]
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    adapter._db_models = models
    adapter._db_enums = SimpleNamespace(
        SubjectStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC")),
    )
    adapter._utc_now = lambda: datetime(2026, 10, 11, tzinfo=UTC)
    adapter._uow = lambda: uow
    adapter._select = lambda *selected: _Query(selected)
    adapter.protection = SimpleNamespace(
        decrypt_json=lambda *_args: (_ for _ in ()).throw(AssertionError("must not decrypt"))
    )

    async def resolve_actor(actual_uow, _actor, _role, _at):
        assert actual_uow is uow
        return 12, 34

    adapter._school_actor_role = resolve_actor
    actor = SimpleNamespace(
        scope_profile="school_tenant",
        role=BackendRole.STUDENT,
        school_id=8,
        school_ref="SCHOOL_SYNTHETIC",
    )

    result = await adapter.school_list_assessment_metadata_for_actor(
        actor, {"SUBJECT_SYNTHETIC"}, limit=1, skip=1, status="created"
    )

    assert result == [
        {
            "assessment_id": "ASSESS_SYNTHETIC_STARTED",
            "status": "in_progress",
            "items_answered": 2,
            "started_at": datetime(2026, 10, 11, 12, 30, 45, tzinfo=UTC),
            "completed_at": datetime(2026, 10, 11, 13, 0, 0, tzinfo=UTC),
        }
    ]
    serialized = StudentAssessmentMetadataDto.model_validate(result[0]).model_dump(mode="json")
    assert serialized["started_at"] == "2026-10-11T12:30:45Z"
    assert serialized["completed_at"] == "2026-10-11T13:00:00Z"
    assert uow.session.statement.selected[0] == models.AssessmentSession.assessment_ref
    assert uow.session.statement.selected[1] == models.AssessmentSession.status
    assert len(uow.session.statement.selected) == 5
    assert uow.session.statement.offset_value == 1
    assert uow.session.statement.limit_value == 1
    assert uow.session.statement.where_fields >= {
        "school_id",
        "principal_account_id",
        "relationship_type",
        "revoked_at",
        "role_code",
        "status",
        "valid_from",
        "valid_until",
        "opens_at",
        "due_at",
        "task_enrollment_id",
    }
    assert max(
        index for index, event in enumerate(uow.session.statement.events) if event == "where"
    ) < uow.session.statement.events.index("offset")
    assert max(
        index for index, event in enumerate(uow.session.statement.events) if event == "where"
    ) < uow.session.statement.events.index("limit")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actor_overrides",
    [
        {"role": BackendRole.TEACHER},
        {"school_id": None},
        {"school_ref": None},
        {"scope_profile": "legacy_demo"},
    ],
)
async def test_school_assessment_metadata_fails_closed_for_wrong_actor_context(actor_overrides):
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    adapter._uow = lambda: (_ for _ in ()).throw(AssertionError("unauthorized query opened"))
    actor = {
        "scope_profile": "school_tenant",
        "role": BackendRole.STUDENT,
        "school_id": 8,
        "school_ref": "SCHOOL_SYNTHETIC",
    }
    actor.update(actor_overrides)
    result = await adapter.school_list_assessment_metadata_for_actor(
        SimpleNamespace(**actor), {"SUBJECT_SYNTHETIC"}, limit=30, skip=0
    )
    assert result == []


def test_student_assessment_metadata_allows_pending_timestamps_and_rejects_extra_fields():
    dto = StudentAssessmentMetadataDto.model_validate(
        {
            "assessment_id": "ASSESS_SYNTHETIC_PENDING",
            "status": "created",
            "items_answered": 0,
            "started_at": None,
            "completed_at": None,
        }
    )
    assert dto.started_at is None
    assert dto.completed_at is None
    with pytest.raises(ValidationError):
        StudentAssessmentMetadataDto.model_validate(
            {
                "assessment_id": "ASSESS_SYNTHETIC_PENDING",
                "status": "created",
                "items_answered": 0,
                "started_at": None,
                "completed_at": None,
                "subject_id": "SUBJ_SYNTHETIC_PRIVATE",
            }
        )
