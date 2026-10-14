from __future__ import annotations

import ast
import hashlib
import json
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
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research.catalog import (
    RepositoryResearchProfileInput,
    ResearchProfilePublicMetadata,
    ResearchProfileRepositoryProjection,
    ResearchProfileSelection,
    SchoolResearchCatalog,
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
        self.entries.append(kwargs)


class _ResearchRepo:
    def __init__(self) -> None:
        self.metadata: dict[tuple[int, str, int], Any] = {}
        self.created: list[dict[str, Any]] = []
        self.fail_code: str | None = None
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


class _Uow:
    def __init__(self, repo: _ResearchRepo) -> None:
        self.research_cat = repo
        self.audit = _Audit()


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


def _adapter(owner: _Owner | None = None, catalog: SchoolResearchCatalog | None = None):
    return SchoolResearchProfilesPersistenceAdapter(owner or _Owner(), catalog or _catalog())


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
