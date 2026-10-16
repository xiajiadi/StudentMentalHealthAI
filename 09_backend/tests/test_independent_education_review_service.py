from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.independent_education_reviews.schemas import (
    EducationReviewStateRequest,
    IndependentEducationCandidateProjection,
    publish_material_sha256,
)
from smhai_backend.domains.independent_education_reviews.service import (
    IndependentEducationReviewService,
)
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.integrations.safety import SafetyCheckView, SafetyDecisionView

_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
_CONTEXT = RequestContext(request_id="REQ_review_publish", trace_id="TRACE_review_publish")
_CHUNK = "CHUNK_SCHOOL_RESEARCH_RECORD_1"
_MANIFEST = "a" * 64
_BODY = "资料仅支持谨慎、一般性的教育说明。"


def _candidate() -> dict[str, object]:
    card = {
        "chunk_id": _CHUNK,
        "record_id": "record-1",
        "source_id": "source-1",
        "title": "General education source",
        "organization": "Example organization",
        "canonical_url": "https://example.edu/source",
        "record_locator": "Abstract",
        "source_population_scope": "Secondary school students",
        "source_language": "en",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Example organization",
        "excerpt_sha256": "b" * 64,
        "excerpt_text": "A short source excerpt.",
        "consumer_age_min": 14,
        "consumer_age_max": 17,
    }
    citation = {
        "citation_id": "CITATION_test_1",
        "chunk_id": _CHUNK,
        "document_id": "DOC_test_1",
        "title": card["title"],
        "organization": card["organization"],
        "locator": "Abstract",
        "rank": 1,
        "source_version": "knowledge.v1",
        "source_hash": "sha256:" + card["excerpt_sha256"],
    }
    candidate = {
        "schema_version": "independent-research-education-candidate.v1",
        "content": {
            "summary": "一般教育信息。",
            "observations": [],
            "suggestions": [{"text": "可继续查阅来源。", "source_chunk_ids": [_CHUNK]}],
            "disclaimer": "此信息仅用于研究演示。",
        },
        "citations": [citation],
        "source_cards": [card],
        "provenance": {
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "source_study_ref": "school-study-r1",
            "source_package_ref": "student-package-r3",
            "source_manifest_sha256": _MANIFEST,
            "retrieval_id": "RETR_test_1",
            "retrieval_bundle_sha256": "c" * 64,
            "prompt_id": "PROMPT_research_student",
            "prompt_version": "1.4.0",
            "prompt_sha256": None,
            "model_id": "MODEL_local_7b",
            "logical_model_id": "qwen-pinned-7b",
            "model_version": "7b-v1",
            "model_digest_sha256": "d" * 64,
            "runtime_version": "runtime-pinned",
            "trace_id": "TRACE_source_generation",
            "input_safety_action": "PROCEED",
            "input_safety_reason_codes": ["SYNTHETIC_TEST"],
            "retrieval_safety_action": "PROCEED",
            "retrieval_safety_reason_codes": ["SYNTHETIC_TEST"],
            "output_safety_action": "PROCEED",
            "output_safety_reason_codes": ["SYNTHETIC_TEST"],
            "claim_boundary_status": "ACCEPTED",
            "citation_binding_status": "BOUND",
        },
    }
    projection = IndependentEducationCandidateProjection.model_validate(candidate, strict=True)
    return projection.model_dump(mode="json")


def _detail() -> dict[str, object]:
    candidate = _candidate()
    draft = {
        "title": "一般教育资料摘要",
        "body": _BODY,
        "content_revision": 2,
        "citations": candidate["citations"],
        "source_cards": candidate["source_cards"],
        "updated_at": _NOW.isoformat().replace("+00:00", "Z"),
    }
    return {
        "review_ref": "EDUREV_" + "e" * 32,
        "status": "DRAFT",
        "state_version": 3,
        "created_at": _NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": _NOW.isoformat().replace("+00:00", "Z"),
        "shared_at": _NOW.isoformat().replace("+00:00", "Z"),
        "candidate": candidate,
        "reviewed_draft": draft,
    }


def _summary() -> dict[str, object]:
    draft = _detail()["reviewed_draft"]
    return {
        "review_ref": "EDUREV_" + "e" * 32,
        "status": "PUBLISHED",
        "state_version": 4,
        "created_at": _NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": _NOW.isoformat().replace("+00:00", "Z"),
        "reviewer_ref": None,
        "published_content": {
            "title": draft["title"],
            "body": draft["body"],
            "citations": draft["citations"],
            "source_cards": draft["source_cards"],
            "published_at": _NOW.isoformat().replace("+00:00", "Z"),
        },
    }


class _FakePersistence:
    def __init__(self, *, failure: BackendError | None = None) -> None:
        self.failure = failure
        self.publish_calls: list[dict[str, object]] = []

    async def staff_detail(self, actor, review_ref):
        return _detail()

    async def publish(self, actor, review_ref, **kwargs):
        self.publish_calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return _summary()


class _FakeSafety:
    def __init__(
        self,
        *,
        action: str = "PROCEED",
        requires_human: bool = False,
        failure: Exception | None = None,
    ) -> None:
        self.action = action
        self.requires_human = requires_human
        self.failure = failure
        self.calls: list[tuple[dict[str, object], str]] = []

    async def check_output(self, context, candidate_text, request_context):
        self.calls.append((dict(context), candidate_text))
        if self.failure is not None:
            raise self.failure
        return SafetyCheckView(
            operation="OUTPUT",
            trace_id=request_context.trace_id,
            decision=SafetyDecisionView(
                action=self.action,
                reason_codes=["SYNTHETIC_TEST"],
                requires_human=self.requires_human,
                trace_id=request_context.trace_id,
                decision_id="DEC_test_publish",
            ),
        )


ACTOR = Actor(
    user_id="ACCOUNT_specialist",
    username="synthetic_specialist",
    role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
    subject_id=None,
    school_id=1,
    school_ref="SCHOOL_synthetic",
    scope_profile="school_tenant",
)


def _publish(service: IndependentEducationReviewService):
    return service.publish(
        ACTOR,
        "EDUREV_" + "e" * 32,
        payload=EducationReviewStateRequest(expected_version=3),
        idempotency_key="publish-key-1",
        context=_CONTEXT,
    )


@pytest.mark.asyncio
async def test_publish_runs_standard_output_safety_and_stores_separate_receipt() -> None:
    persistence = _FakePersistence()
    safety = _FakeSafety()
    service = IndependentEducationReviewService(persistence=persistence, safety=safety)

    result = await _publish(service)

    assert result.status == "PUBLISHED"
    assert len(safety.calls) == 1
    context, candidate_text = safety.calls[0]
    assert context["trace_id"] == _CONTEXT.trace_id
    assert context["current_user_message"] == ""
    assert context["conversation_metadata"]["source_manifest_sha256"] == _MANIFEST
    assert context["generation_metadata"]["source_model_id"] == "MODEL_local_7b"
    assert _BODY in json.loads(candidate_text)["summary"]
    assert "original question" not in candidate_text
    call = persistence.publish_calls[0]
    assert call["safety_material_sha256"] == publish_material_sha256(
        _detail()["candidate"], _detail()["reviewed_draft"]
    )
    assert call["publish_safety_check"]["action"] == "PROCEED"
    assert call["publish_safety_check"]["requires_human"] is False
    assert call["publish_safety_check"]["trace_id"] == _CONTEXT.trace_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "requires_human"),
    [("REVIEW_REQUIRED", True), ("BLOCK", False), ("CRISIS_ROUTE", True)],
)
async def test_publish_safety_stop_preserves_draft_without_publish(
    action: str, requires_human: bool
) -> None:
    persistence = _FakePersistence()
    service = IndependentEducationReviewService(
        persistence=persistence,
        safety=_FakeSafety(action=action, requires_human=requires_human),
    )

    with pytest.raises(BackendError):
        await _publish(service)

    assert persistence.publish_calls == []


@pytest.mark.asyncio
async def test_publish_safety_dependency_failure_preserves_draft() -> None:
    persistence = _FakePersistence()
    service = IndependentEducationReviewService(
        persistence=persistence,
        safety=_FakeSafety(failure=TimeoutError("synthetic timeout")),
    )

    with pytest.raises(BackendError) as raised:
        await _publish(service)

    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert persistence.publish_calls == []


@pytest.mark.asyncio
async def test_stale_publish_version_is_rejected_after_safety_without_publish_success() -> None:
    persistence = _FakePersistence(
        failure=error(ErrorCode.WORKFLOW_CONFLICT, detail="stale version")
    )
    safety = _FakeSafety()
    service = IndependentEducationReviewService(persistence=persistence, safety=safety)

    with pytest.raises(BackendError) as raised:
        await _publish(service)

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert len(safety.calls) == 1
    assert len(persistence.publish_calls) == 1
    assert persistence.publish_calls[0]["publish_safety_check"]["requires_human"] is False
