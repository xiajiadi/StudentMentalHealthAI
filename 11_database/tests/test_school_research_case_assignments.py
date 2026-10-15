from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from database_layer.base import Base
from database_layer.models import SchoolResearchCaseAssignment, SchoolResearchTaskBinding
from database_layer.school_research_cat import (
    ResearchCatRepositoryError,
    ResearchCatRepositoryErrorCode,
    SchoolResearchCatRepository,
    _binding_metadata,
    _profile_metadata,
    _validate_public_case_index_plan,
)
from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def _fk(table, name: str):
    return next(item for item in table.foreign_key_constraints if item.name == name)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261014_0014_public_observed_case_assignments.py"
    )
    spec = spec_from_file_location("migration_20261014_0014", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_assignment_schema_is_private_exactly_scoped_and_mysql_compilable():
    assert len(Base.metadata.tables) == 59
    binding = SchoolResearchTaskBinding.__table__
    assignment = SchoolResearchCaseAssignment.__table__
    assert binding.c.corpus_sha256.nullable is True
    assert binding.c.case_count.nullable is True
    assert "800" in str(
        next(
            c
            for c in binding.constraints
            if isinstance(c, CheckConstraint) and "corpus_pin_shape" in c.name
        ).sqltext
    )
    assert assignment.c.case_count.server_default.arg == "800"
    assert assignment.c.purpose.server_default.arg == "RESEARCH_SIMULATION"
    assert {
        "raw_response", "raw_answers", "answers", "response", "case_payload",
        "student_id", "account_id", "display_name", "login_name", "password",
    }.isdisjoint(assignment.c.keys())
    assert len(str(CreateTable(binding).compile(dialect=mysql.dialect()))) > 0
    assert len(str(CreateTable(assignment).compile(dialect=mysql.dialect()))) > 0

    expected = {
        "fk_school_research_case_assignments_task_scope": (
            ("task_id", "school_id", "class_id"),
            ("measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"),
        ),
        "fk_school_research_case_assignments_enrollment_scope": (
            ("task_enrollment_id", "task_id", "school_id", "subject_id"),
            (
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ),
        ),
        "fk_school_research_case_assignments_subject_scope": (
            ("subject_id", "school_id"), ("subjects.id", "subjects.school_id"),
        ),
        "fk_school_research_case_assignments_binding_exact": (
            (
                "task_binding_id", "school_id", "task_id", "class_id", "profile_version_id",
                "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
                "corpus_sha256", "case_count",
            ),
            (
                "school_research_task_bindings.id", "school_research_task_bindings.school_id",
                "school_research_task_bindings.task_id", "school_research_task_bindings.class_id",
                "school_research_task_bindings.profile_version_id",
                "school_research_task_bindings.profile_ref",
                "school_research_task_bindings.profile_version_number",
                "school_research_task_bindings.profile_sha256",
                "school_research_task_bindings.response_origin",
                "school_research_task_bindings.corpus_sha256",
                "school_research_task_bindings.case_count",
            ),
        ),
    }
    for name, (local, remote) in expected.items():
        constraint = _fk(assignment, name)
        assert tuple(item.parent.name for item in constraint.elements) == local
        assert tuple(item.target_fullname for item in constraint.elements) == remote
        assert constraint.ondelete == "RESTRICT"


def _sqlite_assignment_fixture(*, legacy_binding: bool = False):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_fk_and_collation(dbapi_connection, _record):
        dbapi_connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        )
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    parents = MetaData()
    schools = Table("schools", parents, Column("id", Integer, primary_key=True))
    tasks = Table(
        "measurement_tasks", parents,
        Column("id", Integer, primary_key=True), Column("school_id", Integer, nullable=False),
        Column("class_id", Integer, nullable=False),
        UniqueConstraint("id", "school_id", "class_id"),
    )
    enrollments = Table(
        "task_enrollments", parents,
        Column("id", Integer, primary_key=True), Column("task_id", Integer, nullable=False),
        Column("school_id", Integer, nullable=False), Column("subject_id", Integer, nullable=False),
        UniqueConstraint("id", "task_id", "school_id", "subject_id"),
    )
    subjects = Table(
        "subjects", parents,
        Column("id", Integer, primary_key=True), Column("school_id", Integer, nullable=False),
        UniqueConstraint("id", "school_id"),
    )
    profiles = Table(
        "school_research_profile_versions", parents,
        Column("id", Integer, primary_key=True), Column("school_id", Integer, nullable=False),
        Column("profile_ref", String(128, collation="ascii_bin"), nullable=False),
        Column("version_number", Integer, nullable=False),
        Column("profile_sha256", String(64, collation="ascii_bin"), nullable=False),
        UniqueConstraint("id", "school_id", "profile_ref", "version_number", "profile_sha256"),
    )
    bindings = Table(
        "school_research_task_bindings", parents,
        Column("id", Integer, primary_key=True), Column("school_id", Integer, nullable=False),
        Column("task_id", Integer, nullable=False), Column("class_id", Integer, nullable=False),
        Column("profile_version_id", Integer, nullable=False),
        Column("profile_ref", String(128, collation="ascii_bin"), nullable=False),
        Column("profile_version_number", Integer, nullable=False),
        Column("profile_sha256", String(64, collation="ascii_bin"), nullable=False),
        Column("response_origin", String(32, collation="ascii_bin"), nullable=False),
        Column("corpus_sha256", String(64, collation="ascii_bin"), nullable=True),
        Column("case_count", Integer, nullable=True),
        Column("cohort_id", Integer, nullable=True),
        UniqueConstraint(
            "id", "school_id", "task_id", "class_id", "profile_version_id", "profile_ref",
            "profile_version_number", "profile_sha256", "response_origin", "corpus_sha256",
            "case_count",
        ),
        UniqueConstraint("id", "cohort_id"),
        CheckConstraint(
            "(corpus_sha256 IS NULL AND case_count IS NULL) OR "
            "(corpus_sha256 IS NOT NULL AND case_count IS NOT NULL AND case_count = 800)",
            name="corpus_pin_shape",
        ),
    )
    Table(
        "school_research_cohort_assignments", parents,
        Column("id", Integer, primary_key=True),
        Column("cohort_id", Integer, nullable=False),
        Column("school_id", Integer, nullable=False),
        Column("subject_id", Integer, nullable=False),
        Column("case_index", Integer, nullable=False),
        UniqueConstraint("id", "cohort_id", "school_id", "subject_id", "case_index"),
    )
    parents.create_all(engine)
    SchoolResearchCaseAssignment.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(schools.insert(), {"id": 1})
        connection.execute(tasks.insert(), {"id": 10, "school_id": 1, "class_id": 20})
        connection.execute(subjects.insert(), {"id": 40, "school_id": 1})
        connection.execute(
            enrollments.insert(),
            [
                {"id": 30, "task_id": 10, "school_id": 1, "subject_id": 40},
                {"id": 31, "task_id": 10, "school_id": 1, "subject_id": 40},
            ],
        )
        connection.execute(
            profiles.insert(),
            {
                "id": 50, "school_id": 1, "profile_ref": "profile-a",
                "version_number": 1, "profile_sha256": _SHA_A,
            },
        )
        connection.execute(
            bindings.insert(),
            {
                "id": 60, "school_id": 1, "task_id": 10, "class_id": 20,
                "profile_version_id": 50, "profile_ref": "profile-a",
                "profile_version_number": 1, "profile_sha256": _SHA_A,
                "response_origin": "PUBLIC_OBSERVED",
                "corpus_sha256": None if legacy_binding else _SHA_C,
                "case_count": None if legacy_binding else 800,
            },
        )
    return engine


def _assignment_row(**changes):
    row = {
        "id": 70,
        "public_id": str(uuid4()),
        "created_at": datetime.now(UTC).replace(tzinfo=None),
        "updated_at": datetime.now(UTC).replace(tzinfo=None),
        "school_id": 1,
        "task_id": 10,
        "class_id": 20,
        "task_enrollment_id": 30,
        "subject_id": 40,
        "task_binding_id": 60,
        "profile_version_id": 50,
        "profile_ref": "profile-a",
        "profile_version_number": 1,
        "profile_sha256": _SHA_A,
        "response_origin": "PUBLIC_OBSERVED",
        "corpus_sha256": _SHA_C,
        "case_count": 800,
        "case_index": 5,
        "purpose": "RESEARCH_SIMULATION",
    }
    row.update(changes)
    return row


def test_sqlite_composite_fks_and_uniques_reject_cross_scope_duplicate_and_legacy_pins():
    engine = _sqlite_assignment_fixture()
    table = SchoolResearchCaseAssignment.__table__
    with engine.begin() as connection:
        connection.execute(table.insert(), _assignment_row())
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(table.insert(), _assignment_row(id=71, school_id=2))
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    table.insert(), _assignment_row(id=72, task_enrollment_id=999)
                )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    table.insert(), _assignment_row(id=73, task_enrollment_id=31)
                )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    table.insert(), _assignment_row(id=74, corpus_sha256=_SHA_B)
                )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(table.insert(), _assignment_row(id=75, case_index=800))

    legacy = _sqlite_assignment_fixture(legacy_binding=True)
    with legacy.begin() as connection:
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(table.insert(), _assignment_row())


def test_binding_corpus_pin_check_rejects_each_half_null_but_keeps_legacy_null_pair():
    engine = _sqlite_assignment_fixture(legacy_binding=True)
    bindings = Table("school_research_task_bindings", MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        for corpus_sha256, case_count in ((_SHA_C, None), (None, 800)):
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        bindings.update()
                        .where(bindings.c.id == 60)
                        .values(corpus_sha256=corpus_sha256, case_count=case_count)
                    )
        result = connection.execute(
            bindings.select().where(bindings.c.id == 60)
        ).one()
        assert result.corpus_sha256 is None
        assert result.case_count is None


def test_plan_requires_unique_in_range_indices_and_full_800_permutation():
    one = _validate_public_case_index_plan((17,))
    assert one == (17,)
    full = tuple(range(800))
    assert len(_validate_public_case_index_plan(full)) == 800
    for invalid in (
        (1, 1),
        (800,),
        (True,),
        (),
    ):
        with pytest.raises(ResearchCatRepositoryError) as caught:
            _validate_public_case_index_plan(invalid)
        assert caught.value.code is ResearchCatRepositoryErrorCode.CASE_ASSIGNMENT_INVALID


def test_binding_metadata_exposes_nullable_corpus_pin_without_changing_legacy_rows():
    metadata = _binding_metadata(
        SimpleNamespace(
            id=60, school_id=1, task_id=10, class_id=20, profile_version_id=50,
            profile_ref="profile-a", profile_version_number=1, profile_sha256=_SHA_A,
            response_origin="PUBLIC_OBSERVED", status="ACTIVE", config_version="cfg-v1",
            config_sha256=_SHA_B, research_only=True,
            created_at=datetime.now(UTC).replace(tzinfo=None), revoked_at=None,
            corpus_sha256=None, case_count=None,
        )
    )
    assert metadata.corpus_sha256 is None
    assert metadata.case_count is None


class _FakeSession:
    def __init__(self, enrollments=(), final_enrollment_ids=None):
        self.enrollments = list(enrollments)
        self.final_enrollment_ids = final_enrollment_ids
        self.added = []
        self.scalars_calls = 0
        self.flush_calls = 0

    async def scalars(self, statement):
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            rows = self.enrollments
        else:
            rows = self.final_enrollment_ids or [row.id for row in self.enrollments]
        return SimpleNamespace(all=lambda: list(rows))

    def add_all(self, rows):
        self.added.extend(rows)

    async def flush(self):
        self.flush_calls += 1


def _binding(*, corpus_sha256=_SHA_C, cohort_id=None):
    return SimpleNamespace(
        id=60, school_id=1, task_id=10, class_id=20, profile_version_id=50,
        profile_ref="profile-a", profile_version_number=1, profile_sha256=_SHA_A,
        response_origin="PUBLIC_OBSERVED", corpus_sha256=corpus_sha256,
        case_count=800, cohort_id=cohort_id,
    )


@pytest.mark.asyncio
async def test_repository_inserts_complete_small_scope_plan_without_commit_or_public_repr():
    candidates = [
        SimpleNamespace(id=30, school_id=1, task_id=10, class_id=20, subject_id=40),
        SimpleNamespace(id=31, school_id=1, task_id=10, class_id=20, subject_id=40),
    ]
    session = _FakeSession(candidates, final_enrollment_ids=(30, 31))
    repo = object.__new__(SchoolResearchCatRepository)
    repo.session = session
    repo._require_synthetic_school = _async_noop
    repo._require_active_membership_role = _async_noop
    repo._lock_active_task_binding = _async_binding
    repo._require_session_scope = _async_scope
    repo._one = _async_none

    result = await repo.create_public_observed_case_assignments(
        school_id=1, task_id=10, class_id=20, task_binding_id=60,
        expected_profile_sha256=_SHA_A, expected_corpus_sha256=_SHA_C,
        creator_membership_role_id=7, case_index_plan=(2, 9),
    )
    assert len(result) == 2
    assert session.flush_calls == 1
    assert len(session.added) == 2
    assert session.added[0].case_index == 2
    assert session.added[1].case_index == 9
    assert session.added[0].purpose == "RESEARCH_SIMULATION"
    assert "case_index" not in repr(result[0])
    assert "task_enrollment_id" not in repr(result[1])


@pytest.mark.asyncio
async def test_repository_refuses_legacy_null_corpus_binding_before_enrollment_query():
    session = _FakeSession()
    repo = object.__new__(SchoolResearchCatRepository)
    repo.session = session
    repo._require_synthetic_school = _async_noop
    repo._require_active_membership_role = _async_noop
    repo._lock_active_task_binding = _async_binding_without_corpus

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_public_observed_case_assignments(
            school_id=1, task_id=10, class_id=20, task_binding_id=60,
            expected_profile_sha256=_SHA_A, expected_corpus_sha256=_SHA_C,
            creator_membership_role_id=7, case_index_plan=(0,),
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CORPUS_PIN_UNAVAILABLE
    assert session.scalars_calls == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_cohort_assignment_reuses_exact_sealed_mapping_and_rejects_new_plan():
    candidates = [
        SimpleNamespace(
            id=30 + offset,
            school_id=1,
            task_id=10,
            class_id=20,
            class_student_id=1030 + offset,
            subject_id=40 + offset,
        )
        for offset in range(100)
    ]
    session = _FakeSession(candidates, final_enrollment_ids=tuple(row.id for row in candidates))
    repo = object.__new__(SchoolResearchCatRepository)
    repo.session = session
    repo._require_synthetic_school = _async_noop
    repo._require_active_membership_role = _async_noop
    repo._lock_active_task_binding = _async_binding_with_cohort
    repo._require_session_scope = _async_scope
    repo._require_sealed_cohort_scope = _async_cohort_scope
    repo._one = _async_none

    async def cohort_assignment(**scope):
        offset = scope["subject_id"] - 40
        assert scope["class_id"] == 20
        assert scope["class_student_id"] == 1030 + offset
        return SimpleNamespace(
            cohort_id=900,
            school_id=1,
            class_id=20,
            class_student_id=1030 + offset,
            subject_id=40 + offset,
            assignment_id=5000 + offset,
            case_index=799 - offset,
        )

    repo._require_cohort_case_assignment = cohort_assignment
    result = await repo.create_public_observed_case_assignments(
        school_id=1,
        task_id=10,
        class_id=20,
        task_binding_id=60,
        expected_profile_sha256=_SHA_A,
        expected_corpus_sha256=_SHA_C,
        creator_membership_role_id=7,
        case_index_plan=None,
    )
    assert len(result) == 100
    assert [row.case_index for row in session.added] == list(range(799, 699, -1))
    assert {row.cohort_id for row in session.added} == {900}
    assert {row.cohort_assignment_id for row in session.added} == set(range(5000, 5100))
    assert "case_index" not in repr(result[0])
    assert "cohort_assignment_id" not in repr(result[0])

    rejected_session = _FakeSession(candidates)
    rejected = object.__new__(SchoolResearchCatRepository)
    rejected.session = rejected_session
    rejected._require_synthetic_school = _async_noop
    rejected._require_active_membership_role = _async_noop
    rejected._lock_active_task_binding = _async_binding_with_cohort
    with pytest.raises(ResearchCatRepositoryError) as caught:
        await rejected.create_public_observed_case_assignments(
            school_id=1,
            task_id=10,
            class_id=20,
            task_binding_id=60,
            expected_profile_sha256=_SHA_A,
            expected_corpus_sha256=_SHA_C,
            creator_membership_role_id=7,
            case_index_plan=(0,),
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CASE_ASSIGNMENT_INVALID
    assert rejected_session.scalars_calls == 0
    assert rejected_session.added == []


@pytest.mark.asyncio
async def test_cohort_assignment_requires_exact_one_hundred_active_members():
    candidates = [
        SimpleNamespace(
            id=30 + offset,
            school_id=1,
            task_id=10,
            class_id=20,
            class_student_id=1030 + offset,
            subject_id=40 + offset,
        )
        for offset in range(99)
    ]
    session = _FakeSession(candidates, final_enrollment_ids=tuple(row.id for row in candidates))
    repo = object.__new__(SchoolResearchCatRepository)
    repo.session = session
    repo._require_synthetic_school = _async_noop
    repo._require_active_membership_role = _async_noop
    repo._lock_active_task_binding = _async_binding_with_cohort
    repo._require_sealed_cohort_scope = _async_cohort_scope

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_public_observed_case_assignments(
            school_id=1,
            task_id=10,
            class_id=20,
            task_binding_id=60,
            expected_profile_sha256=_SHA_A,
            expected_corpus_sha256=_SHA_C,
            creator_membership_role_id=7,
            case_index_plan=None,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CASE_ASSIGNMENT_INVALID
    assert session.added == []


@pytest.mark.asyncio
async def test_assignment_lookup_locks_metadata_scope_before_return_and_never_decrypts():
    session = _FakeSession()
    repo = object.__new__(SchoolResearchCatRepository)
    repo.session = session
    events = []
    binding = _binding()
    task = SimpleNamespace(class_id=20)
    enrollment = SimpleNamespace(id=30, task_id=10, school_id=1, class_id=20, subject_id=40)
    subject = SimpleNamespace(id=40)
    row = SimpleNamespace(
        school_id=1, task_id=10, class_id=20, task_enrollment_id=30, subject_id=40,
        task_binding_id=60, profile_version_id=50, profile_ref="profile-a",
        profile_version_number=1, profile_sha256=_SHA_A, corpus_sha256=_SHA_C,
        case_count=800, case_index=11,
    )

    async def lock_binding(**_kwargs):
        events.append("profile_task_binding_class")
        return binding, SimpleNamespace(profile_sha256=_SHA_A), task

    async def lock_scope(**_kwargs):
        events.append("roster_enrollment_subject")
        return enrollment, task, object(), subject, object()

    async def get_assignment(*_args, **_kwargs):
        events.append("assignment")
        return row

    repo._lock_active_task_binding = lock_binding
    repo._require_session_scope = lock_scope
    repo._one = get_assignment
    now = datetime.now(UTC).replace(tzinfo=None)
    profile = _profile_metadata(
        SimpleNamespace(
            id=50, school_id=1, profile_ref="profile-a", version_number=1,
            instrument_id="instrument", dimension="dimension",
            source_population_scope="synthetic-fixture", profile_sha256=_SHA_A,
            manifest_sha256=_SHA_B, fit_sha256=None, calibration_sha256=None,
            parameter_origin="LOCAL_RESEARCH_FIT",
            published_parameter_crosswalk_sha256=None, rights_status="VERIFIED",
            execution_status="SIMULATION_ENABLED", research_only=True,
            human_curated=False, psychological_interpretation_allowed=False,
            publication_status="not_approved_for_publication_or_operational_use",
            created_at=now, simulation_enabled_at=now, rights_revoked_at=None,
            disabled_at=None,
        )
    )
    binding = _binding_metadata(
        SimpleNamespace(
            id=60, school_id=1, task_id=10, class_id=20, profile_version_id=50,
            profile_ref="profile-a", profile_version_number=1,
            profile_sha256=_SHA_A, response_origin="PUBLIC_OBSERVED", status="ACTIVE",
            config_version="config-v1", config_sha256=_SHA_B, research_only=True,
            created_at=now, revoked_at=None, corpus_sha256=_SHA_C, case_count=800,
        )
    )
    result = await repo.require_public_observed_case_assignment(
        profile=profile, binding=binding, task_enrollment_id=30, subject_id=40,
        expected_profile_sha256=_SHA_A, expected_corpus_sha256=_SHA_C,
    )
    assert events == ["assignment"]
    assert result.case_index == 11
    assert repr(result) == object.__repr__(result)


@pytest.mark.asyncio
async def test_cohort_student_assignment_matches_locked_roster_identity_before_read():
    session = _FakeSession()
    scalar_calls = []

    async def scalar(statement):
        scalar_calls.append(statement)
        return 1030

    session.scalar = scalar
    repo = object.__new__(SchoolResearchCatRepository)
    repo.session = session
    binding = _binding_metadata(
        SimpleNamespace(
            id=60,
            school_id=1,
            task_id=10,
            class_id=20,
            profile_version_id=50,
            profile_ref="profile-a",
            profile_version_number=1,
            profile_sha256=_SHA_A,
            response_origin="PUBLIC_OBSERVED",
            status="ACTIVE",
            config_version="config-v1",
            config_sha256=_SHA_B,
            research_only=True,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            revoked_at=None,
            corpus_sha256=_SHA_C,
            case_count=800,
            cohort_id=900,
        )
    )
    profile = SimpleNamespace(
        school_id=1,
        profile_version_id=50,
        profile_ref="profile-a",
        version_number=1,
        profile_sha256=_SHA_A,
        manifest_sha256=_SHA_B,
    )
    row = SimpleNamespace(
        school_id=1,
        task_id=10,
        class_id=20,
        task_enrollment_id=30,
        subject_id=40,
        task_binding_id=60,
        profile_version_id=50,
        profile_ref="profile-a",
        profile_version_number=1,
        profile_sha256=_SHA_A,
        corpus_sha256=_SHA_C,
        case_count=800,
        case_index=77,
        cohort_id=900,
        cohort_assignment_id=5077,
    )
    seen_conditions = []

    async def sealed_scope(**kwargs):
        assert kwargs["cohort_id"] == 900
        assert kwargs["expected_study_ref"] == "study-fixture-v1"
        assert kwargs["verify_seal"] is False
        return SimpleNamespace(id=900)

    async def member_assignment(**kwargs):
        assert kwargs == {
            "cohort_id": 900,
            "school_id": 1,
            "class_id": 20,
            "class_student_id": 1030,
            "subject_id": 40,
        }
        return SimpleNamespace(assignment_id=5077)

    async def assignment_row(_model, *conditions, **_kwargs):
        seen_conditions.extend(str(item) for item in conditions)
        return row

    repo._require_sealed_cohort_scope = sealed_scope
    repo._require_cohort_case_assignment = member_assignment
    repo._one = assignment_row
    result = await repo.require_public_observed_case_assignment(
        profile=profile,
        binding=binding,
        task_enrollment_id=30,
        subject_id=40,
        expected_profile_sha256=_SHA_A,
        expected_corpus_sha256=_SHA_C,
        expected_study_ref="study-fixture-v1",
    )
    assert len(scalar_calls) == 1
    assert "class_student_id" in str(scalar_calls[0])
    assert any("cohort_assignment_id" in item for item in seen_conditions)
    assert result.cohort_id == 900
    assert result.cohort_assignment_id == 5077
    assert "cohort_assignment_id" not in repr(result)
    assert "case_index" not in repr(result)

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.require_public_observed_case_assignment(
            profile=profile,
            binding=binding,
            task_enrollment_id=30,
            subject_id=40,
            expected_profile_sha256=_SHA_A,
            expected_corpus_sha256=_SHA_C,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CORPUS_PIN_UNAVAILABLE


@pytest.mark.asyncio
async def test_task_assignment_replay_requires_full_exact_existing_mapping():
    session = _FakeSession()
    repo = object.__new__(SchoolResearchCatRepository)
    repo.session = session
    binding = _binding()
    profile = SimpleNamespace(profile_sha256=_SHA_A)
    task = SimpleNamespace(class_id=20)
    assignments = [
        SimpleNamespace(
            task_enrollment_id=30, case_index=14, profile_sha256=_SHA_A,
            corpus_sha256=_SHA_C, case_count=800, response_origin="PUBLIC_OBSERVED",
            purpose="RESEARCH_SIMULATION", task_binding_id=60, profile_version_id=50,
            profile_ref="profile-a", profile_version_number=1,
        ),
        SimpleNamespace(
            task_enrollment_id=31, case_index=29, profile_sha256=_SHA_A,
            corpus_sha256=_SHA_C, case_count=800, response_origin="PUBLIC_OBSERVED",
            purpose="RESEARCH_SIMULATION", task_binding_id=60, profile_version_id=50,
            profile_ref="profile-a", profile_version_number=1,
        ),
    ]

    async def lock_binding(**_kwargs):
        return binding, profile, task

    class _MappingSession:
        def __init__(self, rows):
            self.responses = iter(
                (
                    SimpleNamespace(all=lambda: [30, 31]),
                    SimpleNamespace(all=lambda: rows),
                )
            )

        async def scalars(self, _statement):
            return next(self.responses)

    repo._lock_active_task_binding = lock_binding
    repo.session = _MappingSession(assignments)
    assert await repo.require_public_observed_task_assignments(
        school_id=1, task_id=10, class_id=20, task_binding_id=60,
        expected_profile_sha256=_SHA_A, expected_corpus_sha256=_SHA_C,
    ) is None

    repo.session = _MappingSession(assignments[:1])
    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.require_public_observed_task_assignments(
            school_id=1, task_id=10, class_id=20, task_binding_id=60,
            expected_profile_sha256=_SHA_A, expected_corpus_sha256=_SHA_C,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CASE_ASSIGNMENT_NOT_FOUND


@pytest.mark.asyncio
async def test_cohort_task_assignment_replay_rechecks_exact_active_members_and_map():
    candidates = [
        SimpleNamespace(
            id=30 + offset,
            school_id=1,
            task_id=10,
            class_id=20,
            class_student_id=1030 + offset,
            subject_id=40 + offset,
        )
        for offset in range(100)
    ]
    candidate_by_id = {row.id: row for row in candidates}
    assignments = [
        SimpleNamespace(
            task_enrollment_id=row.id,
            subject_id=row.subject_id,
            case_index=offset,
            profile_sha256=_SHA_A,
            corpus_sha256=_SHA_C,
            case_count=800,
            response_origin="PUBLIC_OBSERVED",
            purpose="RESEARCH_SIMULATION",
            task_binding_id=60,
            profile_version_id=50,
            profile_ref="profile-a",
            profile_version_number=1,
            cohort_id=900,
            cohort_assignment_id=5000 + offset,
        )
        for offset, row in enumerate(candidates)
    ]

    class _MappingSession:
        def __init__(self, assignment_rows):
            self.responses = iter(
                (
                    SimpleNamespace(all=lambda: candidates),
                    SimpleNamespace(all=lambda: [row.id for row in candidates]),
                    SimpleNamespace(all=lambda: assignment_rows),
                )
            )

        async def scalars(self, _statement):
            return next(self.responses)

    repo = object.__new__(SchoolResearchCatRepository)
    binding = _binding(cohort_id=900)

    async def lock_binding(**_kwargs):
        return binding, SimpleNamespace(profile_sha256=_SHA_A), SimpleNamespace(class_id=20)

    async def sealed_scope(**_kwargs):
        return SimpleNamespace(id=900)

    async def locked_scope(**kwargs):
        candidate = candidate_by_id[kwargs["task_enrollment_id"]]
        enrollment = candidate
        roster = SimpleNamespace(id=candidate.class_student_id)
        return enrollment, SimpleNamespace(class_id=20), roster, SimpleNamespace(
            id=candidate.subject_id
        ), SimpleNamespace(id=20)

    async def member_assignment(**kwargs):
        offset = kwargs["subject_id"] - 40
        assert kwargs["class_student_id"] == 1030 + offset
        return SimpleNamespace(
            assignment_id=5000 + offset,
            case_index=offset,
        )

    repo._lock_active_task_binding = lock_binding
    repo._require_sealed_cohort_scope = sealed_scope
    repo._require_session_scope = locked_scope
    repo._require_cohort_case_assignment = member_assignment
    repo.session = _MappingSession(assignments)
    assert await repo.require_public_observed_task_assignments(
        school_id=1,
        task_id=10,
        class_id=20,
        task_binding_id=60,
        expected_profile_sha256=_SHA_A,
        expected_corpus_sha256=_SHA_C,
    ) is None

    malformed = [SimpleNamespace(**vars(row)) for row in assignments]
    malformed[0].cohort_assignment_id = 5999
    repo.session = _MappingSession(malformed)
    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.require_public_observed_task_assignments(
            school_id=1,
            task_id=10,
            class_id=20,
            task_binding_id=60,
            expected_profile_sha256=_SHA_A,
            expected_corpus_sha256=_SHA_C,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CASE_ASSIGNMENT_NOT_FOUND

    duplicate_index = dict(vars(assignments[1]))
    duplicate_index["case_index"] = 14
    malformed = [assignments[0], SimpleNamespace(**duplicate_index)]
    repo.session = _MappingSession(malformed)
    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.require_public_observed_task_assignments(
            school_id=1, task_id=10, class_id=20, task_binding_id=60,
            expected_profile_sha256=_SHA_A, expected_corpus_sha256=_SHA_C,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CASE_ASSIGNMENT_NOT_FOUND


def _async_noop(*_args, **_kwargs):
    async def _return_none():
        return None

    return _return_none()


def _async_binding(*_args, **_kwargs):
    async def _return_binding():
        return _binding(), SimpleNamespace(profile_sha256=_SHA_A), SimpleNamespace(class_id=20)

    return _return_binding()


def _async_binding_without_corpus(*_args, **_kwargs):
    async def _return_binding():
        return (
            _binding(corpus_sha256=None),
            SimpleNamespace(profile_sha256=_SHA_A),
            SimpleNamespace(class_id=20),
        )

    return _return_binding()


def _async_scope(*_args, **kwargs):
    async def _return_scope():
        enrollment_id = kwargs["task_enrollment_id"]
        subject_id = kwargs["subject_id"]
        return (
            SimpleNamespace(
                id=enrollment_id, school_id=1, task_id=10, class_id=20,
                class_student_id=enrollment_id + 1000, subject_id=subject_id,
            ),
            SimpleNamespace(class_id=20),
            SimpleNamespace(id=enrollment_id + 1000),
            SimpleNamespace(id=subject_id),
            SimpleNamespace(id=20),
        )

    return _return_scope()


def _async_binding_with_cohort(*_args, **_kwargs):
    async def _return_binding():
        return (
            _binding(cohort_id=900),
            SimpleNamespace(profile_sha256=_SHA_A),
            SimpleNamespace(class_id=20),
        )

    return _return_binding()


def _async_cohort_scope(*_args, **_kwargs):
    async def _return_cohort():
        return SimpleNamespace(id=900)

    return _return_cohort()


def _async_none(*_args, **_kwargs):
    async def _return_none():
        return None

    return _return_none()


def test_assignment_migration_is_additive_and_preserves_existing_pins(monkeypatch):
    migration = _load_migration()
    assert migration.revision == "20261014_0014"
    assert migration.down_revision == "20261014_0013"
    operations = []

    class _Connection:
        def __init__(self, counts):
            self.counts = iter(counts)

        def execute(self, statement):
            operations.append(("guard", str(statement)))
            value = next(self.counts)
            return SimpleNamespace(scalar_one=lambda: value)

    class _Ops:
        def __init__(self, counts=(0, 0)):
            self.counts = counts

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.counts)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    created = next(item for item in operations if item[0] == "create_table")
    migrated_assignment = Table(
        created[1], MetaData(), *created[2:-1], **created[-1]
    )
    migrated_columns = {
        column.name for column in migrated_assignment.c
    }
    assert migrated_columns == (
        set(SchoolResearchCaseAssignment.__table__.c.keys())
        - {"cohort_id", "cohort_assignment_id"}
    )
    assert tuple(migrated_assignment.c.keys()) == tuple(
        name for name in SchoolResearchCaseAssignment.__table__.c.keys()
        if name not in {"cohort_id", "cohort_assignment_id"}
    )
    assert {"corpus_sha256", "case_count"} == {
        item[2].name for item in operations if item[0] == "add_column"
    }
    assert not any(item[0] in {"drop_table", "drop_column"} for item in operations)

    model_assignment = SchoolResearchCaseAssignment.__table__
    assert len(str(CreateTable(model_assignment).compile(dialect=mysql.dialect()))) > 0
    assert {
        (
            constraint.name,
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in migrated_assignment.foreign_key_constraints
    } == {
        (
            constraint.name,
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in model_assignment.foreign_key_constraints
        if constraint.name not in {
            "fk_school_research_case_assignments_cohort_exact",
            "fk_school_research_case_assignments_binding_cohort",
        }
    }
    assert {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in migrated_assignment.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in model_assignment.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert {
        (constraint.name, str(constraint.sqltext))
        for constraint in migrated_assignment.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        (
            constraint.name.removeprefix("ck_school_research_case_assignments_"),
            str(constraint.sqltext),
        )
        for constraint in model_assignment.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name != "ck_school_research_case_assignments_cohort_assignment_pair"
    }

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops(counts=(1, 0)))
    with pytest.raises(RuntimeError, match="cannot downgrade public case assignments"):
        migration.downgrade()
    assert [item[0] for item in operations] == ["guard", "guard"]

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops(counts=(0, 1)))
    with pytest.raises(RuntimeError, match="cannot downgrade public case assignments"):
        migration.downgrade()
    assert [item[0] for item in operations] == ["guard", "guard"]
