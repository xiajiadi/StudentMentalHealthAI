from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from database_layer.errors import NotFound, UniqueConflict
from database_layer.models import (
    AssessmentSession,
    MeasurementTask,
    SchoolClass,
    SchoolClassStudent,
    SchoolClassTeacher,
    TaskEnrollment,
)
from database_layer.repositories import SchoolOperationsRepository, TaskProgressCounts
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError


def _at() -> datetime:
    return datetime(2026, 10, 11, tzinfo=UTC).replace(tzinfo=None)


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class _Result:
    def __init__(self, row: object | None) -> None:
        self.row = row

    def one_or_none(self) -> object | None:
        return self.row


class _NestedTransaction:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.snapshot: list[object] = []

    async def __aenter__(self):
        self.snapshot = list(self.session.added)
        self.session.nested_started = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        del exc, traceback
        if exc_type is not None:
            self.session.added = self.snapshot
            self.session.nested_rolled_back = True
        return False


class _Session:
    """Scripted AsyncSession surface; it never opens a connection."""

    def __init__(
        self,
        *,
        scalar_values: list[object] | None = None,
        scalar_rows: list[list[Any]] | None = None,
        get_values: dict[tuple[type, int], object] | None = None,
        execute_row: object | None = None,
        fail_flush_at: int | None = None,
    ) -> None:
        self.scalar_values = list(scalar_values or [])
        self.scalar_rows = list(scalar_rows or [])
        self.get_values = dict(get_values or {})
        self.execute_row = execute_row
        self.fail_flush_at = fail_flush_at
        self.added: list[object] = []
        self.flush_count = 0
        self.nested_started = False
        self.nested_rolled_back = False
        self.statements: list[Any] = []
        self.executed_updates: list[object] = []
        self._next_id = 1000

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flush_count += 1
        if self.fail_flush_at == self.flush_count:
            raise IntegrityError("synthetic insert", {}, RuntimeError("SYNTHETIC_CONFLICT"))
        for row in self.added:
            if getattr(row, "id", None) is None:
                self._next_id += 1
                cast(Any, row).id = self._next_id

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.scalar_values:
            raise AssertionError("unexpected scalar query")
        return self.scalar_values.pop(0)

    async def scalars(self, statement):
        self.statements.append(statement)
        if not self.scalar_rows:
            raise AssertionError("unexpected scalar-list query")
        return _ScalarRows(self.scalar_rows.pop(0))

    async def execute(self, statement):
        self.statements.append(statement)
        if statement.__class__.__name__ == "Update":
            self.executed_updates.append(statement)
            return _Result(None)
        return _Result(self.execute_row)

    async def get(self, model, identity):
        return self.get_values.get((model, identity))

    def begin_nested(self):
        return _NestedTransaction(self)


def _admin_role():
    return SimpleNamespace(
        id=11, school_id=7, role_code="admin", status="ACTIVE", revoked_at=None
    )


def _active_class():
    return SimpleNamespace(id=21, school_id=7, status="ACTIVE")


def _student_link(link_id: int, subject_id: int):
    return SimpleNamespace(id=link_id, school_id=7, class_id=21, subject_id=subject_id)


def _task_publish_args() -> dict[str, Any]:
    return {
        "school_id": 7,
        "class_id": 21,
        "task_ref": "TASK_SYNTHETIC_SCOPE_A_V1",
        "admin_membership_role_id": 11,
        "instrument_id": "instrument.synthetic",
        "instrument_version": "1.0.0",
        "item_bank_version": "bank.synthetic.v1",
        "config_version": "config.synthetic.v1",
        "opens_at": _at(),
        "due_at": None,
        "published_at": _at(),
    }


async def test_class_links_require_typed_same_school_roles_and_active_self_grant():
    wrong_teacher_role = SimpleNamespace(
        id=31, school_id=7, role_code="student", status="ACTIVE", revoked_at=None
    )
    teacher_session = _Session(
        scalar_values=[_admin_role(), _active_class(), wrong_teacher_role]
    )
    with pytest.raises(ValueError, match="same-school teacher role"):
        await SchoolOperationsRepository(cast(Any, teacher_session)).add_teacher_role_to_class(
            school_id=7,
            class_id=21,
            teacher_membership_role_id=31,
            admin_membership_role_id=11,
            at=_at(),
        )
    assert teacher_session.added == []

    student_session = _Session(scalar_values=[_admin_role(), _active_class(), 0])
    with pytest.raises(ValueError, match="student SELF grant"):
        await SchoolOperationsRepository(cast(Any, student_session)).add_student_subject_to_class(
            school_id=7,
            class_id=21,
            subject_id=41,
            admin_membership_role_id=11,
            at=_at(),
        )
    assert student_session.added == []


async def test_class_create_and_valid_typed_links_persist_only_same_school_links():
    create_session = _Session(scalar_values=[_admin_role()])
    school_class = await SchoolOperationsRepository(cast(Any, create_session)).create_class(
        school_id=7,
        class_ref="CLASS_SYNTHETIC_01",
        admin_membership_role_id=11,
        at=_at(),
    )
    assert isinstance(school_class, SchoolClass)
    assert school_class.school_id == 7
    assert create_session.flush_count == 1

    student_session = _Session(scalar_values=[_admin_role(), _active_class(), 1, None])
    student_repository = SchoolOperationsRepository(cast(Any, student_session))
    student_link = await student_repository.add_student_subject_to_class(
        school_id=7,
        class_id=21,
        subject_id=61,
        admin_membership_role_id=11,
        at=_at(),
    )
    assert isinstance(student_link, SchoolClassStudent)
    assert (student_link.school_id, student_link.class_id, student_link.subject_id) == (
        7,
        21,
        61,
    )

    teacher_role = SimpleNamespace(
        id=31, school_id=7, role_code="teacher", status="ACTIVE", revoked_at=None
    )
    teacher_session = _Session(
        scalar_values=[_admin_role(), _active_class(), teacher_role, None]
    )
    teacher_repository = SchoolOperationsRepository(cast(Any, teacher_session))
    teacher_link = await teacher_repository.add_teacher_role_to_class(
        school_id=7,
        class_id=21,
        teacher_membership_role_id=31,
        admin_membership_role_id=11,
        at=_at(),
    )
    assert isinstance(teacher_link, SchoolClassTeacher)
    assert (teacher_link.school_id, teacher_link.class_id, teacher_link.membership_role_id) == (
        7,
        21,
        31,
    )


async def test_readding_revoked_roster_link_reactivates_row_without_rewriting_history():
    link = SimpleNamespace(
        id=51,
        school_id=7,
        class_id=21,
        subject_id=61,
        status="REVOKED",
        valid_from=_at().replace(day=1),
        valid_until=None,
        revoked_at=_at(),
    )
    historic_enrollment = SimpleNamespace(id=71, status="REVOKED", revoked_at=_at())
    session = _Session(
        scalar_values=[_admin_role(), _active_class(), 1, link],
    )
    reactivated = await SchoolOperationsRepository(cast(Any, session)).add_student_subject_to_class(
        school_id=7,
        class_id=21,
        subject_id=61,
        admin_membership_role_id=11,
        at=_at(),
    )
    assert reactivated is link
    assert link.status == "ACTIVE"
    assert link.revoked_at is None
    assert link.valid_from == _at()
    assert historic_enrollment.status == "REVOKED"
    assert session.added == []


async def test_task_publish_snapshots_active_class_students_in_one_savepoint():
    links = [_student_link(51, 61), _student_link(52, 62)]
    session = _Session(
        scalar_values=[_admin_role(), _active_class(), 1, 1],
        scalar_rows=[links],
    )
    result = await SchoolOperationsRepository(cast(Any, session)).publish_task_with_snapshot(
        **_task_publish_args()
    )

    assert result.enrollment_count == 2
    assert result.task.status == "PUBLISHED"
    assert session.nested_started is True
    enrollments = [row for row in session.added if isinstance(row, TaskEnrollment)]
    assert len(enrollments) == 2
    assert {(row.class_student_id, row.subject_id) for row in enrollments} == {
        (51, 61),
        (52, 62),
    }
    assert {row.status for row in enrollments} == {"ACTIVE"}


@pytest.mark.parametrize("failure", ["unique_conflict", "invalid_member"])
async def test_task_publish_rolls_back_task_and_partial_snapshot(failure: str):
    links = [_student_link(51, 61), _student_link(52, 62)]
    session = _Session(
        scalar_values=[_admin_role(), _active_class(), 1, 1 if failure == "unique_conflict" else 0],
        scalar_rows=[links],
        fail_flush_at=3 if failure == "unique_conflict" else None,
    )
    repository = SchoolOperationsRepository(cast(Any, session))
    expected = UniqueConflict if failure == "unique_conflict" else ValueError
    with pytest.raises(expected):
        await repository.publish_task_with_snapshot(**_task_publish_args())
    assert session.nested_started is True
    assert session.nested_rolled_back is True
    assert session.added == []


async def test_enrollment_session_link_is_immutable_and_same_link_is_recoverable():
    enrollment = SimpleNamespace(id=71, school_id=7, subject_id=61, status="ACTIVE")
    linked_session = SimpleNamespace(
        id=81, subject_id=61, status="IN_PROGRESS", task_enrollment_id=71
    )
    session = _Session(
        scalar_values=[enrollment],
        get_values={
            (TaskEnrollment, 71): enrollment,
            (AssessmentSession, 81): linked_session,
        },
    )
    recovered = await SchoolOperationsRepository(cast(Any, session)).link_assessment_session(
        enrollment_id=71,
        assessment_session_id=81,
        school_id=7,
        student_account_id=91,
        at=_at(),
    )
    assert recovered is linked_session
    assert session.flush_count == 0

    for status in ("CREATED", "IN_PROGRESS", "COMPLETED"):
        candidate = SimpleNamespace(
            id=82, subject_id=61, status=status, task_enrollment_id=None
        )
        conflict_session = _Session(
            scalar_values=[enrollment],
            get_values={
                (TaskEnrollment, 71): enrollment,
                (AssessmentSession, 82): candidate,
            },
        )
        with pytest.raises(ValueError, match="unbound assessment sessions"):
            await SchoolOperationsRepository(cast(Any, conflict_session)).link_assessment_session(
                enrollment_id=71,
                assessment_session_id=82,
                school_id=7,
                student_account_id=91,
                at=_at(),
            )
        assert candidate.task_enrollment_id is None


async def test_task_start_creates_bound_session_from_task_and_repeat_resolves_same_session():
    enrollment = SimpleNamespace(
        id=71, school_id=7, class_id=21, task_id=101, subject_id=61, status="ACTIVE"
    )
    task = SimpleNamespace(
        id=101,
        school_id=7,
        class_id=21,
        status="PUBLISHED",
        opens_at=_at(),
        due_at=None,
        instrument_id="instrument.from.task",
        instrument_version="version.from.task",
        item_bank_version="bank.from.task",
        config_version="config.from.task",
    )
    session = _Session(
        scalar_values=[enrollment, None],
        get_values={
            (MeasurementTask, 101): task,
        },
    )
    linked = await SchoolOperationsRepository(cast(Any, session)).create_task_assessment_session(
        enrollment_id=71,
        assessment_ref="ASSESS_task_start_001",
        school_id=7,
        student_account_id=91,
        at=_at(),
        trace_id="TRACE_task_start_001",
    )
    assert isinstance(linked, AssessmentSession)
    assert linked.task_enrollment_id == 71
    assert linked.subject_id == 61
    assert linked.instrument_id == task.instrument_id
    assert linked.instrument_version == task.instrument_version
    assert linked.item_bank_version == task.item_bank_version
    assert linked.config_version == task.config_version
    assert linked.trace_id == "TRACE_task_start_001"
    assert session.flush_count == 1

    resume_session = _Session(scalar_values=[enrollment, linked])
    resumed = await SchoolOperationsRepository(
        cast(Any, resume_session)
    ).create_task_assessment_session(
        enrollment_id=71,
        assessment_ref="ASSESS_different_ref_is_ignored",
        school_id=7,
        student_account_id=91,
        at=_at(),
    )
    assert resumed is linked


async def test_task_start_recovers_concurrent_unique_enrollment_winner():
    enrollment = SimpleNamespace(
        id=71, school_id=7, class_id=21, task_id=101, subject_id=61, status="ACTIVE"
    )
    task = SimpleNamespace(
        id=101,
        school_id=7,
        class_id=21,
        status="PUBLISHED",
        opens_at=_at(),
        due_at=None,
        instrument_id="instrument.task",
        instrument_version="v1",
        item_bank_version=None,
        config_version=None,
    )
    winner = SimpleNamespace(id=82, subject_id=61, task_enrollment_id=71)
    session = _Session(
        scalar_values=[enrollment, None, winner],
        get_values={(MeasurementTask, 101): task},
        fail_flush_at=1,
    )
    recovered = await SchoolOperationsRepository(cast(Any, session)).create_task_assessment_session(
        enrollment_id=71,
        assessment_ref="ASSESS_task_race_loser",
        school_id=7,
        student_account_id=91,
        at=_at(),
    )
    assert recovered is winner
    assert session.nested_rolled_back is True
    assert session.added == []
    assert "FOR UPDATE" in str(session.statements[-1].compile(dialect=mysql.dialect()))


@pytest.mark.parametrize(
    "task_changes",
    [
        {"status": "CLOSED"},
        {"status": "CANCELLED"},
        {"opens_at": _at().replace(day=12)},
        {"due_at": _at().replace(day=10)},
    ],
    ids=("closed", "cancelled", "not-yet-open", "expired"),
)
async def test_task_start_rejects_closed_or_out_of_window_task(task_changes):
    enrollment = SimpleNamespace(
        id=71, school_id=7, class_id=21, task_id=101, subject_id=61, status="ACTIVE"
    )
    task_values = {
        "id": 101,
        "school_id": 7,
        "class_id": 21,
        "status": "PUBLISHED",
        "opens_at": _at(),
        "due_at": None,
        "instrument_id": "instrument.task",
        "instrument_version": "v1",
        "item_bank_version": None,
        "config_version": None,
    }
    task_values.update(task_changes)
    session = _Session(
        scalar_values=[enrollment, None],
        get_values={(MeasurementTask, 101): SimpleNamespace(**task_values)},
    )
    with pytest.raises(NotFound, match="open measurement task"):
        await SchoolOperationsRepository(cast(Any, session)).create_task_assessment_session(
            enrollment_id=71,
            assessment_ref="ASSESS_task_outside_window",
            school_id=7,
            student_account_id=91,
            at=_at(),
        )
    assert session.added == []


async def test_link_rejects_subject_mismatch_and_unbound_session():
    enrollment = SimpleNamespace(id=71, school_id=7, subject_id=61, status="ACTIVE")
    mismatch = SimpleNamespace(
        id=81, subject_id=62, status="CREATED", task_enrollment_id=None
    )
    mismatch_session = _Session(
        scalar_values=[enrollment],
        get_values={(TaskEnrollment, 71): enrollment, (AssessmentSession, 81): mismatch},
    )
    with pytest.raises(ValueError, match="subject does not match"):
        await SchoolOperationsRepository(cast(Any, mismatch_session)).link_assessment_session(
            enrollment_id=71,
            assessment_session_id=81,
            school_id=7,
            student_account_id=91,
            at=_at(),
        )

    terminal = SimpleNamespace(id=82, subject_id=61, status="ABANDONED", task_enrollment_id=None)
    terminal_session = _Session(
        scalar_values=[enrollment, None],
        get_values={(TaskEnrollment, 71): enrollment, (AssessmentSession, 82): terminal},
    )
    with pytest.raises(ValueError, match="unbound assessment sessions"):
        await SchoolOperationsRepository(cast(Any, terminal_session)).link_assessment_session(
            enrollment_id=71,
            assessment_session_id=82,
            school_id=7,
            student_account_id=91,
            at=_at(),
        )


async def test_revocation_retains_enrollment_row_and_progress_is_task_only():
    enrollment = SimpleNamespace(
        id=71, school_id=7, status="ACTIVE", revoked_at=None, subject_id=61
    )
    session = _Session(
        scalar_values=[_admin_role()],
        get_values={(TaskEnrollment, 71): enrollment},
    )
    revoked = await SchoolOperationsRepository(cast(Any, session)).revoke_enrollment(
        enrollment_id=71,
        school_id=7,
        admin_membership_role_id=11,
        at=_at(),
    )
    assert revoked is enrollment
    assert session.get_values[(TaskEnrollment, 71)] is enrollment
    assert enrollment.status == "REVOKED"
    assert enrollment.revoked_at == _at()

    aggregate_session = _Session(
        execute_row=(5, 3, 2, 1, 0, 1, 1, 0, 0)
    )
    counts = await SchoolOperationsRepository(cast(Any, aggregate_session)).task_progress_counts(
        task_id=101,
        school_id=7,
    )
    assert counts == TaskProgressCounts(5, 3, 2, 1, 0, 1, 1, 0, 0)
    selected = set(aggregate_session.statements[0].selected_columns.keys())
    assert selected == {
        "published_enrollment_count",
        "active_enrollment_count",
        "revoked_enrollment_count",
        "not_started_count",
        "created_count",
        "in_progress_count",
        "completed_count",
        "abandoned_count",
        "invalid_count",
    }
    compiled = str(aggregate_session.statements[0].compile(dialect=mysql.dialect()))
    assert "payload_ciphertext" not in compiled.lower()
    assert "assessment_results" not in compiled.lower()
    assert "assessment_responses" not in compiled.lower()
    assert "report" not in compiled.lower()
    assert "review" not in compiled.lower()


async def test_student_active_enrollment_lookup_keeps_current_task_window_gate():
    expected = SimpleNamespace(id=71, school_id=7, subject_id=61, status="ACTIVE")
    session = _Session(scalar_values=[expected])
    found = await SchoolOperationsRepository(cast(Any, session)).active_enrollment_for_assessment(
        assessment_ref="ASSESS_synthetic_task",
        student_account_id=91,
        at=_at(),
    )
    assert found is expected
    compiled = str(
        session.statements[0].compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "assessment_ref" in compiled
    assert "principal_account_id" in compiled
    assert "relationship_type" in compiled and "self" in compiled
    assert "revoked_at" in compiled
    assert "status" in compiled
    assert "measurement_tasks" in compiled
    assert "opens_at" in compiled and "due_at" in compiled
    assert "published" in compiled
    params = session.statements[0].compile(dialect=mysql.dialect()).params
    assert params["opens_at_1"] == _at()
    assert params["due_at_1"] == _at()


async def test_post_assessment_scope_uses_completion_time_but_current_authorization():
    expected = SimpleNamespace(id=71, school_id=7, subject_id=61, status="ACTIVE")
    completed_at = _at() + timedelta(days=1)
    now = completed_at + timedelta(days=2)
    session = _Session(scalar_values=[expected])
    found = await SchoolOperationsRepository(
        cast(Any, session)
    ).completed_enrollment_for_post_assessment(
        assessment_ref="ASSESS_synthetic_task", student_account_id=91, at=now
    )
    assert found is expected

    statement = session.statements[0]
    compiled = str(
        statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()
    now_literal = now.strftime("%Y-%m-%d %H:%M:%S")
    assert "assessment_sessions.status = 'completed'" in compiled
    assert "assessment_sessions.completed_at is not null" in compiled
    assert f"assessment_sessions.completed_at <= '{now_literal}'" in compiled
    assert "measurement_tasks.opens_at <= assessment_sessions.completed_at" in compiled
    assert (
        "assessment_sessions.completed_at <= measurement_tasks.due_at" in compiled
    )
    assert "measurement_tasks.status = 'published'" in compiled
    assert "measurement_tasks.due_at is null" in compiled
    assert "task_enrollments.revoked_at is null" in compiled
    assert "principal_account_id = 91" in compiled
    assert "relationship_type = 'self'" in compiled
    assert "subject_access_grants.status = 'active'" in compiled
    assert "accounts.status = 'active'" in compiled
    assert "account_school_memberships.status = 'active'" in compiled
    assert "membership_roles.role_code = 'student'" in compiled
    assert "membership_roles.status = 'active'" in compiled
    assert "school_class_students.status = 'active'" in compiled
    assert "school_classes.status = 'active'" in compiled
    assert "schools.status = 'active'" in compiled
    # The current time is used for active identity/consent windows, not for the
    # task due-time check; that check is against the immutable completion time.
    assert f"measurement_tasks.due_at >= '{now_literal}'" not in compiled


async def test_missing_progress_task_fails_closed():
    session = _Session(execute_row=None)
    with pytest.raises(NotFound):
        await SchoolOperationsRepository(cast(Any, session)).task_progress_counts(
            task_id=404,
            school_id=7,
        )
