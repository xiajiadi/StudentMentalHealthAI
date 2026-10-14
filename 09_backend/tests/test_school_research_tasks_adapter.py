from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_tasks import (
    SchoolResearchTasksPersistenceAdapter,
    _server_case_index_plan,
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
from smhai_backend.domains.school_research.observed_corpus import ObservedResponseCorpus
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUsePolicy,
)

SCHOOL_ID = 71
PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
PROFILE_SHA = "a" * 64
MANIFEST_SHA = "b" * 64
CROSSWALK_SHA = "c" * 64
CONFIG_SHA = "d" * 64
CORPUS_SHA = "9" * 64
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

    def in_(self, values):
        return (self.name, "in", tuple(values))

    def is_(self, value):
        return (self.name, "is", value)

    def is_not(self, value):
        return (self.name, "is_not", value)


class _SchoolClass:
    school_id = _Field("SchoolClass.school_id")
    class_ref = _Field("SchoolClass.class_ref")
    id = _Field("SchoolClass.id")


class _MeasurementTask:
    school_id = _Field("MeasurementTask.school_id")
    task_ref = _Field("MeasurementTask.task_ref")
    public_id = _Field("MeasurementTask.public_id")
    class_id = _Field("MeasurementTask.class_id")


class _SchoolResearchProfileVersion:
    id = _Field("SchoolResearchProfileVersion.id")
    school_id = _Field("SchoolResearchProfileVersion.school_id")
    profile_ref = _Field("SchoolResearchProfileVersion.profile_ref")
    version_number = _Field("SchoolResearchProfileVersion.version_number")
    instrument_id = _Field("SchoolResearchProfileVersion.instrument_id")
    source_population_scope = _Field("SchoolResearchProfileVersion.source_population_scope")
    profile_sha256 = _Field("SchoolResearchProfileVersion.profile_sha256")
    manifest_sha256 = _Field("SchoolResearchProfileVersion.manifest_sha256")
    fit_sha256 = _Field("SchoolResearchProfileVersion.fit_sha256")
    calibration_sha256 = _Field("SchoolResearchProfileVersion.calibration_sha256")
    parameter_origin = _Field("SchoolResearchProfileVersion.parameter_origin")
    published_parameter_crosswalk_sha256 = _Field(
        "SchoolResearchProfileVersion.published_parameter_crosswalk_sha256"
    )
    research_only = _Field("SchoolResearchProfileVersion.research_only")
    human_curated = _Field("SchoolResearchProfileVersion.human_curated")
    psychological_interpretation_allowed = _Field(
        "SchoolResearchProfileVersion.psychological_interpretation_allowed"
    )
    publication_status = _Field("SchoolResearchProfileVersion.publication_status")
    rights_status = _Field("SchoolResearchProfileVersion.rights_status")
    execution_status = _Field("SchoolResearchProfileVersion.execution_status")
    rights_revoked_at = _Field("SchoolResearchProfileVersion.rights_revoked_at")
    disabled_at = _Field("SchoolResearchProfileVersion.disabled_at")
    simulation_enabled_at = _Field("SchoolResearchProfileVersion.simulation_enabled_at")
    purpose = _Field("SchoolResearchProfileVersion.purpose")


class _Query:
    def __init__(self, *columns):
        self.entity = columns[0]
        self.columns = columns
        self.conditions = ()
        self.ordering = ()
        self.row_limit = None

    def where(self, *conditions):
        self.conditions += conditions
        return self

    def scalar_subquery(self):
        return self

    def order_by(self, *columns):
        self.ordering = columns
        return self

    def limit(self, value):
        self.row_limit = value
        return self


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, *, school_class=None, task=None, catalog_rows=()):
        self.school_class = school_class
        self.task = task
        self.catalog_rows = list(catalog_rows)
        self.executed_queries = []
        self.flush_count = 0

    async def scalar(self, query):
        if query.entity is _SchoolClass:
            return self.school_class
        if query.entity is _MeasurementTask:
            return self.task
        raise AssertionError("unexpected scoped query")

    async def execute(self, query):
        self.executed_queries.append(query)
        return _Rows(self.catalog_rows)

    async def flush(self):
        self.flush_count += 1


class _Uow(AbstractAsyncContextManager):
    def __init__(self, *, school_class=None, task=None, profile_metadata=None, catalog_rows=()):
        self.school_operations = _Operations()
        self.session = _Session(
            school_class=school_class,
            task=self.school_operations.task if task is True else task,
            catalog_rows=catalog_rows,
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
        self.enrollment_count = 5
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
        return SimpleNamespace(task=self.task, enrollment_count=self.enrollment_count)

    async def task_progress_counts(self, **_kwargs):
        return SimpleNamespace(published_enrollment_count=5)


class _ResearchCat:
    def __init__(self, profile_metadata):
        self.profile_metadata = profile_metadata
        self.binding = None
        self.calls = []
        self.assignment_verifications = []

    async def get_profile_metadata(self, **_kwargs):
        return self.profile_metadata

    async def create_task_binding(self, **kwargs):
        self.calls.append(("create_binding", kwargs))
        self.binding = SimpleNamespace(
            binding_id=1001,
            school_id=kwargs["school_id"],
            task_id=kwargs["task_id"],
            class_id=kwargs["class_id"],
            profile_version_id=kwargs["profile_version_id"],
            profile_ref=kwargs["profile_ref"],
            profile_version_number=kwargs["profile_version_number"],
            profile_sha256=kwargs["expected_profile_sha256"],
            response_origin=kwargs["response_origin"],
            corpus_sha256=kwargs.get("corpus_sha256"),
            case_count=kwargs.get("case_count"),
            status="ACTIVE",
            config_version=kwargs["config_version"],
            config_sha256=kwargs["expected_config_sha256"],
            research_only=True,
            revoked_at=None,
        )
        return self.binding

    async def create_public_observed_case_assignments(self, **kwargs):
        self.calls.append(("create_assignments", kwargs))
        return tuple(
            SimpleNamespace(
                school_id=kwargs["school_id"],
                task_id=kwargs["task_id"],
                class_id=kwargs["class_id"],
                task_enrollment_id=2000 + index,
                subject_id=3000 + index,
                task_binding_id=kwargs["task_binding_id"],
                profile_version_id=41,
                profile_ref=PROFILE_REF,
                profile_version_number=2,
                profile_sha256=kwargs["expected_profile_sha256"],
                corpus_sha256=kwargs["expected_corpus_sha256"],
                case_count=800,
                case_index=case_index,
            )
            for index, case_index in enumerate(kwargs["case_index_plan"])
        )

    async def require_public_observed_task_assignments(self, **kwargs):
        self.assignment_verifications.append(kwargs)

    async def get_task_binding_metadata(self, **_kwargs):
        return self.binding


class _Audit:
    def __init__(self):
        self.calls = []

    async def append(self, **kwargs):
        allowed = {
            "schema_version",
            "component_version",
            "reason_code",
            "count",
            "source",
            "state",
        }
        unknown = set(kwargs.get("safe_metadata", {})) - allowed
        if unknown:
            raise ValueError("audit metadata contains a non-whitelisted field")
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
    def __init__(
        self,
        *,
        profile_metadata=None,
        school_class=None,
        task=None,
        replay=False,
        catalog_rows=(),
    ):
        self.events = []
        self._db_models = SimpleNamespace(
            SchoolClass=_SchoolClass,
            MeasurementTask=_MeasurementTask,
            SchoolResearchProfileVersion=_SchoolResearchProfileVersion,
        )
        self._db_enums = SimpleNamespace(AuditResult=SimpleNamespace(SUCCESS="SUCCESS"))
        self.uow = _Uow(
            school_class=school_class or SimpleNamespace(id=902),
            task=True if replay and task is None else task,
            profile_metadata=profile_metadata,
            catalog_rows=catalog_rows,
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


def _catalog(*, verified=True):
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
        trusted_profile=SimpleNamespace(
            profile_ref=PROFILE_REF,
            profile_schema="psynova.research-profile.v3",
            profile_sha256=PROFILE_SHA,
            manifest_sha256=MANIFEST_SHA,
            raw_profile_bytes=raw,
        ),
        repository=repository,
    )
    corpus = _observed_corpus() if verified else None
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
        observed_corpus=corpus,
        observed_corpus_sha256=CORPUS_SHA if corpus else None,
        observed_corpus_row_count=800 if corpus else None,
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


def _observed_corpus():
    return ObservedResponseCorpus(
        profile_ref=PROFILE_REF,
        profile_sha256=PROFILE_SHA,
        manifest_sha256=MANIFEST_SHA,
        response_csv_sha256=CORPUS_SHA,
        row_count=800,
        _column_by_item={f"ITEM_{index}": index for index in range(8)},
        _rows=tuple(tuple(1 for _ in range(8)) for _ in range(800)),
    )


def _idempotency():
    return "synthetic-key", "e" * 64, "f" * 64


def _trusted_policy():
    return ResearchStudyUsePolicy(
        study_ref="synthetic-study-replay",
        school_id=SCHOOL_ID,
        institution="Synthetic School",
        use_scope="ISOLATED_HISTORICAL_REPLAY",
        noncommercial=True,
        historical_replay_only=True,
        english_unchanged=True,
        starts_at=datetime(2026, 10, 1, tzinfo=UTC),
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        profiles=(
            ResearchStudyProfilePin(
                profile_ref=PROFILE_REF,
                profile_sha256=PROFILE_SHA,
                manifest_sha256=MANIFEST_SHA,
                published_crosswalk_sha256=CROSSWALK_SHA,
            ),
        ),
        rights_basis="synthetic test declaration",
        rights_source_urls=("https://example.invalid/rights",),
        recorded_by="synthetic-test-operator",
        recorded_at=datetime(2026, 10, 13, tzinfo=UTC),
        operator_declaration="synthetic test only",
        source_rights_verified=True,
    )


def _catalog_row(metadata):
    fields = (
        "profile_version_id",
        "school_id",
        "profile_ref",
        "version_number",
        "instrument_id",
        "source_population_scope",
        "profile_sha256",
        "manifest_sha256",
        "fit_sha256",
        "calibration_sha256",
        "parameter_origin",
        "published_parameter_crosswalk_sha256",
        "research_only",
        "human_curated",
        "psychological_interpretation_allowed",
        "publication_status",
        "rights_status",
        "execution_status",
        "rights_revoked_at",
        "disabled_at",
        "simulation_enabled_at",
    )
    return tuple(getattr(metadata, name) for name in fields)


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
    assert binding_call["corpus_sha256"] == CORPUS_SHA
    assert binding_call["case_count"] == 800
    assert binding_call["config_payload"] == {"max_items": 8, "min_items": 8}
    assignment_name, assignment_call = owner.uow.research_cat.calls[1]
    assert assignment_name == "create_assignments"
    assert assignment_call["case_index_plan"] == tuple(
        dict.fromkeys(assignment_call["case_index_plan"])
    )
    assert len(assignment_call["case_index_plan"]) == result.published_enrollment_count
    assert len(set(assignment_call["case_index_plan"])) == result.published_enrollment_count
    assert all(0 <= index < 800 for index in assignment_call["case_index_plan"])
    assert result.response_origin == "PUBLIC_OBSERVED"
    assert result.research_only is True
    assert result.publication_status == "not_approved_for_publication_or_operational_use"
    assert result.published_enrollment_count == 5
    assert owner.events[-1][0] == "idempotency_complete"
    assert owner.uow.audit.calls[0]["action"] == "school_research_tasks.task.published"
    assert owner.uow.audit.calls[0]["safe_metadata"] == {
        "schema_version": "psynova.research-study-use.v1",
        "component_version": POLICY_SHA,
        "reason_code": "ISOLATED_HISTORICAL_REPLAY",
        "source": "school_research_tasks",
        "state": "PUBLISHED",
    }
    assert policy.calls[0]["task_opens_at"] == OPEN
    assert policy.calls[0]["task_due_at"] == DUE


def test_server_case_plan_is_stable_without_replacement_for_partial_and_full_cohorts():
    plan = _server_case_index_plan(
        school_id=SCHOOL_ID,
        task_id=501,
        profile_sha256=PROFILE_SHA,
        corpus_sha256=CORPUS_SHA,
        enrollment_count=23,
    )
    assert plan == _server_case_index_plan(
        school_id=SCHOOL_ID,
        task_id=501,
        profile_sha256=PROFILE_SHA,
        corpus_sha256=CORPUS_SHA,
        enrollment_count=23,
    )
    assert len(plan) == 23
    assert len(set(plan)) == 23
    assert all(0 <= index < 800 for index in plan)
    full_plan = _server_case_index_plan(
        school_id=SCHOOL_ID,
        task_id=501,
        profile_sha256=PROFILE_SHA,
        corpus_sha256=CORPUS_SHA,
        enrollment_count=800,
    )
    assert len(full_plan) == 800
    assert set(full_plan) == set(range(800))


@pytest.mark.asyncio
@pytest.mark.parametrize("enrollment_count", [0, 801])
async def test_out_of_range_enrollment_count_rolls_back_before_binding(enrollment_count):
    owner = _Owner(profile_metadata=_metadata())
    owner.uow.school_operations.enrollment_count = enrollment_count
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as blocked:
        await _publish(adapter)

    assert blocked.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.uow.school_operations.calls[0][0] == "publish_snapshot"
    assert owner.uow.research_cat.calls == []
    assert owner.uow.exception is not None
    assert not any(event[0] == "idempotency_complete" for event in owner.events)
    assert owner.uow.audit.calls == []


@pytest.mark.asyncio
async def test_assignment_creation_failure_rolls_back_task_binding_receipt_and_audit():
    owner = _Owner(profile_metadata=_metadata())

    async def fail_assignment(**_kwargs):
        raise RuntimeError("synthetic assignment persistence fault")

    owner.uow.research_cat.create_public_observed_case_assignments = fail_assignment
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as failed:
        await _publish(adapter)

    assert failed.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert owner.uow.exception is not None
    assert owner.uow.research_cat.binding is not None
    assert not any(event[0] == "idempotency_complete" for event in owner.events)
    assert owner.uow.audit.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["receipt", "audit"])
async def test_post_assignment_receipt_and_audit_failures_rollback_publication(failure_point):
    owner = _Owner(profile_metadata=_metadata())
    if failure_point == "receipt":
        async def fail_receipt(*_args, **_kwargs):
            raise RuntimeError("synthetic receipt persistence fault")

        owner._school_idempotency_complete = fail_receipt
    else:
        async def fail_audit(**_kwargs):
            raise RuntimeError("synthetic audit persistence fault")

        owner.uow.audit.append = fail_audit
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as failed:
        await _publish(adapter)

    assert failed.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert owner.uow.exception is not None
    assert any(name == "create_assignments" for name, _ in owner.uow.research_cat.calls)
    if failure_point == "receipt":
        assert owner.uow.audit.calls == []
    else:
        assert owner.uow.audit.calls == []


@pytest.mark.asyncio
async def test_unverified_binding_is_hidden_from_admin_catalog_and_cannot_publish():
    owner = _Owner(catalog_rows=[_catalog_row(_metadata())])
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner,
        _catalog(verified=False),
        study_use_policy=_trusted_policy(),
        study_use_policy_sha256=POLICY_SHA,
    )

    options = await adapter.list_catalog_options(_actor(), at=NOW)
    assert options == ()
    assert owner.uow.session.executed_queries == []
    assert owner.uow.audit.calls[0]["safe_metadata"]["count"] == 0

    with pytest.raises(BackendError) as blocked:
        await _publish(adapter)
    assert blocked.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.uow.school_operations.calls == []


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
        binding_id=1001,
        school_id=SCHOOL_ID,
        task_id=501,
        class_id=902,
        profile_version_id=41,
        profile_ref=PROFILE_REF,
        profile_version_number=2,
        profile_sha256=PROFILE_SHA,
        response_origin="PUBLIC_OBSERVED",
        corpus_sha256=CORPUS_SHA,
        case_count=800,
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
    assert len(owner.uow.research_cat.assignment_verifications) == 1
    assert owner.uow.research_cat.assignment_verifications[0] == {
        "school_id": SCHOOL_ID,
        "task_id": 501,
        "class_id": 902,
        "task_binding_id": 1001,
        "expected_profile_sha256": PROFILE_SHA,
        "expected_corpus_sha256": CORPUS_SHA,
    }

    owner.uow.research_cat.binding.config_sha256 = "0" * 64
    with pytest.raises(BackendError) as mismatch:
        await _publish(adapter)
    assert mismatch.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_legacy_public_observed_binding_replay_fails_closed_without_retroactive_assignment():
    owner = _Owner(profile_metadata=_metadata(), replay=True)
    owner.uow.school_operations.task.cat_binding_mode = "RESEARCH_PROFILE"
    owner.uow.research_cat.binding = SimpleNamespace(
        binding_id=1001,
        school_id=SCHOOL_ID,
        task_id=501,
        class_id=902,
        profile_version_id=41,
        profile_ref=PROFILE_REF,
        profile_version_number=2,
        profile_sha256=PROFILE_SHA,
        response_origin="PUBLIC_OBSERVED",
        corpus_sha256=None,
        case_count=None,
        status="ACTIVE",
        config_version="promis_v3_research",
        config_sha256=CONFIG_SHA,
        research_only=True,
        revoked_at=None,
    )
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as blocked:
        await _publish(adapter)

    assert blocked.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.uow.research_cat.assignment_verifications == []
    assert owner.uow.research_cat.calls == []
    assert owner.uow.audit.calls == []


@pytest.mark.asyncio
async def test_replay_rejects_pinned_binding_when_complete_assignment_map_is_missing():
    owner = _Owner(profile_metadata=_metadata(), replay=True)
    owner.uow.school_operations.task.cat_binding_mode = "RESEARCH_PROFILE"
    owner.uow.research_cat.binding = SimpleNamespace(
        binding_id=1001,
        school_id=SCHOOL_ID,
        task_id=501,
        class_id=902,
        profile_version_id=41,
        profile_ref=PROFILE_REF,
        profile_version_number=2,
        profile_sha256=PROFILE_SHA,
        response_origin="PUBLIC_OBSERVED",
        corpus_sha256=CORPUS_SHA,
        case_count=800,
        status="ACTIVE",
        config_version="promis_v3_research",
        config_sha256=CONFIG_SHA,
        research_only=True,
        revoked_at=None,
    )

    async def missing_map(**_kwargs):
        failure = RuntimeError("synthetic mapping unavailable")
        failure.code = "RESEARCH_CASE_ASSIGNMENT_NOT_FOUND"
        raise failure

    owner.uow.research_cat.require_public_observed_task_assignments = missing_map
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner, _catalog(), study_use_policy=_StudyPolicy(), study_use_policy_sha256=POLICY_SHA
    )

    with pytest.raises(BackendError) as blocked:
        await _publish(adapter)

    assert blocked.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.uow.research_cat.calls == []
    assert not any(event[0] == "idempotency_complete" for event in owner.events)
    assert owner.uow.audit.calls == []


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


@pytest.mark.asyncio
async def test_admin_catalog_lists_exact_enabled_pair_without_encrypted_columns():
    owner = _Owner(catalog_rows=[_catalog_row(_metadata())])
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner,
        _catalog(),
        study_use_policy=_trusted_policy(),
        study_use_policy_sha256=POLICY_SHA,
    )

    result = await adapter.list_catalog_options(_actor(), at=NOW)

    assert len(result) == 1
    item = result[0]
    assert item.binding_ref == BINDING_REF
    assert item.profile_ref == PROFILE_REF
    assert item.profile_version_number == 2
    assert item.source_population_scope == "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17"
    assert item.instrument_id == "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
    assert item.instrument_version == "research-v2"
    assert item.research_only is True
    assert item.publication_status == "not_approved_for_publication_or_operational_use"
    assert owner.events[0][0:2] == ("authorize", "admin")
    query = owner.uow.session.executed_queries[0]
    selected = {column.name for column in query.columns}
    assert all(not name.endswith(("payload_ciphertext", "config_ciphertext")) for name in selected)
    predicates = {
        condition[0]: condition[1:]
        for condition in query.conditions
        if isinstance(condition, tuple) and len(condition) == 3
    }
    assert predicates["SchoolResearchProfileVersion.school_id"] == ("eq", SCHOOL_ID)
    assert predicates["SchoolResearchProfileVersion.rights_status"] == ("eq", "VERIFIED")
    assert predicates["SchoolResearchProfileVersion.execution_status"] == (
        "eq",
        "SIMULATION_ENABLED",
    )
    assert predicates["SchoolResearchProfileVersion.profile_ref"][0] == "in"
    assert predicates["SchoolResearchProfileVersion.rights_revoked_at"] == ("is", None)
    assert predicates["SchoolResearchProfileVersion.disabled_at"] == ("is", None)
    assert query.row_limit == 101
    assert owner.uow.audit.calls[0]["action"] == "school_research_tasks.catalog.list"
    assert owner.uow.audit.calls[0]["safe_metadata"] == {
        "source": "school_research_tasks",
        "state": "READ",
        "count": 1,
    }


@pytest.mark.asyncio
async def test_admin_catalog_authorizes_before_policy_and_profile_query():
    owner = _Owner(catalog_rows=[_catalog_row(_metadata())])
    adapter = SchoolResearchTasksPersistenceAdapter(owner, _catalog())

    with pytest.raises(BackendError) as no_policy:
        await adapter.list_catalog_options(_actor(), at=NOW)
    assert no_policy.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert owner.events[0][0:2] == ("authorize", "admin")
    assert owner.uow.session.executed_queries == []

    owner.events.clear()
    with pytest.raises(BackendError) as role_denied:
        await adapter.list_catalog_options(_actor(BackendRole.TEACHER), at=NOW)
    assert role_denied.value.code is ErrorCode.FORBIDDEN
    assert owner.events == []
    assert owner.uow.session.executed_queries == []


@pytest.mark.asyncio
async def test_admin_catalog_rejects_profile_pin_mismatch_and_expired_policy():
    metadata = _metadata()
    metadata.profile_sha256 = "f" * 64
    owner = _Owner(catalog_rows=[_catalog_row(metadata)])
    adapter = SchoolResearchTasksPersistenceAdapter(
        owner,
        _catalog(),
        study_use_policy=_trusted_policy(),
        study_use_policy_sha256=POLICY_SHA,
    )
    with pytest.raises(BackendError) as mismatched:
        await adapter.list_catalog_options(_actor(), at=NOW)
    assert mismatched.value.code is ErrorCode.WORKFLOW_CONFLICT

    expired_policy = replace(
        _trusted_policy(),
        ends_at=datetime(2026, 10, 13, 23, 59, tzinfo=UTC),
    )
    expired_adapter = SchoolResearchTasksPersistenceAdapter(
        _Owner(catalog_rows=[]),
        _catalog(),
        study_use_policy=expired_policy,
        study_use_policy_sha256=POLICY_SHA,
    )
    with pytest.raises(BackendError) as expired:
        await expired_adapter.list_catalog_options(_actor(), at=NOW)
    assert expired.value.code is ErrorCode.FORBIDDEN

    wrong_school_policy = replace(_trusted_policy(), school_id=SCHOOL_ID + 1)
    wrong_school_owner = _Owner(catalog_rows=[])
    wrong_school_adapter = SchoolResearchTasksPersistenceAdapter(
        wrong_school_owner,
        _catalog(),
        study_use_policy=wrong_school_policy,
        study_use_policy_sha256=POLICY_SHA,
    )
    with pytest.raises(BackendError) as wrong_school:
        await wrong_school_adapter.list_catalog_options(_actor(), at=NOW)
    assert wrong_school.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert wrong_school_owner.events[0][0:2] == ("authorize", "admin")
    assert wrong_school_owner.uow.session.executed_queries == []
