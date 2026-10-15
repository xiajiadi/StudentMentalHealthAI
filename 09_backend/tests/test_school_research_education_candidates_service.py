from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from smhai_backend.core.errors import BackendError
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
)
from smhai_backend.domains.research_general_education.service import (
    EXPECTED_MODEL_DIGEST_SHA256,
    EXPECTED_MODEL_ID,
    EXPECTED_MODEL_VERSION,
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_VERSION,
    SAFETY_POLICY_VERSION,
)
from smhai_backend.domains.school_research_education_candidates.service import (
    SchoolResearchEducationCandidateService,
)
from smhai_backend.domains.support.schemas import GenerationContent, Suggestion, SupportCitation


def actor(role: BackendRole) -> Actor:
    return Actor(
        user_id=f"USER_synthetic_{role.value.lower()}",
        username="synthetic-specialist",
        role=role,
        subject_id="SUBJ_student" if role is BackendRole.STUDENT else None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )


def candidate_payload():
    excerpt = "公开来源中逐字保留的人群范围与限制。"
    excerpt_sha256 = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
    return ResearchGeneralEducationCandidatePayload(
        schema_version="school-research-general-education-candidate.v1",
        content=GenerationContent(
            summary="一般教育信息",
            observations=["公开资料中的一般观察"],
            suggestions=[Suggestion(text="查看来源资料", source_chunk_ids=["CHUNK_R3_A"])],
            disclaimer="供研究任务中的专业人员复核。",
        ),
        citations=[
            SupportCitation(
                citation_id="C1",
                chunk_id="CHUNK_R3_A",
                document_id="DOC_R3_A",
                title="Public source",
                organization="Public organization",
                locator=(
                    "section-1; source population: population-14-17; "
                    "source: https://example.org/source; license: CC BY 4.0 "
                    "(https://creativecommons.org/licenses/by/4.0/); "
                    "attribution: public organization"
                ),
                rank=1,
                source_version="R3-v1",
                source_hash=f"sha256:{excerpt_sha256}",
            )
        ],
        source_cards=[
            {
                "chunk_id": "CHUNK_R3_A",
                "record_id": "R3_RECORD_A",
                "source_id": "R3_SOURCE_A",
                "title": "Public source",
                "organization": "Public organization",
                "canonical_url": "https://example.org/source",
                "record_locator": "section-1",
                "source_population_scope": "population-14-17",
                "source_language": "zh",
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "public organization",
                "excerpt_sha256": excerpt_sha256,
                "excerpt_text": excerpt,
                "consumer_age_min": 14,
                "consumer_age_max": 17,
            }
        ],
        provenance={
            "policy_version": "RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
            "policy_hash": "1" * 64,
            "source_package_ref": "R3_PACKAGE_SYNTHETIC",
            "source_study_ref": "R3_STUDY_SYNTHETIC",
            "safety_policy_version": SAFETY_POLICY_VERSION,
            "source_manifest_sha256": "2" * 64,
            "source_age_scope": "14-17",
            "retrieval_id": "RETR_synthetic_1",
            "retrieval_bundle_sha256": "3" * 64,
            "cited_chunk_ids": ["CHUNK_R3_A"],
            "generation_id": "GEN_synthetic_1",
            "prompt_id": PROMPT_ID,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": PROMPT_SHA256,
            "model_id": EXPECTED_MODEL_ID,
            "model_version": EXPECTED_MODEL_VERSION,
            "model_digest_sha256": EXPECTED_MODEL_DIGEST_SHA256,
            "runtime_version": "runtime-synthetic",
            "runtime_attempt_count": 1,
            "runtime_retry_count": 0,
            "runtime_fallback_count": 0,
            "runtime_fallback_attempted": False,
            "runtime_local_only": True,
            "input_safety_action": "PROCEED",
            "input_safety_reason_codes": ["SAFE"],
            "retrieval_safety_action": "PROCEED",
            "retrieval_safety_reason_codes": ["SAFE"],
            "output_safety_action": "PROCEED",
            "output_safety_reason_codes": ["SAFE"],
        },
    )


def summary(**changes):
    return {
        "candidate_ref": "REEDUC_synthetic_1",
        "task_ref": "TASK_demo",
        "session_ref": "RSESSION_synthetic_1",
        "status": "HELD",
        "state_version": 1,
        "purpose": "RESEARCH_SIMULATION",
        "research_only": True,
        "psychological_interpretation_allowed": False,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "student_feedback_eligible": False,
        "created_at": datetime(2026, 10, 15, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 15, tzinfo=UTC),
        **changes,
    }


def generation_job_page(**changes):
    statuses = (
        "QUEUED", "LEASED", "RETRY", "HELD", "ABSTAINED", "REVIEW_REQUIRED",
        "CRISIS_ROUTED", "FAILED", "CANCELLED",
    )
    return {
        "items": [
            {
                "job_ref": "REJ_" + "a" * 64,
                "status": "HELD",
                "attempt_count": 1,
                "last_error_code": None,
                "created_at": datetime(2026, 10, 15, tzinfo=UTC),
                "updated_at": datetime(2026, 10, 15, tzinfo=UTC),
            }
        ],
        "offset": 0,
        "limit": 20,
        "total": 1,
        "has_more": False,
        "status_counts": {status: int(status == "HELD") for status in statuses},
        "policy_version": "RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        "purpose": "RESEARCH_SIMULATION",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "student_feedback_eligible": False,
        **changes,
    }


class FakePersistence:
    def __init__(self):
        self.calls = []

    async def school_research_education_candidate_list_tasks(self, actor_arg):
        self.calls.append(("tasks", actor_arg))
        return {
            "items": [
                {
                    "task_ref": "TASK_demo",
                    "class_ref": "CLASS_demo",
                    "class_display_name": "演示班级",
                    "published_at": datetime(2026, 10, 14, tzinfo=UTC),
                }
            ]
        }

    async def school_research_education_candidate_list(
        self, actor_arg, task_ref, *, status, offset, limit
    ):
        self.calls.append(("list", actor_arg, task_ref, status, offset, limit))
        return {"items": [summary()], "offset": offset, "limit": limit, "has_more": False}

    async def school_research_education_candidate_generation_job_list(
        self, actor_arg, task_ref, *, offset, limit
    ):
        self.calls.append(("jobs", actor_arg, task_ref, offset, limit))
        return generation_job_page(offset=offset, limit=limit)

    async def school_research_education_candidate_get(self, actor_arg, task_ref, candidate_ref):
        self.calls.append(("get", actor_arg, task_ref, candidate_ref))
        return {**summary(), "candidate_payload": candidate_payload()}

    async def school_research_education_candidate_queue_batch(
        self, actor_arg, task_ref, *, limit, offset, idempotency, trace_id
    ):
        self.calls.append(("queue", actor_arg, task_ref, limit, offset, idempotency, trace_id))
        return {
            "batch_ref": "REGENBATCH_" + "a" * 64,
            "job_refs": ["REJ_" + "b" * 64],
            "job_count": 1,
            "offset": offset,
            "limit": limit,
            "next_offset": None,
            "policy_version": "RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "publication_status": "not_approved_for_publication_or_operational_use",
            "student_feedback_eligible": False,
        }

    async def school_research_education_candidate_resolve(
        self,
        actor_arg,
        task_ref,
        candidate_ref,
        *,
        expected_state_version,
        target,
        idempotency,
        trace_id,
    ):
        self.calls.append(("resolve", actor_arg, task_ref, candidate_ref, target))
        return summary(status=target, state_version=2)


@pytest.mark.parametrize(
    "role",
    [BackendRole.STUDENT, BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER],
)
async def test_non_specialists_cannot_read_enqueue_or_resolve_candidates(role):
    persistence = FakePersistence()
    service = SchoolResearchEducationCandidateService(persistence=persistence)
    staff = actor(role)
    operations = (
        lambda: service.list_tasks(staff),
        lambda: service.list_for_task(staff, "TASK_demo"),
        lambda: service.list_jobs(staff, "TASK_demo"),
        lambda: service.get(staff, "TASK_demo", "REEDUC_demo"),
        lambda: service.queue_batch(
            staff,
            "TASK_demo",
            limit=2,
            offset=0,
            idempotency=("key", "body", "scope"),
            trace_id="TRACE_demo",
        ),
        lambda: service.resolve(
            staff,
            "TASK_demo",
            "REEDUC_demo",
            expected_state_version=1,
            target="ADOPTED",
            idempotency=("key", "body", "scope"),
            trace_id="TRACE_demo",
        ),
    )
    for operation in operations:
        with pytest.raises(BackendError) as raised:
            await operation()
        assert raised.value.code.value == "forbidden"
    assert persistence.calls == []


async def test_specialist_operations_use_closed_task_bound_ports():
    persistence = FakePersistence()
    service = SchoolResearchEducationCandidateService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    tasks = await service.list_tasks(specialist)
    listed = await service.list_for_task(specialist, "TASK_demo", offset=5, limit=12)
    jobs = await service.list_jobs(specialist, "TASK_demo", offset=2, limit=7)
    detail = await service.get(specialist, "TASK_demo", "REEDUC_synthetic_1")
    queued = await service.queue_batch(
        specialist,
        "TASK_demo",
        limit=2,
        offset=10,
        idempotency=("batch-key", "request-hash", "scope-hash"),
        trace_id="TRACE_demo",
    )
    resolved = await service.resolve(
        specialist,
        "TASK_demo",
        "REEDUC_synthetic_1",
        expected_state_version=1,
        target="ADOPTED",
        idempotency=("resolve-key", "request-hash", "scope-hash"),
        trace_id="TRACE_demo",
    )

    assert tasks["items"][0]["task_ref"] == "TASK_demo"
    assert listed["items"][0]["student_feedback_eligible"] is False
    assert jobs["items"][0]["status"] == "HELD"
    assert jobs["status_counts"]["HELD"] == 1
    assert jobs["items"][0]["created_at"].tzinfo is UTC
    assert detail["candidate_payload"]["source_cards"][0]["chunk_id"] == "CHUNK_R3_A"
    assert set(queued) == {
        "batch_ref",
        "job_refs",
        "job_count",
        "offset",
        "limit",
        "next_offset",
        "policy_version",
        "purpose",
        "research_only",
        "publication_status",
        "student_feedback_eligible",
    }
    assert resolved["status"] == "ADOPTED"
    assert resolved["student_feedback_eligible"] is False


async def test_detail_rejects_unknown_nested_citation_fields():
    persistence = FakePersistence()
    service = SchoolResearchEducationCandidateService(persistence=persistence)
    raw_payload = candidate_payload().model_dump(mode="json")
    raw_payload["citations"][0]["raw_excerpt"] = "must not cross the API boundary"

    async def return_open_citation(_actor, _task_ref, _candidate_ref):
        return {**summary(), "candidate_payload": raw_payload}

    persistence.school_research_education_candidate_get = return_open_citation
    with pytest.raises(BackendError) as raised:
        await service.get(
            actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
            "TASK_demo",
            "REEDUC_synthetic_1",
        )
    assert raised.value.code.value == "dependency_invalid_response"


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 25), (0, 101), (True, 25), (0, True)],
)
async def test_candidate_pagination_rejects_out_of_bounds_or_bool(offset, limit):
    persistence = FakePersistence()
    service = SchoolResearchEducationCandidateService(persistence=persistence)
    with pytest.raises(BackendError) as raised:
        await service.list_for_task(
            actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
            "TASK_demo",
            offset=offset,
            limit=limit,
        )
    assert raised.value.code.value == "validation_failed"
    assert persistence.calls == []


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 20), (100_001, 20), (0, 51), (True, 20), (0, True)],
)
async def test_generation_job_pagination_rejects_out_of_bounds_or_bool(offset, limit):
    persistence = FakePersistence()
    service = SchoolResearchEducationCandidateService(persistence=persistence)
    with pytest.raises(BackendError) as raised:
        await service.list_jobs(
            actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
            "TASK_demo",
            offset=offset,
            limit=limit,
        )
    assert raised.value.code.value == "validation_failed"
    assert persistence.calls == []


async def test_generation_job_page_rejects_unknown_status_or_inconsistent_counts():
    persistence = FakePersistence()
    service = SchoolResearchEducationCandidateService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    async def unknown_status(*_args, **_kwargs):
        page = generation_job_page()
        page["items"][0]["status"] = "PRIVATE_STATE"
        return page

    persistence.school_research_education_candidate_generation_job_list = unknown_status
    with pytest.raises(BackendError) as raised:
        await service.list_jobs(specialist, "TASK_demo")
    assert raised.value.code.value == "dependency_invalid_response"

    async def inconsistent_counts(*_args, **_kwargs):
        return generation_job_page(total=2)

    persistence.school_research_education_candidate_generation_job_list = inconsistent_counts
    with pytest.raises(BackendError) as raised:
        await service.list_jobs(specialist, "TASK_demo")
    assert raised.value.code.value == "dependency_invalid_response"


@pytest.mark.parametrize("limit", [0, 101, True])
async def test_enqueue_batch_rejects_invalid_limit_before_port(limit):
    persistence = FakePersistence()
    service = SchoolResearchEducationCandidateService(persistence=persistence)
    with pytest.raises(BackendError) as raised:
        await service.queue_batch(
            actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
            "TASK_demo",
            limit=limit,
            offset=0,
            idempotency=("key", "body", "scope"),
            trace_id="TRACE_demo",
        )
    assert raised.value.code.value == "validation_failed"
    assert persistence.calls == []
