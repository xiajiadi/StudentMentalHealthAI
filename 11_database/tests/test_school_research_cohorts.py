from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.fernet import Fernet
from database_layer.base import Base
from database_layer.crypto import FernetDataProtectionProvider, MappingKeyProvider
from database_layer.models import (
    Account,
    AccountSchoolMembership,
    MeasurementTask,
    MembershipRole,
    School,
    SchoolAccountBatch,
    SchoolAccountProvision,
    SchoolClass,
    SchoolClassStudent,
    SchoolResearchCaseAssignment,
    SchoolResearchCohort,
    SchoolResearchCohortAssignment,
    SchoolResearchCohortBatch,
    SchoolResearchProfileVersion,
    SchoolResearchTaskBinding,
    Subject,
    SubjectAccessGrant,
    TaskEnrollment,
)
from database_layer.provenance import SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
from database_layer.school_research_cat import (
    ResearchCatRepositoryError,
    ResearchCatRepositoryErrorCode,
    SchoolResearchCatRepository,
    _canonical_json,
)
from database_layer.school_research_cohorts import (
    ResearchCohortErrorCode,
    ResearchCohortRepositoryError,
    SchoolResearchCohortRepository,
    _assignment_map_sha256,
    _eligible_profile,
)
from sqlalchemy import (
    CheckConstraint,
    Column,
    Table,
    UniqueConstraint,
    create_engine,
    event,
    select,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

_PROFILE_SHA = "a" * 64
_MANIFEST_SHA = "b" * 64
_CORPUS_SHA = "c" * 64
_CROSSWALK_SHA = "d" * 64
_AT = datetime(2026, 10, 14, 8, 0, tzinfo=UTC).replace(tzinfo=None)


class _AsyncSessionAdapter:
    """Run async repository methods over a real sync SQLite ORM session."""

    def __init__(self, session: Session) -> None:
        self.sync = session
        self.flush_count = 0
        self.fail_flush_number: int | None = None
        self.locked_models = []

    def _record_lock(self, statement):
        if statement._for_update_arg is not None:
            self.locked_models.append(statement.column_descriptions[0]["entity"])

    async def scalar(self, statement):
        self._record_lock(statement)
        return self.sync.scalar(statement)

    async def scalars(self, statement):
        self._record_lock(statement)
        return self.sync.scalars(statement)

    async def execute(self, statement):
        return self.sync.execute(statement)

    def add(self, instance):
        self.sync.add(instance)

    def add_all(self, instances):
        self.sync.add_all(instances)

    async def flush(self):
        self.flush_count += 1
        if self.fail_flush_number == self.flush_count:
            raise IntegrityError("synthetic flush", {}, RuntimeError("injected constraint failure"))
        self.sync.flush()

    @asynccontextmanager
    async def begin_nested(self):
        with self.sync.begin_nested():
            yield self


@pytest.fixture
def sqlite_engine(monkeypatch):
    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch

    def compile_sqlite_blob(self, visitor, **kw):
        if visitor.dialect.name == "sqlite":
            return "BLOB"
        return medium_blob_dispatch(self, visitor, **kw)

    def compile_sqlite_bigint(self, visitor, **kw):
        if visitor.dialect.name == "sqlite":
            return "INTEGER"
        return big_int_dispatch(self, visitor, **kw)

    monkeypatch.setattr(medium_blob_cls, "_compiler_dispatch", compile_sqlite_blob)
    monkeypatch.setattr(big_int_cls, "_compiler_dispatch", compile_sqlite_bigint)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_sqlite_constraints(connection, _record):
        connection.create_collation("ascii_bin", lambda a, b: (a > b) - (a < b))
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _seed_full_cohort(session: Session) -> None:
    session.add_all(
        [
            School(
                id=1,
                school_ref="synthetic-school",
                display_name="Synthetic School",
                status="ACTIVE",
                data_origin="SYNTHETIC",
                provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
            ),
            Account(
                id=1,
                login_name="cohort-operator",
                password_hash="not-a-real-password-hash",
                status="ACTIVE",
            ),
        ]
    )
    session.flush()
    session.add(
        AccountSchoolMembership(
            id=1,
            account_id=1,
            school_id=1,
            display_name="Operator",
            status="ACTIVE",
            valid_from=_AT - timedelta(days=1),
        )
    )
    session.flush()
    session.add(
        MembershipRole(
            id=1,
            membership_id=1,
            school_id=1,
            role_code="admin",
            status="ACTIVE",
            valid_from=_AT - timedelta(days=1),
        )
    )
    session.flush()
    session.add(
        SchoolResearchProfileVersion(
            id=50,
            school_id=1,
            profile_ref="pinned-promis",
            version_number=3,
            instrument_id="PROMIS_PEDIATRIC_ANXIETY_RESEARCH",
            dimension="PROMIS_PEDIATRIC_ANXIETY_RESEARCH",
            source_population_scope="US_CHILDREN_8_17",
            profile_sha256=_PROFILE_SHA,
            manifest_sha256=_MANIFEST_SHA,
            fit_sha256=None,
            calibration_sha256=None,
            rights_status="VERIFIED",
            execution_status="SIMULATION_ENABLED",
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            human_curated=False,
            psychological_interpretation_allowed=False,
            publication_status="not_approved_for_publication_or_operational_use",
            payload_ciphertext=b"ciphertext-only-fixture",
            cipher_format_version="fernet.v1",
            key_version="test-key-v1",
            payload_schema_version="research-profile.v3",
            created_by_membership_role_id=1,
            status_changed_by_membership_role_id=1,
            simulation_enabled_at=_AT - timedelta(days=1),
            parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
            published_parameter_crosswalk_sha256=_CROSSWALK_SHA,
        )
    )
    session.flush()
    for class_index in range(8):
        session.add(
            SchoolClass(
                id=100 + class_index,
                school_id=1,
                class_ref=f"class-{class_index:02d}",
                display_name=f"Class {class_index}",
                created_by_membership_role_id=1,
                status="ACTIVE",
            )
        )
    session.flush()
    for class_index in range(8):
        session.add(
            SchoolAccountBatch(
                id=200 + class_index,
                batch_ref=f"batch-{class_index:02d}",
                school_id=1,
                created_by_membership_role_id=1,
                class_id=100 + class_index,
                row_count=100,
            )
        )
    session.flush()
    accounts, memberships, roles, subjects = [], [], [], []
    for offset in range(800):
        account_id = 1000 + offset
        membership_id = 2000 + offset
        role_id = 3000 + offset
        subject_id = 4000 + offset
        accounts.append(
            Account(
                id=account_id,
                login_name=f"synthetic-student-{offset:04d}",
                password_hash="synthetic-account-hash",
                status="ACTIVE",
            )
        )
        memberships.append(
            AccountSchoolMembership(
                id=membership_id,
                account_id=account_id,
                school_id=1,
                display_name=f"Synthetic Student {offset:04d}",
                status="ACTIVE",
                valid_from=_AT - timedelta(days=1),
            )
        )
        roles.append(
            MembershipRole(
                id=role_id,
                membership_id=membership_id,
                school_id=1,
                role_code="student",
                status="ACTIVE",
                valid_from=_AT - timedelta(days=1),
            )
        )
        subjects.append(
            Subject(
                id=subject_id,
                subject_ref=f"subject-{offset:04d}",
                school_id=1,
                status="ACTIVE",
                data_origin="SYNTHETIC",
            )
        )
    session.add_all(accounts)
    session.flush()
    session.add_all(memberships)
    session.flush()
    session.add_all(roles)
    session.add_all(subjects)
    session.flush()
    grants, provisions, rosters = [], [], []
    for offset in range(800):
        class_index, row_no = divmod(offset, 100)
        account_id = 1000 + offset
        membership_id = 2000 + offset
        role_id = 3000 + offset
        subject_id = 4000 + offset
        grants.append(
            SubjectAccessGrant(
                id=5000 + offset,
                principal_account_id=account_id,
                subject_id=subject_id,
                school_id=1,
                relationship_type="SELF",
                status="ACTIVE",
                valid_from=_AT - timedelta(days=1),
            )
        )
        provisions.append(
            SchoolAccountProvision(
                id=6000 + offset,
                school_id=1,
                batch_id=200 + class_index,
                account_id=account_id,
                membership_id=membership_id,
                membership_role_id=role_id,
                row_no=row_no,
                role_code="student",
                status="ACTIVE",
                activated_at=_AT - timedelta(days=1),
            )
        )
        rosters.append(
            SchoolClassStudent(
                id=7000 + offset,
                school_id=1,
                class_id=100 + class_index,
                subject_id=subject_id,
                status="ACTIVE",
                valid_from=_AT - timedelta(days=1),
            )
        )
    session.add_all(grants + provisions + rosters)
    session.flush()


def _seal(repo: SchoolResearchCohortRepository, **overrides):
    values = {
        "school_id": 1,
        "cohort_ref": "cohort-fixture-v1",
        "study_ref": "study-fixture-v1",
        "profile_version_id": 50,
        "profile_ref": "pinned-promis",
        "profile_version_number": 3,
        "expected_profile_sha256": _PROFILE_SHA,
        "expected_manifest_sha256": _MANIFEST_SHA,
        "expected_corpus_sha256": _CORPUS_SHA,
        "creator_membership_role_id": 1,
        "batch_refs": tuple(f"batch-{index:02d}" for index in range(8)),
        "case_index_plan": tuple(range(800)),
        "at": _AT,
    }
    values.update(overrides)
    return asyncio.run(repo.seal_cohort(**values))


def _repo(session: Session) -> SchoolResearchCohortRepository:
    return SchoolResearchCohortRepository(cast(AsyncSession, _AsyncSessionAdapter(session)))


def test_cohort_model_schema_mysql_and_nullable_0014_compatibility():
    assert len(Base.metadata.tables) == 50
    cohort = cast(Table, SchoolResearchCohort.__table__)
    batches = cast(Table, SchoolResearchCohortBatch.__table__)
    assignments = cast(Table, SchoolResearchCohortAssignment.__table__)
    binding = cast(Table, SchoolResearchTaskBinding.__table__)
    task_assignment = cast(Table, SchoolResearchCaseAssignment.__table__)
    assert set(cohort.c.keys()).isdisjoint({"case_index", "subject_id", "account_id", "login_name"})
    assert cohort.c.assignment_sha256.nullable is False
    assert set(assignments.c.keys()).isdisjoint(
        {"raw_response", "answers", "display_name", "login_name", "row_no", "case_payload"}
    )
    assert binding.c.cohort_id.nullable is True
    assert task_assignment.c.cohort_id.nullable is True
    assert task_assignment.c.cohort_assignment_id.nullable is True
    assert list(binding.c.keys())[-1] == "cohort_id"
    assert list(task_assignment.c.keys())[-2:] == ["cohort_id", "cohort_assignment_id"]
    binding_cohort_fk = next(
        item
        for item in binding.foreign_key_constraints
        if item.name == "fk_school_research_bindings_cohort_exact"
    )
    assert tuple(element.parent.name for element in binding_cohort_fk.elements) == (
        "cohort_id",
        "school_id",
        "profile_version_id",
        "profile_ref",
        "profile_version_number",
        "profile_sha256",
        "corpus_sha256",
        "case_count",
    )
    assert tuple(element.target_fullname for element in binding_cohort_fk.elements) == (
        "school_research_cohorts.id",
        "school_research_cohorts.school_id",
        "school_research_cohorts.profile_version_id",
        "school_research_cohorts.profile_ref",
        "school_research_cohorts.profile_version_number",
        "school_research_cohorts.profile_sha256",
        "school_research_cohorts.corpus_sha256",
        "school_research_cohorts.case_count",
    )
    assert any(
        isinstance(item, UniqueConstraint)
        and tuple(column.name for column in item.columns)
        == (
            "id",
            "school_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "corpus_sha256",
            "case_count",
        )
        for item in cohort.constraints
    )
    pair_check = next(
        check
        for check in task_assignment.constraints
        if isinstance(check, CheckConstraint)
        and "cohort_assignment_pair" in str(check.name or "")
    )
    assert "IS NULL" in str(pair_check.sqltext) and "IS NOT NULL" in str(pair_check.sqltext)
    cohort_assignment_fk = next(
        item
        for item in task_assignment.foreign_key_constraints
        if item.name == "fk_school_research_case_assignments_cohort_exact"
    )
    assert tuple(element.parent.name for element in cohort_assignment_fk.elements) == (
        "cohort_assignment_id",
        "cohort_id",
        "school_id",
        "subject_id",
        "case_index",
    )
    assert tuple(element.target_fullname for element in cohort_assignment_fk.elements) == (
        "school_research_cohort_assignments.id",
        "school_research_cohort_assignments.cohort_id",
        "school_research_cohort_assignments.school_id",
        "school_research_cohort_assignments.subject_id",
        "school_research_cohort_assignments.case_index",
    )
    assert cohort_assignment_fk.onupdate == "RESTRICT"
    for table in (cohort, batches, assignments, binding, task_assignment):
        assert len(str(CreateTable(cast(Table, table)).compile(dialect=mysql.dialect()))) > 0


def test_repository_seals_complete_cross_class_permutation_and_hides_private_mapping(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        adapter = _AsyncSessionAdapter(session)
        repo = SchoolResearchCohortRepository(cast(AsyncSession, adapter))
        metadata = _seal(repo, case_index_plan=tuple(reversed(range(800))))
        assert metadata.case_count == metadata.subject_count == 800
        assert metadata.class_count == 8
        assert "case_index" not in repr(metadata)
        assert _CORPUS_SHA not in repr(metadata)
        stored_cohort = session.get(SchoolResearchCohort, metadata.cohort_id)
        assert stored_cohort is not None and len(stored_cohort.assignment_sha256) == 64
        assert stored_cohort.assignment_sha256 not in repr(metadata)
        assert not hasattr(metadata, "assignment_sha256")
        assignments = session.scalars(
            select(SchoolResearchCohortAssignment).where(
                SchoolResearchCohortAssignment.cohort_id == metadata.cohort_id
            )
        ).all()
        assert len(assignments) == 800
        assert {row.subject_id for row in assignments} == set(range(4000, 4800))
        assert {row.case_index for row in assignments} == set(range(800))
        assert adapter.locked_models == [
            SchoolResearchProfileVersion,
            Account,
            SchoolAccountProvision,
            SchoolAccountProvision,
            AccountSchoolMembership,
            MembershipRole,
            SchoolAccountBatch,
            SchoolClassStudent,
            SchoolClass,
            Subject,
            SubjectAccessGrant,
        ]
        private = asyncio.run(
            repo.require_subject_assignment(
                cohort_id=metadata.cohort_id,
                school_id=1,
                class_id=100,
                class_student_id=7000,
                subject_id=4000,
            )
        )
        assert "case_index" not in repr(private)
        assert str(private.case_index) not in repr(private)
        assert "class_student_id" not in repr(private)
        roundtrip = asyncio.run(
            repo.get_cohort_metadata(school_id=1, cohort_ref=metadata.cohort_ref)
        )
        assert roundtrip == metadata


def test_exact_cohort_replay_returns_original_receipt_without_new_case_plan(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        repo = _repo(session)
        original = _seal(repo)
        replay = _seal(repo, case_index_plan=None)
        assert replay == original
        with pytest.raises(ResearchCohortRepositoryError) as error:
            _seal(repo, case_index_plan=None, expected_corpus_sha256="e" * 64)
        assert error.value.code == ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH


def test_sealed_map_digest_rejects_pretask_case_swap_with_valid_permutation(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        repo = _repo(session)
        metadata = _seal(repo)
        first, second = session.scalars(
            select(SchoolResearchCohortAssignment)
            .where(SchoolResearchCohortAssignment.cohort_id == metadata.cohort_id)
            .order_by(SchoolResearchCohortAssignment.case_index)
            .limit(2)
        ).all()
        assert first.case_index == 0 and second.case_index == 1
        first_case, second_case = first.case_index, second.case_index
        member_fields = (
            "cohort_id",
            "school_id",
            "cohort_batch_id",
            "batch_id",
            "class_id",
            "provision_id",
            "account_id",
            "membership_id",
            "membership_role_id",
            "class_student_id",
            "subject_id",
            "self_grant_id",
        )
        first_values = {name: getattr(first, name) for name in member_fields}
        second_values = {name: getattr(second, name) for name in member_fields}
        session.delete(first)
        session.delete(second)
        session.flush()
        session.add_all(
            [
                SchoolResearchCohortAssignment(**first_values, case_index=second_case),
                SchoolResearchCohortAssignment(**second_values, case_index=first_case),
            ]
        )
        session.flush()
        with pytest.raises(ResearchCohortRepositoryError) as error:
            asyncio.run(
                repo.get_cohort_metadata(school_id=1, cohort_ref=metadata.cohort_ref)
            )
        assert error.value.code is ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH


def test_sealed_map_rejects_nonuniform_class_counts_even_with_matching_digest():
    cohort = SimpleNamespace(
        id=1,
        school_id=1,
        cohort_ref="cohort-fixture-v1",
        study_ref="study-fixture-v1",
        profile_version_id=50,
        profile_ref="pinned-promis",
        profile_version_number=3,
        profile_sha256=_PROFILE_SHA,
        manifest_sha256=_MANIFEST_SHA,
        corpus_sha256=_CORPUS_SHA,
        case_count=800,
        class_count=8,
        subject_count=800,
        status="SEALED",
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        human_curated=False,
        psychological_interpretation_allowed=False,
        assignment_sha256="0" * 64,
    )
    batches = [
        SimpleNamespace(
            id=100 + index,
            cohort_id=1,
            school_id=1,
            class_id=200 + index,
            batch_id=300 + index,
            class_ref=f"class-{index}",
            batch_ref=f"batch-{index}",
            row_count=100,
        )
        for index in range(8)
    ]
    class_counts = (99, 101, 100, 100, 100, 100, 100, 100)
    assignments = []
    member_index = 0
    for batch, count in zip(batches, class_counts, strict=True):
        for _ in range(count):
            assignments.append(
                SimpleNamespace(
                    id=1000 + member_index,
                    cohort_batch_id=batch.id,
                    cohort_id=1,
                    school_id=1,
                    batch_id=batch.batch_id,
                    class_id=batch.class_id,
                    provision_id=4000 + member_index,
                    account_id=5000 + member_index,
                    membership_id=6000 + member_index,
                    membership_role_id=7000 + member_index,
                    class_student_id=8000 + member_index,
                    subject_id=9000 + member_index,
                    self_grant_id=10000 + member_index,
                    case_index=member_index,
                )
            )
            member_index += 1
    assert member_index == 800
    cohort.assignment_sha256 = _assignment_map_sha256(
        cohort, tuple(batches), tuple(assignments)
    )

    class _InvalidMapSession:
        def __init__(self):
            self.responses = iter((batches, assignments))

        async def scalar(self, _statement):
            return cohort

        async def scalars(self, _statement):
            return SimpleNamespace(all=lambda: next(self.responses))

    repo = object.__new__(SchoolResearchCohortRepository)
    repo.session = cast(AsyncSession, _InvalidMapSession())
    with pytest.raises(ResearchCohortRepositoryError) as error:
        asyncio.run(repo._verify_sealed_map(1))
    assert error.value.code is ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH


def test_cat_binding_requires_actual_sealed_cohort_profile_corpus_and_class(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        metadata = _seal(_repo(session))
        profile = session.get(SchoolResearchProfileVersion, 50)
        assert profile is not None
        cat_repo = object.__new__(SchoolResearchCatRepository)
        cat_repo.session = cast(AsyncSession, _AsyncSessionAdapter(session))

        cohort = asyncio.run(
            cat_repo._require_sealed_cohort_scope(
                cohort_id=metadata.cohort_id,
                school_id=1,
                class_id=100,
                profile=profile,
                expected_profile_sha256=_PROFILE_SHA,
                expected_corpus_sha256=_CORPUS_SHA,
                expected_study_ref="study-fixture-v1",
            )
        )
        assert cohort.id == metadata.cohort_id

        for invalid in (
            {"class_id": 108, "expected_profile_sha256": _PROFILE_SHA,
             "expected_corpus_sha256": _CORPUS_SHA},
            {"class_id": 100, "expected_profile_sha256": "e" * 64,
             "expected_corpus_sha256": _CORPUS_SHA},
            {"class_id": 100, "expected_profile_sha256": _PROFILE_SHA,
             "expected_corpus_sha256": "f" * 64},
            {"class_id": 100, "expected_profile_sha256": _PROFILE_SHA,
             "expected_corpus_sha256": _CORPUS_SHA,
             "expected_study_ref": "another-trusted-study"},
        ):
            with pytest.raises(ResearchCatRepositoryError) as error:
                asyncio.run(
                    cat_repo._require_sealed_cohort_scope(
                        cohort_id=metadata.cohort_id,
                        school_id=1,
                        profile=profile,
                        **invalid,
                    )
                )
            assert error.value.code is ResearchCatRepositoryErrorCode.CORPUS_PIN_UNAVAILABLE


def test_cat_binding_and_task_assignments_reuse_real_sealed_class_mapping(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        adapter = _AsyncSessionAdapter(session)
        cohort_repo = _repo(session)
        cohort = _seal(cohort_repo)
        session.add(
            MeasurementTask(
                id=80,
                school_id=1,
                class_id=100,
                task_ref="research-task-class-00",
                created_by_membership_role_id=1,
                instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
                instrument_version="research-profile-v3",
                opens_at=_AT - timedelta(days=1),
                due_at=_AT + timedelta(days=1),
                published_at=_AT - timedelta(days=1),
                status="PUBLISHED",
                cat_binding_mode="RESEARCH_PROFILE",
            )
        )
        session.flush()
        session.add_all(
            [
                TaskEnrollment(
                    id=9000 + offset,
                    school_id=1,
                    task_id=80,
                    class_id=100,
                    class_student_id=7000 + offset,
                    subject_id=4000 + offset,
                    status="ACTIVE",
                )
                for offset in range(100)
            ]
        )
        session.flush()

        protection = FernetDataProtectionProvider(
            MappingKeyProvider({"test-v1": Fernet.generate_key()}, "test-v1")
        )
        cat_repo = SchoolResearchCatRepository(cast(AsyncSession, adapter), protection)
        config_payload = {"model": "GRM", "max_items": 1}
        config_sha256 = hashlib.sha256(_canonical_json(config_payload).encode()).hexdigest()
        binding = asyncio.run(
            cat_repo.create_task_binding(
                school_id=1,
                task_id=80,
                class_id=100,
                profile_version_id=50,
                profile_ref="pinned-promis",
                profile_version_number=3,
                expected_profile_sha256=_PROFILE_SHA,
                response_origin="PUBLIC_OBSERVED",
                corpus_sha256=_CORPUS_SHA,
                case_count=800,
                config_version="cohort-config-v1",
                config_payload=config_payload,
                expected_config_sha256=config_sha256,
                creator_membership_role_id=1,
                cohort_id=cohort.cohort_id,
            )
        )
        created = asyncio.run(
            cat_repo.create_public_observed_case_assignments(
                school_id=1,
                task_id=80,
                class_id=100,
                task_binding_id=binding.binding_id,
                expected_profile_sha256=_PROFILE_SHA,
                expected_corpus_sha256=_CORPUS_SHA,
                creator_membership_role_id=1,
                case_index_plan=None,
            )
        )
        rows = session.scalars(
            select(SchoolResearchCaseAssignment)
            .where(SchoolResearchCaseAssignment.task_id == 80)
            .order_by(SchoolResearchCaseAssignment.task_enrollment_id)
        ).all()
        assert binding.cohort_id == cohort.cohort_id
        assert len(created) == len(rows) == 100
        assert all(row.cohort_id == cohort.cohort_id for row in rows)
        assert {row.cohort_assignment_id for row in rows} == {
            item.id
            for item in session.scalars(
                select(SchoolResearchCohortAssignment).where(
                    SchoolResearchCohortAssignment.class_id == 100
                )
            ).all()
        }
        assert {
            row.case_index for row in rows
        } == {
            row.case_index
            for row in session.scalars(
                select(SchoolResearchCohortAssignment).where(
                    SchoolResearchCohortAssignment.class_id == 100
                )
            ).all()
        }


def test_existing_cohort_receipt_fails_closed_if_mapping_is_incomplete(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        repo = _repo(session)
        metadata = _seal(repo)
        assignment = session.scalar(
            select(SchoolResearchCohortAssignment).where(
                SchoolResearchCohortAssignment.cohort_id == metadata.cohort_id
            )
        )
        assert assignment is not None
        session.delete(assignment)
        session.flush()
        with pytest.raises(ResearchCohortRepositoryError) as error:
            asyncio.run(repo.get_cohort_metadata(school_id=1, cohort_ref=metadata.cohort_ref))
        assert error.value.code == ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_profile_sha256": "A" * 64},
        {"expected_manifest_sha256": "not-a-sha"},
        {"expected_corpus_sha256": "z" * 64},
        {"batch_refs": tuple([f"batch-{index:02d}" for index in range(7)] + ["unknown"])},
        {"case_index_plan": tuple(range(799)) + (798,)},
        {"case_index_plan": tuple(range(799)) + (True,)},
    ],
)
def test_repository_rejects_untrusted_pins_or_incomplete_case_plan(sqlite_engine, overrides):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        repo = _repo(session)
        with pytest.raises(ResearchCohortRepositoryError) as error:
            _seal(repo, **overrides)
        expected = (
            ResearchCohortErrorCode.INVALID_INPUT
            if "case_index_plan" in overrides or any("expected_" in key for key in overrides)
            else ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
        )
        assert error.value.code == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rights_status", "REVOKED"),
        ("execution_status", "CANDIDATE_RESEARCH_ONLY"),
        ("rights_revoked_at", _AT),
        ("disabled_at", _AT),
    ],
)
def test_repository_fails_closed_for_profile_eligibility_flags(sqlite_engine, field, value):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        profile = session.get(SchoolResearchProfileVersion, 50)
        assert profile is not None
        setattr(profile, field, value)
        if field == "rights_status":
            profile.execution_status = "DISABLED"
        session.flush()
        repo = _repo(session)
        with pytest.raises(ResearchCohortRepositoryError) as error:
            _seal(repo)
        assert error.value.code == ResearchCohortErrorCode.PROFILE_NOT_ELIGIBLE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("human_curated", True),
        ("research_only", False),
        ("psychological_interpretation_allowed", True),
        ("publication_status", "approved"),
        ("fit_sha256", "e" * 64),
        ("published_parameter_crosswalk_sha256", None),
    ],
)
def test_profile_predicate_rejects_disallowed_flags_and_provenance(field, value):
    profile = SimpleNamespace(
        rights_status="VERIFIED",
        execution_status="SIMULATION_ENABLED",
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        human_curated=False,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
        rights_revoked_at=None,
        disabled_at=None,
        simulation_enabled_at=_AT,
        parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
        fit_sha256=None,
        calibration_sha256=None,
        published_parameter_crosswalk_sha256=_CROSSWALK_SHA,
    )
    setattr(profile, field, value)
    assert not _eligible_profile(cast(SchoolResearchProfileVersion, profile))


def test_repository_failure_after_partial_flush_rolls_back_only_seal_savepoint(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        adapter = _AsyncSessionAdapter(session)
        adapter.fail_flush_number = 3
        repo = SchoolResearchCohortRepository(cast(AsyncSession, adapter))
        with pytest.raises(ResearchCohortRepositoryError) as error:
            _seal(repo)
        assert error.value.code == ResearchCohortErrorCode.PERSISTENCE_CONFLICT
        assert session.scalar(select(SchoolResearchCohort.id)) is None
        assert session.scalar(select(SchoolResearchCohortBatch.id)) is None
        assert session.scalar(select(SchoolResearchCohortAssignment.id)) is None


@pytest.mark.parametrize(
    ("model", "row_id", "field", "value", "extra"),
    [
        (Account, 1000, "status", "DISABLED", None),
        (SchoolAccountProvision, 6000, "status", "PENDING_ACTIVATION", {"activated_at": None}),
        (AccountSchoolMembership, 2000, "status", "REVOKED", {"revoked_at": _AT}),
        (MembershipRole, 3000, "role_code", "teacher", None),
        (SchoolClassStudent, 7000, "status", "REVOKED", {"revoked_at": _AT}),
        (SubjectAccessGrant, 5000, "status", "REVOKED", {"revoked_at": _AT}),
        (Subject, 4000, "data_origin", "PRODUCTION_PENDING", None),
        (SchoolClass, 100, "status", "ARCHIVED", None),
    ],
)
def test_repository_requires_current_active_synthetic_membership_rows(
    sqlite_engine, model, row_id, field, value, extra
):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        row = session.get(model, row_id)
        setattr(row, field, value)
        for key, item in (extra or {}).items():
            setattr(row, key, item)
        session.flush()
        repo = _repo(session)
        with pytest.raises(ResearchCohortRepositoryError) as error:
            _seal(repo)
        assert error.value.code == ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID


def test_sqlite_database_rejects_cohort_count_and_cross_scope_links(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        repo = _repo(session)
        metadata = _seal(repo)
        with pytest.raises(IntegrityError):
            session.add(
                SchoolResearchCohortBatch(
                    cohort_id=metadata.cohort_id,
                    school_id=2,
                    class_id=100,
                    batch_id=200,
                    class_ref="class-00",
                    batch_ref="batch-00",
                    row_count=100,
                )
            )
            session.flush()


def test_private_case_lookup_requires_exact_school_class_roster_and_subject(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        repo = _repo(session)
        metadata = _seal(repo)
        for scope in (
            {"school_id": 2, "class_id": 100, "class_student_id": 7000},
            {"school_id": 1, "class_id": 101, "class_student_id": 7000},
            {"school_id": 1, "class_id": 100, "class_student_id": 7001},
        ):
            with pytest.raises(ResearchCohortRepositoryError) as error:
                asyncio.run(
                    repo.require_subject_assignment(
                        cohort_id=metadata.cohort_id,
                        subject_id=4000,
                        **scope,
                    )
                )
            assert error.value.code == ResearchCohortErrorCode.CASE_ASSIGNMENT_NOT_FOUND


def test_db_constraints_reject_duplicate_case_subject_and_out_of_range(sqlite_engine):
    with Session(sqlite_engine) as session, session.begin():
        _seed_full_cohort(session)
        repo = _repo(session)
        metadata = _seal(repo)
        source = session.scalar(
            select(SchoolResearchCohortAssignment).where(
                SchoolResearchCohortAssignment.cohort_id == metadata.cohort_id
            )
        )
        assert source is not None
        with session.begin_nested():
            session.add(
                SchoolResearchCohortAssignment(
                    id=90000,
                    public_id="duplicate-subject-map",
                    cohort_id=source.cohort_id,
                    school_id=source.school_id,
                    cohort_batch_id=source.cohort_batch_id,
                    batch_id=source.batch_id,
                    class_id=source.class_id,
                    provision_id=source.provision_id,
                    account_id=source.account_id,
                    membership_id=source.membership_id,
                    membership_role_id=source.membership_role_id,
                    class_student_id=source.class_student_id,
                    subject_id=source.subject_id,
                    self_grant_id=source.self_grant_id,
                    case_index=799,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
        with session.begin_nested():
            session.add(
                SchoolResearchCohortAssignment(
                    id=90001,
                    public_id="out-of-range-map",
                    cohort_id=source.cohort_id,
                    school_id=source.school_id,
                    cohort_batch_id=source.cohort_batch_id,
                    batch_id=source.batch_id,
                    class_id=source.class_id,
                    provision_id=source.provision_id,
                    account_id=source.account_id,
                    membership_id=source.membership_id,
                    membership_role_id=source.membership_role_id,
                    class_student_id=source.class_student_id,
                    subject_id=8000,
                    self_grant_id=source.self_grant_id,
                    case_index=800,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()


def _load_0015_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261014_0015_sealed_research_cohorts.py"
    )
    spec = spec_from_file_location("migration_20261014_0015", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_0015_migration_is_additive_exact_and_preserves_nullable_0014_rows(monkeypatch):
    migration = _load_0015_migration()
    assert migration.revision == "20261014_0015"
    assert migration.down_revision == "20261014_0014"
    operations = []

    class _Connection:
        def execute(self, statement):
            operations.append(("guard", str(statement)))
            return SimpleNamespace(scalar_one=lambda: 0)

    class _Ops:
        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection()

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    created = {item[1]: item for item in operations if item[0] == "create_table"}
    assert set(created) == {
        "school_research_cohorts",
        "school_research_cohort_batches",
        "school_research_cohort_assignments",
    }
    for name, model in (
        ("school_research_cohorts", SchoolResearchCohort),
        ("school_research_cohort_batches", SchoolResearchCohortBatch),
        ("school_research_cohort_assignments", SchoolResearchCohortAssignment),
    ):
        migration_columns = [
            element for element in created[name][2:-1] if isinstance(element, Column)
        ]
        assert tuple(column.name for column in migration_columns) == tuple(model.__table__.c.keys())
        for actual, expected in zip(migration_columns, model.__table__.columns, strict=True):
            assert actual.nullable is expected.nullable
            assert actual.type.compile(dialect=mysql.dialect()) == expected.type.compile(
                dialect=mysql.dialect()
            )

    nullable_additions = [operation[2] for operation in operations if operation[0] == "add_column"]
    assert {
        (operation[1], column.name, column.nullable)
        for operation in operations
        if operation[0] == "add_column"
        for column in (operation[2],)
    } == {
        ("school_research_task_bindings", "cohort_id", True),
        ("school_research_case_assignments", "cohort_id", True),
        ("school_research_case_assignments", "cohort_assignment_id", True),
    }
    assert len(nullable_additions) == 3
    assert not any(
        operation[0] == "drop_constraint"
        and operation[1] == "fk_school_research_case_assignments_binding_exact"
        for operation in operations
    )
    assert not any(operation[0] in {"execute", "bulk_insert"} for operation in operations)
    for model in (SchoolResearchCohort, SchoolResearchCohortBatch, SchoolResearchCohortAssignment):
        statement = CreateTable(cast(Table, model.__table__)).compile(dialect=mysql.dialect())
        assert len(str(statement)) > 0

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert sum(operation[0] == "guard" for operation in operations) == 5
