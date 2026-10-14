from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_tasks import SchoolResearchTasksPersistenceAdapter
from smhai_backend.core.errors import BackendError
from tests.test_school_research_tasks_adapter import (
    BINDING_REF,
    CORPUS_SHA,
    DUE,
    MANIFEST_SHA,
    NOW,
    OPEN,
    POLICY_SHA,
    PROFILE_REF,
    PROFILE_SHA,
    _actor,
    _catalog,
    _idempotency,
    _metadata,
    _Owner,
    _trusted_policy,
)


class _Cohorts:
    def __init__(self, changed=False):
        self.calls = []
        self.changed = changed

    async def get_cohort_metadata(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            cohort_id=801, study_ref="synthetic-study-replay", profile_ref=PROFILE_REF,
            profile_version_number=2, profile_sha256=PROFILE_SHA,
            manifest_sha256=MANIFEST_SHA,
            corpus_sha256="0" * 64 if self.changed else CORPUS_SHA,
            case_count=800, class_count=8, subject_count=800,
        )


def _adapter(*, changed=False, count=100):
    owner = _Owner(profile_metadata=_metadata())
    owner.uow.research_cohorts = _Cohorts(changed)
    owner.uow.school_operations.enrollment_count = count
    repository = owner.uow.research_cat
    create_binding = repository.create_task_binding
    create_assignments = repository.create_public_observed_case_assignments

    async def linked_binding(**kwargs):
        binding = await create_binding(**kwargs)
        binding.cohort_id = kwargs.get("cohort_id")
        return binding

    async def linked_assignments(**kwargs):
        assert kwargs["case_index_plan"] is None
        # Test projection only; real membership-to-case resolution lives in DB.
        rows = await create_assignments(**{**kwargs, "case_index_plan": tuple(range(count))})
        for index, row in enumerate(rows):
            row.cohort_id = 801
            row.cohort_assignment_id = index + 1
        return rows

    repository.create_task_binding = linked_binding
    repository.create_public_observed_case_assignments = linked_assignments
    return SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_trusted_policy(),
        study_use_policy_sha256=POLICY_SHA,
    ), owner


def _publish(adapter):
    return adapter.publish_task(
        _actor(), class_ref="CLASS_demo_01", task_ref="TASK_synthetic_replay_01",
        binding_ref=BINDING_REF, profile_version_number=2,
        opens_at=OPEN, due_at=DUE, at=NOW, idempotency=_idempotency(),
        cohort_ref="COHORT_R_demo_01",
    )


@pytest.mark.asyncio
async def test_cohort_task_delegates_existing_mapping_without_new_permutation(monkeypatch):
    def forbid_new_task_plan(**kwargs):
        raise AssertionError("cohort publication must not reshuffle")

    monkeypatch.setattr(
        "smhai_backend.adapters.school_research_tasks._server_case_index_plan",
        forbid_new_task_plan,
    )
    adapter, owner = _adapter()
    result = await _publish(adapter)
    assert result.published_enrollment_count == 100
    assert owner.uow.research_cat.binding.cohort_id == 801
    assert owner.uow.exception is None
    assert owner.events[-1][0] == "idempotency_complete"


@pytest.mark.asyncio
async def test_cohort_source_mismatch_rejects_before_snapshot_or_binding():
    adapter, owner = _adapter(changed=True)
    with pytest.raises(BackendError):
        await _publish(adapter)
    assert owner.uow.school_operations.calls == []
    assert owner.uow.research_cat.calls == []
    assert not any(event[0] == "idempotency_begin" for event in owner.events)


@pytest.mark.asyncio
async def test_partial_cohort_class_does_not_commit_task_or_receipt():
    adapter, owner = _adapter(count=99)
    with pytest.raises(BackendError):
        await _publish(adapter)
    assert owner.uow.exception is not None
    assert not owner.uow.audit.calls
    assert not any(event[0] == "idempotency_complete" for event in owner.events)


@pytest.mark.asyncio
async def test_cohort_publication_replay_keeps_binding_and_verifies_complete_map():
    adapter, owner = _adapter()
    await _publish(adapter)
    owner._replay = True
    owner.uow.session.task = owner.uow.school_operations.task

    async def progress(**kwargs):
        return SimpleNamespace(published_enrollment_count=100)

    owner.uow.school_operations.task_progress_counts = progress
    binding_calls = len(owner.uow.research_cat.calls)
    result = await _publish(adapter)
    assert result.published_enrollment_count == 100
    assert len(owner.uow.research_cat.calls) == binding_calls
    assert len(owner.uow.research_cat.assignment_verifications) == 1
    assert owner.uow.research_cat.binding.cohort_id == 801


@pytest.mark.asyncio
async def test_replay_rejects_binding_from_different_cohort_even_with_same_source():
    adapter, owner = _adapter()
    await _publish(adapter)
    owner._replay = True
    owner.uow.session.task = owner.uow.school_operations.task
    lookup = owner.uow.research_cohorts.get_cohort_metadata

    async def different_cohort(**kwargs):
        result = await lookup(**kwargs)
        result.cohort_id = 802
        return result

    owner.uow.research_cohorts.get_cohort_metadata = different_cohort
    with pytest.raises(BackendError):
        await _publish(adapter)
    assert owner.uow.exception is not None
    assert not owner.uow.research_cat.assignment_verifications
