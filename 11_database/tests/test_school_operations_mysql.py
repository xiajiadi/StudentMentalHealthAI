from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

import pytest
from database_layer.base import utc_now
from database_layer.crypto import FernetDataProtectionProvider
from database_layer.enums import DataOrigin
from database_layer.errors import NotFound
from database_layer.models import (
    Account,
    AssessmentSession,
    MeasurementTask,
    School,
    SchoolClass,
    SchoolClassStudent,
    SchoolClassTeacher,
    Subject,
    TaskEnrollment,
)
from database_layer.repositories import (
    SYNTHETIC_SCHOOL_PROVENANCE_REF,
    AccountRepository,
    AssessmentRepository,
    SchoolMembershipRepository,
    SchoolOperationsRepository,
    SubjectRepository,
)
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.mysql


@dataclass(slots=True)
class _Student:
    account: Account
    subject: Subject
    class_link: SchoolClassStudent


@dataclass(slots=True)
class _SchoolGraph:
    school: School
    admin: Account
    admin_role_id: int
    teacher: Account
    teacher_role_id: int
    school_class: SchoolClass
    teacher_link: SchoolClassTeacher
    students: list[_Student]


@pytest.fixture
async def mysql_transaction(session_factory):
    """Each ordinary scenario runs in one transaction and rolls back its seed."""

    async with session_factory() as session:
        await session.begin()
        try:
            yield session
        finally:
            await session.rollback()


async def _create_graph(
    session: AsyncSession,
    *,
    now,
    student_count: int = 1,
    school_label: str = "A",
) -> _SchoolGraph:
    suffix = uuid4().hex
    accounts = AccountRepository(session)
    memberships = SchoolMembershipRepository(session)
    subjects = SubjectRepository(session)

    school = await memberships.create_school(
        school_ref=f"SCHOOL_{school_label}_{suffix}",
        data_origin=DataOrigin.SYNTHETIC,
        provenance_ref=SYNTHETIC_SCHOOL_PROVENANCE_REF,
    )
    admin = await accounts.create(
        login_name=f"admin_{suffix}", password_hash=f"synthetic-hash-{suffix}"
    )
    admin_membership = await memberships.create_membership(
        account_id=admin.id, school_id=school.id, valid_from=now
    )
    admin_role = await memberships.add_role(
        membership_id=admin_membership.id,
        school_id=school.id,
        role_code="admin",
        valid_from=now,
    )

    teacher = await accounts.create(
        login_name=f"teacher_{suffix}", password_hash=f"synthetic-hash-{suffix}"
    )
    teacher_membership = await memberships.create_membership(
        account_id=teacher.id, school_id=school.id, valid_from=now
    )
    teacher_role = await memberships.add_role(
        membership_id=teacher_membership.id,
        school_id=school.id,
        role_code="teacher",
        valid_from=now,
    )

    school_class = await SchoolOperationsRepository(session).create_class(
        school_id=school.id,
        class_ref=f"CLASS_{suffix}",
        admin_membership_role_id=admin_role.id,
        at=now,
    )
    teacher_link = await SchoolOperationsRepository(session).add_teacher_role_to_class(
        school_id=school.id,
        class_id=school_class.id,
        teacher_membership_role_id=teacher_role.id,
        admin_membership_role_id=admin_role.id,
        at=now,
    )

    students: list[_Student] = []
    for _ in range(student_count):
        student = await accounts.create(
            login_name=f"student_{uuid4().hex}", password_hash=f"synthetic-hash-{uuid4().hex}"
        )
        student_membership = await memberships.create_membership(
            account_id=student.id, school_id=school.id, valid_from=now
        )
        await memberships.add_role(
            membership_id=student_membership.id,
            school_id=school.id,
            role_code="student",
            valid_from=now,
        )
        subject = await subjects.create(
            subject_ref=f"SUBJ_{uuid4().hex}", school_id=school.id
        )
        await memberships.grant_subject_in_school(
            principal_account_id=student.id,
            subject_id=subject.id,
            school_id=school.id,
            role_code="student",
            valid_from=now,
        )
        class_link = await SchoolOperationsRepository(session).add_student_subject_to_class(
            school_id=school.id,
            class_id=school_class.id,
            subject_id=subject.id,
            admin_membership_role_id=admin_role.id,
            at=now,
        )
        students.append(_Student(student, subject, class_link))

    return _SchoolGraph(
        school=school,
        admin=admin,
        admin_role_id=admin_role.id,
        teacher=teacher,
        teacher_role_id=teacher_role.id,
        school_class=school_class,
        teacher_link=teacher_link,
        students=students,
    )


async def _publish_task(
    session: AsyncSession,
    graph: _SchoolGraph,
    *,
    now,
    opens_at=None,
    due_at=None,
) -> MeasurementTask:
    result = await SchoolOperationsRepository(session).publish_task_with_snapshot(
        school_id=graph.school.id,
        class_id=graph.school_class.id,
        task_ref=f"TASK_{uuid4().hex}",
        admin_membership_role_id=graph.admin_role_id,
        instrument_id="instrument.synthetic.task",
        instrument_version="synthetic-v1",
        item_bank_version="bank.synthetic-v1",
        config_version="config.synthetic-v1",
        opens_at=opens_at or now - timedelta(minutes=1),
        due_at=due_at,
        published_at=now,
    )
    return result.task


async def test_mysql_task_publish_rolls_back_task_and_partial_snapshot(
    mysql_transaction: AsyncSession,
) -> None:
    now = utc_now()
    graph = await _create_graph(mysql_transaction, now=now)
    invalid_subject = await SubjectRepository(mysql_transaction).create(
        subject_ref=f"SUBJ_NO_SELF_GRANT_{uuid4().hex}", school_id=graph.school.id
    )
    task_ref = f"TASK_ROLLBACK_{uuid4().hex}"
    # Deliberately insert a structurally valid roster row without the required
    # student SELF grant. Snapshot validation fails after the task insert; the
    # repository savepoint must remove the task and any enrollment rows.
    mysql_transaction.add(
        SchoolClassStudent(
            school_id=graph.school.id,
            class_id=graph.school_class.id,
            subject_id=invalid_subject.id,
            status="ACTIVE",
            valid_from=now,
        )
    )
    await mysql_transaction.flush()

    with pytest.raises(ValueError, match="student SELF grant"):
        await SchoolOperationsRepository(mysql_transaction).publish_task_with_snapshot(
            school_id=graph.school.id,
            class_id=graph.school_class.id,
            task_ref=task_ref,
            admin_membership_role_id=graph.admin_role_id,
            instrument_id="instrument.synthetic.task",
            instrument_version="synthetic-v1",
            item_bank_version=None,
            config_version=None,
            opens_at=now - timedelta(minutes=1),
            due_at=None,
            published_at=now,
        )

    assert await mysql_transaction.scalar(
        select(func.count())
        .select_from(MeasurementTask)
        .where(MeasurementTask.task_ref == task_ref)
    ) == 0
    assert await mysql_transaction.scalar(
        select(func.count())
        .select_from(TaskEnrollment)
        .join(MeasurementTask, MeasurementTask.id == TaskEnrollment.task_id)
        .where(MeasurementTask.task_ref == task_ref)
    ) == 0


async def test_mysql_same_school_typed_links_and_snapshot(mysql_transaction: AsyncSession) -> None:
    now = utc_now()
    graph = await _create_graph(mysql_transaction, now=now, student_count=2)
    graph.students[1].class_link.status = "INACTIVE"
    await mysql_transaction.flush()

    task = await _publish_task(mysql_transaction, graph, now=now)
    assert task.school_id == graph.school.id
    assert task.class_id == graph.school_class.id
    assert task.created_by_membership_role_id == graph.admin_role_id

    teacher_link = await mysql_transaction.get(SchoolClassTeacher, graph.teacher_link.id)
    assert teacher_link is not None
    assert teacher_link.school_id == graph.school.id
    assert teacher_link.class_id == graph.school_class.id
    assert teacher_link.membership_role_id == graph.teacher_role_id

    enrollments = list(
        (
            await mysql_transaction.scalars(
                select(TaskEnrollment).where(TaskEnrollment.task_id == task.id)
            )
        ).all()
    )
    assert len(enrollments) == 1
    assert enrollments[0].school_id == graph.school.id
    assert enrollments[0].class_id == graph.school_class.id
    assert enrollments[0].class_student_id == graph.students[0].class_link.id
    assert enrollments[0].subject_id == graph.students[0].subject.id


async def test_mysql_task_assessment_start_binds_fields_and_reuses_same_session(
    mysql_transaction: AsyncSession, protection: FernetDataProtectionProvider
) -> None:
    now = utc_now()
    graph = await _create_graph(mysql_transaction, now=now)
    task = await _publish_task(
        mysql_transaction,
        graph,
        now=now,
        due_at=now + timedelta(hours=1),
    )
    enrollment = await mysql_transaction.scalar(
        select(TaskEnrollment).where(TaskEnrollment.task_id == task.id)
    )
    assert enrollment is not None
    repository = SchoolOperationsRepository(mysql_transaction)

    first = await repository.create_task_assessment_session(
        enrollment_id=enrollment.id,
        assessment_ref=f"ASSESS_TASK_{uuid4().hex}",
        school_id=graph.school.id,
        student_account_id=graph.students[0].account.id,
        at=now,
    )
    repeated = await repository.create_task_assessment_session(
        enrollment_id=enrollment.id,
        assessment_ref=f"ASSESS_UNUSED_{uuid4().hex}",
        school_id=graph.school.id,
        student_account_id=graph.students[0].account.id,
        at=now,
    )
    assert repeated.id == first.id
    assert first.task_enrollment_id == enrollment.id
    assert first.subject_id == enrollment.subject_id
    assert first.instrument_id == task.instrument_id
    assert first.instrument_version == task.instrument_version
    assert first.item_bank_version == task.item_bank_version
    assert first.config_version == task.config_version

    persisted = await mysql_transaction.get(AssessmentSession, first.id)
    assert persisted is not None
    assert persisted.task_enrollment_id == enrollment.id


async def test_mysql_closed_future_expired_and_revoked_enrollments_cannot_start(
    mysql_transaction: AsyncSession,
) -> None:
    now = utc_now()
    graph = await _create_graph(mysql_transaction, now=now)
    task = await _publish_task(
        mysql_transaction,
        graph,
        now=now,
        due_at=now + timedelta(hours=1),
    )
    enrollment = await mysql_transaction.scalar(
        select(TaskEnrollment).where(TaskEnrollment.task_id == task.id)
    )
    assert enrollment is not None
    operations = SchoolOperationsRepository(mysql_transaction)

    task.status = "CLOSED"
    await mysql_transaction.flush()
    with pytest.raises(NotFound):
        await operations.create_task_assessment_session(
            enrollment_id=enrollment.id,
            assessment_ref=f"ASSESS_CLOSED_{uuid4().hex}",
            school_id=graph.school.id,
            student_account_id=graph.students[0].account.id,
            at=now,
        )

    task.status = "PUBLISHED"
    task.opens_at = now + timedelta(minutes=5)
    await mysql_transaction.flush()
    with pytest.raises(NotFound):
        await operations.create_task_assessment_session(
            enrollment_id=enrollment.id,
            assessment_ref=f"ASSESS_FUTURE_{uuid4().hex}",
            school_id=graph.school.id,
            student_account_id=graph.students[0].account.id,
            at=now,
        )

    task.opens_at = now - timedelta(minutes=1)
    task.due_at = now - timedelta(seconds=1)
    await mysql_transaction.flush()
    with pytest.raises(NotFound):
        await operations.create_task_assessment_session(
            enrollment_id=enrollment.id,
            assessment_ref=f"ASSESS_EXPIRED_{uuid4().hex}",
            school_id=graph.school.id,
            student_account_id=graph.students[0].account.id,
            at=now,
        )

    task.due_at = now + timedelta(hours=1)
    await mysql_transaction.flush()
    await operations.revoke_class_student_link(
        link_id=graph.students[0].class_link.id,
        school_id=graph.school.id,
        admin_membership_role_id=graph.admin_role_id,
        at=now,
    )
    with pytest.raises(NotFound):
        await operations.create_task_assessment_session(
            enrollment_id=enrollment.id,
            assessment_ref=f"ASSESS_REVOKED_{uuid4().hex}",
            school_id=graph.school.id,
            student_account_id=graph.students[0].account.id,
            at=now,
        )
    assert enrollment.status == "REVOKED"


async def test_mysql_standalone_created_and_completed_sessions_cannot_be_rebound(
    mysql_transaction: AsyncSession, protection: FernetDataProtectionProvider
) -> None:
    now = utc_now()
    graph = await _create_graph(mysql_transaction, now=now)
    task = await _publish_task(mysql_transaction, graph, now=now)
    enrollment = await mysql_transaction.scalar(
        select(TaskEnrollment).where(TaskEnrollment.task_id == task.id)
    )
    assert enrollment is not None
    assessments = AssessmentRepository(mysql_transaction, protection)
    operations = SchoolOperationsRepository(mysql_transaction)

    created = await assessments.create_session(
        assessment_ref=f"ASSESS_STANDALONE_CREATED_{uuid4().hex}",
        subject_id=enrollment.subject_id,
        instrument_id="instrument.standalone.synthetic",
        instrument_version="standalone-v1",
        item_bank_version=None,
        config_version=None,
        trace_id=None,
    )
    completed = await assessments.create_session(
        assessment_ref=f"ASSESS_STANDALONE_COMPLETED_{uuid4().hex}",
        subject_id=enrollment.subject_id,
        instrument_id="instrument.standalone.synthetic",
        instrument_version="standalone-v1",
        item_bank_version=None,
        config_version=None,
        trace_id=None,
    )
    completed.status = "COMPLETED"
    await mysql_transaction.flush()

    for standalone in (created, completed):
        with pytest.raises(ValueError, match="unbound assessment sessions"):
            await operations.link_assessment_session(
                enrollment_id=enrollment.id,
                assessment_session_id=standalone.id,
                school_id=graph.school.id,
                student_account_id=graph.students[0].account.id,
                at=now,
            )
        assert standalone.task_enrollment_id is None


async def test_mysql_teacher_progress_is_aggregate_only_for_active_and_revoked_enrollment(
    mysql_transaction: AsyncSession,
) -> None:
    now = utc_now()
    graph = await _create_graph(mysql_transaction, now=now, student_count=3)
    task = await _publish_task(mysql_transaction, graph, now=now)
    enrollments = list(
        (
            await mysql_transaction.scalars(
                select(TaskEnrollment)
                .where(TaskEnrollment.task_id == task.id)
                .order_by(TaskEnrollment.id)
            )
        ).all()
    )
    assert len(enrollments) == 3
    completed = await SchoolOperationsRepository(
        mysql_transaction
    ).create_task_assessment_session(
        enrollment_id=enrollments[0].id,
        assessment_ref=f"ASSESS_PROGRESS_{uuid4().hex}",
        school_id=graph.school.id,
        student_account_id=graph.students[0].account.id,
        at=now,
    )
    completed.status = "COMPLETED"
    await SchoolOperationsRepository(mysql_transaction).revoke_enrollment(
        enrollment_id=enrollments[2].id,
        school_id=graph.school.id,
        admin_membership_role_id=graph.admin_role_id,
        at=now,
    )
    await mysql_transaction.flush()

    assert graph.teacher_role_id == graph.teacher_link.membership_role_id
    assert graph.teacher_link.class_id == graph.school_class.id
    captured_sql: list[str] = []
    sync_engine = mysql_transaction.bind.sync_engine

    def capture_progress_sql(connection, cursor, statement, parameters, context, executemany):
        del connection, cursor, parameters, context, executemany
        normalized = statement.lower()
        if "measurement_tasks" in normalized and "task_enrollments" in normalized:
            captured_sql.append(normalized)

    event.listen(sync_engine, "before_cursor_execute", capture_progress_sql)
    try:
        counts = await SchoolOperationsRepository(mysql_transaction).task_progress_counts(
            task_id=task.id,
            school_id=graph.school.id,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture_progress_sql)

    assert counts.published_enrollment_count == 3
    assert counts.active_enrollment_count == 2
    assert counts.revoked_enrollment_count == 1
    assert counts.not_started_count == 1
    assert counts.completed_count == 1
    assert len(captured_sql) == 1
    assert "assessment_responses" not in captured_sql[0]
    assert "assessment_results" not in captured_sql[0]
    assert "payload_ciphertext" not in captured_sql[0]


async def test_mysql_composite_foreign_keys_reject_cross_school_class_student_link(
    mysql_transaction: AsyncSession,
) -> None:
    now = utc_now()
    school_a = await _create_graph(mysql_transaction, now=now, school_label="A")
    school_b = await _create_graph(mysql_transaction, now=now, school_label="B")

    with pytest.raises(IntegrityError):
        async with mysql_transaction.begin_nested():
            mysql_transaction.add(
                SchoolClassStudent(
                    school_id=school_a.school.id,
                    class_id=school_a.school_class.id,
                    subject_id=school_b.students[0].subject.id,
                    status="ACTIVE",
                    valid_from=now,
                )
            )
            await mysql_transaction.flush()


async def test_mysql_two_concurrent_task_starts_return_one_bound_session(session_factory) -> None:
    """Committed rows use fresh UUID references and remain append-only test data."""

    now = utc_now()
    async with session_factory() as seed_session:
        async with seed_session.begin():
            graph = await _create_graph(seed_session, now=now)
            task = await _publish_task(seed_session, graph, now=now)
            enrollment = await seed_session.scalar(
                select(TaskEnrollment).where(TaskEnrollment.task_id == task.id)
            )
            assert enrollment is not None
            enrollment_id = enrollment.id
            school_id = graph.school.id
            student_id = graph.students[0].account.id

    rendezvous = asyncio.Barrier(2)

    async def start_once() -> int:
        async with session_factory() as session:
            async with session.begin():
                repository = SchoolOperationsRepository(session)
                original = repository._linked_session_for_enrollment

                async def synchronized_lookup(
                    enrollment_id: int,
                    subject_id: int,
                    *,
                    current_read: bool = False,
                ):
                    result = await original(
                        enrollment_id,
                        subject_id,
                        current_read=current_read,
                    )
                    if not current_read:
                        await rendezvous.wait()
                    return result

                repository._linked_session_for_enrollment = synchronized_lookup
                created = await repository.create_task_assessment_session(
                    enrollment_id=enrollment_id,
                    assessment_ref=f"ASSESS_CONCURRENT_{uuid4().hex}",
                    school_id=school_id,
                    student_account_id=student_id,
                    at=now,
                )
                return created.id

    session_ids = await asyncio.gather(start_once(), start_once())
    assert session_ids[0] == session_ids[1]

    async with session_factory() as verify_session:
        persisted = list(
            (
                await verify_session.scalars(
                    select(AssessmentSession).where(
                        AssessmentSession.task_enrollment_id == enrollment_id
                    )
                )
            ).all()
        )
    assert len(persisted) == 1
    assert persisted[0].id == session_ids[0]
