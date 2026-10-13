from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from itertools import product
from types import SimpleNamespace

import pytest

from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research.authorization import (
    ResearchScopeResolutionError,
    ResearchStudentScope,
    resolve_research_student_scope,
)

_NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC).replace(tzinfo=None)


class _Predicate:
    def __init__(self, check):
        self.check = check

    def __and__(self, other):
        return _Predicate(lambda rows: self.check(rows) and other.check(rows))

    def __or__(self, other):
        return _Predicate(lambda rows: self.check(rows) or other.check(rows))

    def __bool__(self):
        raise AssertionError("SQL-like predicates must not be evaluated during construction")


class _ColumnExpression:
    def __init__(self, model, name):
        self.model = model
        self.name = name

    def _value(self, other, rows):
        if isinstance(other, _ColumnExpression):
            return getattr(rows[other.model], other.name)
        return other

    def _compare(self, other, comparison):
        return _Predicate(
            lambda rows: comparison(
                getattr(rows[self.model], self.name), self._value(other, rows)
            )
        )

    def __eq__(self, other):
        return self._compare(other, lambda left, right: left == right)

    def __le__(self, other):
        return self._compare(other, lambda left, right: left <= right)

    def __ge__(self, other):
        return self._compare(other, lambda left, right: left >= right)

    def is_(self, other):
        return self._compare(other, lambda left, right: left is right)


class _Column:
    def __set_name__(self, _owner, name):
        self.name = name

    def __get__(self, instance, owner):
        return _ColumnExpression(owner, self.name)


def _model(name, *columns):
    return type(name, (), {column: _Column() for column in columns})


class _FakeSelect:
    def __init__(self, entities):
        self.entities = list(entities)
        self.joins = []
        self.predicates = []
        self.row_limit = None
        self.options = {}

    def join(self, entity, onclause):
        self.joins.append((entity, onclause))
        return self

    def add_columns(self, entity):
        self.entities.append(entity)
        return self

    def where(self, *predicates):
        self.predicates.extend(predicates)
        return self

    def limit(self, count):
        self.row_limit = count
        return self

    def execution_options(self, **options):
        self.options.update(options)
        return self


def _select(*entities):
    return _FakeSelect(entities)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, models, rows):
        self.models = models
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        contexts = [{statement.entities[0]: row} for row in self.rows[statement.entities[0]]]
        for model, join_predicate in statement.joins:
            contexts = [
                {**context, model: row}
                for context, row in product(contexts, self.rows[model])
                if join_predicate.check({**context, model: row})
            ]
        contexts = [
            context
            for context in contexts
            if all(predicate.check(context) for predicate in statement.predicates)
        ]
        if statement.row_limit is not None:
            contexts = contexts[: statement.row_limit]
        return _FakeResult(
            [tuple(context[entity] for entity in statement.entities) for context in contexts]
        )


def _schema():
    models = SimpleNamespace(
        MeasurementTask=_model(
            "MeasurementTask",
            "id",
            "task_ref",
            "school_id",
            "class_id",
            "status",
            "cat_binding_mode",
            "opens_at",
            "due_at",
        ),
        SchoolClass=_model("SchoolClass", "id", "school_id", "class_ref", "status"),
        TaskEnrollment=_model(
            "TaskEnrollment",
            "id",
            "public_id",
            "task_id",
            "school_id",
            "class_id",
            "class_student_id",
            "subject_id",
            "status",
            "revoked_at",
        ),
        SchoolClassStudent=_model(
            "SchoolClassStudent",
            "id",
            "school_id",
            "class_id",
            "subject_id",
            "status",
            "revoked_at",
            "valid_from",
            "valid_until",
        ),
        Subject=_model("Subject", "id", "school_id", "subject_ref", "status", "data_origin"),
        SubjectAccessGrant=_model(
            "SubjectAccessGrant",
            "id",
            "school_id",
            "subject_id",
            "principal_account_id",
            "relationship_type",
            "status",
            "revoked_at",
            "valid_from",
            "valid_until",
        ),
        School=_model("School", "id", "school_ref", "status", "data_origin"),
        SchoolResearchSession=_model(
            "SchoolResearchSession",
            "id",
            "session_ref",
            "school_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "status",
        ),
    )
    enums = SimpleNamespace(
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC")),
        SubjectStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
        RelationshipType=SimpleNamespace(SELF=SimpleNamespace(value="SELF")),
        GrantStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
    )
    rows = {
        models.MeasurementTask: [
            SimpleNamespace(
                id=20,
                task_ref="TASK_demo_20",
                school_id=1,
                class_id=10,
                status="PUBLISHED",
                cat_binding_mode="RESEARCH_PROFILE",
                opens_at=_NOW - timedelta(days=1),
                due_at=_NOW + timedelta(days=1),
            )
        ],
        models.SchoolClass: [
            SimpleNamespace(id=10, school_id=1, class_ref="CLASS_demo_10", status="ACTIVE")
        ],
        models.TaskEnrollment: [
            SimpleNamespace(
                id=70,
                public_id="ENROLL_demo_70",
                task_id=20,
                school_id=1,
                class_id=10,
                class_student_id=40,
                subject_id=30,
                status="ACTIVE",
                revoked_at=None,
            )
        ],
        models.SchoolClassStudent: [
            SimpleNamespace(
                id=40,
                school_id=1,
                class_id=10,
                subject_id=30,
                status="ACTIVE",
                revoked_at=None,
                valid_from=_NOW - timedelta(days=5),
                valid_until=_NOW + timedelta(days=5),
            )
        ],
        models.Subject: [
            SimpleNamespace(
                id=30,
                school_id=1,
                subject_ref="SUBJECT_demo_30",
                status="ACTIVE",
                data_origin="SYNTHETIC",
            )
        ],
        models.SubjectAccessGrant: [
            SimpleNamespace(
                id=60,
                school_id=1,
                subject_id=30,
                principal_account_id=5,
                relationship_type="SELF",
                status="ACTIVE",
                revoked_at=None,
                valid_from=_NOW - timedelta(days=2),
                valid_until=_NOW + timedelta(days=2),
            )
        ],
        models.School: [
            SimpleNamespace(
                id=1,
                school_ref="SCHOOL_demo_1",
                status="ACTIVE",
                data_origin="SYNTHETIC",
            )
        ],
        models.SchoolResearchSession: [
            SimpleNamespace(
                id=80,
                session_ref="SESSION_demo_80",
                school_id=1,
                task_id=20,
                class_id=10,
                task_enrollment_id=70,
                subject_id=30,
                status="IN_PROGRESS",
            )
        ],
    }
    return models, enums, rows


def _actor(
    *, role=BackendRole.STUDENT, school_id=1, school_ref="SCHOOL_demo_1"
):
    return Actor(
        user_id="USER_demo_5",
        username="student-demo",
        role=role,
        subject_id="SUBJECT_untrusted_actor_hint",
        scope_profile="school_tenant",
        school_id=school_id,
        school_ref=school_ref,
        school_contexts=(
            SchoolRoleContext(
                context_id="50",
                role=role,
                school_id=school_id,
                school_ref=school_ref,
            ),
        ),
    )


async def _role_resolver(_actor, _at):
    return 5, 50


def _resolver_args(models, enums, rows, *, actor=None, role_resolver=_role_resolver):
    return {
        "session": _FakeSession(models, rows),
        "actor": actor or _actor(),
        "db_models": models,
        "db_enums": enums,
        "select": _select,
        "resolve_student_role": role_resolver,
        "at": _NOW,
    }


@pytest.mark.asyncio
async def test_task_scope_resolves_server_derived_self_enrollment_and_returns_frozen_projection():
    models, enums, rows = _schema()
    kwargs = _resolver_args(models, enums, rows)
    scope = await resolve_research_student_scope(task_ref="TASK_demo_20", **kwargs)

    assert scope == ResearchStudentScope(
        account_id=5,
        membership_role_id=50,
        school_id=1,
        school_ref="SCHOOL_demo_1",
        task_id=20,
        task_ref="TASK_demo_20",
        class_id=10,
        class_ref="CLASS_demo_10",
        task_enrollment_id=70,
        task_enrollment_ref="ENROLL_demo_70",
        subject_id=30,
        subject_ref="SUBJECT_demo_30",
    )
    assert not hasattr(scope, "answers")
    assert not hasattr(scope, "snapshot")
    assert not hasattr(scope, "profile_bytes")
    assert not {
        "answers",
        "snapshot",
        "raw_value",
        "signed_snapshot",
        "profile_bytes",
    }.intersection(field.name for field in fields(scope))
    with pytest.raises(FrozenInstanceError):
        scope.subject_id = 99  # type: ignore[misc]
    statement = kwargs["session"].statements[0]
    assert statement.row_limit == 2
    assert statement.options == {"populate_existing": True}
    assert models.SchoolResearchSession not in statement.entities


@pytest.mark.asyncio
async def test_session_scope_derives_and_binds_exact_session_to_active_student_scope():
    models, enums, rows = _schema()
    kwargs = _resolver_args(models, enums, rows)
    scope = await resolve_research_student_scope(
        session_ref="SESSION_demo_80",
        **kwargs,
    )
    assert scope.session_ref == "SESSION_demo_80"
    assert scope.research_session_id == 80
    statement = kwargs["session"].statements[0]
    assert statement.row_limit == 2
    assert statement.options == {"populate_existing": True}
    assert models.SchoolResearchSession in statement.entities


@pytest.mark.parametrize(
    "mutation",
    [
        "cross_school_actor",
        "cross_subject_grant",
        "other_principal_grant",
        "non_self_grant",
        "revoked_enrollment",
        "revoked_roster",
        "expired_roster",
        "revoked_self_grant",
        "expired_self_grant",
        "future_task_window",
        "expired_task_window",
        "wrong_task_mode",
        "closed_class",
        "production_subject",
        "duplicate_self_grant",
    ],
)
@pytest.mark.asyncio
async def test_task_scope_denies_cross_scope_revoked_expired_or_ambiguous_rows(mutation):
    models, enums, rows = _schema()
    actor = _actor()
    if mutation == "cross_school_actor":
        actor = _actor(school_id=2, school_ref="SCHOOL_other_2")
    elif mutation == "cross_subject_grant":
        rows[models.SubjectAccessGrant][0].subject_id = 31
    elif mutation == "other_principal_grant":
        rows[models.SubjectAccessGrant][0].principal_account_id = 6
    elif mutation == "non_self_grant":
        rows[models.SubjectAccessGrant][0].relationship_type = "TEACHER_OF"
    elif mutation == "revoked_enrollment":
        rows[models.TaskEnrollment][0].status = "REVOKED"
        rows[models.TaskEnrollment][0].revoked_at = _NOW
    elif mutation == "revoked_roster":
        rows[models.SchoolClassStudent][0].status = "REVOKED"
        rows[models.SchoolClassStudent][0].revoked_at = _NOW
    elif mutation == "expired_roster":
        rows[models.SchoolClassStudent][0].valid_until = _NOW - timedelta(seconds=1)
    elif mutation == "revoked_self_grant":
        rows[models.SubjectAccessGrant][0].status = "REVOKED"
        rows[models.SubjectAccessGrant][0].revoked_at = _NOW
    elif mutation == "expired_self_grant":
        rows[models.SubjectAccessGrant][0].valid_until = _NOW - timedelta(seconds=1)
    elif mutation == "future_task_window":
        rows[models.MeasurementTask][0].opens_at = _NOW + timedelta(seconds=1)
    elif mutation == "expired_task_window":
        rows[models.MeasurementTask][0].due_at = _NOW - timedelta(seconds=1)
    elif mutation == "wrong_task_mode":
        rows[models.MeasurementTask][0].cat_binding_mode = "SAVED_VERSION"
    elif mutation == "closed_class":
        rows[models.SchoolClass][0].status = "ARCHIVED"
    elif mutation == "production_subject":
        rows[models.Subject][0].data_origin = "PRODUCTION_PENDING"
    else:
        rows[models.SubjectAccessGrant].append(
            SimpleNamespace(**vars(rows[models.SubjectAccessGrant][0]))
        )

    with pytest.raises(ResearchScopeResolutionError) as caught:
        await resolve_research_student_scope(
            task_ref="TASK_demo_20",
            **_resolver_args(models, enums, rows, actor=actor),
        )
    assert caught.value.code == "research_scope_unavailable"
    assert "USER_demo_5" not in str(caught.value)


@pytest.mark.parametrize(
    "mutation", ["wrong_enrollment", "wrong_subject", "wrong_school", "wrong_task", "completed"]
)
@pytest.mark.asyncio
async def test_resume_scope_denies_session_not_bound_to_current_enrollment(mutation):
    models, enums, rows = _schema()
    target = rows[models.SchoolResearchSession][0]
    if mutation == "wrong_enrollment":
        target.task_enrollment_id = 71
    elif mutation == "wrong_subject":
        target.subject_id = 31
    elif mutation == "wrong_school":
        target.school_id = 2
    elif mutation == "wrong_task":
        target.task_id = 21
    else:
        target.status = "COMPLETED"

    with pytest.raises(ResearchScopeResolutionError):
        await resolve_research_student_scope(
            session_ref="SESSION_demo_80",
            **_resolver_args(models, enums, rows),
        )


@pytest.mark.asyncio
async def test_nonstudent_or_invalid_role_resolution_fails_before_query():
    models, enums, rows = _schema()
    resolver_called = False

    async def role_resolver(_actor, _at):
        nonlocal resolver_called
        resolver_called = True
        return 5, 50

    kwargs = _resolver_args(
        models,
        enums,
        rows,
        actor=_actor(role=BackendRole.TEACHER),
        role_resolver=role_resolver,
    )
    with pytest.raises(ResearchScopeResolutionError, match="research_actor_invalid"):
        await resolve_research_student_scope(task_ref="TASK_demo_20", **kwargs)
    assert not resolver_called
    assert kwargs["session"].statements == []


@pytest.mark.asyncio
async def test_revoked_persisted_student_role_hook_denial_propagates_without_fallback():
    models, enums, rows = _schema()
    calls = []

    async def revoked_role(_actor, _at):
        calls.append("resolved")
        raise RuntimeError("persisted student membership is revoked")

    kwargs = _resolver_args(models, enums, rows, role_resolver=revoked_role)
    with pytest.raises(RuntimeError, match="persisted student membership is revoked"):
        await resolve_research_student_scope(task_ref="TASK_demo_20", **kwargs)
    assert calls == ["resolved"]
    assert kwargs["session"].statements == []


@pytest.mark.asyncio
async def test_requires_exactly_one_server_resolved_reference_and_rejects_bad_hook_ids():
    models, enums, rows = _schema()
    kwargs = _resolver_args(models, enums, rows)
    with pytest.raises(ResearchScopeResolutionError, match="research_scope_reference_invalid"):
        await resolve_research_student_scope(**kwargs)
    with pytest.raises(ResearchScopeResolutionError, match="research_scope_reference_invalid"):
        await resolve_research_student_scope(
            task_ref="TASK_demo_20", session_ref="SESSION_demo_80", **kwargs
        )

    async def malformed_role(_actor, _at):
        return 0, 50

    with pytest.raises(ResearchScopeResolutionError, match="research_actor_invalid"):
        await resolve_research_student_scope(
            task_ref="TASK_demo_20",
            **_resolver_args(models, enums, rows, role_resolver=malformed_role),
        )
