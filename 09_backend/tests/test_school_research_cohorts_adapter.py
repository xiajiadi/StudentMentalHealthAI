"""Adapter orchestration checks; database membership is tested in module11."""

from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_cohorts import SchoolResearchCohortsPersistenceAdapter
from smhai_backend.adapters.school_research_tasks import SchoolResearchTasksPersistenceAdapter
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import BackendRole

# Reuse the trusted task-catalog fixture and guard rather than replacing its
# actual provenance/policy checks with a permissive stub.
from tests.test_school_research_tasks_adapter import (
    BINDING_REF,
    CORPUS_SHA,
    NOW,
    POLICY_SHA,
    PROFILE_REF,
    SCHOOL_ID,
    _actor,
    _catalog,
    _idempotency,
    _metadata,
    _Owner,
    _trusted_policy,
)


class _Cohorts:
    def __init__(self, failure=False):
        self.calls = []
        self.failure = failure

    async def seal_cohort(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise RuntimeError("private driver failure must not escape")
        return SimpleNamespace(
            cohort_ref=kwargs["cohort_ref"], study_ref=kwargs["study_ref"],
            profile_ref=PROFILE_REF, profile_version_number=2,
            case_count=800, class_count=8, subject_count=800, sealed_at=NOW,
        )


def _adapter(*, policy=True, verified=True, failure=False):
    owner = _Owner(profile_metadata=_metadata())
    owner.uow.research_cohorts = _Cohorts(failure)
    guard = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(verified=verified),
        study_use_policy=_trusted_policy() if policy else None,
        study_use_policy_sha256=POLICY_SHA if policy else None,
    )
    return SchoolResearchCohortsPersistenceAdapter(guard), owner


def _seal(adapter, actor=None):
    return adapter.seal_cohort(
        actor or _actor(), binding_ref=BINDING_REF, profile_version_number=2,
        batch_refs=tuple(f"BATCH_demo_{n}" for n in range(8)), at=NOW,
        idempotency=_idempotency(),
    )


@pytest.mark.asyncio
async def test_uses_trusted_pins_and_complete_server_owned_map_in_same_uow():
    adapter, owner = _adapter()
    result = await _seal(adapter)
    call = owner.uow.research_cohorts.calls[0]
    assert call["school_id"] == SCHOOL_ID
    assert call["expected_corpus_sha256"] == CORPUS_SHA
    assert set(call["case_index_plan"]) == set(range(800))
    assert len(call["case_index_plan"]) == 800
    assert call["cohort_ref"].startswith("COHORT_R_")
    assert owner.events[0][0] == "authorize"
    assert owner.events[-1][0] == "idempotency_complete"
    assert owner.uow.exception is None
    assert result["assigned_distinct_cases"] == 800
    assert not {"case_index_plan", "corpus_sha256", "school_id", "subject_ids"} & set(result)
    assert owner.uow.audit.calls[0]["safe_metadata"] == {
        "source": "school_research_cohorts", "state": "SEALED",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [BackendRole.STUDENT, BackendRole.TEACHER,
                                  BackendRole.PSYCHOLOGICAL_SPECIALIST])
async def test_non_admin_never_opens_database_uow(role):
    adapter, owner = _adapter()
    with pytest.raises(BackendError) as caught:
        await _seal(adapter, _actor(role))
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert not owner.events
    assert not owner.uow.research_cohorts.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("policy,verified", [(False, True), (True, False)])
async def test_unqualified_policy_or_corpus_never_creates_map(policy, verified):
    adapter, owner = _adapter(policy=policy, verified=verified)
    with pytest.raises(BackendError):
        await _seal(adapter)
    assert not owner.uow.research_cohorts.calls
    assert not any(event[0] == "idempotency_complete" for event in owner.events)


@pytest.mark.asyncio
async def test_repository_failure_rolls_back_before_receipt_audit():
    adapter, owner = _adapter(failure=True)
    with pytest.raises(BackendError) as caught:
        await _seal(adapter)
    assert caught.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert "private driver" not in str(caught.value)
    assert owner.uow.exception is not None
    assert not owner.uow.audit.calls
    assert not any(event[0] == "idempotency_complete" for event in owner.events)
