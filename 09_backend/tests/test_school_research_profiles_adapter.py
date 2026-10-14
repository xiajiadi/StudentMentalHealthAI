from __future__ import annotations

import ast
import hashlib
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from smhai_backend.adapters.school_research_profiles import (
    SchoolResearchProfilesPersistenceAdapter,
    SchoolResearchProfileView,
)
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research.catalog import (
    RepositoryResearchProfileInput,
    ResearchProfilePublicMetadata,
    ResearchProfileRepositoryProjection,
    ResearchProfileSelection,
    SchoolResearchCatalog,
)
from smhai_backend.domains.school_research.study_use import (
    load_research_study_use_policy,
)

SCHOOL_ID = 71
PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
PROFILE_SHA = "a" * 64
MANIFEST_SHA = "b" * 64
CROSSWALK_SHA = "c" * 64
VERSION = 3
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


class _AuditResult(StrEnum):
    SUCCESS = "SUCCESS"


class _RepoError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("fixed fake repository error")


class _Claim:
    def __init__(self, *, replayed: bool = False, result_ref: str | None = None) -> None:
        self.replayed = replayed
        self.record = SimpleNamespace(
            result_resource_type=("school_research_profile_version" if replayed else None),
            result_public_id=result_ref,
            state="COMPLETED" if replayed else "IN_PROGRESS",
        )


class _Audit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def append(self, **kwargs: Any) -> None:
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
        self.entries.append(kwargs)


class _ResearchRepo:
    def __init__(self) -> None:
        self.metadata: dict[tuple[int, str, int], Any] = {}
        self.created: list[dict[str, Any]] = []
        self.fail_code: str | None = None
        self.eligibility_fail_code: str | None = None
        self.eligibility_changes: list[dict[str, Any]] = []
        self.concurrent_winner: Any | None = None

    async def get_profile_metadata(
        self, *, school_id: int, profile_ref: str, version_number: int
    ) -> Any:
        key = (school_id, profile_ref, version_number)
        if key not in self.metadata:
            raise _RepoError("RESEARCH_PROFILE_NOT_FOUND")
        return self.metadata[key]

    async def create_profile_version(self, **kwargs: Any) -> Any:
        self.created.append(kwargs)
        if self.fail_code:
            if self.concurrent_winner is not None:
                winner = self.concurrent_winner
                self.metadata[
                    (winner.school_id, winner.profile_ref, winner.version_number)
                ] = winner
            raise _RepoError(self.fail_code)
        metadata = _metadata(
            profile_sha256=kwargs["expected_profile_sha256"],
            manifest_sha256=kwargs["expected_manifest_sha256"],
            version_number=kwargs["version_number"],
            school_id=kwargs["school_id"],
            instrument_id=kwargs["profile"].instrument_id,
            dimension="PROMIS_PEDIATRIC_ANXIETY_RESEARCH",
            source_population_scope=kwargs["source_population_scope"],
            rights_status=kwargs["rights_status"],
            execution_status=kwargs["execution_status"],
            parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
            published_parameter_crosswalk_sha256=CROSSWALK_SHA,
        )
        self.metadata[
            (metadata.school_id, metadata.profile_ref, metadata.version_number)
        ] = metadata
        return metadata

    async def change_profile_eligibility(self, **kwargs: Any) -> Any:
        self.eligibility_changes.append(kwargs)
        if self.eligibility_fail_code:
            raise _RepoError(self.eligibility_fail_code)
        key = (kwargs["school_id"], kwargs["profile_ref"], kwargs["version_number"])
        metadata = self.metadata[key]
        metadata.rights_status = kwargs["rights_status"]
        metadata.execution_status = kwargs["execution_status"]
        metadata.simulation_enabled_at = NOW
        return metadata


class _Uow:
    def __init__(self, repo: _ResearchRepo) -> None:
        self.research_cat = repo
        self.audit = _Audit()


class _QueryExpression:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, value):
        return (self.name, value)

    def desc(self):
        return (self.name, "DESC")


class _QueryStatement:
    def __init__(self, columns) -> None:
        self.columns = columns
        self.source = None
        self.filters = ()
        self.ordering = ()
        self.page_offset = None
        self.page_limit = None

    def select_from(self, source):
        self.source = source
        return self

    def where(self, *filters):
        self.filters += filters
        return self

    def order_by(self, *ordering):
        self.ordering = ordering
        return self

    def offset(self, value):
        self.page_offset = value
        return self

    def limit(self, value):
        self.page_limit = value
        return self


class _VersionModel:
    __tablename__ = "school_research_profile_versions"

    school_id = _QueryExpression("school_id")
    profile_ref = _QueryExpression("profile_ref")
    version_number = _QueryExpression("version_number")
    source_population_scope = _QueryExpression("source_population_scope")
    instrument_id = _QueryExpression("instrument_id")
    research_only = _QueryExpression("research_only")
    publication_status = _QueryExpression("publication_status")
    rights_status = _QueryExpression("rights_status")
    execution_status = _QueryExpression("execution_status")
    created_at = _QueryExpression("created_at")
    # These columns exist on the actual table and must not enter either SELECT.
    profile_sha256 = _QueryExpression("profile_sha256")
    manifest_sha256 = _QueryExpression("manifest_sha256")
    payload_ciphertext = _QueryExpression("payload_ciphertext")
    key_version = _QueryExpression("key_version")
    cat_config = _QueryExpression("cat_config")
    case_index = _QueryExpression("case_index")
    subject_id = _QueryExpression("subject_id")


class _VersionQuerySession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return len(self.rows)

    async def execute(self, statement):
        self.statements.append(statement)
        start = statement.page_offset or 0
        stop = start + statement.page_limit if statement.page_limit is not None else None
        page = self.rows[start:stop]
        return SimpleNamespace(all=lambda: page)


class _Owner:
    def __init__(
        self, *, denied: bool = False, replay: bool = False, result_ref: str | None = None
    ) -> None:
        self.repo = _ResearchRepo()
        self.uow = _Uow(self.repo)
        self.denied = denied
        self.replay = replay
        self.result_ref = result_ref
        self.events: list[str] = []
        self.role_times: list[datetime] = []
        self.claim: _Claim | None = None
        self.completed: list[dict[str, Any]] = []
        self.idempotency_calls: list[tuple[str, str, str]] = []
        self._db_enums = SimpleNamespace(AuditResult=_AuditResult)
        self.active_uow = False

    def _utc_now(self) -> datetime:
        return NOW.replace(tzinfo=None)

    @asynccontextmanager
    async def _uow(self):
        assert not self.active_uow
        self.active_uow = True
        try:
            yield self.uow
        finally:
            self.active_uow = False

    async def _school_actor_role(self, uow, actor, role_code: str, at: datetime):
        self.events.append("role")
        self.role_times.append(at)
        assert uow is self.uow
        assert role_code == "psychological_specialist"
        assert at.tzinfo is None
        if self.denied:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return 9001, 9002

    async def _school_idempotency_begin(self, uow, idempotency):
        assert uow is self.uow
        self.events.append("claim")
        self.idempotency_calls.append(idempotency)
        self.claim = _Claim(replayed=self.replay, result_ref=self.result_ref)
        return self.claim

    async def _school_idempotency_complete(self, uow, claim, *, resource_type, result_ref):
        assert uow is self.uow
        assert not claim.replayed
        claim.record.state = "COMPLETED"
        claim.record.result_resource_type = resource_type
        claim.record.result_public_id = result_ref
        self.completed.append(
            {"resource_type": resource_type, "result_ref": result_ref}
        )


def _profile_document() -> bytes:
    return json.dumps(
        {
            "model": {"parameter_origin": "published reference"},
            "provenance": {"parameter_crosswalk_sha256": CROSSWALK_SHA},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _catalog() -> SchoolResearchCatalog:
    raw = _profile_document()
    profile_input = RepositoryResearchProfileInput(
        profile_id=PROFILE_REF,
        profile_type="RESEARCH_ONLY",
        instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        dimension=(
            "Pediatric anxiety item-response research dimension; no psychological interpretation"
        ),
        file_sha256=PROFILE_SHA,
        manifest_sha256=MANIFEST_SHA,
        raw_profile_bytes=raw,
    )
    repository = ResearchProfileRepositoryProjection(
        school_id=SCHOOL_ID,
        profile=profile_input,
        expected_profile_sha256=PROFILE_SHA,
        expected_manifest_sha256=MANIFEST_SHA,
        source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
    )
    public = ResearchProfilePublicMetadata(
        school_id=SCHOOL_ID,
        profile_ref=PROFILE_REF,
        profile_schema="psynova.research-profile.v3",
        source_family="PROMIS",
        instrument_id=profile_input.instrument_id,
        instrument_family="PROMIS_PEDIATRIC_ANXIETY",
        source_population="US children 8-17 self-report",
        source_version="v2.0 subset",
        parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
        research_only=True,
        human_curated=False,
        psychological_interpretation_allowed=False,
        publication_status="not_approved",
    )
    selection = ResearchProfileSelection(
        public=public,
        trusted_profile=SimpleNamespace(
            raw_profile_bytes=raw,
            profile_schema="psynova.research-profile.v3",
            profile_ref=PROFILE_REF,
        ),
        repository=repository,
    )
    return SchoolResearchCatalog(
        school_id=SCHOOL_ID,
        _profiles={PROFILE_REF: selection},
        _bindings={},
    )


def _actor(role: BackendRole = BackendRole.PSYCHOLOGICAL_SPECIALIST) -> Actor:
    return Actor(
        user_id="USER_specialist01",
        username="specialist",
        role=role,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=SCHOOL_ID,
        school_ref="SCHOOL_test01",
        school_contexts=(
            SchoolRoleContext(
                context_id="9002",
                role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
                school_id=SCHOOL_ID,
                school_ref="SCHOOL_test01",
            ),
        ),
    )


def _metadata(
    *,
    profile_sha256: str = PROFILE_SHA,
    manifest_sha256: str = MANIFEST_SHA,
    version_number: int = VERSION,
    school_id: int = SCHOOL_ID,
    instrument_id: str = "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
    dimension: str = "PROMIS_PEDIATRIC_ANXIETY_RESEARCH",
    source_population_scope: str = "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
    rights_status: str = "PENDING",
    execution_status: str = "CANDIDATE_RESEARCH_ONLY",
    parameter_origin: str = "PUBLISHED_ROUNDED_REFERENCE",
    published_parameter_crosswalk_sha256: str | None = CROSSWALK_SHA,
) -> Any:
    return SimpleNamespace(
        profile_version_id=41,
        school_id=school_id,
        profile_ref=PROFILE_REF,
        version_number=version_number,
        instrument_id=instrument_id,
        dimension=dimension,
        source_population_scope=source_population_scope,
        profile_sha256=profile_sha256,
        manifest_sha256=manifest_sha256,
        fit_sha256=None,
        calibration_sha256=None,
        parameter_origin=parameter_origin,
        published_parameter_crosswalk_sha256=published_parameter_crosswalk_sha256,
        rights_status=rights_status,
        execution_status=execution_status,
        research_only=True,
        human_curated=False,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
        created_at=NOW,
        simulation_enabled_at=None,
        rights_revoked_at=None,
        disabled_at=None,
    )


def _adapter(
    owner: _Owner | None = None,
    catalog: SchoolResearchCatalog | None = None,
    *,
    study_use_policy=None,
    study_use_policy_sha256: str | None = None,
):
    return SchoolResearchProfilesPersistenceAdapter(
        owner or _Owner(),
        catalog or _catalog(),
        study_use_policy=study_use_policy,
        study_use_policy_sha256=study_use_policy_sha256,
    )


def _study_use_policy(tmp_path: Path, *, school_id: int = SCHOOL_ID):
    document = {
        "schema": "psynova.research-study-use.v1",
        "study_ref": "study:replay-01",
        "school_id": school_id,
        "institution": "Synthetic institution declaration",
        "use_scope": "ISOLATED_HISTORICAL_REPLAY",
        "noncommercial": True,
        "historical_replay_only": True,
        "english_unchanged": True,
        "starts_at": "2026-10-14T00:00:00Z",
        "ends_at": "2027-06-30T23:59:59Z",
        "profiles": [{
            "profile_ref": PROFILE_REF,
            "profile_sha256": PROFILE_SHA,
            "manifest_sha256": MANIFEST_SHA,
            "published_crosswalk_sha256": CROSSWALK_SHA,
        }],
        "rights_basis": "Synthetic scoped research-use record for historical replay.",
        "rights_source_urls": ["https://example.org/research-rights"],
        "recorded_by": "operator:synthetic-review",
        "recorded_at": "2026-10-14T00:00:00Z",
        "operator_declaration": "Server-pinned test policy; not an external approval.",
        "clinical_approval": False,
        "ethics_approval": False,
        "psychometric_approval": False,
    }
    path = tmp_path / "trusted-study-use.json"
    path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    policy = load_research_study_use_policy(
        path,
        expected_sha256=digest,
        source_rights_verified=True,
        latest_allowed_ends_at=datetime(2027, 6, 30, 23, 59, 59, tzinfo=UTC),
    )
    return policy, digest


def _idempotency() -> tuple[str, str, str]:
    return (
        "opaque-key-01",
        hashlib.sha256(b"request").hexdigest(),
        hashlib.sha256(b"scope").hexdigest(),
    )


@pytest.mark.asyncio
async def test_list_profiles_returns_catalog_candidates_after_specialist_authorization() -> None:
    owner = _Owner()
    catalog = _catalog()
    adapter = SchoolResearchProfilesPersistenceAdapter(owner, catalog)

    profiles = await adapter.list_profiles(_actor())

    assert owner.events == ["role"]
    assert owner.role_times == [NOW.replace(tzinfo=None)]
    assert len(profiles) == 1
    candidate = profiles[0]
    assert candidate.profile_ref == PROFILE_REF
    assert candidate.version_number is None
    assert candidate.catalog_state == "REGISTRY_CANDIDATE"
    assert candidate.rights_status == "PENDING"
    assert candidate.execution_status == "CANDIDATE_RESEARCH_ONLY"
    assert candidate.publication_status == "not_approved_for_publication_or_operational_use"
    assert not (
        {"profile_sha256", "manifest_sha256", "raw_profile_bytes", "school_id"}
        & set(asdict(candidate))
    )


@pytest.mark.asyncio
async def test_list_profile_versions_queries_only_safe_metadata_after_persisted_role(
    monkeypatch,
) -> None:
    import types

    rows = [
        SimpleNamespace(
            profile_ref=PROFILE_REF,
            version_number=4,
            source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
            research_only=True,
            publication_status="not_approved_for_publication_or_operational_use",
            rights_status="VERIFIED",
            execution_status="SIMULATION_ENABLED",
            created_at=NOW.replace(tzinfo=None),
        ),
        SimpleNamespace(
            profile_ref=PROFILE_REF,
            version_number=3,
            source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
            research_only=True,
            publication_status="not_approved_for_publication_or_operational_use",
            rights_status="REVOKED",
            execution_status="DISABLED",
            created_at=NOW.replace(tzinfo=None),
        ),
    ]
    session = _VersionQuerySession(rows)
    owner = _Owner()
    owner._db_models = SimpleNamespace(SchoolResearchProfileVersion=_VersionModel)
    owner._select = lambda *columns: _QueryStatement(columns)
    owner.uow.session = session
    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        types.SimpleNamespace(func=SimpleNamespace(count=lambda: _QueryExpression("COUNT"))),
    )
    adapter = _adapter(owner)

    page = await adapter.list_profile_versions(
        _actor(), PROFILE_REF, limit=1, offset=0
    )

    assert owner.events == ["role"]
    assert page.total == 2
    assert page.has_more is True
    assert page.next_offset == 1
    assert page.items[0].version_number == 4
    assert page.items[0].rights_status == "VERIFIED"
    assert page.items[0].execution_status == "SIMULATION_ENABLED"
    assert page.items[0].use_eligibility == "RECHECK_REQUIRED"
    assert len(session.statements) == 2
    metadata_query = session.statements[1]
    selected_names = {column.name for column in metadata_query.columns}
    assert selected_names == {
        "profile_ref",
        "version_number",
        "source_population_scope",
        "instrument_id",
        "research_only",
        "publication_status",
        "rights_status",
        "execution_status",
        "created_at",
    }
    assert metadata_query.page_limit == 1
    assert metadata_query.page_offset == 0
    assert metadata_query.ordering == (("version_number", "DESC"),)
    assert metadata_query.filters == (("school_id", SCHOOL_ID), ("profile_ref", PROFILE_REF))
    assert owner.uow.audit.entries[-1]["action"] == "school_research_profiles.versions.list"
    assert owner.uow.audit.entries[-1]["safe_metadata"] == {
        "source": "school_research_profiles",
        "state": "READ",
    }


@pytest.mark.asyncio
async def test_profile_version_selector_is_not_queried_before_role_or_registry_check(
    monkeypatch,
) -> None:
    import types

    owner = _Owner(denied=True)
    owner._db_models = SimpleNamespace(SchoolResearchProfileVersion=_VersionModel)
    owner._select = lambda *columns: _QueryStatement(columns)
    owner.uow.session = _VersionQuerySession([])
    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        types.SimpleNamespace(func=SimpleNamespace(count=lambda: _QueryExpression("COUNT"))),
    )
    adapter = _adapter(owner)
    with pytest.raises(BackendError) as denied:
        await adapter.list_profile_versions(_actor(), "bad selector!", limit=30, offset=0)
    assert denied.value.code is ErrorCode.FORBIDDEN
    assert owner.events == ["role"]
    assert owner.uow.session.statements == []

    owner.denied = False
    with pytest.raises(BackendError) as unknown:
        await adapter.list_profile_versions(_actor(), "unregistered-ref", limit=30, offset=0)
    assert unknown.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert owner.events == ["role", "role"]
    assert owner.uow.session.statements == []


@pytest.mark.asyncio
async def test_list_accepts_actual_naive_utc_database_clock() -> None:
    owner = _Owner()
    actual_database_now = _repository_utc_now()
    assert actual_database_now.tzinfo is None
    owner._utc_now = lambda: actual_database_now
    adapter = _adapter(owner)

    await adapter.list_profiles(_actor())

    assert owner.role_times == [actual_database_now]


def _repository_utc_now() -> datetime:
    source = (
        Path(__file__).resolve().parents[2] / "11_database" / "database_layer" / "base.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "utc_now"
    )
    isolated = ast.Module(
        body=[
            ast.ImportFrom(
                module="datetime",
                names=[ast.alias(name="UTC"), ast.alias(name="datetime")],
                level=0,
            ),
            function,
        ],
        type_ignores=[],
    )
    namespace: dict[str, Any] = {}
    code = compile(ast.fix_missing_locations(isolated), "database_layer.base.utc_now", "exec")
    exec(code, namespace)
    return namespace["utc_now"]()


@pytest.mark.asyncio
async def test_import_creates_candidate_with_trusted_pins_audit_and_receipt_in_one_uow() -> None:
    owner = _Owner()
    catalog = _catalog()
    adapter = _adapter(owner, catalog)

    receipt = await adapter.import_profile(
        _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
    )

    assert receipt.profile_ref == PROFILE_REF
    assert receipt.version_number == VERSION
    assert receipt.catalog_state == "IMPORTED_CANDIDATE"
    assert receipt.rights_status == "PENDING"
    assert receipt.execution_status == "CANDIDATE_RESEARCH_ONLY"
    assert owner.events == ["role", "claim"]
    assert owner.role_times == [NOW.replace(tzinfo=None)]
    assert len(owner.repo.created) == 1
    values = owner.repo.created[0]
    assert values["school_id"] == SCHOOL_ID
    assert values["version_number"] == VERSION
    assert values["creator_membership_role_id"] == 9002
    assert values["expected_profile_sha256"] == PROFILE_SHA
    assert values["expected_manifest_sha256"] == MANIFEST_SHA
    assert values["rights_status"] == "PENDING"
    assert values["execution_status"] == "CANDIDATE_RESEARCH_ONLY"
    assert values["profile"].raw_profile_bytes == _profile_document()
    assert owner.completed == [
        {"resource_type": "school_research_profile_version", "result_ref": PROFILE_REF}
    ]
    assert len(owner.uow.audit.entries) == 1
    audit = owner.uow.audit.entries[0]
    assert audit["action"] == "school_research_profiles.import"
    assert audit["resource_public_id"] == PROFILE_REF
    assert audit["safe_metadata"] == {
        "source": "school_research_profiles",
        "state": "CANDIDATE_IMPORTED",
    }
    assert not ({"school_id", "profile_sha256", "manifest_sha256"} & set(asdict(receipt)))


@pytest.mark.asyncio
async def test_import_normalizes_offset_aware_time_to_naive_utc_for_database_role_query() -> None:
    owner = _Owner()
    adapter = _adapter(owner)
    offset_at = datetime(2026, 10, 14, 17, 0, tzinfo=timezone(timedelta(hours=8)))

    await adapter.import_profile(
        _actor(), PROFILE_REF, VERSION, at=offset_at, idempotency=_idempotency()
    )

    assert owner.role_times == [NOW.replace(tzinfo=None)]


@pytest.mark.asyncio
async def test_exact_existing_revoked_profile_is_returned_without_reactivation() -> None:
    owner = _Owner()
    existing = _metadata(rights_status="REVOKED", execution_status="DISABLED")
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = existing
    adapter = _adapter(owner)

    receipt = await adapter.import_profile(
        _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
    )

    assert receipt.rights_status == "REVOKED"
    assert receipt.execution_status == "DISABLED"
    assert receipt.catalog_state == "EXISTING_CANDIDATE"
    assert owner.repo.created == []
    assert owner.completed


@pytest.mark.asyncio
async def test_existing_mismatched_pins_conflict_without_receipt_or_audit() -> None:
    owner = _Owner()
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata(profile_sha256="d" * 64)
    adapter = _adapter(owner)

    with pytest.raises(BackendError) as raised:
        await adapter.import_profile(
            _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.completed == []
    assert owner.uow.audit.entries == []


@pytest.mark.asyncio
async def test_concurrent_exact_insert_winner_is_reloaded_without_mutating_status() -> None:
    owner = _Owner()
    owner.repo.fail_code = "RESEARCH_PERSISTENCE_CONFLICT"
    owner.repo.concurrent_winner = _metadata(rights_status="REVOKED", execution_status="DISABLED")
    adapter = _adapter(owner)

    receipt = await adapter.import_profile(
        _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
    )

    assert receipt.catalog_state == "EXISTING_CANDIDATE"
    assert receipt.rights_status == "REVOKED"
    assert receipt.execution_status == "DISABLED"
    assert owner.repo.created
    assert owner.completed


@pytest.mark.asyncio
async def test_replay_reauthorizes_and_verifies_exact_catalog_and_database_pins() -> None:
    owner = _Owner(replay=True, result_ref=PROFILE_REF)
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata()
    adapter = _adapter(owner)

    receipt = await adapter.import_profile(
        _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
    )

    assert owner.events == ["role", "claim"]
    assert receipt.catalog_state == "IDEMPOTENT_REPLAY"
    assert owner.repo.created == []
    assert owner.completed == []
    assert owner.uow.audit.entries == []


@pytest.mark.asyncio
async def test_replay_with_changed_registry_pin_is_rejected() -> None:
    owner = _Owner(replay=True, result_ref=PROFILE_REF)
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata(manifest_sha256="d" * 64)
    adapter = _adapter(owner)

    with pytest.raises(BackendError) as raised:
        await adapter.import_profile(
            _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_persisted_specialist_check_precedes_catalog_selector_and_source_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _Owner(denied=True)
    catalog = _catalog()
    events = owner.events
    original = SchoolResearchCatalog.select_profile

    def observed(self, *args, **kwargs):
        events.append("select_profile")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SchoolResearchCatalog, "select_profile", observed)
    adapter = SchoolResearchProfilesPersistenceAdapter(owner, catalog)

    with pytest.raises(BackendError) as raised:
        await adapter.import_profile(
            _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )

    assert raised.value.code is ErrorCode.FORBIDDEN
    assert events == ["role"]
    assert owner.repo.created == []


@pytest.mark.asyncio
async def test_wrong_role_and_foreign_school_fail_before_catalog_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _Owner()
    events = owner.events
    catalog = _catalog()
    original = SchoolResearchCatalog.select_profile

    def observed(self, *args, **kwargs):
        events.append("select_profile")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SchoolResearchCatalog, "select_profile", observed)
    adapter = SchoolResearchProfilesPersistenceAdapter(owner, catalog)

    with pytest.raises(BackendError) as wrong_role:
        await adapter.import_profile(
            _actor(BackendRole.ADMIN), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )
    assert wrong_role.value.code is ErrorCode.FORBIDDEN
    assert events == []

    foreign = Actor(
        user_id="USER_specialist01",
        username="specialist",
        role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=SCHOOL_ID + 1,
        school_ref="SCHOOL_other01",
        school_contexts=(
            SchoolRoleContext(
                context_id="9002",
                role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
                school_id=SCHOOL_ID + 1,
                school_ref="SCHOOL_other01",
            ),
        ),
    )
    with pytest.raises(BackendError) as foreign_scope:
        await adapter.import_profile(
            foreign, PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )
    assert foreign_scope.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert events == ["role"]


@pytest.mark.asyncio
async def test_bad_selector_version_and_naive_timestamp_are_rejected() -> None:
    adapter = _adapter()
    for profile_ref, version, at in (
        ("unknown-profile", VERSION, NOW),
        (PROFILE_REF, True, NOW),
        (PROFILE_REF, VERSION, datetime(2026, 10, 14, 9, 0)),
    ):
        with pytest.raises(BackendError):
            await adapter.import_profile(
                _actor(), profile_ref, version, at=at, idempotency=_idempotency()
            )


def test_view_dataclass_is_immutable_and_repr_omits_hashes_and_source_bytes() -> None:
    view = SchoolResearchProfileView(
        profile_ref=PROFILE_REF,
        version_number=VERSION,
        source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        research_only=True,
        publication_status="not_approved_for_publication_or_operational_use",
        rights_status="PENDING",
        execution_status="CANDIDATE_RESEARCH_ONLY",
        created_at=NOW,
        catalog_state="IMPORTED_CANDIDATE",
    )
    assert PROFILE_SHA not in repr(view)
    assert MANIFEST_SHA not in repr(view)
    with pytest.raises(FrozenInstanceError):
        view.version_number = 4


@pytest.mark.asyncio
async def test_enable_simulation_uses_policy_pins_repository_transition_receipt_and_audit(
    tmp_path: Path,
) -> None:
    owner = _Owner()
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata()
    policy, policy_sha = _study_use_policy(tmp_path)
    adapter = _adapter(
        owner,
        _catalog(),
        study_use_policy=policy,
        study_use_policy_sha256=policy_sha,
    )

    receipt = await adapter.enable_simulation(
        _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
    )

    assert owner.events == ["role", "claim"]
    assert owner.idempotency_calls == [
        (
            "opaque-key-01",
            fingerprint(
                {
                    "request_fingerprint": hashlib.sha256(b"request").hexdigest(),
                    "study_policy_sha256": policy_sha,
                }
            ),
            hashlib.sha256(b"scope").hexdigest(),
        )
    ]
    assert owner.repo.eligibility_changes == [{
        "school_id": SCHOOL_ID,
        "profile_ref": PROFILE_REF,
        "version_number": VERSION,
        "expected_profile_sha256": PROFILE_SHA,
        "status_actor_membership_role_id": 9002,
        "rights_status": "VERIFIED",
        "execution_status": "SIMULATION_ENABLED",
    }]
    assert owner.completed == [{
        "resource_type": "school_research_profile_version",
        "result_ref": PROFILE_REF,
    }]
    assert receipt.study_ref == "study:replay-01"
    assert receipt.policy_expires_at == datetime(2027, 6, 30, 23, 59, 59, tzinfo=UTC)
    assert receipt.research_only is True
    assert receipt.human_curated is False
    assert receipt.rights_status == "VERIFIED"
    assert receipt.execution_status == "SIMULATION_ENABLED"
    assert receipt.simulation_only is True
    assert receipt.clinical_approval is False
    assert receipt.ethics_approval is False
    assert receipt.psychometric_approval is False
    assert owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)].publication_status == (
        "not_approved_for_publication_or_operational_use"
    )
    audit = owner.uow.audit.entries[0]
    assert audit["action"] == "school_research_profiles.enable_simulation"
    assert audit["safe_metadata"] == {
        "schema_version": "psynova.research-study-use.v1",
        "component_version": policy_sha,
        "reason_code": "ISOLATED_HISTORICAL_REPLAY",
        "source": "school_research_profiles",
        "state": "SIMULATION_ENABLED",
    }


@pytest.mark.asyncio
async def test_activation_defaults_deny_without_policy_without_affecting_import(
    tmp_path: Path,
) -> None:
    owner = _Owner()
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata()
    adapter = _adapter(owner)

    with pytest.raises(BackendError) as denied:
        await adapter.enable_simulation(
            _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )
    assert denied.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert owner.events == ["role", "claim"]
    assert owner.repo.eligibility_changes == []
    assert owner.completed == []
    assert owner.uow.audit.entries == []

    import_adapter = _adapter(_Owner(), _catalog())
    imported = await import_adapter.import_profile(
        _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
    )
    assert imported.execution_status == "CANDIDATE_RESEARCH_ONLY"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rights, execution, revoked, disabled",
    [
        ("REVOKED", "DISABLED", NOW, NOW),
        ("PENDING", "DISABLED", None, NOW),
        ("VERIFIED", "SIMULATION_ENABLED", None, None),
    ],
)
async def test_activation_does_not_reactivate_revoked_disabled_or_already_enabled_version(
    tmp_path: Path, rights, execution, revoked, disabled
) -> None:
    owner = _Owner()
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata(
        rights_status=rights,
        execution_status=execution,
    )
    existing = owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)]
    existing.rights_revoked_at = revoked
    existing.disabled_at = disabled
    policy, policy_sha = _study_use_policy(tmp_path)
    adapter = _adapter(
        owner,
        _catalog(),
        study_use_policy=policy,
        study_use_policy_sha256=policy_sha,
    )

    with pytest.raises(BackendError) as denied:
        await adapter.enable_simulation(
            _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )
    assert denied.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert owner.repo.eligibility_changes == []
    assert owner.completed == []
    assert owner.uow.audit.entries == []


@pytest.mark.asyncio
async def test_activation_requires_exact_policy_school_profile_hash_and_crosswalk(
    tmp_path: Path,
) -> None:
    for school_id, policy_profile_sha, policy_crosswalk in (
        (SCHOOL_ID + 1, PROFILE_SHA, CROSSWALK_SHA),
        (SCHOOL_ID, "d" * 64, CROSSWALK_SHA),
        (SCHOOL_ID, PROFILE_SHA, "d" * 64),
    ):
        owner = _Owner()
        owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata()
        altered = {
                "schema": "psynova.research-study-use.v1",
                "study_ref": "study:replay-01",
                "school_id": school_id,
                "institution": "Synthetic institution declaration",
                "use_scope": "ISOLATED_HISTORICAL_REPLAY",
                "noncommercial": True,
                "historical_replay_only": True,
                "english_unchanged": True,
                "starts_at": "2026-10-14T00:00:00Z",
                "ends_at": "2027-06-30T23:59:59Z",
                "profiles": [{
                    "profile_ref": PROFILE_REF,
                    "profile_sha256": policy_profile_sha,
                    "manifest_sha256": MANIFEST_SHA,
                    "published_crosswalk_sha256": policy_crosswalk,
                }],
                "rights_basis": "Synthetic scoped research-use record.",
                "rights_source_urls": ["https://example.org/research-rights"],
                "recorded_by": "operator:synthetic-review",
                "recorded_at": "2026-10-14T00:00:00Z",
                "operator_declaration": "Server-pinned test policy.",
                "clinical_approval": False,
                "ethics_approval": False,
                "psychometric_approval": False,
        }
        path = tmp_path / f"policy-{school_id}-{policy_profile_sha[0]}-{policy_crosswalk[0]}.json"
        path.write_text(json.dumps(altered, separators=(",", ":")), encoding="utf-8")
        policy_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        policy = load_research_study_use_policy(
            path,
            expected_sha256=policy_sha,
            source_rights_verified=True,
            latest_allowed_ends_at=datetime(2027, 6, 30, 23, 59, 59, tzinfo=UTC),
        )
        adapter = _adapter(
            owner,
            _catalog(),
            study_use_policy=policy,
            study_use_policy_sha256=policy_sha,
        )
        with pytest.raises(BackendError) as denied:
            await adapter.enable_simulation(
                _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
            )
        assert denied.value.code in {ErrorCode.RESOURCE_NOT_FOUND, ErrorCode.WORKFLOW_CONFLICT}
        assert owner.repo.eligibility_changes == []
        assert owner.completed == []
        assert owner.uow.audit.entries == []


@pytest.mark.asyncio
async def test_expired_policy_and_repository_rejection_do_not_create_receipts_or_audit(
    tmp_path: Path,
) -> None:
    policy, policy_sha = _study_use_policy(tmp_path)
    expired_owner = _Owner()
    expired_owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata()
    expired_adapter = _adapter(
        expired_owner,
        _catalog(),
        study_use_policy=policy,
        study_use_policy_sha256=policy_sha,
    )
    with pytest.raises(BackendError) as expired:
        await expired_adapter.enable_simulation(
            _actor(),
            PROFILE_REF,
            VERSION,
            at=datetime(2028, 1, 1, tzinfo=UTC),
            idempotency=_idempotency(),
        )
    assert expired.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert expired_owner.repo.eligibility_changes == []
    assert expired_owner.completed == []
    assert expired_owner.uow.audit.entries == []

    rejected_owner = _Owner()
    rejected_owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = _metadata()
    rejected_owner.repo.eligibility_fail_code = "RESEARCH_PROFILE_NOT_ELIGIBLE"
    rejected_adapter = _adapter(
        rejected_owner,
        _catalog(),
        study_use_policy=policy,
        study_use_policy_sha256=policy_sha,
    )
    with pytest.raises(BackendError) as rejected:
        await rejected_adapter.enable_simulation(
            _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )
    assert rejected.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert len(rejected_owner.repo.eligibility_changes) == 1
    assert rejected_owner.completed == []
    assert rejected_owner.uow.audit.entries == []


@pytest.mark.asyncio
async def test_activation_replay_reauthorizes_and_never_mutates_again(tmp_path: Path) -> None:
    owner = _Owner(replay=True, result_ref=PROFILE_REF)
    metadata = _metadata(
        rights_status="VERIFIED",
        execution_status="SIMULATION_ENABLED",
    )
    metadata.simulation_enabled_at = NOW
    owner.repo.metadata[(SCHOOL_ID, PROFILE_REF, VERSION)] = metadata
    policy, policy_sha = _study_use_policy(tmp_path)
    adapter = _adapter(
        owner,
        _catalog(),
        study_use_policy=policy,
        study_use_policy_sha256=policy_sha,
    )

    receipt = await adapter.enable_simulation(
        _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
    )

    assert owner.events == ["role", "claim"]
    assert owner.repo.eligibility_changes == []
    assert owner.completed == []
    assert owner.uow.audit.entries == []
    assert receipt.catalog_state == "IDEMPOTENT_REPLAY"

    denied_owner = _Owner(denied=True, replay=True, result_ref=PROFILE_REF)
    denied_adapter = _adapter(
        denied_owner,
        _catalog(),
        study_use_policy=policy,
        study_use_policy_sha256=policy_sha,
    )
    with pytest.raises(BackendError) as denied:
        await denied_adapter.enable_simulation(
            _actor(), PROFILE_REF, VERSION, at=NOW, idempotency=_idempotency()
        )
    assert denied.value.code is ErrorCode.FORBIDDEN
    assert denied_owner.events == ["role"]
