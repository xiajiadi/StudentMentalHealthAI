from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import Request
from pydantic import ValidationError

from smhai_backend.adapters.school_cat_assets import SchoolCatAssetsPersistenceAdapter
from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings, ModuleClientSettings
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.cat_assets.router import router as cat_assets_router
from smhai_backend.domains.cat_assets.schemas import (
    BankCreateRequest,
    BankPatchRequest,
    BankVersionRequest,
    PlanCreateRequest,
    PlanDetailDto,
    PlanVersionRequest,
)
from smhai_backend.domains.cat_assets.service import (
    MAX_ASSET_DOCUMENT_BYTES,
    SchoolCatAssetService,
)
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.integrations.cat_assets import CAT_ASSETS_TIMEOUT_SECONDS, HttpCatAssetsClient


def specialist(*, school_id: int = 7) -> Actor:
    school_ref = f"SCHOOL_{school_id}"
    role_context = SchoolRoleContext(
        context_id=f"ROLECAT_{school_id}",
        role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        school_id=school_id,
        school_ref=school_ref,
    )
    return Actor(
        user_id="USER_cat_specialist",
        username="cat-specialist",
        role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=school_id,
        school_ref=school_ref,
        school_contexts=(role_context,),
    )


def bank_document(*, item_id: str = "ITEM_demo_001", stem: str = "Synthetic item") -> dict:
    return {
        "item_bank_id": "ITEMBANK_demo_cat",
        "version": "demo.v1",
        "instrument_id": "CURRENT_SYNTHETIC_GRM",
        "target_population": "SYNTHETIC_STUDENT_DEMO",
        "measurement_model": "GRM",
        "dimensions": ["demo_trait"],
        "items": [
            {
                "item_id": item_id,
                "dimension": "demo_trait",
                "stem": stem,
                "response_type": "likert",
                "response_options": ["a", "b"],
                "scoring": {"a": 0, "b": 1},
                "model": "GRM",
                "parameters": {"a": 1.0, "thresholds": [0.0]},
                "source": "synthetic_fixture",
                "status": "synthetic",
            }
        ],
        "status": "draft",
        "metadata": {
            "synthetic": True,
            "intended_use": "engineering_test_only",
            "psychological_interpretation_allowed": False,
            "instrument_version": "synthetic_item_bank.v1 / demo.v1",
            "notice": "NOT FOR PSYCHOLOGICAL INTERPRETATION; DEMO / ENGINEERING USE ONLY",
            "psychometric_status": "PENDING_PSYCHOMETRIC_CONFIRMATION",
        },
    }


def config_document(*, version: str = "demo.cat.v1") -> dict:
    return {
        "config_version": version,
        "model": "GRM",
        "estimator": "EAP",
        "selection_method": "MFI",
        "min_items": 1,
        "max_items": 1,
        "se_threshold": 0.55,
        "initial_theta": 0.0,
        "prior_mean": 0.0,
        "prior_sd": 1.0,
        "optimization_interval": [-4.0, 4.0],
        "seed": 1234,
        "exposure_control": "none",
        "content_balancing": "none",
    }


def request_context() -> RequestContext:
    return RequestContext("REQ_asset_test", "TRACE_asset_test")


@pytest.mark.parametrize(
    "dto,body",
    [
        (BankCreateRequest, {"display_name": "Bank", "bank_document": {}, "extra": 1}),
        (BankPatchRequest, {"expected_revision": True, "display_name": "New"}),
        (BankVersionRequest, {"expected_revision": 1.0, "bank_document": {}}),
        (
            PlanCreateRequest,
            {
                "display_name": "Plan",
                "bank_version_ref": "CBVER_" + "a" * 36,
                "config_document": {},
                "seed": 1,
            },
        ),
        (
            PlanVersionRequest,
            {
                "expected_revision": "1",
                "bank_version_ref": "CBVER_" + "a" * 36,
                "config_document": {},
            },
        ),
    ],
)
def test_mutation_dtos_reject_unknown_fields_and_coercive_revision_values(dto, body):
    with pytest.raises(ValidationError):
        dto.model_validate(body, strict=True)


def test_plan_detail_only_accepts_plan_version_references():
    timestamp = "2026-10-12T00:00:00+00:00"
    plan = {
        "plan_ref": "CPLAN_" + str(uuid4()),
        "display_name": "Demo plan",
        "status": "ACTIVE",
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
        "versions": [
            {"version_ref": "CPVER_" + str(uuid4()), "version_number": 1, "created_at": timestamp}
        ],
    }
    assert PlanDetailDto.model_validate(plan).versions[0].version_ref.startswith("CPVER_")
    plan["versions"][0]["version_ref"] = "CBVER_" + str(uuid4())
    with pytest.raises(ValidationError):
        PlanDetailDto.model_validate(plan)


class Expr:
    def __init__(self, model, name):
        self.model = model
        self.name = name

    def __eq__(self, value):
        return (self.name, value)

    def desc(self):
        return (self.name, True)

    def asc(self):
        return (self.name, False)


class Column:
    def __init__(self, _type=None, **_kwargs):
        self.name = None

    def __set_name__(self, _owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return Expr(owner, self.name)
        return instance.__dict__.get(self.name)

    def __set__(self, instance, value):
        instance.__dict__[self.name] = value


class FakeModel:
    id = Column()
    public_id = Column()
    school_id = Column()
    created_at = Column()
    updated_at = Column()

    def __init__(self, **values):
        self.__dict__.update(values)


class Bank(FakeModel):
    display_name = Column()
    status = Column()
    revision = Column()
    creator_membership_role_id = Column()


class BankVersion(FakeModel):
    bank_id = Column()
    version_number = Column()
    creator_membership_role_id = Column()
    item_count = Column()
    dimension_count = Column()
    payload_ciphertext = Column()
    cipher_format_version = Column()
    key_version = Column()
    payload_schema_version = Column()


class Plan(FakeModel):
    display_name = Column()
    status = Column()
    revision = Column()
    creator_membership_role_id = Column()


class PlanVersion(FakeModel):
    plan_id = Column()
    version_number = Column()
    bank_version_id = Column()
    creator_membership_role_id = Column()
    payload_ciphertext = Column()
    cipher_format_version = Column()
    key_version = Column()
    payload_schema_version = Column()


class IdempotencyRecord(FakeModel):
    scope = Column()
    key_hash = Column()
    request_hash = Column()
    state = Column()
    expires_at = Column()
    result_resource_type = Column()
    result_public_id = Column()


class FakeIdempotencyState(StrEnum):
    COMPLETED = "COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"


class Query:
    def __init__(self, target):
        self.target = target
        self.predicates = []
        self.order = None
        self.offset_value = 0
        self.limit_value = None

    def where(self, *predicates):
        self.predicates.extend(predicates)
        return self

    def order_by(self, order):
        self.order = order
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def with_for_update(self):
        return self


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, backend):
        self.backend = backend
        self.pending = []

    def add(self, row):
        self.pending.append(row)

    async def flush(self):
        for row in self.pending:
            if row.id is None:
                row.id = self.backend.next_id
                self.backend.next_id += 1
                row.public_id = str(uuid4())
                now = datetime.now(UTC)
                row.created_at = now
                row.updated_at = now
                self.backend.rows.setdefault(type(row), []).append(row)
        self.pending.clear()

    def _select_rows(self, query):
        target = query.target
        model = target.model if isinstance(target, Expr) else target
        rows = list(self.backend.rows.get(model, []))
        for name, value in query.predicates:
            rows = [row for row in rows if getattr(row, name) == value]
        if query.order:
            name, reverse = query.order
            rows.sort(key=lambda row: getattr(row, name), reverse=reverse)
        rows = rows[query.offset_value :]
        if query.limit_value is not None:
            rows = rows[: query.limit_value]
        return rows

    async def scalar(self, query):
        rows = self._select_rows(query)
        if isinstance(query.target, Expr):
            return getattr(rows[0], query.target.name) if rows else None
        return rows[0] if rows else None

    async def scalars(self, query):
        return ScalarRows(self._select_rows(query))


class FakeProtection:
    cipher_format_version = "fernet.v1"

    def encrypt_json(self, payload, *, payload_schema_version):
        clear = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()
        return SimpleNamespace(
            ciphertext=b"encrypted:" + clear.hex().encode(),
            key_version="test-key-v1",
            cipher_format_version=self.cipher_format_version,
            payload_schema_version=payload_schema_version,
        )

    def decrypt_json(self, encrypted):
        if not encrypted.ciphertext.startswith(b"encrypted:"):
            raise ValueError("ciphertext unavailable")
        clear = bytes.fromhex(encrypted.ciphertext.removeprefix(b"encrypted:").decode())
        return json.loads(clear)


@dataclass
class FakeReceipt:
    result_resource_type: str | None = None
    result_public_id: str | None = None
    request_hash: str | None = None
    state: str = "IN_PROGRESS"


@dataclass
class FakeClaim:
    record: FakeReceipt
    replayed: bool


class FakeAudit:
    def __init__(self, backend):
        self.backend = backend

    async def append(self, **event):
        self.backend.events.append(("audit", event))
        if self.backend.audit_failure:
            raise RuntimeError("fake audit failure")


class FakeUow:
    def __init__(self, backend):
        self.backend = backend
        self.session = FakeSession(backend)
        self.protection = backend.protection
        self.audit = FakeAudit(backend)
        self.snapshot = None

    async def __aenter__(self):
        self.snapshot = deepcopy(
            (self.backend.rows, self.backend.idempotency, self.backend.next_id)
        )
        self.backend.events.append(("uow_open",))
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        if exc_type is not None:
            self.backend.rows, self.backend.idempotency, self.backend.next_id = self.snapshot
            self.backend.events.append(("rollback",))
        else:
            self.backend.events.append(("commit",))
        self.backend.events.append(("uow_close",))


class FakePersistence:
    identity_profile = "school_tenant"
    _select = staticmethod(lambda target: Query(target))
    _db_models = SimpleNamespace(
        SchoolCatItemBank=Bank,
        SchoolCatItemBankVersion=BankVersion,
        SchoolCatPlan=Plan,
        SchoolCatPlanVersion=PlanVersion,
        IdempotencyRecord=IdempotencyRecord,
    )
    _db_enums = SimpleNamespace(
        AuditResult=SimpleNamespace(SUCCESS="SUCCESS"),
        IdempotencyState=FakeIdempotencyState,
    )

    def __init__(self, *, deny_call=None):
        self.rows = {}
        self.idempotency = {}
        self.next_id = 1
        self.events = []
        self.role_checks = 0
        self.deny_call = deny_call
        self.audit_failure = False
        self.protection = FakeProtection()

    def _uow(self):
        return FakeUow(self)

    def _utc_now(self):
        return datetime.now(UTC)

    async def _school_actor_role(self, _uow, actor, role_code, _at):
        self.role_checks += 1
        self.events.append(("role", role_code, self.role_checks, actor.school_id))
        if self.role_checks == self.deny_call:
            raise BackendError(ErrorCode.FORBIDDEN, detail="access denied")
        return 11, 22

    async def _school_idempotency_begin(self, uow, idempotency):
        key, request_hash, scope = idempotency
        lookup = (scope, key)
        record = self.idempotency.get(lookup)
        if record is not None:
            if record.request_hash != bytes.fromhex(request_hash):
                raise BackendError(ErrorCode.WORKFLOW_CONFLICT, detail="idempotency conflict")
            return FakeClaim(record, record.state == "COMPLETED")
        record = IdempotencyRecord(
            scope=scope,
            key_hash=hashlib.sha256(key.encode()).digest(),
            request_hash=bytes.fromhex(request_hash),
            state="IN_PROGRESS",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        uow.session.add(record)
        await uow.session.flush()
        self.idempotency[lookup] = record
        return FakeClaim(record, False)

    async def _school_idempotency_complete(self, _uow, claim, *, resource_type, result_ref):
        claim.record.result_resource_type = resource_type
        claim.record.result_public_id = result_ref
        claim.record.state = "COMPLETED"


class FakeAssetsClient:
    def __init__(self, backend):
        self.backend = backend

    async def template(self, *, context):
        self.backend.events.append(("template", context.trace_id))
        return {
            "engineering_only": True,
            "psychological_interpretation_allowed": False,
            "bank_document": bank_document(),
            "config_document": config_document(),
            "item_count": 1,
            "dimension_count": 1,
        }

    async def validate_assets(self, bank_doc, config_doc, *, context):
        self.backend.events.append(("validate", context.trace_id))
        if bank_doc.get("status") not in {"draft", "published"}:
            raise BackendError(ErrorCode.VALIDATION_FAILED, detail="asset invalid")
        return {
            "engineering_only": True,
            "psychological_interpretation_allowed": False,
            "bank_document": bank_doc,
            "config_document": config_doc,
            "item_count": len(bank_doc["items"]),
            "dimension_count": len(bank_doc["dimensions"]),
        }


def adapter_for(backend: FakePersistence, client=None):
    return SchoolCatAssetsPersistenceAdapter(backend, client or FakeAssetsClient(backend))


class CountingAssetsClient(FakeAssetsClient):
    def __init__(self, backend):
        super().__init__(backend)
        self.validation_calls = 0

    async def validate_assets(self, bank_doc, config_doc, *, context):
        self.validation_calls += 1
        return await super().validate_assets(bank_doc, config_doc, context=context)


def idem(key: str, operation: str, request_hash: str = "a" * 64):
    return key, request_hash, f"school:7:{operation}"


def install_encrypted_payload_module(monkeypatch):
    package = ModuleType("database_layer")
    crypto = ModuleType("database_layer.crypto")

    @dataclass
    class EncryptedPayload:
        ciphertext: bytes
        key_version: str
        cipher_format_version: str
        payload_schema_version: str

    crypto.EncryptedPayload = EncryptedPayload
    package.crypto = crypto
    monkeypatch.setitem(sys.modules, "database_layer", package)
    monkeypatch.setitem(sys.modules, "database_layer.crypto", crypto)


@pytest.mark.asyncio
async def test_school_bank_versions_encrypt_payload_preserve_history_and_idempotency(monkeypatch):
    install_encrypted_payload_module(monkeypatch)
    backend = FakePersistence()
    adapter = adapter_for(backend)
    actor = specialist()
    first_document = bank_document(stem="Private synthetic item body")

    created = await adapter.school_cat_assets_create_bank(
        actor,
        "Demo bank",
        first_document,
        item_count=1,
        dimension_count=1,
        idempotency=idem("bank-create-1", "create_bank"),
        trace_id="TRACE_test",
    )
    bank_ref = created["bank"]["bank_ref"]
    first_version_ref = created["version_ref"]
    version_row = backend.rows[BankVersion][0]
    assert b"Private synthetic item body" not in version_row.payload_ciphertext
    assert version_row.payload_schema_version == "school_cat_bank_document.v1"
    assert created["bank"]["versions"][0]["version_ref"] == first_version_ref

    replay = await adapter.school_cat_assets_replay(actor, idem("bank-create-1", "create_bank"))
    assert replay is not None
    assert replay["version_ref"] == first_version_ref

    retry = await adapter.school_cat_assets_create_bank(
        actor,
        "Demo bank",
        first_document,
        item_count=1,
        dimension_count=1,
        idempotency=idem("bank-create-1", "create_bank"),
        trace_id="TRACE_test",
    )
    assert retry["version_ref"] == first_version_ref
    assert len(backend.rows[Bank]) == 1
    assert len(backend.rows[BankVersion]) == 1

    opened = await adapter.school_cat_assets_get_bank_version(actor, first_version_ref)
    assert opened["bank_document"] == first_document

    second_document = bank_document(item_id="ITEM_demo_002", stem="Second version")
    second = await adapter.school_cat_assets_create_bank_version(
        actor,
        bank_ref,
        1,
        second_document,
        item_count=1,
        dimension_count=1,
        idempotency=idem("bank-version-2", "create_bank_version"),
        trace_id="TRACE_test",
    )
    assert second["bank"]["revision"] == 2
    assert second["version_ref"] != first_version_ref
    assert len(backend.rows[BankVersion]) == 2
    assert (await adapter.school_cat_assets_get_bank_version(actor, first_version_ref))[
        "bank_document"
    ] == first_document


@pytest.mark.asyncio
async def test_expected_revision_cross_school_archive_and_audit_failure_roll_back(monkeypatch):
    install_encrypted_payload_module(monkeypatch)
    backend = FakePersistence()
    adapter = adapter_for(backend)
    actor = specialist()
    created = await adapter.school_cat_assets_create_bank(
        actor,
        "Demo",
        bank_document(),
        item_count=1,
        dimension_count=1,
        idempotency=idem("create", "create_bank"),
        trace_id="TRACE_test",
    )
    bank_ref = created["bank"]["bank_ref"]

    with pytest.raises(BackendError) as stale:
        await adapter.school_cat_assets_patch_bank(
            actor,
            bank_ref,
            expected_revision=99,
            display_name="Stale",
            status=None,
            idempotency=idem("stale-patch", "patch_bank"),
            trace_id="TRACE_test",
        )
    assert stale.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert len(backend.rows[BankVersion]) == 1

    with pytest.raises(BackendError) as cross_school:
        await adapter.school_cat_assets_get_bank(specialist(school_id=8), bank_ref)
    assert cross_school.value.code is ErrorCode.RESOURCE_NOT_FOUND

    await adapter.school_cat_assets_patch_bank(
        actor,
        bank_ref,
        expected_revision=1,
        display_name=None,
        status="ARCHIVED",
        idempotency=idem("archive", "patch_bank"),
        trace_id="TRACE_test",
    )
    with pytest.raises(BackendError) as archived:
        await adapter.school_cat_assets_create_bank_version(
            actor,
            bank_ref,
            2,
            bank_document(item_id="ITEM_demo_003"),
            item_count=1,
            dimension_count=1,
            idempotency=idem("archived-version", "create_version"),
            trace_id="TRACE_test",
        )
    assert archived.value.code is ErrorCode.WORKFLOW_CONFLICT

    bank = backend.rows[Bank][0]
    before = (bank.revision, bank.display_name, len(backend.events))
    backend.audit_failure = True
    with pytest.raises(RuntimeError, match="fake audit failure"):
        await adapter.school_cat_assets_patch_bank(
            actor,
            bank_ref,
            expected_revision=2,
            display_name="Should roll back",
            status=None,
            idempotency=idem("audit-fail", "patch_bank"),
            trace_id="TRACE_test",
        )
    bank_after = backend.rows[Bank][0]
    assert (bank_after.revision, bank_after.display_name) == before[:2]
    assert ("rollback",) in backend.events[before[2] :]


@pytest.mark.asyncio
async def test_plan_version_binds_exact_school_bank_version_and_returns_only_its_config(
    monkeypatch,
):
    install_encrypted_payload_module(monkeypatch)
    backend = FakePersistence()
    adapter = adapter_for(backend)
    actor = specialist()
    bank_result = await adapter.school_cat_assets_create_bank(
        actor,
        "Bank",
        bank_document(),
        item_count=1,
        dimension_count=1,
        idempotency=idem("create-bank", "create_bank"),
        trace_id="TRACE_test",
    )
    config_v1 = config_document(version="plan.v1")
    plan_result = await adapter.school_cat_assets_create_plan(
        actor,
        "Plan",
        bank_result["version_ref"],
        config_v1,
        idempotency=idem("create-plan", "create_plan"),
        trace_id="TRACE_test",
    )
    version_ref = plan_result["version_ref"]
    assert backend.rows[PlanVersion][0].bank_version_id == backend.rows[BankVersion][0].id
    opened = await adapter.school_cat_assets_get_plan_version(actor, version_ref)
    assert opened["bank_version_ref"] == bank_result["version_ref"]
    assert opened["config_document"] == config_v1

    config_v2 = config_document(version="plan.v2")
    revised = await adapter.school_cat_assets_create_plan_version(
        actor,
        plan_result["plan"]["plan_ref"],
        1,
        bank_result["version_ref"],
        config_v2,
        idempotency=idem("plan-version-2", "new_plan_version"),
        trace_id="TRACE_test",
    )
    assert revised["plan"]["revision"] == 2
    assert (await adapter.school_cat_assets_get_plan_version(actor, version_ref))[
        "config_document"
    ] == config_v1


@pytest.mark.asyncio
async def test_authoring_preflight_denies_bad_scope_state_and_revision_before_cat(monkeypatch):
    install_encrypted_payload_module(monkeypatch)
    backend = FakePersistence()
    cat_client = CountingAssetsClient(backend)
    persistence = adapter_for(backend, cat_client)
    service = SchoolCatAssetService(persistence=persistence)
    actor = specialist()
    other_school = specialist(school_id=8)
    bank_result = await persistence.school_cat_assets_create_bank(
        actor,
        "Bank",
        bank_document(),
        item_count=1,
        dimension_count=1,
        idempotency=idem("preflight-bank", "create_bank"),
        trace_id="TRACE_test",
    )
    bank_ref = bank_result["bank"]["bank_ref"]
    bank_version_ref = bank_result["version_ref"]

    async def denied_without_validation(call, expected_code):
        validation_count = cat_client.validation_calls
        with pytest.raises(BackendError) as rejected:
            await call
        assert rejected.value.code is expected_code
        assert cat_client.validation_calls == validation_count

    bank_version_payload = {
        "expected_revision": 1,
        "bank_document": bank_document(item_id="ITEM_demo_next"),
    }
    await denied_without_validation(
        service.create_bank_version(
            actor,
            "CBANK_" + str(uuid4()),
            payload=bank_version_payload,
            idempotency=idem("missing-bank-version-target", "new_bank_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.RESOURCE_NOT_FOUND,
    )
    await denied_without_validation(
        service.create_bank_version(
            other_school,
            bank_ref,
            payload=bank_version_payload,
            idempotency=idem("cross-school-bank-version-target", "new_bank_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.RESOURCE_NOT_FOUND,
    )
    await denied_without_validation(
        service.create_bank_version(
            actor,
            bank_ref,
            payload={**bank_version_payload, "expected_revision": 88},
            idempotency=idem("stale-bank-version-target", "new_bank_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.WORKFLOW_CONFLICT,
    )

    plan_payload = {
        "display_name": "Plan",
        "bank_version_ref": bank_version_ref,
        "config_document": config_document(),
    }
    missing_bank_version = "CBVER_" + str(uuid4())
    await denied_without_validation(
        service.create_plan(
            actor,
            payload={**plan_payload, "bank_version_ref": missing_bank_version},
            idempotency=idem("missing-plan-bank-version", "create_plan"),
            trace_id="TRACE_test",
        ),
        ErrorCode.RESOURCE_NOT_FOUND,
    )
    await denied_without_validation(
        service.create_plan(
            other_school,
            payload=plan_payload,
            idempotency=idem("cross-school-plan-bank-version", "create_plan"),
            trace_id="TRACE_test",
        ),
        ErrorCode.RESOURCE_NOT_FOUND,
    )

    plan_result = await persistence.school_cat_assets_create_plan(
        actor,
        "Plan",
        bank_version_ref,
        config_document(),
        idempotency=idem("preflight-plan", "create_plan"),
        trace_id="TRACE_test",
    )
    plan_ref = plan_result["plan"]["plan_ref"]
    plan_version_payload = {
        "expected_revision": 1,
        "bank_version_ref": bank_version_ref,
        "config_document": config_document(version="next"),
    }
    await denied_without_validation(
        service.create_plan_version(
            actor,
            "CPLAN_" + str(uuid4()),
            payload=plan_version_payload,
            idempotency=idem("missing-plan-version-target", "new_plan_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.RESOURCE_NOT_FOUND,
    )
    await denied_without_validation(
        service.create_plan_version(
            other_school,
            plan_ref,
            payload=plan_version_payload,
            idempotency=idem("cross-school-plan-version-target", "new_plan_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.RESOURCE_NOT_FOUND,
    )
    await denied_without_validation(
        service.create_plan_version(
            actor,
            plan_ref,
            payload={**plan_version_payload, "expected_revision": 88},
            idempotency=idem("stale-plan-version-target", "new_plan_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.WORKFLOW_CONFLICT,
    )
    await denied_without_validation(
        service.create_plan_version(
            actor,
            plan_ref,
            payload={
                **plan_version_payload,
                "bank_version_ref": "CBVER_" + str(uuid4()),
            },
            idempotency=idem("missing-plan-version-bank", "new_plan_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.RESOURCE_NOT_FOUND,
    )

    await persistence.school_cat_assets_patch_plan(
        actor,
        plan_ref,
        expected_revision=1,
        display_name=None,
        status="ARCHIVED",
        idempotency=idem("archive-plan-preflight", "patch_plan"),
        trace_id="TRACE_test",
    )
    await denied_without_validation(
        service.create_plan_version(
            actor,
            plan_ref,
            payload={**plan_version_payload, "expected_revision": 2},
            idempotency=idem("archived-plan-version-target", "new_plan_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.WORKFLOW_CONFLICT,
    )
    await persistence.school_cat_assets_patch_plan(
        actor,
        plan_ref,
        expected_revision=2,
        display_name=None,
        status="ACTIVE",
        idempotency=idem("reactivate-plan-preflight", "patch_plan"),
        trace_id="TRACE_test",
    )

    await persistence.school_cat_assets_patch_bank(
        actor,
        bank_ref,
        expected_revision=1,
        display_name=None,
        status="ARCHIVED",
        idempotency=idem("archive-bank-preflight", "patch_bank"),
        trace_id="TRACE_test",
    )
    await denied_without_validation(
        service.create_bank_version(
            actor,
            bank_ref,
            payload={**bank_version_payload, "expected_revision": 2},
            idempotency=idem("archived-bank-version-target", "new_bank_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.WORKFLOW_CONFLICT,
    )
    await denied_without_validation(
        service.create_plan(
            actor,
            payload=plan_payload,
            idempotency=idem("archived-plan-bank", "create_plan"),
            trace_id="TRACE_test",
        ),
        ErrorCode.WORKFLOW_CONFLICT,
    )
    await denied_without_validation(
        service.create_plan_version(
            actor,
            plan_ref,
            payload={**plan_version_payload, "expected_revision": 3},
            idempotency=idem("archived-plan-version-bank", "new_plan_version"),
            trace_id="TRACE_test",
        ),
        ErrorCode.WORKFLOW_CONFLICT,
    )


@pytest.mark.asyncio
async def test_authoring_write_rechecks_revision_after_successful_preflight(monkeypatch):
    install_encrypted_payload_module(monkeypatch)
    backend = FakePersistence()
    cat_client = CountingAssetsClient(backend)
    adapter = adapter_for(backend, cat_client)
    actor = specialist()
    bank_result = await adapter.school_cat_assets_create_bank(
        actor,
        "Bank",
        bank_document(),
        item_count=1,
        dimension_count=1,
        idempotency=idem("race-bank", "create_bank"),
        trace_id="TRACE_test",
    )

    class RevisionRace:
        def __getattr__(self, name):
            return getattr(adapter, name)

        async def school_cat_assets_preflight_bank_version(self, *args):
            await adapter.school_cat_assets_preflight_bank_version(*args)
            backend.rows[Bank][0].revision += 1

    service = SchoolCatAssetService(persistence=RevisionRace())
    with pytest.raises(BackendError) as raced:
        await service.create_bank_version(
            actor,
            bank_result["bank"]["bank_ref"],
            payload={
                "expected_revision": 1,
                "bank_document": bank_document(item_id="ITEM_after_race"),
            },
            idempotency=idem("race-bank-version", "new_bank_version"),
            trace_id="TRACE_test",
        )
    assert raced.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert cat_client.validation_calls == 1
    assert len(backend.rows[BankVersion]) == 1


@pytest.mark.asyncio
async def test_new_plan_write_rechecks_bank_state_after_successful_preflight(monkeypatch):
    install_encrypted_payload_module(monkeypatch)
    backend = FakePersistence()
    cat_client = CountingAssetsClient(backend)
    adapter = adapter_for(backend, cat_client)
    actor = specialist()
    bank_result = await adapter.school_cat_assets_create_bank(
        actor,
        "Bank",
        bank_document(),
        item_count=1,
        dimension_count=1,
        idempotency=idem("archive-race-bank", "create_bank"),
        trace_id="TRACE_test",
    )

    class ArchiveRace:
        def __getattr__(self, name):
            return getattr(adapter, name)

        async def school_cat_assets_preflight_plan(self, *args):
            await adapter.school_cat_assets_preflight_plan(*args)
            backend.rows[Bank][0].status = "ARCHIVED"

    service = SchoolCatAssetService(persistence=ArchiveRace())
    with pytest.raises(BackendError) as raced:
        await service.create_plan(
            actor,
            payload={
                "display_name": "Plan",
                "bank_version_ref": bank_result["version_ref"],
                "config_document": config_document(),
            },
            idempotency=idem("archive-race-plan", "create_plan"),
            trace_id="TRACE_test",
        )
    assert raced.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert cat_client.validation_calls == 1
    assert backend.rows.get(Plan, []) == []


@pytest.mark.asyncio
async def test_role_is_rechecked_after_network_and_access_audit_has_no_asset_content():
    backend = FakePersistence(deny_call=2)
    adapter = adapter_for(backend)
    with pytest.raises(BackendError) as denied:
        await adapter.school_cat_assets_template(specialist())
    assert denied.value.code is ErrorCode.FORBIDDEN
    assert [event[0] for event in backend.events if event[0] in {"role", "template", "audit"}] == [
        "role",
        "template",
        "role",
    ]
    assert not any(event[0] == "audit" for event in backend.events)

    backend = FakePersistence()
    adapter = adapter_for(backend)
    result = await adapter.school_cat_assets_template(specialist())
    assert result["item_count"] == 1
    assert [event[0] for event in backend.events if event[0] in {"role", "template", "audit"}] == [
        "role",
        "template",
        "role",
        "audit",
    ]
    audit = next(event[1] for event in backend.events if event[0] == "audit")
    assert audit["safe_metadata"] == {"source": "school_cat_assets", "state": "SUCCESS"}
    assert "bank_document" not in repr(audit) and "Synthetic item" not in repr(audit)


@pytest.mark.asyncio
async def test_service_denies_non_specialist_and_enforces_document_size():
    class NeverCalled:
        async def school_cat_assets_validate(self, *_args, **_kwargs):
            raise AssertionError("validation must not be called")

    service = SchoolCatAssetService(persistence=NeverCalled())
    for role in (BackendRole.STUDENT, BackendRole.TEACHER, BackendRole.ADMIN):
        actor = Actor(
            user_id=f"USER_{role.value.lower()}",
            username=role.value.lower(),
            role=role,
            subject_id="SUBJ_demo" if role is BackendRole.STUDENT else None,
            scope_profile="school_tenant",
            school_id=7,
            school_ref="SCHOOL_7",
        )
        with pytest.raises(BackendError) as denied:
            await service.template(actor)
        assert denied.value.code is ErrorCode.FORBIDDEN
    with pytest.raises(BackendError) as too_large:
        service._bounded_document(
            {"content": "x" * MAX_ASSET_DOCUMENT_BYTES}, field="bank_document"
        )
    assert too_large.value.code is ErrorCode.VALIDATION_FAILED


@pytest.mark.asyncio
async def test_service_persists_only_validator_returned_documents_and_fails_closed():
    events = []

    class Persistence:
        async def school_cat_assets_validate(self, _actor, bank_doc, *, config_document):
            events.append("validated")
            assert config_document is None
            return {
                "bank_document": {**bank_doc, "version": "validated.v2"},
                "config_document": None,
                "item_count": 1,
                "dimension_count": 1,
            }

        async def school_cat_assets_create_bank(self, _actor, _name, document, **kwargs):
            events.append(("stored", document, kwargs))
            return {"version_ref": "CBVER_" + "a" * 36}

    service = SchoolCatAssetService(persistence=Persistence())
    result = await service.create_bank(
        specialist(),
        payload={"display_name": "Bank", "bank_document": bank_document()},
        idempotency=("key", "hash", "scope"),
        trace_id="TRACE_test",
    )
    assert result["version_ref"].startswith("CBVER_")
    assert events[0] == "validated"
    assert events[1][0] == "stored"
    assert events[1][1]["version"] == "validated.v2"
    assert events[1][2]["item_count"] == 1

    class RejectingPersistence(Persistence):
        async def school_cat_assets_validate(self, *_args, **_kwargs):
            raise BackendError(ErrorCode.VALIDATION_FAILED, detail="asset invalid")

        async def school_cat_assets_create_bank(self, *_args, **_kwargs):
            raise AssertionError("invalid document must not be persisted")

    rejecting = SchoolCatAssetService(persistence=RejectingPersistence())
    with pytest.raises(BackendError) as invalid:
        await rejecting.create_bank(
            specialist(),
            payload={"display_name": "Bank", "bank_document": bank_document()},
            idempotency=("key2", "hash2", "scope"),
            trace_id="TRACE_test",
        )
    assert invalid.value.code is ErrorCode.VALIDATION_FAILED


@pytest.mark.asyncio
async def test_completed_idempotent_replay_skips_external_validator_but_resolves_scope():
    result = {"engineering_only": True, "version_ref": "CBVER_" + "a" * 36}
    calls = []

    class Persistence:
        async def school_cat_assets_replay(self, actor, idempotency):
            calls.append(("replay", actor.school_id, idempotency[0]))
            return result

        async def school_cat_assets_validate(self, *_args, **_kwargs):
            raise AssertionError("completed replay must not invoke CAT validation")

        async def school_cat_assets_create_bank(self, *_args, **_kwargs):
            raise AssertionError("completed replay must not create another bank")

    service = SchoolCatAssetService(persistence=Persistence())
    actual = await service.create_bank(
        specialist(),
        payload={"display_name": "Bank", "bank_document": bank_document()},
        idempotency=("stable-key", "a" * 64, "school-scope"),
        trace_id="TRACE_test",
    )
    assert actual is result
    assert calls == [("replay", 7, "stable-key")]


@pytest.mark.asyncio
async def test_http_client_uses_30_second_budget_and_sanitizes_internal_errors():
    seen = []

    async def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(422, json={"detail": "private item text"})

    client = HttpCatAssetsClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.client.timeout.read == CAT_ASSETS_TIMEOUT_SECONDS == 30.0
        with pytest.raises(BackendError) as invalid:
            await client.validate_assets(
                bank_document(), config_document(), context=request_context()
            )
        assert invalid.value.code is ErrorCode.VALIDATION_FAILED
        assert "private item text" not in invalid.value.detail
        assert seen[0].headers["X-Trace-ID"] == "TRACE_asset_test"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_http_client_reads_template_and_round_trips_validated_assets():
    seen = []
    expected_bank = bank_document()
    expected_config = config_document()

    async def handler(request: httpx.Request):
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "engineering_only": True,
                    "psychological_interpretation_allowed": False,
                    "bank_document": expected_bank,
                    "config_document": expected_config,
                    "item_count": 1,
                    "dimension_count": 1,
                },
            )
        request_body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "engineering_only": True,
                "psychological_interpretation_allowed": False,
                "bank_document": request_body["bank_document"],
                "config_document": request_body["config_document"],
                "item_count": 1,
                "dimension_count": 1,
            },
        )

    client = HttpCatAssetsClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(handler),
    )
    try:
        template = await client.template(context=request_context())
        assert template["bank_document"] == expected_bank
        result = await client.validate_assets(
            expected_bank, expected_config, context=request_context()
        )
        assert result["config_document"] == expected_config
        assert seen[0].url.path == "/internal/cat/management/template"
        assert seen[1].url.path == "/internal/cat/management/validate-assets"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_http_client_maps_validator_transport_failure_and_timeout_to_gateway_errors():
    async def unavailable(_request: httpx.Request):
        return httpx.Response(503, json={"detail": "private validator trace"})

    client = HttpCatAssetsClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(unavailable),
    )
    try:
        with pytest.raises(BackendError) as failed:
            await client.template(context=request_context())
        assert failed.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
        assert failed.value.status_code == 502
        assert "private validator trace" not in failed.value.detail
    finally:
        await client.close()

    async def timeout(_request: httpx.Request):
        raise httpx.ReadTimeout("private timeout detail")

    client = HttpCatAssetsClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(timeout),
    )
    try:
        with pytest.raises(BackendError) as timed_out:
            await client.template(context=request_context())
        assert timed_out.value.code is ErrorCode.DEPENDENCY_TIMEOUT
        assert timed_out.value.status_code == 504
        assert "private timeout detail" not in timed_out.value.detail
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_routes_hidden_from_frozen_openapi_and_post_uses_csrf(client):
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert login.status_code == 200
    csrf = login.json()["data"]["csrf_token"]
    with_csrf = await client.post(
        "/api/v1/school/cat-assets/banks",
        json={"display_name": "A bank", "bank_document": bank_document()},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "student-denied"},
    )
    without_csrf = await client.post(
        "/api/v1/school/cat-assets/banks",
        json={"display_name": "A bank", "bank_document": bank_document()},
    )
    assert with_csrf.status_code == 403
    assert with_csrf.json()["code"] == "forbidden"
    assert without_csrf.status_code == 403
    assert without_csrf.json()["code"] == "csrf_failed"

    app = create_app(settings=BackendSettings(environment="test", docs_enabled=True))
    included = [
        route
        for route in app.router.routes
        if getattr(route, "original_router", None) is cat_assets_router
    ]
    assert len(included) == 1
    assert included[0].include_context.include_in_schema is False
    assert all("cat-assets" not in path for path in app.openapi()["paths"])


@pytest.mark.asyncio
async def test_create_bank_and_plan_return_201_including_idempotent_replay(client, app):
    now = "2026-10-12T00:00:00+00:00"
    bank_ref = "CBANK_" + str(uuid4())
    bank_version_ref = "CBVER_" + str(uuid4())
    plan_ref = "CPLAN_" + str(uuid4())
    plan_version_ref = "CPVER_" + str(uuid4())
    bank_result = {
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "bank": {
            "bank_ref": bank_ref,
            "display_name": "Demo bank",
            "status": "ACTIVE",
            "revision": 1,
            "created_at": now,
            "updated_at": now,
            "versions": [
                {
                    "version_ref": bank_version_ref,
                    "version_number": 1,
                    "created_at": now,
                    "item_count": 1,
                    "dimension_count": 1,
                }
            ],
        },
        "version_ref": bank_version_ref,
    }
    plan_result = {
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "plan": {
            "plan_ref": plan_ref,
            "display_name": "Demo plan",
            "status": "ACTIVE",
            "revision": 1,
            "created_at": now,
            "updated_at": now,
            "versions": [
                {
                    "version_ref": plan_version_ref,
                    "version_number": 1,
                    "created_at": now,
                }
            ],
        },
        "version_ref": plan_version_ref,
    }

    class ReplayService:
        def __init__(self):
            self.keys = []

        async def create_bank(self, _actor, *, idempotency, **_kwargs):
            self.keys.append(idempotency[0])
            return bank_result

        async def create_plan(self, _actor, *, idempotency, **_kwargs):
            self.keys.append(idempotency[0])
            return plan_result

        async def create_bank_version(self, _actor, _bank_ref, *, idempotency, **_kwargs):
            self.keys.append(idempotency[0])
            return bank_result

        async def create_plan_version(self, _actor, _plan_ref, *, idempotency, **_kwargs):
            self.keys.append(idempotency[0])
            return plan_result

    service = ReplayService()
    app.state.container.cat_assets = service

    async def authenticated_specialist(request: Request):
        request.state.session = SimpleNamespace(csrf_token="route-csrf-token")
        return specialist()

    app.dependency_overrides[current_actor] = authenticated_specialist
    headers = {"X-CSRF-Token": "route-csrf-token"}
    bank_payload = {"display_name": "Demo bank", "bank_document": bank_document()}
    first_bank = await client.post(
        "/api/v1/school/cat-assets/banks",
        json=bank_payload,
        headers={**headers, "Idempotency-Key": "stable-bank-create"},
    )
    replayed_bank = await client.post(
        "/api/v1/school/cat-assets/banks",
        json=bank_payload,
        headers={**headers, "Idempotency-Key": "stable-bank-create"},
    )
    plan_payload = {
        "display_name": "Demo plan",
        "bank_version_ref": bank_version_ref,
        "config_document": config_document(),
    }
    first_plan = await client.post(
        "/api/v1/school/cat-assets/plans",
        json=plan_payload,
        headers={**headers, "Idempotency-Key": "stable-plan-create"},
    )
    replayed_plan = await client.post(
        "/api/v1/school/cat-assets/plans",
        json=plan_payload,
        headers={**headers, "Idempotency-Key": "stable-plan-create"},
    )

    assert [response.status_code for response in (first_bank, replayed_bank)] == [201, 201]
    assert [response.status_code for response in (first_plan, replayed_plan)] == [201, 201]
    assert first_bank.json()["data"] == replayed_bank.json()["data"] == bank_result
    assert first_plan.json()["data"] == replayed_plan.json()["data"] == plan_result
    assert service.keys == [
        "stable-bank-create",
        "stable-bank-create",
        "stable-plan-create",
        "stable-plan-create",
    ]

    bank_version = await client.post(
        f"/api/v1/school/cat-assets/banks/{bank_ref}/versions",
        json={"expected_revision": 1, "bank_document": bank_document()},
        headers={**headers, "Idempotency-Key": "stable-bank-version"},
    )
    plan_version = await client.post(
        f"/api/v1/school/cat-assets/plans/{plan_ref}/versions",
        json={
            "expected_revision": 1,
            "bank_version_ref": bank_version_ref,
            "config_document": config_document(),
        },
        headers={**headers, "Idempotency-Key": "stable-plan-version"},
    )
    assert bank_version.status_code == 200
    assert plan_version.status_code == 200
