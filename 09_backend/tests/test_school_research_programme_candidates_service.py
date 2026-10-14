from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smhai_backend.adapters.school_research_programme_candidates import (
    SchoolResearchProgrammeCandidatePersistenceAdapter,
    _finished_job_matches_candidate_scope,
)
from smhai_backend.core.errors import BackendError
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.research_programme_generation.schemas import (
    CLAIM_BOUNDARY_VERSION,
    STUDY_REF,
)
from smhai_backend.domains.school_research_programme_candidates.schemas import (
    GeneratedProgrammeCandidate,
)
from smhai_backend.domains.school_research_programme_candidates.service import (
    SchoolResearchProgrammeCandidateService,
)

_MODEL_REF = "qwen2.5-7b-instruct-school-demo"
_MODEL_DIGEST = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
_PROMPT_REF = "PROMPT_staff_school_programme_research_v1"
_PROMPT_VERSION = "1.0.1"


def actor(role: BackendRole) -> Actor:
    return Actor(
        user_id=f"USER_synthetic_{role.value.lower()}",
        username="synthetic-candidate-reviewer",
        role=role,
        subject_id="SUBJ_student" if role is BackendRole.STUDENT else None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )


def summary(**changes):
    return {
        "candidate_ref": "RPCAND_synthetic_1",
        "programme_ref": "staff-programme-r1",
        "status": "HELD",
        "state_version": 1,
        "student_feedback_eligible": False,
        "output_boundary": "STAFF_REFERENCE_ONLY",
        "created_at": datetime(2026, 10, 14, tzinfo=UTC),
        **changes,
    }


class FakePersistence:
    def __init__(self):
        self.calls = []

    async def school_research_programme_candidate_list(self, actor_arg, task_ref, *, offset, limit):
        self.calls.append(("list", actor_arg, task_ref, offset, limit))
        return [summary()]

    async def school_research_programme_candidate_get(self, actor_arg, task_ref, candidate_ref):
        self.calls.append(("get", actor_arg, task_ref, candidate_ref))
        return {
            **summary(),
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "psychological_interpretation_allowed": False,
            "publication_status": "not_approved_for_publication_or_operational_use",
            "output_boundary": "STAFF_REFERENCE_ONLY",
            "content": {
                "programme_ref": "staff-programme-r1",
                "title": "教职工项目资料摘要",
                "body": "这是一般项目资料，不关联个人测评信息。[S1]",
                "citations": [
                    {
                        "citation_id": "S1",
                        "source_title": "公开教育资料",
                        "source_organization": "公开机构",
                        "source_url": "https://example.org/education",
                        "source_locator": None,
                    }
                ],
            },
        }

    async def school_research_programme_candidate_adopt(
        self, actor_arg, task_ref, candidate_ref, *, expected_state_version, idempotency, trace_id
    ):
        self.calls.append(("adopt", actor_arg, task_ref, candidate_ref, expected_state_version))
        return summary(status="ADOPTED", state_version=2)

    async def school_research_programme_candidate_discard(
        self, actor_arg, task_ref, candidate_ref, *, expected_state_version, idempotency, trace_id
    ):
        self.calls.append(("discard", actor_arg, task_ref, candidate_ref, expected_state_version))
        return summary(status="DISCARDED", state_version=2)

    async def school_research_programme_generation_queue(
        self, actor_arg, task_ref, *, idempotency, trace_id
    ):
        self.calls.append(("queue", actor_arg, task_ref, idempotency, trace_id))
        return {
            "job_ref": "REJ_synthetic_1",
            "status": "QUEUED",
            "policy_version": "RESEARCH_STAFF_PROGRAMME_POLICY_V1",
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "publication_status": "not_approved_for_publication_or_operational_use",
            "student_feedback_eligible": False,
        }

    async def store_generated_candidate(self, generated):
        self.calls.append(("store", generated))
        return summary()


@pytest.mark.parametrize(
    "role",
    [BackendRole.STUDENT, BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER],
)
async def test_non_specialists_cannot_read_adopt_or_discard_candidate(role):
    persistence = FakePersistence()
    service = SchoolResearchProgrammeCandidateService(persistence=persistence)
    for operation in (
        lambda: service.list_for_task(actor(role), "TASK_demo"),
        lambda: service.get(actor(role), "TASK_demo", "RPCAND_demo"),
        lambda: service.adopt(
            actor(role), "TASK_demo", "RPCAND_demo", expected_state_version=1,
            idempotency=("key", "body", "scope"), trace_id="TRACE_demo",
        ),
        lambda: service.discard(
            actor(role), "TASK_demo", "RPCAND_demo", expected_state_version=1,
            idempotency=("key", "body", "scope"), trace_id="TRACE_demo",
        ),
    ):
        with pytest.raises(BackendError) as exc:
            await operation()
        assert exc.value.code.value == "forbidden"
    assert persistence.calls == []


async def test_specialist_can_review_and_adopt_only_to_staff_material_state():
    persistence = FakePersistence()
    service = SchoolResearchProgrammeCandidateService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    listed = await service.list_for_task(specialist, "TASK_demo")
    detail = await service.get(specialist, "TASK_demo", "RPCAND_synthetic_1")
    adopted = await service.adopt(
        specialist,
        "TASK_demo",
        "RPCAND_synthetic_1",
        expected_state_version=1,
        idempotency=("key", "body", "scope"),
        trace_id="TRACE_demo",
    )

    assert listed["items"][0]["student_feedback_eligible"] is False
    assert listed["items"][0]["output_boundary"] == "STAFF_REFERENCE_ONLY"
    assert detail["student_feedback_eligible"] is False
    assert detail["output_boundary"] == "STAFF_REFERENCE_ONLY"
    assert detail["content"]["citations"][0]["citation_id"] == "S1"
    assert adopted["status"] == "ADOPTED"
    assert adopted["student_feedback_eligible"] is False
    assert adopted["output_boundary"] == "STAFF_REFERENCE_ONLY"
    assert [call[0] for call in persistence.calls] == ["list", "get", "adopt"]


def _generated_candidate_input():
    content = {
        "programme_ref": "staff-programme-r1",
        "title": "一般项目摘要",
        "body": "通用教职工项目资料内容。[S1]",
        "citations": [
            {
                "citation_id": "S1",
                "source_title": "公开资料",
                "source_organization": "公开机构",
                "source_url": "https://example.org/source",
                "source_locator": None,
            }
        ],
    }
    valid = {
        "job": {
            "job_id": 1,
            "school_id": 1,
            "research_session_id": 2,
            "lease_owner": "programme-worker",
            "lease_token": "lease_token",
            "policy_version": "RESEARCH_STAFF_PROGRAMME_POLICY_V1",
            "policy_hash": "3" * 64,
        },
        "trace_id": "TRACE_synthetic_1",
        "task_scope": {
            "school_id": 1,
            "task_id": 1,
            "class_id": 1,
            "task_binding_id": 1,
            "profile_version_id": 1,
            "profile_ref": "research-profile",
            "profile_version_number": 3,
            "profile_sha256": "b" * 64,
            "response_origin": "PUBLIC_OBSERVED",
        },
        "study_ref": "study-r1",
        "source_study_ref": STUDY_REF,
        "study_policy_sha256": "a" * 64,
        "processor_policy_sha256": "3" * 64,
        "programme_ref": "staff-programme-r1",
        "source_manifest_sha256": "c" * 64,
        "source_set_sha256": "d" * 64,
        "retrieval_id": "RETR_synthetic_1",
        "retrieval_bundle_sha256": "e" * 64,
        "chunk_set_sha256": "f" * 64,
        "prompt_ref": _PROMPT_REF,
        "prompt_version": _PROMPT_VERSION,
        "prompt_sha256": "1" * 64,
        "model_ref": _MODEL_REF,
        "model_digest_sha256": _MODEL_DIGEST,
        "runtime_version": "runtime-v1",
        "safety_policy_version": "safety-v1",
        "input_safety_action": "PROCEED",
        "retrieval_safety_action": "PROCEED",
        "output_safety_action": "PROCEED_WITH_BOUNDARY",
        "claim_boundary_version": CLAIM_BOUNDARY_VERSION,
        "claim_boundary_status": "ACCEPTED",
        "output_boundary": "STAFF_REFERENCE_ONLY",
        "content": content,
    }
    return valid


def test_generated_candidate_type_is_closed_and_requires_safety_and_staff_boundary():
    valid = _generated_candidate_input()
    parsed = GeneratedProgrammeCandidate.model_validate(valid, strict=True)
    candidate_adapter = SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=None,
        study_use_policy_sha256=None,
        enabled=False,
        expected_processor_policy_sha256="3" * 64,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )
    candidate_adapter._require_generation_pins(parsed)
    wrong_source = dict(valid)
    wrong_source["source_study_ref"] = "untrusted-source-study"
    with pytest.raises(BackendError):
        candidate_adapter._require_generation_pins(
            GeneratedProgrammeCandidate.model_validate(wrong_source, strict=True)
        )
    finished_job = SimpleNamespace(
        school_id=1,
        task_id=1,
        class_id=1,
        task_binding_id=1,
        profile_version_id=1,
        profile_ref="research-profile",
        profile_version_number=3,
        profile_sha256="b" * 64,
        response_origin="PUBLIC_OBSERVED",
        policy_version="RESEARCH_STAFF_PROGRAMME_POLICY_V1",
        policy_hash="3" * 64,
    )
    assert _finished_job_matches_candidate_scope(finished_job, parsed)
    assert not _finished_job_matches_candidate_scope(
        SimpleNamespace(**{**vars(finished_job), "task_id": 2}), parsed
    )
    assert "lease_token" not in repr(parsed)
    assert "通用教职工项目资料" not in repr(parsed)
    with pytest.raises(ValidationError):
        GeneratedProgrammeCandidate.model_validate(
            {**valid, "output_boundary": "STUDENT_PERSONAL_FEEDBACK"}, strict=True
        )
    with pytest.raises(ValidationError):
        GeneratedProgrammeCandidate.model_validate(
            {**valid, "input_safety_action": "BLOCK"}, strict=True
        )
    with pytest.raises(ValidationError):
        GeneratedProgrammeCandidate.model_validate(
            {**valid, "assessment_id": "ASSESS_not_allowed"}, strict=True
        )
    wrong_model = GeneratedProgrammeCandidate.model_validate(
        {**valid, "model_ref": "untrusted-model-ref"}, strict=True
    )
    with pytest.raises(BackendError):
        candidate_adapter._require_generation_pins(wrong_model)
    with pytest.raises(ValidationError):
        GeneratedProgrammeCandidate.model_validate(
            {**valid, "processor_policy_sha256": "4" * 64}, strict=True
        )
