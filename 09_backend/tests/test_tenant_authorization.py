from __future__ import annotations

import copy
import json
from pathlib import Path

from pwdlib import PasswordHash

from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import (
    Actor,
    AssessmentRecord,
    BackendRole,
    SchoolRoleContext,
    SyntheticUser,
)


def test_school_roles_do_not_inherit_legacy_or_internal_privileges():
    authorization = NativeAuthorizationProvider()
    teacher = Actor(
        user_id="USER_teacher_a",
        username="teacher_a",
        role=BackendRole.TEACHER,
        subject_id=None,
        accessible_subject_ids=frozenset({"SUBJ_school_a"}),
        scope_profile="school_tenant",
        school_id=101,
        school_ref="SCHOOL_synthetic_a",
    )
    assert authorization.can(
        teacher, "teacher:summary", resource={"subject_id": "SUBJ_school_a"}
    )
    assert not authorization.can(
        teacher, "teacher:summary", resource={"subject_id": "SUBJ_school_b"}
    )
    for action in ("assessment:read", "report:read", "support:create", "retrieval:create"):
        assert not authorization.can(teacher, action, resource={"subject_id": "SUBJ_school_a"})

    student = SyntheticUser(
        user_id="USER_student_a",
        username="student_a",
        role=BackendRole.STUDENT,
        subject_id=None,
        password_hash="synthetic-only",
        scope_profile="school_tenant",
        school_contexts=(
            SchoolRoleContext(
                context_id="membership-role-a",
                role=BackendRole.STUDENT,
                school_id=101,
                school_ref="SCHOOL_synthetic_a",
                accessible_subject_ids=frozenset({"SUBJ_school_a"}),
            ),
        ),
        default_context_id="membership-role-a",
    ).actor()
    assert student is not None
    assert student.subject_id == "SUBJ_school_a"
    assert authorization.can(
        student, "assessment:read", resource={"subject_id": "SUBJ_school_a"}
    )
    assert not authorization.can(
        student, "assessment:read", resource={"subject_id": "SUBJ_legacy"}
    )

    unbound_teacher = Actor(
        user_id="USER_unbound",
        username="unbound",
        role=BackendRole.TEACHER,
        subject_id=None,
        accessible_subject_ids=frozenset({"SUBJ_legacy"}),
        scope_profile="school_tenant",
    )
    assert not authorization.can(
        unbound_teacher, "teacher:summary", resource={"subject_id": "SUBJ_legacy"}
    )


def _record(subject_id: str, assessment_id: str) -> AssessmentRecord:
    return AssessmentRecord(
        assessment_id=assessment_id,
        subject_id=subject_id,
        data_origin="SYNTHETIC",
        assessment={
            "schema_version": "assessment.v1",
            "assessment_id": assessment_id,
            "subject_id": subject_id,
            "population_scope": "SYNTHETIC_STUDENT_DEMO",
            "status": "completed",
            "timestamps": {"started_at": "2026-10-11T00:00:00Z"},
        },
        responses={},
    )


def _bound_synthetic_record(subject_id: str, assessment_id: str) -> AssessmentRecord:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "03_assessment-adapter"
        / "fixtures"
        / "synthetic_assessment.v1.json"
    )
    assessment = json.loads(fixture.read_text(encoding="utf-8"))
    assessment["assessment_id"] = assessment_id
    assessment["subject_id"] = subject_id
    return AssessmentRecord(
        assessment_id=assessment_id,
        subject_id=subject_id,
        assessment=copy.deepcopy(assessment),
        data_origin="SYNTHETIC",
    )


async def test_tenant_teacher_routes_remain_in_membership_scope_and_not_individual_reads(
    app, client
):
    user = SyntheticUser(
        user_id="USER_tenant_teacher",
        username="tenant_teacher",
        role=BackendRole.TEACHER,
        subject_id=None,
        password_hash=PasswordHash.recommended().hash("synthetic-password"),
        scope_profile="school_tenant",
        school_contexts=(
            SchoolRoleContext(
                context_id="tenant-role-a",
                role=BackendRole.TEACHER,
                school_id=101,
                school_ref="SCHOOL_synthetic_a",
                accessible_subject_ids=frozenset({"SUBJ_school_a"}),
            ),
        ),
        default_context_id=None,
    )
    app.state.container.users._add(user)
    app.state.container.assessments_repo.save(_record("SUBJ_school_a", "ASSESS_school_a"))
    app.state.container.assessments_repo.save(_record("SUBJ_school_b", "ASSESS_school_b"))
    app.state.container.assessments_repo.save(_record("SUBJ_legacy", "ASSESS_legacy"))

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "tenant_teacher", "password": "synthetic-password"},
    )
    assert login.status_code == 200
    csrf = login.json()["data"]["csrf_token"]
    selected = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "TEACHER", "school_ref": "SCHOOL_synthetic_a"},
    )
    assert selected.status_code == 200

    overview = await client.get("/api/v1/teacher/overview")
    assert overview.status_code == 200
    assert [row["subject_id"] for row in overview.json()["data"]["students"]] == [
        "SUBJ_school_a"
    ]
    assert overview.json()["data"]["assessments_count"] == 1

    history = await client.get("/api/v1/teacher/students/SUBJ_school_b")
    assert history.status_code == 403
    assessments = await client.get("/api/v1/assessments")
    assert assessments.status_code == 200
    assert assessments.json()["data"] == []


async def test_tenant_student_assessment_and_support_routes_keep_subject_scope(app, client):
    user = SyntheticUser(
        user_id="USER_tenant_student",
        username="tenant_student",
        role=BackendRole.STUDENT,
        subject_id=None,
        password_hash=PasswordHash.recommended().hash("synthetic-password"),
        scope_profile="school_tenant",
        school_contexts=(
            SchoolRoleContext(
                context_id="tenant-student-role-a",
                role=BackendRole.STUDENT,
                school_id=101,
                school_ref="SCHOOL_synthetic_a",
                accessible_subject_ids=frozenset({"SUBJ_school_a"}),
            ),
        ),
        default_context_id=None,
    )
    app.state.container.users._add(user)
    app.state.container.assessments_repo.save(
        _bound_synthetic_record("SUBJ_school_b", "ASSESS_other_school")
    )
    app.state.container.assessments_repo.save(
        _bound_synthetic_record("SUBJ_legacy", "ASSESS_legacy")
    )

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "tenant_student", "password": "synthetic-password"},
    )
    assert login.status_code == 200
    csrf = login.json()["data"]["csrf_token"]
    selected = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "STUDENT", "school_ref": "SCHOOL_synthetic_a"},
    )
    assert selected.status_code == 200
    headers = {"X-CSRF-Token": csrf}

    assessment = await client.post(
        "/api/v1/assessments",
        headers=headers,
        json={
            "subject_id": "SUBJ_school_a",
            "instrument_id": "INST_synthetic_v1",
            "instrument_version": "1.0",
        },
    )
    assert assessment.status_code == 201
    assessment_id = assessment.json()["data"]["assessment_id"]
    app.state.container.assessments_repo.save(
        _bound_synthetic_record("SUBJ_school_a", assessment_id)
    )

    support = await client.post(
        "/api/v1/support/requests",
        headers=headers,
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "Synthetic request for route authorization coverage.",
        },
    )
    # The ContractFake pipeline may return a buffered result or its documented
    # fail-closed dependency response; either outcome means this request passed
    # persisted-assessment ownership and tenant-subject authorization.
    assert support.status_code in {202, 502}, support.text
    assert app.state.container.support.call_order
    call_order_after_authorized_request = list(app.state.container.support.call_order)

    for assessment_id in ("ASSESS_other_school", "ASSESS_legacy"):
        denied = await client.post(
            "/api/v1/support/requests",
            headers=headers,
            json={
                "assessment_id": assessment_id,
                "target_role": "student",
                "message": "Synthetic cross-scope negative case.",
            },
        )
        assert denied.status_code == 404
        assert app.state.container.support.call_order == call_order_after_authorized_request
