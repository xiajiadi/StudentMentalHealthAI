from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from smhai_backend.core.errors import (
    BackendError,
    backend_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.school_research_education_candidates.router import router
from smhai_backend.domains.school_research_education_candidates.service import (
    SchoolResearchEducationCandidateService,
)

from .test_school_research_education_candidates_service import FakePersistence, actor


def mounted_app(role: BackendRole):
    app = FastAPI()
    persistence = FakePersistence()
    app.state.container = SimpleNamespace(
        school_research_education_candidates=SchoolResearchEducationCandidateService(
            persistence=persistence
        ),
        settings=SimpleNamespace(
            allowed_origins=(),
            auth=SimpleNamespace(csrf_header_name="X-CSRF-Token"),
        ),
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        request.state.session = SimpleNamespace(csrf_token="synthetic-csrf-token")
        return await call_next(request)

    async def provide_actor():
        return actor(role)

    app.dependency_overrides[current_actor] = provide_actor
    return app, persistence


@pytest.mark.parametrize(
    "role",
    [BackendRole.STUDENT, BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER],
)
async def test_non_specialist_cannot_read_enqueue_or_resolve(role):
    app, persistence = mounted_app(role)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = "/api/v1/school/research-education-candidates"
        tasks = await client.get(f"{root}/tasks")
        listed = await client.get(f"{root}/tasks/TASK_demo/candidates")
        jobs = await client.get(f"{root}/tasks/TASK_demo/generation-jobs")
        detail = await client.get(f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1")
        input_reviews = await client.get(f"{root}/tasks/TASK_demo/input-reviews")
        output_reviews = await client.get(
            f"{root}/tasks/TASK_demo/output-reviews?offset=0&limit=20"
        )
        output_review = await client.get(
            f"{root}/tasks/TASK_demo/output-reviews/REOR_{'a' * 32}"
        )
        input_review = await client.get(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1"
        )
        queued = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2, "offset": 0},
            headers={"Idempotency-Key": "denied", "X-CSRF-Token": "synthetic-csrf-token"},
        )
        resolved = await client.post(
            f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "ADOPTED"},
            headers={"Idempotency-Key": "denied", "X-CSRF-Token": "synthetic-csrf-token"},
        )
        input_review_resolved = await client.post(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "REVOKED"},
            headers={
                "Idempotency-Key": "denied-input-review",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        output_review_resolved = await client.post(
            f"{root}/tasks/TASK_demo/output-reviews/REOR_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "REJECTED"},
            headers={
                "Idempotency-Key": "denied-output-review",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
    assert [
        tasks.status_code,
        listed.status_code,
        jobs.status_code,
        detail.status_code,
        input_reviews.status_code,
        input_review.status_code,
        queued.status_code,
        resolved.status_code,
        input_review_resolved.status_code,
        output_reviews.status_code,
        output_review.status_code,
        output_review_resolved.status_code,
    ] == [403] * 12
    assert persistence.calls == []


async def test_specialist_api_is_bounded_csrf_idempotent_and_payload_closed():
    app, persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = "/api/v1/school/research-education-candidates"
        tasks = await client.get(f"{root}/tasks")
        listed = await client.get(f"{root}/tasks/TASK_demo/candidates?offset=3&limit=7")
        jobs = await client.get(f"{root}/tasks/TASK_demo/generation-jobs?offset=2&limit=7")
        input_reviews = await client.get(f"{root}/tasks/TASK_demo/input-reviews")
        output_reviews = await client.get(
            f"{root}/tasks/TASK_demo/output-reviews?offset=0&limit=20"
        )
        output_review = await client.get(
            f"{root}/tasks/TASK_demo/output-reviews/REOR_{'a' * 32}"
        )
        input_review = await client.get(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1"
        )
        input_review_bad_page = await client.get(
            f"{root}/tasks/TASK_demo/input-reviews?limit=21"
        )
        detail = await client.get(f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1")
        missing_idem = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2},
            headers={"X-CSRF-Token": "synthetic-csrf-token"},
        )
        missing_csrf = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2},
            headers={"Idempotency-Key": "batch"},
        )
        queued = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2, "offset": 9},
            headers={
                "Idempotency-Key": "batch",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        bad_payload = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 101},
            headers={
                "Idempotency-Key": "batch-bad",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        resolved = await client.post(
            f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "ADOPTED"},
            headers={
                "Idempotency-Key": "resolve",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        input_review_resolved = await client.post(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "REJECTED"},
            headers={
                "Idempotency-Key": "input-review-resolve",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        input_review_missing_idem = await client.post(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "REVOKED"},
            headers={"X-CSRF-Token": "synthetic-csrf-token"},
        )
        input_review_missing_csrf = await client.post(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "REVOKED"},
            headers={"Idempotency-Key": "input-review-no-csrf"},
        )
        input_review_bad_target = await client.post(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "APPROVED"},
            headers={
                "Idempotency-Key": "input-review-bad-target",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        input_review_bad_version = await client.post(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1/resolve",
            json={"expected_state_version": 0, "target": "REVOKED"},
            headers={
                "Idempotency-Key": "input-review-bad-version",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        input_review_unavailable_action = await client.post(
            f"{root}/tasks/TASK_demo/input-reviews/REI_synthetic_1/continue",
            json={},
            headers={
                "Idempotency-Key": "input-review-continue",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        output_review_missing_idem = await client.post(
            f"{root}/tasks/TASK_demo/output-reviews/REOR_{'a' * 32}/resolve",
            json={"expected_state_version": 1, "target": "REJECTED"},
            headers={"X-CSRF-Token": "synthetic-csrf-token"},
        )
        output_review_missing_csrf = await client.post(
            f"{root}/tasks/TASK_demo/output-reviews/REOR_{'a' * 32}/resolve",
            json={"expected_state_version": 1, "target": "REJECTED"},
            headers={"Idempotency-Key": "output-review-no-csrf"},
        )
        output_review_resolved = await client.post(
            f"{root}/tasks/TASK_demo/output-reviews/REOR_{'a' * 32}/resolve",
            json={"expected_state_version": 1, "target": "REJECTED"},
            headers={
                "Idempotency-Key": "output-review-reject",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        output_review_candidate = await client.post(
            f"{root}/tasks/TASK_demo/output-reviews/REOR_{'a' * 32}/resolve",
            json={"expected_state_version": 1, "target": "CREATE_HELD_CANDIDATE"},
            headers={
                "Idempotency-Key": "output-review-candidate",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        unapproved_publish_route = await client.post(
            f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1/publish",
            json={},
            headers={
                "Idempotency-Key": "publish",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )

    assert tasks.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["data"]["offset"] == 3
    assert listed.json()["data"]["limit"] == 7
    assert jobs.status_code == 200
    jobs_data = jobs.json()["data"]
    assert jobs_data["offset"] == 2
    assert jobs_data["limit"] == 7
    assert jobs_data["policy_version"] == "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
    assert set(jobs_data["status_counts"]) == {
        "QUEUED", "LEASED", "RETRY", "HELD", "ABSTAINED", "REVIEW_REQUIRED",
        "CRISIS_ROUTED", "FAILED", "CANCELLED",
    }
    assert not ({"subject_id", "lease_owner", "lease_token", "candidate_payload"}
                & set(jobs_data["items"][0]))
    assert jobs_data["items"][0]["generation_round"] == 0
    assert jobs_data["items"][0]["input_review_ref"] is None
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["candidate_payload"]["schema_version"] == (
        "school-research-general-education-candidate.v1"
    )
    assert detail_data["student_feedback_eligible"] is False
    assert not ({"subject_id", "score", "answers", "response_text"} & set(detail_data))
    assert input_reviews.status_code == 200
    review_page = input_reviews.json()["data"]
    assert review_page["limit"] == 20
    assert review_page["items"][0]["reason_codes"] == ["CONTENT_CONTROVERSIAL"]
    assert review_page["items"][0]["continuation_enabled"] is False
    assert input_review.status_code == 200
    assert input_review_bad_page.status_code == 422
    review_data = input_review.json()["data"]
    assert review_data["fixed_request"]
    assert review_data["policy_version"] == "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
    assert not ({"subject_id", "score", "answers", "response_text", "safety_review_ref"}
                & set(review_data))
    assert missing_idem.status_code == 422
    assert missing_csrf.status_code == 403
    assert queued.status_code == 200
    assert queued.json()["data"]["policy_version"] == "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
    assert queued.json()["data"]["student_feedback_eligible"] is False
    assert bad_payload.status_code == 422
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "ADOPTED"
    assert resolved.json()["data"]["student_feedback_eligible"] is False
    assert unapproved_publish_route.status_code in {404, 405}
    assert input_review_resolved.status_code == 200
    assert input_review_resolved.json()["data"]["status"] == "REJECTED"
    assert input_review_resolved.json()["data"]["continuation_enabled"] is False
    assert input_review_missing_idem.status_code == 422
    assert input_review_missing_csrf.status_code == 403
    assert input_review_bad_target.status_code == 422
    assert input_review_bad_version.status_code == 422
    assert input_review_unavailable_action.status_code in {404, 405}
    assert output_reviews.status_code == 200
    output_page = output_reviews.json()["data"]
    assert set(output_page) == {"items", "offset", "limit", "has_more"}
    assert output_page["items"][0]["safety_action"] == "REVIEW_REQUIRED"
    assert output_page["items"][0]["reason_codes"] == ["CONTENT_CONTROVERSIAL"]
    assert output_review.status_code == 200
    output_detail = output_review.json()["data"]
    assert output_detail["review_payload"]["citations"] == []
    assert output_detail["review_payload"]["citation_binding_status"] == (
        "NOT_EVALUATED_AT_OUTPUT_STOP"
    )
    assert "retrieval_snapshot" not in output_detail["review_payload"]
    assert "payload_ciphertext" not in output_detail
    assert output_review_missing_idem.status_code == 422
    assert output_review_missing_csrf.status_code == 403
    assert output_review_resolved.status_code == 200
    assert output_review_resolved.json()["data"]["output_review"]["status"] == "REJECTED"
    assert "candidate" not in output_review_resolved.json()["data"]
    assert output_review_candidate.status_code == 200
    candidate_result = output_review_candidate.json()["data"]
    assert candidate_result["output_review"]["status"] == "CONSUMED"
    assert candidate_result["candidate"]["status"] == "HELD"
    assert [call[0] for call in persistence.calls] == [
        "tasks", "list", "jobs", "input_review_list", "output_review_list",
        "output_review_get", "input_review_get", "get", "queue", "resolve",
        "input_review_resolve", "output_review_resolve", "output_review_resolve",
    ]


async def test_specialist_can_authorize_once_and_revoke_unused_authorization():
    app, persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    persistence.input_review_continuation_enabled = True
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = (
            "/api/v1/school/research-education-candidates/tasks/"
            "TASK_demo/input-reviews/REI_synthetic_1"
        )
        listed = await client.get(root.rsplit("/REI_synthetic_1", 1)[0])
        authorized = await client.post(
            f"{root}/resolve",
            json={"expected_state_version": 1, "target": "CONTINUATION_AUTHORIZED"},
            headers={
                "Idempotency-Key": "authorize-once",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        revoked = await client.post(
            f"{root}/resolve",
            json={"expected_state_version": 2, "target": "REVOKED"},
            headers={
                "Idempotency-Key": "revoke-unused-authorization",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )

    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["continuation_enabled"] is True
    assert authorized.status_code == 200
    assert authorized.json()["data"]["status"] == "CONTINUATION_AUTHORIZED"
    assert authorized.json()["data"]["state_version"] == 2
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "REVOKED"
    assert revoked.json()["data"]["state_version"] == 3
    assert [call[0] for call in persistence.calls] == [
        "input_review_list", "input_review_resolve", "input_review_resolve"
    ]
