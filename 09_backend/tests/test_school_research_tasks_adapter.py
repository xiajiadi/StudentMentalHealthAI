from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_tasks import (
    SchoolResearchTasksPersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research.catalog import (
    RepositoryResearchProfileInput,
    ResearchBindingPublicMetadata,
    ResearchBindingSelection,
    ResearchProfilePublicMetadata,
    ResearchProfileRepositoryProjection,
    ResearchProfileSelection,
    SchoolResearchCatalog,
)
from smhai_backend.domains.school_research.study_use import ResearchStudyProfilePin

SCHOOL_ID = 71
PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
PROFILE_SHA = "a" * 64
MANIFEST_SHA = "b" * 64
CROSSWALK_SHA = "c" * 64
CONFIG_SHA = "d" * 64
POLICY_SHA = "e" * 64
BINDING_REF = "promis-research-binding-r1"
OPEN = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
DUE = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


class _Field:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return (self.name, "eq", other)


class _SchoolClass:
    school_id = _Field("SchoolClass.school_id")
    class_ref = _Field("SchoolClass.class_ref")
    id = _Field("SchoolClass.id")


class _MeasurementTask:
    school_id = _Field("MeasurementTask.school_id")
    task_ref = _Field("MeasurementTask.task_ref")
    public_id = _Field("MeasurementTask.public_id")
    class_id = _Field("MeasurementTask.class_id")


class _Query:
    def __init__(self, entity):
        self.entity = entity
        self.conditions = ()

    def where(self, *conditions):
        self.conditions += conditions
        return self

    def scalar_subquery(self):
        return self


class _Session:
    def __init__(self, *, school_class=None, task=None):
        self.school_class = school_class
        self.task = task
        self.flush_count = 0

    async def scalar(self, query):
        if query.entity is _SchoolClass:
            return self.school_class
        if query.entity is _MeasurementTask:
            return self.task
        raise AssertionError("unexpected scoped query")

    async def flush(self):
        self.flush_count += 1


class _Uow(AbstractAsyncContextManager):
    def __init__(self, *, school_class=None, task=None, profile_metadata=None):
        self.school_operations = _Operations()
        self.session = _Session(
            school_class=school_class,
            task=self.school_operations.task if task is True else task,
        )
        self.research_cat = _ResearchCat(profile_metadata)
        self.audit = _Audit()
        self.exception = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, _tb):
        self.exception = exc
        return False


class _Operations:
    def __init__(self):
        self.calls = []
        self.task = SimpleNamespace(
            id=501,
            public_id="MEASTASK_syntheticpublic",
            task_ref="TASK_synthetic_replay_01",
            school_id=SCHOOL_ID,
            class_id=902,
            instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
            instrument_version="research-v2",
            config_version="promis_v3_research",
            status="PUBLISHED",
            opens_at=OPEN.replace(tzinfo=None),
            due_at=DUE.replace(tzinfo=None),
            published_at=NOW.replace(tzinfo=None),
            cat_binding_mode="FIXTURE",
        )

    async def publish_task_with_snapshot(self, **kwargs):
        self.calls.append(("publish_snapshot", kwargs))
        self.task.cat_binding_mode = "RESEARCH_PROFILE"
        return SimpleNamespace(task=self.task, enrollment_count=5)

    async def task_progress_counts(self, **_kwargs):
        return SimpleNamespace(published_enrollment_count=5)


class _ResearchCat:
    def __init__(self, profile_metadata):
        self.profile_metadata = profile_metadata
        self.binding = None
        self.calls = []

    async def get_profile_metadata(self, **_kwargs):
        return self.profile_metadata

    async def create_task_binding(self, **kwargs):
        self.calls.append(("create_binding", kwargs))
        self.binding = SimpleNamespace(
            school_id=kwargs["school_id"],
            task_id=kwargs["task_id"],
            class_id=kwargs["class_id"],
            profile_version_id=kwargs["profile_version_id"],
            profile_ref=kwargs["profile_ref"],
            profile_version_number=kwargs["profile_version_number"],
            profile_sha256=kwargs["expected_profile_sha256"],
            response_origin=kwargs["response_origin"],
            status="ACTIVE",
            config_version=kwargs["config_version"],
            config_sha256=kwargs["expected_config_sha256"],
            research_only=True,
            revoked_at=None,
        )
        return self.binding

    async def get_task_binding_metadata(self, **_kwargs):
        return self.binding


class _Audit:
    def __init__(self):
        self.calls = []

    async def append(self, **kwargs):
        self.calls.append(kwargs)


class _StudyPolicy:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    def require_scope(self, **kwargs):
        self.calls.append(kwargs)
        if not self.allowed:
            from smhai_backend.domains.school_research.study_use import ResearchStudyUseError

            raise ResearchStudyUseError("task_window_outside_policy")
        return ResearchStudyProfilePin(
            profile_ref=PROFILE_REF,
            profile_sha256=PROFILE_SHA,
            manifest_sha256=MANIFEST_SHA,
            published_crosswalk_sha256=CROSSWALK_SHA,
        )


class _Owner:
    def __init__(self, *, profile_metadata=None, school_class=None, task=None, replay=False):
        self.events = []
        self._db_models = SimpleNamespace(
            SchoolClass=_SchoolClass, MeasurementTask=_MeasurementTask
        )
        self._db_enums = SimpleNamespace(AuditResult=SimpleNamespace(SUCCESS="SUCCESS"))
        self.uow = _Uow(
            school_class=school_class or SimpleNamespace(id=902),
            task=True if replay and task is None else task,
            profile_metadata=profile_metadata,
        )
        self._uow = lambda: self.uow
        self._select = _Query
        self._replay = replay

    async def _school_actor_role(self, uow, _actor, role, at):
        self.events.append(("authorize", role, at))
        assert role == "admin"
        return 101, 202

    async def _school_idempotency_begin(self, _uow, _idempotency):
        self.events.append(("idempotency_begin",))
        record = SimpleNamespace(
            result_resource_type="measurement_task" if self._replay else None,
            result_public_id="MEASTASK_syntheticpublic" if self._replay else None,
        )
        return SimpleNamespace(record=record, replayed=self._replay)

    async def _school_idempotency_complete(self, _uow, _claim, **kwargs):
        self.events.append(("idempotency_complete", kwargs))


def _actor(role=BackendRole.ADMIN, school_id=SCHOOL_ID):
    return Actor(
        user_id="USER_synthetic_admin",
        username="synthetic-admin",
        role=role,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=school_id,
        school_ref="SCHOOL_synthetic",
        school_contexts=(
            SchoolRoleContext(
                context_id="membership-role-71",
                role=role,
                school_id=school_id,
                school_ref="SCHOOL_synthetic",
            ),
        ),
    )


def _catalog():
    raw = json.dumps(
        {
            "model": {"parameter_version": "published-v1"},
            "provenance": {"parameter_crosswalk_sha256": CROSSWALK_SHA},
        }
    ).encode()
    repository_profile = RepositoryResearchProfileInput(
        profile_id=PROFILE_REF,
        profile_type="CAT_RESEARCH_PROFILE_CANDIDATE",
        instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        dimension="PROMIS Pediatric Anxiety 8 item research dimension",
        file_sha256=PROFILE_SHA,
        manifest_sha256=MANIFEST_SHA,
        raw_profile_bytes=raw,
    )
    repository = ResearchProfileRepositoryProjection(
        school_id=SCHOOL_ID,
        profile=repository_profile,
        expected_profile_sha256=PROFILE_SHA,
        expected_manifest_sha256=MANIFEST_SHA,
        source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
    )
    profile = ResearchProfileSelection(
        public=ResearchProfilePublicMetadata(
            school_id=SCHOOL_ID,
            profile_ref=PROFILE_REF,
            profile_schema="psynova.research-profile.v3",
            source_family="PROMIS",
            instrument_id=repository_profile.instrument_id,
            instrument_family="PROMIS_PEDIATRIC_ANXIETY",
            source_population="US children 8–17 self-report",
            source_version="published-v1",
            parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
            research_only=True,
            human_curated=False,
            psychological_interpretation_allowed=False,
            publication_status="not_approved",
        ),
        trusted_profile=SimpleNamespace(raw_profile_bytes=raw),
        repository=repository,
    )
    binding = ResearchBindingSelection(
        public=ResearchBindingPublicMetadata(
            school_id=SCHOOL_ID,
            binding_ref=BINDING_REF,
            profile_ref=PROFILE_REF,
            config_version="promis_v3_research",
            research_only=True,
            publication_status="not_approved_for_publication_or_operational_use",
        ),
        config_sha256=CONFIG_SHA,
        _canonical_cat_config_json='{"max_items":8,"min_items":8}',
    )
    return SchoolResearchCatalog(
        school_id=SCHOOL_ID,
        _profiles={PROFILE_REF: profile},
        _bindings={BINDING_REF: binding},
    )


def _metadata(*, rights="VERIFIED", execution="SIMULATION_ENABLED"):
    return SimpleNamespace(
        profile_version_id=41,
        school_id=SCHOOL_ID,
        profile_ref=PROFILE_REF,
        version_number=2,
        instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        profile_sha256=PROFILE_SHA,
        manifest_sha256=MANIFEST_SHA,
        fit_sha256=None,
        calibration_sha256=None,
        parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
        published_parameter_crosswalk_sha256=CROSSWALK_SHA,
        research_only=True,
        human_curated=False,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
        rights_status=rights,
        execution_status=execution,
        rights_revoked_at=None,
        disabled_at=None,
        simulation_enabled_at=datetime(2026, 10, 14),
    )


def _idempotency():
    return "synthetic-key", "e" * 64, "f" * 64


def _publish(adapter, actor=None):
    return adapter.publish_task(
        actor or _actor(),
        class_ref="CLASS_demo_01",
        task_ref="TASK_synthetic_replay_01",
        binding_ref=BINDING_REF,
        profile_version_number=2,
        opens_at=OPEN,
        due_at=DUE,
        at=NOW,
        idempotency=_idempotency(),
    )


@pytest.mark.asyncio
async def test_publish_is_atomic_and_binds_exact_profile_with_public_observed_origin():
    owner = _Owner(profile_metadata=_metadata())
    policy = _StudyPolicy()
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=policy, study_use_policy_sha256=POLICY_SHA
    )

    result = await _publish(adapter)

    assert owner.events[0][0] == "authorize"
    assert owner.uow.school_operations.calls[0][0] == "publish_snapshot"
    task = owner.uow.school_operations.task
    assert task.cat_binding_mode == "RESEARCH_PROFILE"
    assert owner.uow.session.flush_count == 1
    name, binding_call = owner.uow.research_cat.calls[0]
    assert name == "create_binding"
    assert binding_call["profile_version_id"] == 41
    assert binding_call["profile_ref"] == PROFILE_REF
    assert binding_call["expected_profile_sha256"] == PROFILE_SHA
    assert binding_call["response_origin"] == "PUBLIC_OBSERVED"
    assert binding_call["config_payload"] == {"max_items": 8, "min_items": 8}
    assert result.response_origin == "PUBLIC_OBSERVED"
    assert result.research_only is True
    assert result.publication_status == "not_approved_for_publication_or_operational_use"
    assert result.published_enrollment_count == 5
    assert owner.events[-1][0] == "idempotency_complete"
    assert owner.uow.audit.calls[0]["action"] == "school_research_tasks.task.published"
    assert owner.uow.audit.calls[0]["safe_metadata"]["study_use_policy_sha256"] == POLICY_SHA
    assert policy.calls[0]["task_opens_at"] == OPEN
    assert policy.calls[0]["task_due_at"] == DUE


@pytest.mark.asyncio
async def test_missing_or_denied_trusted_study_policy_fails_closed_before_task_creation():
    owner = _Owner(profile_metadata=_metadata())
    adapter = SchoolResearchTasksPersistenceAdapter(owner, _catalog())

    with pytest.raises(BackendError) as no_policy:
        await _publish(adapter)
    assert no_policy.value.code is ErrorCode.FORBIDDEN
    assert owner.uow.school_operations.calls == []

    owner = _Owner(profile_metadata=_metadata())
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner,
        _catalog(),
        study_use_policy=_StudyPolicy(allowed=False),
        study_use_policy_sha256=POLICY_SHA,
    )
    with pytest.raises(BackendError) as denied:
        await _publish(adapter)
    assert denied.value.code is ErrorCode.FORBIDDEN
    assert owner.uow.school_operations.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rights", "execution"),
    [
        ("PENDING", "CANDIDATE_RESEARCH_ONLY"),
        ("REVOKED", "SIMULATION_ENABLED"),
        ("VERIFIED", "CANDIDATE_RESEARCH_ONLY"),
    ],
)
async def test_candidate_or_revoked_profile_cannot_publish_task(rights, execution):
    owner = _Owner(profile_metadata=_metadata(rights=rights, execution=execution))
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as blocked:
        await _publish(adapter)
    assert blocked.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.uow.school_operations.calls == []


@pytest.mark.asyncio
async def test_non_admin_and_foreign_school_fail_before_catalog_or_database_work():
    owner = _Owner(profile_metadata=_metadata())
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as role_error:
        await _publish(adapter, _actor(BackendRole.TEACHER))
    assert role_error.value.code is ErrorCode.FORBIDDEN
    assert owner.events == []

    with pytest.raises(BackendError) as school_error:
        await _publish(adapter, _actor(BackendRole.ADMIN, school_id=72))
    assert school_error.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert owner.events[0][0] == "authorize"
    assert owner.uow.school_operations.calls == []


@pytest.mark.asyncio
async def test_persisted_admin_authorization_precedes_catalog_selection(monkeypatch):
    owner = _Owner(profile_metadata=_metadata())
    original = SchoolResearchCatalog.select_binding

    def require_authorized_selection(catalog, binding_ref, *, school_id=None):
        assert owner.events and owner.events[0][0] == "authorize"
        return original(catalog, binding_ref, school_id=school_id)

    monkeypatch.setattr(SchoolResearchCatalog, "select_binding", require_authorized_selection)
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    result = await _publish(adapter)
    assert result.task_ref == "TASK_synthetic_replay_01"


@pytest.mark.asyncio
async def test_profile_hash_drift_is_rejected_before_task_snapshot():
    metadata = _metadata()
    metadata.profile_sha256 = "0" * 64
    owner = _Owner(profile_metadata=metadata)
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as blocked:
        await _publish(adapter)
    assert blocked.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.uow.school_operations.calls == []


@pytest.mark.asyncio
async def test_binding_persistence_failure_leaves_receipt_and_audit_unfinished():
    owner = _Owner(profile_metadata=_metadata())

    async def fail_binding(**_kwargs):
        raise RuntimeError("synthetic persistence fault")

    owner.uow.research_cat.create_task_binding = fail_binding
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as failed:
        await _publish(adapter)
    assert failed.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert owner.uow.exception is not None
    assert not any(event[0] == "idempotency_complete" for event in owner.events)
    assert owner.uow.audit.calls == []


@pytest.mark.asyncio
async def test_replay_reauthorizes_and_requires_exact_existing_task_and_binding():
    owner = _Owner(profile_metadata=_metadata(), replay=True)
    owner.uow.school_operations.task.cat_binding_mode = "RESEARCH_PROFILE"
    owner.uow.research_cat.binding = SimpleNamespace(
        school_id=SCHOOL_ID,
        task_id=501,
        class_id=902,
        profile_version_id=41,
        profile_ref=PROFILE_REF,
        profile_version_number=2,
        profile_sha256=PROFILE_SHA,
        response_origin="PUBLIC_OBSERVED",
        status="ACTIVE",
        config_version="promis_v3_research",
        config_sha256=CONFIG_SHA,
        research_only=True,
        revoked_at=None,
    )
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    result = await _publish(adapter)

    assert result.task_ref == "TASK_synthetic_replay_01"
    assert owner.events[0][0] == "authorize"
    assert len([event for event in owner.events if event[0] == "authorize"]) == 1
    assert result.response_origin == "PUBLIC_OBSERVED"

    owner.uow.research_cat.binding.config_sha256 = "0" * 64
    with pytest.raises(BackendError) as mismatch:
        await _publish(adapter)
    assert mismatch.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_policy_failure_never_changes_profile_eligibility_or_creates_a_task():
    owner = _Owner(
        profile_metadata=_metadata(rights="PENDING", execution="CANDIDATE_RESEARCH_ONLY")
    )
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError):
        await _publish(adapter)
    assert owner.uow.research_cat.profile_metadata.rights_status == "PENDING"
    assert owner.uow.research_cat.profile_metadata.execution_status == "CANDIDATE_RESEARCH_ONLY"
    assert owner.uow.school_operations.calls == []
