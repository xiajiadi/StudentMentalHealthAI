"""Provision a small, independent synthetic school in the normal school tables."""

from __future__ import annotations

from datetime import datetime, timedelta
from random import Random
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.assessment.binding import D3_IDENTITY

CLASS_COUNT = 12
STUDENT_COUNT = 800
COMPLETED_BASELINE_COUNT = 520
# One task in each of these rounds per original class. Dates are offsets from
# the school's first run of this seed, so the first calendar has all phases.
DEMO_ROUNDS = (
    ("ADJUST", -35, -17, 0.82),
    ("ROUTINE", -25, -5, 0.73),
    ("PEERS", -18, 3, 0.75),
    ("CAMPUS", -12, 8, 0.70),
    ("COPING", -6, 12, 0.67),
    ("GOALS", 4, 18, 0),
)
# Responses recorded by exercising the checked-in synthetic GRM fixture
# with fixed option sequences. Only original seeded users receive these traces.
BASELINE_CAT_TRACES = (
    ((8, 'never'), (3, 'rarely'), (2, 'sometimes'), (5, 'often'), (7, 'always'), (1, 'never'), (9, 'rarely'), (4, 'sometimes')),
    ((8, 'often'), (3, 'never'), (5, 'sometimes'), (2, 'always'), (7, 'rarely'), (1, 'often')),
    ((8, 'rarely'), (3, 'always'), (5, 'sometimes'), (2, 'never'), (7, 'often'), (1, 'rarely'), (9, 'always'), (4, 'sometimes')),
    ((8, 'always'), (3, 'often'), (5, 'sometimes'), (2, 'rarely'), (7, 'never'), (1, 'always'), (9, 'often')),
    ((8, 'sometimes'), (3, 'often'), (5, 'always'), (2, 'never'), (7, 'rarely'), (1, 'sometimes'), (9, 'often')),
    ((8, 'never'), (3, 'sometimes'), (5, 'always'), (2, 'rarely'), (7, 'often'), (1, 'never'), (9, 'sometimes'), (4, 'always')),
    ((8, 'often'), (3, 'rarely'), (5, 'always'), (2, 'sometimes'), (7, 'never'), (1, 'often')),
    ((8, 'rarely'), (3, 'never'), (2, 'always'), (5, 'often'), (7, 'sometimes'), (1, 'rarely'), (9, 'never'), (4, 'always')),
    ((8, 'always'), (3, 'never'), (5, 'rarely'), (2, 'sometimes'), (7, 'often'), (1, 'always'), (9, 'never'), (4, 'rarely')),
    ((8, 'sometimes'), (3, 'always'), (5, 'rarely'), (2, 'often'), (7, 'never'), (1, 'sometimes')),
    ((8, 'never'), (3, 'often'), (5, 'rarely'), (2, 'always'), (7, 'sometimes'), (1, 'never'), (9, 'often'), (4, 'rarely')),
    ((8, 'often'), (3, 'sometimes'), (5, 'rarely'), (2, 'never'), (7, 'always'), (1, 'often')),
)



async def _insert_rows(session: Any, model: Any, rows: list[dict[str, Any]]) -> None:
    # Core executemany lets the MySQL driver send multi-row INSERTs. An ORM
    # flush needs to obtain each auto-increment key separately on MySQL.
    await session.execute(insert(model.__table__), rows)


async def _insert_ids(session: Any, model: Any, rows: list[dict[str, Any]]) -> list[int]:
    from database_layer.base import new_public_id

    public_ids = [new_public_id() for _ in rows]
    await _insert_rows(session, model, [
        {**row, "public_id": key} for row, key in zip(rows, public_ids, strict=True)
    ])
    found = await session.execute(
        select(model.public_id, model.id).where(model.public_id.in_(public_ids))
    )
    by_public_id = dict(found.tuples().all())
    return [by_public_id[key] for key in public_ids]


async def provision_school(
    uow: Any,
    *,
    username: str,
    owner_hash: str,
    unused_hash: str,
    claim: str,
    capacity: int,
    now: datetime,
) -> None:
    from database_layer import models as m
    from database_layer.provenance import (
        PUBLIC_DEMO_SCHOOL_PREFIX,
        SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
    )

    session = uow.session
    assert session is not None
    # A stable reference row serializes only signup transactions. The count is
    # the first consistent read after obtaining this MySQL transaction lock.
    lock = await session.scalar(
        select(m.Role.id).where(m.Role.role_code == "admin").with_for_update()
    )
    if lock is None:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="demo provisioning unavailable")
    school_count = await session.scalar(
        select(func.count(m.School.id)).where(
            m.School.school_ref.startswith(PUBLIC_DEMO_SCHOOL_PREFIX, autoescape=True)
        )
    )
    if school_count is None or school_count >= capacity:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="demo capacity reached")

    school_ref = PUBLIC_DEMO_SCHOOL_PREFIX + claim
    school = m.School(
        school_ref=school_ref,
        display_name="PsyNova 合成演示学校",
        data_origin="SYNTHETIC",
        provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
    )
    account_rows = [dict(login_name=username, password_hash=owner_hash)]
    account_rows.extend(
        dict(login_name=f"seed.{claim}.{index:03d}", password_hash=unused_hash)
        for index in range(1, STUDENT_COUNT)
    )
    try:
        session.add(school)
        await session.flush()
        accounts = await _insert_ids(session, m.Account, account_rows)
    except IntegrityError:
        raise error(
            ErrorCode.WORKFLOW_CONFLICT, detail="account or verification already used"
        ) from None

    memberships = await _insert_ids(session, m.AccountSchoolMembership, [
        dict(
            account_id=account,
            school_id=school.id,
            display_name="演示体验者" if index == 0 else f"合成学生 {index:03d}",
            valid_from=now,
        )
        for index, account in enumerate(accounts)
    ])
    subjects = await _insert_ids(session, m.Subject, [
        dict(school_id=school.id, subject_ref=f"SUBJ_{claim}_{index:03d}")
        for index in range(STUDENT_COUNT)
    ])

    role_codes = ("student", "teacher", "psychological_specialist", "admin")
    owner_roles = {
        code: m.MembershipRole(
            membership_id=memberships[0], school_id=school.id, role_code=code, valid_from=now
        )
        for code in role_codes
    }
    session.add_all(owner_roles.values())
    await session.flush()
    await _insert_rows(session, m.MembershipRole,
        [
            dict(
                membership_id=membership,
                school_id=school.id,
                role_code="student",
                valid_from=now,
            )
            for membership in memberships[1:]
        ]
    )
    await _insert_rows(session, m.SubjectAccessGrant,
        [
            dict(
                principal_account_id=account,
                subject_id=subject,
                school_id=school.id,
                relationship_type="SELF",
                valid_from=now,
            )
            for account, subject in zip(accounts, subjects, strict=True)
        ]
    )
    admin_id = owner_roles["admin"].id
    classes = [
        m.SchoolClass(
            school_id=school.id,
            class_ref=f"DEMO-{index // 4 + 7}-{index % 4 + 1:02d}",
            display_name=f"{index // 4 + 7} 年级 {index % 4 + 1} 班",
            grade_level=str(index // 4 + 7),
            grade_ref=f"GRADE_{index // 4 + 7}",
            created_by_membership_role_id=admin_id,
        )
        for index in range(CLASS_COUNT)
    ]
    session.add_all(classes)
    await session.flush()
    links = await _insert_ids(session, m.SchoolClassStudent, [
        dict(
            school_id=school.id,
            class_id=classes[index % CLASS_COUNT].id,
            subject_id=subject,
            valid_from=now,
        )
        for index, subject in enumerate(subjects)
    ])
    tasks = [
        m.MeasurementTask(
            school_id=school.id,
            class_id=class_row.id,
            task_ref=f"TASK_{claim}_{index + 1:02d}",
            created_by_membership_role_id=admin_id,
            instrument_id=D3_IDENTITY.instrument_id,
            instrument_version=D3_IDENTITY.instrument_version,
            opens_at=now,
            due_at=now + timedelta(days=30),
            published_at=now,
            status="PUBLISHED",
            cat_binding_mode="FIXTURE",
        )
        for index, class_row in enumerate(classes)
    ]
    session.add_all(tasks)
    await _insert_rows(session, m.SchoolClassTeacher,
        [
            dict(
                school_id=school.id,
                class_id=class_row.id,
                membership_role_id=owner_roles["teacher"].id,
                valid_from=now,
            )
            for class_row in classes
        ]
    )
    await session.flush()
    await _insert_rows(session, m.TaskEnrollment,
        [
            dict(
                school_id=school.id,
                task_id=tasks[index % CLASS_COUNT].id,
                class_id=classes[index % CLASS_COUNT].id,
                class_student_id=link,
                subject_id=subjects[index],
                status="ACTIVE",
            )
            for index, link in enumerate(links)
        ]
    )
    await _insert_rows(session, m.SchoolTaskSpecialistAssignment,
        [
            dict(
                school_id=school.id,
                task_id=task.id,
                class_id=task.class_id,
                specialist_membership_role_id=owner_roles["psychological_specialist"].id,
                assigned_by_membership_role_id=admin_id,
            )
            for task in tasks
        ]
    )
    await seed_baseline_assessments(uow, school, now=now)
    await seed_demo_rounds(uow, school, now=now)


def _encrypted_baseline_responses(protection, sessions, traces, trace_id):
    rows = []
    for session_id, answers in zip(sessions, traces, strict=True):
        for sequence, (item_number, value) in enumerate(answers, start=1):
            item_ref = f"ITEM_demo_{item_number:03d}"
            protected = protection.encrypt_json(
                {"item_id": item_ref, "value": value},
                payload_schema_version="assessment-response.v1",
            )
            rows.append(dict(
                assessment_session_id=session_id,
                sequence_no=sequence,
                item_ref=item_ref,
                response_ciphertext=protected.ciphertext,
                cipher_format_version=protected.cipher_format_version,
                key_version=protected.key_version,
                payload_schema_version=protected.payload_schema_version,
                trace_id=trace_id,
            ))
    return rows


async def seed_baseline_assessments(
    uow: Any, school: Any, *, now: datetime, apply: bool = True
) -> dict[str, int]:
    """Complete untouched fixture enrollments without modifying an existing session."""
    from database_layer import models as m
    from database_layer.provenance import (
        PUBLIC_DEMO_SCHOOL_PREFIX,
        SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
        is_public_demo_school_ref,
    )

    if (
        not is_public_demo_school_ref(school.school_ref)
        or school.data_origin != "SYNTHETIC"
        or school.provenance_ref != SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
        or school.status != "ACTIVE"
    ):
        raise ValueError("baseline assessments require an active public synthetic school")
    claim = school.school_ref.removeprefix(PUBLIC_DEMO_SCHOOL_PREFIX)
    subject_indexes = {f"SUBJ_{claim}_{index:03d}": index for index in range(STUDENT_COUNT)}
    expected_tasks = [f"TASK_{claim}_{index + 1:02d}" for index in range(CLASS_COUNT)]
    session = uow.session
    matches = (await session.execute(
        select(
            m.TaskEnrollment.id.label("enrollment_id"), m.Subject.id.label("subject_id"), m.Subject.subject_ref,
            m.MeasurementTask.task_ref, m.MeasurementTask.opens_at, m.MeasurementTask.due_at,
        )
        .select_from(m.TaskEnrollment)
        .join(m.Subject, m.Subject.id == m.TaskEnrollment.subject_id)
        .join(m.MeasurementTask, m.MeasurementTask.id == m.TaskEnrollment.task_id)
        .where(
            m.TaskEnrollment.school_id == school.id,
            m.TaskEnrollment.status == "ACTIVE",
            m.Subject.school_id == school.id,
            m.Subject.data_origin == "SYNTHETIC",
            m.Subject.status == "ACTIVE",
            m.Subject.subject_ref.in_(subject_indexes),
            m.MeasurementTask.school_id == school.id,
            m.MeasurementTask.status == "PUBLISHED",
            m.MeasurementTask.cat_binding_mode == "FIXTURE",
            m.MeasurementTask.instrument_id == D3_IDENTITY.instrument_id,
            m.MeasurementTask.instrument_version == D3_IDENTITY.instrument_version,
            m.MeasurementTask.task_ref.in_(expected_tasks),
        ).order_by(m.TaskEnrollment.id).with_for_update()
    )).all()
    matches = [row for row in matches if row.task_ref == expected_tasks[subject_indexes[row.subject_ref] % CLASS_COUNT]]
    if not matches:
        return {"active": 0, "completed_before": 0, "seeded": 0}
    existing = dict((await session.execute(
        select(m.AssessmentSession.task_enrollment_id, m.AssessmentSession.status)
        .where(m.AssessmentSession.task_enrollment_id.in_([row.enrollment_id for row in matches]))
        .order_by(m.AssessmentSession.task_enrollment_id).with_for_update()
    )).tuples().all())
    completed_before = sum(status == "COMPLETED" for status in existing.values())
    target = COMPLETED_BASELINE_COUNT * len(matches) // STUDENT_COUNT
    candidates = [row for row in matches if row.enrollment_id not in existing and subject_indexes[row.subject_ref] != 0]
    candidates.sort(key=lambda row: subject_indexes[row.subject_ref])
    planned = candidates[:max(0, target - completed_before)]
    if not planned:
        return {"active": len(matches), "completed_before": completed_before, "seeded": 0}

    assessment_rows = []
    traces = []
    trace_id = "TRACE_PUBLIC_DEMO_BASELINE_V1"
    for row in planned:
        index = subject_indexes[row.subject_ref]
        finished = min(now, row.due_at) if row.due_at is not None else now
        if row.opens_at > finished:
            continue
        assessment_rows.append(dict(
            assessment_ref=f"ASSESS_PUBLIC_DEMO_BASELINE_{claim}_{index:03d}",
            subject_id=row.subject_id,
            task_enrollment_id=row.enrollment_id,
            instrument_id=D3_IDENTITY.instrument_id,
            instrument_version=D3_IDENTITY.instrument_version,
            cat_binding_mode="FIXTURE",
            status="COMPLETED",
            started_at=max(row.opens_at, finished - timedelta(minutes=2 + index % 4)),
            completed_at=finished,
            trace_id=trace_id,
        ))
        traces.append(BASELINE_CAT_TRACES[index % len(BASELINE_CAT_TRACES)])
    if assessment_rows and apply:
        sessions = await _insert_ids(session, m.AssessmentSession, assessment_rows)
        responses = await run_in_threadpool(_encrypted_baseline_responses, uow.protection, sessions, traces, trace_id)
        await _insert_rows(session, m.AssessmentResponse, responses)
    return {"active": len(matches), "completed_before": completed_before, "seeded": len(assessment_rows)}


async def seed_demo_rounds(
    uow: Any, school: Any, *, now: datetime, apply: bool = True
) -> dict[str, Any]:
    """Add independent synthetic rounds to untouched sets of public demo classes."""
    from database_layer import models as m
    from database_layer.provenance import (
        PUBLIC_DEMO_SCHOOL_PREFIX,
        SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
        is_public_demo_school_ref,
    )

    if (
        not is_public_demo_school_ref(school.school_ref)
        or school.data_origin != "SYNTHETIC"
        or school.provenance_ref != SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
        or school.status != "ACTIVE"
    ):
        raise ValueError("demo rounds require an active public synthetic school")
    session = uow.session
    await session.scalar(select(m.School.id).where(m.School.id == school.id).with_for_update())
    claim = school.school_ref.removeprefix(PUBLIC_DEMO_SCHOOL_PREFIX)
    source_refs = [f"TASK_{claim}_{index + 1:02d}" for index in range(CLASS_COUNT)]
    source_tasks = (await session.scalars(
        select(m.MeasurementTask)
        .join(m.SchoolClass, m.SchoolClass.id == m.MeasurementTask.class_id)
        .where(
            m.MeasurementTask.school_id == school.id,
            m.MeasurementTask.task_ref.in_(source_refs),
            m.MeasurementTask.cat_binding_mode == "FIXTURE",
            m.MeasurementTask.instrument_id == D3_IDENTITY.instrument_id,
            m.MeasurementTask.instrument_version == D3_IDENTITY.instrument_version,
            m.SchoolClass.status == "ACTIVE",
        ).order_by(m.MeasurementTask.task_ref).with_for_update()
    )).all()
    summary: dict[str, Any] = {
        "tasks": 0, "active": 0, "completed": 0, "in_progress": 0,
        "abandoned": 0, "revoked": 0, "task_rates": [],
    }
    if not source_tasks:
        return summary

    target_refs = [
        f"{task.task_ref}_{topic}" for task in source_tasks for topic, *_ in DEMO_ROUNDS
    ]
    existing_refs = set((await session.scalars(
        select(m.MeasurementTask.task_ref).where(
            m.MeasurementTask.school_id == school.id, m.MeasurementTask.task_ref.in_(target_refs),
        ).with_for_update()
    )).all())
    if existing_refs:
        # The entire seed is committed atomically. Respect any later edits to
        # the roster, dates, status and enrollments in a previously seeded school.
        return summary

    task_ids = [task.id for task in source_tasks]
    student_refs = {f"SUBJ_{claim}_{index:03d}": index for index in range(1, STUDENT_COUNT)}
    roster = (await session.execute(
        select(m.TaskEnrollment, m.Subject.subject_ref)
        .join(m.Subject, m.Subject.id == m.TaskEnrollment.subject_id)
        .join(m.SchoolClassStudent, m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
        .where(
            m.TaskEnrollment.school_id == school.id,
            m.TaskEnrollment.task_id.in_(task_ids),
            m.TaskEnrollment.status == "ACTIVE",
            m.SchoolClassStudent.status == "ACTIVE",
            m.SchoolClassStudent.valid_from <= now,
            (m.SchoolClassStudent.valid_until.is_(None)) | (m.SchoolClassStudent.valid_until >= now),
            m.Subject.school_id == school.id,
            m.Subject.data_origin == "SYNTHETIC",
            m.Subject.status == "ACTIVE",
            m.Subject.subject_ref.in_(student_refs),
        ).order_by(m.Subject.subject_ref).with_for_update()
    )).all()
    by_task: dict[int, list[tuple[Any, str]]] = {task_id: [] for task_id in task_ids}
    for enrollment, subject_ref in roster:
        task_ref = source_refs[student_refs[subject_ref] % CLASS_COUNT]
        by_task[enrollment.task_id].append((enrollment, task_ref))

    task_rows = []
    assignments = []
    enrollment_plans = []
    active_specialists = (await session.scalars(
        select(m.SchoolTaskSpecialistAssignment).join(
            m.MembershipRole, m.MembershipRole.id
            == m.SchoolTaskSpecialistAssignment.specialist_membership_role_id
        ).where(
            m.SchoolTaskSpecialistAssignment.school_id == school.id,
            m.SchoolTaskSpecialistAssignment.task_id.in_(task_ids),
            m.SchoolTaskSpecialistAssignment.status == "ACTIVE",
            m.MembershipRole.status == "ACTIVE",
            m.MembershipRole.valid_from <= now,
            (m.MembershipRole.valid_until.is_(None)) | (m.MembershipRole.valid_until >= now),
        )
    )).all()
    for task in source_tasks:
        students = [student for student, ref in by_task[task.id] if ref == task.task_ref]
        if not students:
            continue
        class_effect = Random(task.task_ref).uniform(-0.12, 0.12)
        for topic, opening, deadline, rate in DEMO_ROUNDS:
            ref = f"{task.task_ref}_{topic}"
            rng = Random(ref)
            opens_at = now + timedelta(days=opening + rng.randint(-2, 2), hours=-2)
            due_at = now + timedelta(days=deadline + rng.randint(-2, 2), hours=3)
            task_index = len(task_rows)
            task_rows.append(dict(
                school_id=school.id, class_id=task.class_id, task_ref=ref,
                created_by_membership_role_id=task.created_by_membership_role_id,
                instrument_id=task.instrument_id, instrument_version=task.instrument_version,
                opens_at=opens_at, due_at=due_at, published_at=min(opens_at, now),
                status="CLOSED" if deadline < 0 else "PUBLISHED", cat_binding_mode="FIXTURE",
            ))
            assignments.extend(
                (task_index, task.class_id, assignment)
                for assignment in active_specialists if assignment.task_id == task.id
            )
            # Keep the upcoming round smaller and zero-completed. Give open and
            # historical rounds different cohort sizes, deadlines and velocities.
            min_cohort, max_cohort = (34, 62) if rate else (18, 30)
            cohort = rng.sample(students, min(len(students), rng.randint(min_cohort, max_cohort)))
            revoked = min(len(cohort) // 8, rng.randrange(4))
            active = len(cohort) - revoked
            completion_rate = max(0.39, min(0.93, rate + class_effect + rng.uniform(-0.13, 0.13)))
            completed = round(active * completion_rate) if rate else 0
            remainder = active - completed
            in_progress = round(remainder * rng.uniform(0.22, 0.72)) if opening < 0 < deadline else 0
            abandoned = round(remainder * rng.uniform(0.23, 0.86)) if deadline < 0 else 0
            summary["active"] += active
            summary["completed"] += completed
            summary["in_progress"] += in_progress
            summary["abandoned"] += abandoned
            summary["revoked"] += revoked
            summary["task_rates"].append(round(100 * completed / active, 1))
            for index, student in enumerate(cohort):
                status = None
                if index < completed:
                    status = "COMPLETED"
                elif index < completed + in_progress:
                    status = "IN_PROGRESS"
                elif index < completed + in_progress + abandoned:
                    status = "ABANDONED"
                window_seconds = int((min(now, due_at) - opens_at).total_seconds())
                recorded = (
                    opens_at + timedelta(seconds=rng.randint(300, window_seconds))
                    if status else None
                )
                trace = rng.choice(BASELINE_CAT_TRACES) if status else ()
                if status and status != "COMPLETED":
                    trace = trace[:rng.randint(1, len(trace) - 1)]
                enrollment_plans.append((
                    task_index, ref, student, status, index >= active, recorded, trace
                ))

    summary["tasks"] = len(task_rows)
    if not task_rows or not apply:
        return summary
    created_tasks = await _insert_ids(session, m.MeasurementTask, task_rows)
    if assignments:
        await _insert_rows(session, m.SchoolTaskSpecialistAssignment, [
            dict(
                school_id=school.id, task_id=created_tasks[index], class_id=class_id,
                specialist_membership_role_id=assignment.specialist_membership_role_id,
                assigned_by_membership_role_id=assignment.assigned_by_membership_role_id,
            )
            for index, class_id, assignment in assignments
        ])
    trace_id = "TRACE_PUBLIC_DEMO_ROUNDS_V1"
    for offset in range(0, len(enrollment_plans), 750):
        plans = enrollment_plans[offset:offset + 750]
        enrollments = await _insert_ids(session, m.TaskEnrollment, [
            dict(
                school_id=school.id, task_id=created_tasks[index], class_id=student.class_id,
                class_student_id=student.class_student_id, subject_id=student.subject_id,
                status="REVOKED" if revoked else "ACTIVE", revoked_at=now if revoked else None,
            )
            for index, _, student, _, revoked, _, _ in plans
        ])
        session_rows = []
        traces = []
        for enrollment_id, (_, ref, student, status, _, recorded, trace) in zip(enrollments, plans, strict=True):
            if status is None:
                continue
            session_rows.append(dict(
                assessment_ref=f"ASSESS_{ref}_{student.subject_id}",
                subject_id=student.subject_id, task_enrollment_id=enrollment_id,
                instrument_id=D3_IDENTITY.instrument_id,
                instrument_version=D3_IDENTITY.instrument_version, cat_binding_mode="FIXTURE",
                status=status, started_at=recorded - timedelta(minutes=3),
                completed_at=recorded if status == "COMPLETED" else None, trace_id=trace_id,
                created_at=recorded, updated_at=recorded,
            ))
            traces.append(trace)
        if session_rows:
            ids = await _insert_ids(session, m.AssessmentSession, session_rows)
            responses = await run_in_threadpool(
                _encrypted_baseline_responses, uow.protection, ids, traces, trace_id
            )
            await _insert_rows(session, m.AssessmentResponse, responses)
    return summary
