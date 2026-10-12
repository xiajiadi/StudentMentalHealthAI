"""School-scoped CAT asset persistence with encrypted immutable versions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from smhai_backend.adapters.school_directory import SchoolDirectoryPersistenceAdapter
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.cat_assets.service import MAX_ASSET_DOCUMENT_BYTES
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.integrations.cat_assets import (
    HttpCatAssetsClient,
    HttpCatSavedSimulationClient,
)

_BANK_SCHEMA = "school_cat_bank_document.v1"
_PLAN_SCHEMA = "school_cat_config_document.v1"
_BANK_RESOURCE = "school_cat_item_bank"
_BANK_VERSION_RESOURCE = "school_cat_item_bank_version"
_PLAN_RESOURCE = "school_cat_plan"
_PLAN_VERSION_RESOURCE = "school_cat_plan_version"
_NOT_FOUND = "CAT asset was not found"


def _database_public_id(value: Any, prefix: str) -> str:
    if not isinstance(value, str) or not value.startswith(f"{prefix}_"):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
    public_id = value.removeprefix(f"{prefix}_")
    if len(public_id) != 36:
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
    return public_id


def _asset_ref(prefix: str, row: Any) -> str:
    return f"{prefix}_{row.public_id}"


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class SchoolCatAssetsPersistenceAdapter:
    """Short-UOW operations; no database transaction spans CAT validation calls."""

    def __init__(
        self,
        persistence: Any,
        client: HttpCatAssetsClient | None,
        simulation_client: HttpCatSavedSimulationClient | None = None,
    ) -> None:
        self._directory = SchoolDirectoryPersistenceAdapter(persistence)
        self._client = client
        self._simulation_client = simulation_client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._directory, name)

    def _require_actor(self, actor: Actor) -> None:
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
            or actor.school_id is None
            or actor.school_ref is None
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    async def _authorize(self, uow: Any, actor: Actor, at: datetime) -> tuple[int, int]:
        self._require_actor(actor)
        return await self._school_actor_role(uow, actor, "psychological_specialist", at)

    async def _authorized_read(self, actor: Actor, operation: str, call):
        self._require_actor(actor)
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, _role_id = await self._authorize(uow, actor, now)
            result = await call(uow)
            await self._audit(
                uow,
                actor_account_id=account_id,
                action=f"school_cat_assets.{operation}",
                resource_type="school_cat_assets",
                resource_ref=None,
                trace_id=get_request_context().trace_id,
                state="READ",
            )
        return result

    async def _audit(
        self,
        uow: Any,
        *,
        actor_account_id: int,
        action: str,
        resource_type: str,
        resource_ref: str | None,
        trace_id: str,
        state: str,
    ) -> None:
        await uow.audit.append(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_ref,
            result=self._db_enums.AuditResult.SUCCESS,
            trace_id=trace_id,
            actor_account_id=actor_account_id,
            safe_metadata={"source": "school_cat_assets", "state": state},
        )

    async def _network_call(self, actor: Actor, operation: str, call):
        self._require_actor(actor)
        async with self._uow() as uow:
            await self._authorize(uow, actor, self._utc_now())
        try:
            result = await call(self._require_client())
        except Exception:
            # Recheck live scope even on a failed remote validation; never hold
            # the preflight UOW across the network request.
            async with self._uow() as uow:
                await self._authorize(uow, actor, self._utc_now())
            raise
        context = get_request_context()
        async with self._uow() as uow:
            account_id, _role_id = await self._authorize(uow, actor, self._utc_now())
            await self._audit_resource(
                uow,
                account_id,
                f"school_cat_assets.{operation}",
                "school_cat_assets",
                None,
                context.trace_id,
            )
        return result

    def _require_client(self) -> HttpCatAssetsClient:
        if self._client is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="CAT asset service is not configured",
                retryable=True,
            )
        return self._client

    def _require_simulation_client(self) -> HttpCatSavedSimulationClient:
        if self._simulation_client is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="CAT saved-version simulation is not configured",
                retryable=True,
            )
        return self._simulation_client

    async def school_cat_assets_template(self, actor: Actor) -> dict[str, Any]:
        context = get_request_context()
        return await self._network_call(
            actor,
            "template_read",
            lambda client: client.template(context=context),
        )

    async def school_cat_assets_validate(
        self, actor: Actor, bank_document: dict[str, Any], *, config_document: dict | None
    ) -> dict[str, Any]:
        try:
            request_size = len(
                json.dumps(
                    {"bank_document": bank_document, "config_document": config_document},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise error(
                ErrorCode.VALIDATION_FAILED, detail="CAT asset document is invalid"
            ) from exc
        if request_size > MAX_ASSET_DOCUMENT_BYTES:
            raise error(
                ErrorCode.VALIDATION_FAILED, detail="CAT asset document exceeds the size limit"
            )
        context = get_request_context()
        return await self._network_call(
            actor,
            "assets_validated",
            lambda client: client.validate_assets(bank_document, config_document, context=context),
        )

    async def school_cat_assets_validate_plan(
        self, actor: Actor, bank_version_ref: str, config_document: dict[str, Any]
    ) -> dict[str, Any]:
        bank_data = await self.school_cat_assets_get_bank_version(actor, bank_version_ref)
        validated = await self.school_cat_assets_validate(
            actor,
            bank_data["bank_document"],
            config_document=config_document,
        )
        return {"config_document": validated["config_document"]}

    async def school_cat_assets_preflight_bank_version(
        self, actor: Actor, bank_ref: str, expected_revision: int
    ) -> None:
        """Check the authoring target in a short fresh UOW before CAT validation."""

        async def operation(uow):
            bank = await self._bank(uow, actor, bank_ref)
            if bank.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="archived CAT bank cannot be versioned"
                )
            if bank.revision != expected_revision:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT bank revision changed")

        await self._authorized_read(actor, "bank_version_preflight", operation)

    async def school_cat_assets_preflight_plan(self, actor: Actor, bank_version_ref: str) -> None:
        """Check a new plan's exact bank version and active parent before validation."""

        async def operation(uow):
            bank_version = await self._bank_version(uow, actor, bank_version_ref)
            bank = await uow.session.scalar(
                self._select(self._db_models.SchoolCatItemBank).where(
                    self._db_models.SchoolCatItemBank.id == bank_version.bank_id,
                    self._db_models.SchoolCatItemBank.school_id == actor.school_id,
                )
            )
            if bank is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            if bank.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="archived CAT bank cannot be used by a plan",
                )

        await self._authorized_read(actor, "plan_bank_preflight", operation)

    async def school_cat_assets_preflight_plan_version(
        self,
        actor: Actor,
        plan_ref: str,
        expected_revision: int,
        bank_version_ref: str,
    ) -> None:
        """Check plan and referenced bank scope/state before CAT validation."""

        async def operation(uow):
            plan = await self._plan(uow, actor, plan_ref)
            if plan.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="archived CAT plan cannot be versioned"
                )
            if plan.revision != expected_revision:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan revision changed")
            bank_version = await self._bank_version(uow, actor, bank_version_ref)
            bank = await uow.session.scalar(
                self._select(self._db_models.SchoolCatItemBank).where(
                    self._db_models.SchoolCatItemBank.id == bank_version.bank_id,
                    self._db_models.SchoolCatItemBank.school_id == actor.school_id,
                )
            )
            if bank is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            if bank.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="archived CAT bank cannot be used by a plan",
                )

        await self._authorized_read(actor, "plan_version_preflight", operation)

    def _bank_metadata(self, row: Any) -> dict[str, Any]:
        return {
            "bank_ref": _asset_ref("CBANK", row),
            "display_name": row.display_name,
            "status": row.status,
            "revision": int(row.revision),
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def _plan_metadata(self, row: Any) -> dict[str, Any]:
        return {
            "plan_ref": _asset_ref("CPLAN", row),
            "display_name": row.display_name,
            "status": row.status,
            "revision": int(row.revision),
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def _bank_version_metadata(self, row: Any) -> dict[str, Any]:
        return {
            "version_ref": _asset_ref("CBVER", row),
            "version_number": int(row.version_number),
            "created_at": _iso(row.created_at),
            "item_count": int(row.item_count),
            "dimension_count": int(row.dimension_count),
        }

    def _plan_version_metadata(self, row: Any) -> dict[str, Any]:
        return {
            "version_ref": _asset_ref("CPVER", row),
            "version_number": int(row.version_number),
            "created_at": _iso(row.created_at),
        }

    async def _bank_detail(self, uow: Any, actor: Actor, row: Any) -> dict[str, Any]:
        m = self._db_models
        versions = list(
            (
                await uow.session.scalars(
                    self._select(m.SchoolCatItemBankVersion)
                    .where(
                        m.SchoolCatItemBankVersion.bank_id == row.id,
                        m.SchoolCatItemBankVersion.school_id == actor.school_id,
                    )
                    .order_by(m.SchoolCatItemBankVersion.version_number.desc())
                )
            ).all()
        )
        return {
            "engineering_only": True,
            "psychological_interpretation_allowed": False,
            "bank": {
                **self._bank_metadata(row),
                "versions": [self._bank_version_metadata(v) for v in versions],
            },
        }

    async def _plan_detail(self, uow: Any, actor: Actor, row: Any) -> dict[str, Any]:
        m = self._db_models
        versions = list(
            (
                await uow.session.scalars(
                    self._select(m.SchoolCatPlanVersion)
                    .where(
                        m.SchoolCatPlanVersion.plan_id == row.id,
                        m.SchoolCatPlanVersion.school_id == actor.school_id,
                    )
                    .order_by(m.SchoolCatPlanVersion.version_number.desc())
                )
            ).all()
        )
        return {
            "engineering_only": True,
            "psychological_interpretation_allowed": False,
            "plan": {
                **self._plan_metadata(row),
                "versions": [self._plan_version_metadata(v) for v in versions],
            },
        }

    async def _bank(self, uow: Any, actor: Actor, bank_ref: str, *, lock: bool = False):
        m = self._db_models
        public_id = _database_public_id(bank_ref, "CBANK")
        statement = self._select(m.SchoolCatItemBank).where(
            m.SchoolCatItemBank.public_id == public_id,
            m.SchoolCatItemBank.school_id == actor.school_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await uow.session.scalar(statement)
        if row is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
        return row

    async def _plan(self, uow: Any, actor: Actor, plan_ref: str, *, lock: bool = False):
        m = self._db_models
        public_id = _database_public_id(plan_ref, "CPLAN")
        statement = self._select(m.SchoolCatPlan).where(
            m.SchoolCatPlan.public_id == public_id,
            m.SchoolCatPlan.school_id == actor.school_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await uow.session.scalar(statement)
        if row is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
        return row

    async def _bank_version(self, uow: Any, actor: Actor, version_ref: str, *, lock: bool = False):
        m = self._db_models
        public_id = _database_public_id(version_ref, "CBVER")
        statement = self._select(m.SchoolCatItemBankVersion).where(
            m.SchoolCatItemBankVersion.public_id == public_id,
            m.SchoolCatItemBankVersion.school_id == actor.school_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await uow.session.scalar(statement)
        if row is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
        return row

    async def _plan_version(self, uow: Any, actor: Actor, version_ref: str, *, lock: bool = False):
        m = self._db_models
        public_id = _database_public_id(version_ref, "CPVER")
        statement = self._select(m.SchoolCatPlanVersion).where(
            m.SchoolCatPlanVersion.public_id == public_id,
            m.SchoolCatPlanVersion.school_id == actor.school_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await uow.session.scalar(statement)
        if row is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
        return row

    @staticmethod
    def _decrypt(uow: Any, row: Any, schema_version: str) -> dict[str, Any]:
        from database_layer.crypto import EncryptedPayload

        if (
            not isinstance(row.payload_ciphertext, bytes)
            or not row.key_version
            or row.cipher_format_version != uow.protection.cipher_format_version
            or row.payload_schema_version != schema_version
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="CAT asset is unavailable")
        try:
            return uow.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=row.payload_ciphertext,
                    key_version=row.key_version,
                    cipher_format_version=row.cipher_format_version,
                    payload_schema_version=row.payload_schema_version,
                )
            )
        except Exception as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="CAT asset is unavailable"
            ) from exc

    @staticmethod
    def _encrypt(uow: Any, document: dict[str, Any], schema_version: str):
        return uow.protection.encrypt_json(document, payload_schema_version=schema_version)

    async def _audit_resource(
        self,
        uow: Any,
        account_id: int,
        action: str,
        resource_type: str,
        resource_ref: str | None,
        trace_id: str,
    ) -> None:
        await self._audit(
            uow,
            actor_account_id=account_id,
            action=action,
            resource_type=resource_type,
            resource_ref=resource_ref,
            trace_id=trace_id,
            state="SUCCESS",
        )

    async def _receipt(self, uow: Any, claim: Any, expected_type: str) -> str:
        record = claim.record
        if (
            record is None
            or record.result_resource_type != expected_type
            or not isinstance(record.result_public_id, str)
            or not record.result_public_id
        ):
            raise error(
                ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset idempotency result unavailable"
            )
        return record.result_public_id

    async def school_cat_assets_replay(self, actor: Actor, idempotency) -> dict[str, Any] | None:
        """Resolve an already-completed mutation before CAT network validation."""
        if idempotency is None:
            raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
        key, request_fingerprint, scope = idempotency
        try:
            expected_hash = bytes.fromhex(request_fingerprint)
        except (TypeError, ValueError) as exc:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid idempotency key") from exc
        m = self._db_models
        async with self._uow() as uow:
            account_id, _role_id = await self._authorize(uow, actor, self._utc_now())
            record = await uow.session.scalar(
                self._select(m.IdempotencyRecord)
                .where(
                    m.IdempotencyRecord.scope == scope,
                    m.IdempotencyRecord.key_hash == hashlib.sha256(key.encode()).digest(),
                )
                .with_for_update()
            )
            if record is None or record.expires_at <= self._utc_now():
                return None
            if record.request_hash != expected_hash:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="idempotency key was already used for another request",
                )
            if record.state != self._db_enums.IdempotencyState.COMPLETED.value:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="idempotency request is in progress"
                )

            resource_type = record.result_resource_type
            public_id = record.result_public_id
            if not isinstance(public_id, str) or not public_id:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset idempotency result unavailable"
                )
            if resource_type == _BANK_RESOURCE:
                row = await uow.session.scalar(
                    self._select(m.SchoolCatItemBank).where(
                        m.SchoolCatItemBank.public_id == public_id,
                        m.SchoolCatItemBank.school_id == actor.school_id,
                    )
                )
                if row is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset result is unavailable"
                    )
                result = await self._bank_detail(uow, actor, row)
            elif resource_type == _BANK_VERSION_RESOURCE:
                version = await uow.session.scalar(
                    self._select(m.SchoolCatItemBankVersion).where(
                        m.SchoolCatItemBankVersion.public_id == public_id,
                        m.SchoolCatItemBankVersion.school_id == actor.school_id,
                    )
                )
                if version is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset result is unavailable"
                    )
                row = await uow.session.scalar(
                    self._select(m.SchoolCatItemBank).where(
                        m.SchoolCatItemBank.id == version.bank_id,
                        m.SchoolCatItemBank.school_id == actor.school_id,
                    )
                )
                if row is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset result is unavailable"
                    )
                result = await self._bank_detail(uow, actor, row)
                result["version_ref"] = _asset_ref("CBVER", version)
            elif resource_type == _PLAN_RESOURCE:
                row = await uow.session.scalar(
                    self._select(m.SchoolCatPlan).where(
                        m.SchoolCatPlan.public_id == public_id,
                        m.SchoolCatPlan.school_id == actor.school_id,
                    )
                )
                if row is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan result is unavailable"
                    )
                result = await self._plan_detail(uow, actor, row)
            elif resource_type == _PLAN_VERSION_RESOURCE:
                version = await uow.session.scalar(
                    self._select(m.SchoolCatPlanVersion).where(
                        m.SchoolCatPlanVersion.public_id == public_id,
                        m.SchoolCatPlanVersion.school_id == actor.school_id,
                    )
                )
                if version is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan result is unavailable"
                    )
                row = await uow.session.scalar(
                    self._select(m.SchoolCatPlan).where(
                        m.SchoolCatPlan.id == version.plan_id,
                        m.SchoolCatPlan.school_id == actor.school_id,
                    )
                )
                if row is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan result is unavailable"
                    )
                result = await self._plan_detail(uow, actor, row)
                result["version_ref"] = _asset_ref("CPVER", version)
            else:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset idempotency result unavailable"
                )

            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.idempotent_replay",
                resource_type,
                public_id,
                get_request_context().trace_id,
            )
            return result

    async def school_cat_assets_list_banks(
        self, actor: Actor, *, limit: int, skip: int
    ) -> dict[str, Any]:

        m = self._db_models

        async def operation(uow):
            rows = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolCatItemBank)
                        .where(m.SchoolCatItemBank.school_id == actor.school_id)
                        .order_by(
                            m.SchoolCatItemBank.created_at.desc(), m.SchoolCatItemBank.id.desc()
                        )
                        .offset(skip)
                        .limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            return {
                "engineering_only": True,
                "psychological_interpretation_allowed": False,
                "items": [self._bank_metadata(row) for row in rows[:limit]],
                "has_more": has_more,
            }

        return await self._authorized_read(actor, "banks_listed", operation)

    async def school_cat_assets_get_bank(self, actor: Actor, bank_ref: str) -> dict[str, Any]:
        async def operation(uow):
            row = await self._bank(uow, actor, bank_ref)
            return await self._bank_detail(uow, actor, row)

        return await self._authorized_read(actor, "bank_read", operation)

    async def school_cat_assets_list_plans(
        self, actor: Actor, *, limit: int, skip: int
    ) -> dict[str, Any]:
        m = self._db_models

        async def operation(uow):
            rows = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolCatPlan)
                        .where(m.SchoolCatPlan.school_id == actor.school_id)
                        .order_by(m.SchoolCatPlan.created_at.desc(), m.SchoolCatPlan.id.desc())
                        .offset(skip)
                        .limit(limit + 1)
                    )
                ).all()
            )
            return {
                "engineering_only": True,
                "psychological_interpretation_allowed": False,
                "items": [self._plan_metadata(row) for row in rows[:limit]],
                "has_more": len(rows) > limit,
            }

        return await self._authorized_read(actor, "plans_listed", operation)

    async def school_cat_assets_get_plan(self, actor: Actor, plan_ref: str) -> dict[str, Any]:
        async def operation(uow):
            row = await self._plan(uow, actor, plan_ref)
            return await self._plan_detail(uow, actor, row)

        return await self._authorized_read(actor, "plan_read", operation)

    async def school_cat_assets_get_bank_version(
        self, actor: Actor, version_ref: str
    ) -> dict[str, Any]:
        async def operation(uow):
            row = await self._bank_version(uow, actor, version_ref)
            return {
                "engineering_only": True,
                "psychological_interpretation_allowed": False,
                "version": self._bank_version_metadata(row),
                "bank_document": self._decrypt(uow, row, _BANK_SCHEMA),
            }

        return await self._authorized_read(actor, "bank_version_read", operation)

    async def _claim_write(self, uow: Any, idempotency: Any):
        return await self._school_idempotency_begin(uow, idempotency)

    async def school_cat_assets_create_bank(
        self,
        actor: Actor,
        display_name: str,
        document: dict[str, Any],
        *,
        item_count: int,
        dimension_count: int,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._authorize(uow, actor, self._utc_now())
            claim = await self._claim_write(uow, idempotency)
            if claim.replayed:
                version_public_id = await self._receipt(uow, claim, _BANK_VERSION_RESOURCE)
                version = await uow.session.scalar(
                    self._select(m.SchoolCatItemBankVersion).where(
                        m.SchoolCatItemBankVersion.public_id == version_public_id,
                        m.SchoolCatItemBankVersion.school_id == actor.school_id,
                    )
                )
                if version is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset result is unavailable"
                    )
                row = await uow.session.scalar(
                    self._select(m.SchoolCatItemBank).where(
                        m.SchoolCatItemBank.id == version.bank_id,
                        m.SchoolCatItemBank.school_id == actor.school_id,
                    )
                )
                if row is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset result is unavailable"
                    )
                result = await self._bank_detail(uow, actor, row)
                result["version_ref"] = _asset_ref("CBVER", version)
                await self._audit_resource(
                    uow,
                    account_id,
                    "school_cat_assets.bank_replayed",
                    _BANK_RESOURCE,
                    row.public_id,
                    trace_id,
                )
                return result
            row = m.SchoolCatItemBank(
                school_id=actor.school_id,
                display_name=display_name,
                status="ACTIVE",
                revision=1,
                creator_membership_role_id=role_id,
            )
            uow.session.add(row)
            await uow.session.flush()
            encrypted = self._encrypt(uow, document, _BANK_SCHEMA)
            version = m.SchoolCatItemBankVersion(
                school_id=actor.school_id,
                bank_id=row.id,
                version_number=1,
                creator_membership_role_id=role_id,
                item_count=item_count,
                dimension_count=dimension_count,
                payload_ciphertext=encrypted.ciphertext,
                cipher_format_version=encrypted.cipher_format_version,
                key_version=encrypted.key_version,
                payload_schema_version=encrypted.payload_schema_version,
            )
            uow.session.add(version)
            await uow.session.flush()
            await self._school_idempotency_complete(
                uow, claim, resource_type=_BANK_VERSION_RESOURCE, result_ref=version.public_id
            )
            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.bank_created",
                _BANK_RESOURCE,
                row.public_id,
                trace_id,
            )
            result = await self._bank_detail(uow, actor, row)
            result["version_ref"] = _asset_ref("CBVER", version)
            return result

    async def school_cat_assets_patch_bank(
        self,
        actor: Actor,
        bank_ref: str,
        *,
        expected_revision: int,
        display_name: str | None,
        status: str | None,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        async with self._uow() as uow:
            account_id, _role_id = await self._authorize(uow, actor, self._utc_now())
            claim = await self._claim_write(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt(uow, claim, _BANK_RESOURCE)
                row = await self._bank(uow, actor, f"CBANK_{ref}")
                await self._audit_resource(
                    uow,
                    account_id,
                    "school_cat_assets.bank_replayed",
                    _BANK_RESOURCE,
                    row.public_id,
                    trace_id,
                )
                return await self._bank_detail(uow, actor, row)
            row = await self._bank(uow, actor, bank_ref, lock=True)
            if row.revision != expected_revision:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT bank revision changed")
            if display_name is not None:
                row.display_name = display_name
            if status is not None:
                row.status = status
            row.revision += 1
            row.updated_at = self._utc_now()
            await uow.session.flush()
            await self._school_idempotency_complete(
                uow, claim, resource_type=_BANK_RESOURCE, result_ref=row.public_id
            )
            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.bank_updated",
                _BANK_RESOURCE,
                row.public_id,
                trace_id,
            )
            return await self._bank_detail(uow, actor, row)

    async def school_cat_assets_create_bank_version(
        self,
        actor: Actor,
        bank_ref: str,
        expected_revision: int,
        document: dict[str, Any],
        *,
        item_count: int,
        dimension_count: int,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._authorize(uow, actor, self._utc_now())
            claim = await self._claim_write(uow, idempotency)
            if claim.replayed:
                version_public_id = await self._receipt(uow, claim, _BANK_VERSION_RESOURCE)
                version = await uow.session.scalar(
                    self._select(m.SchoolCatItemBankVersion).where(
                        m.SchoolCatItemBankVersion.public_id == version_public_id,
                        m.SchoolCatItemBankVersion.school_id == actor.school_id,
                    )
                )
                if version is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT asset result is unavailable"
                    )
                bank = await self._bank(uow, actor, bank_ref)
                result = await self._bank_detail(uow, actor, bank)
                result["version_ref"] = _asset_ref("CBVER", version)
                await self._audit_resource(
                    uow,
                    account_id,
                    "school_cat_assets.bank_version_replayed",
                    _BANK_VERSION_RESOURCE,
                    version.public_id,
                    trace_id,
                )
                return result
            bank = await self._bank(uow, actor, bank_ref, lock=True)
            if bank.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="archived CAT bank cannot be versioned"
                )
            if bank.revision != expected_revision:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT bank revision changed")
            latest = await uow.session.scalar(
                self._select(m.SchoolCatItemBankVersion.version_number)
                .where(
                    m.SchoolCatItemBankVersion.bank_id == bank.id,
                    m.SchoolCatItemBankVersion.school_id == actor.school_id,
                )
                .order_by(m.SchoolCatItemBankVersion.version_number.desc())
                .limit(1)
            )
            encrypted = self._encrypt(uow, document, _BANK_SCHEMA)
            version = m.SchoolCatItemBankVersion(
                school_id=actor.school_id,
                bank_id=bank.id,
                version_number=(int(latest) if latest is not None else 0) + 1,
                creator_membership_role_id=role_id,
                item_count=item_count,
                dimension_count=dimension_count,
                payload_ciphertext=encrypted.ciphertext,
                cipher_format_version=encrypted.cipher_format_version,
                key_version=encrypted.key_version,
                payload_schema_version=encrypted.payload_schema_version,
            )
            uow.session.add(version)
            bank.revision += 1
            bank.updated_at = self._utc_now()
            await uow.session.flush()
            await self._school_idempotency_complete(
                uow, claim, resource_type=_BANK_VERSION_RESOURCE, result_ref=version.public_id
            )
            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.bank_version_created",
                _BANK_VERSION_RESOURCE,
                version.public_id,
                trace_id,
            )
            result = await self._bank_detail(uow, actor, bank)
            result["version_ref"] = _asset_ref("CBVER", version)
            return result

    async def school_cat_assets_create_plan(
        self,
        actor: Actor,
        display_name: str,
        bank_version_ref: str,
        document: dict[str, Any],
        *,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._authorize(uow, actor, self._utc_now())
            claim = await self._claim_write(uow, idempotency)
            if claim.replayed:
                version_public_id = await self._receipt(uow, claim, _PLAN_VERSION_RESOURCE)
                version = await uow.session.scalar(
                    self._select(m.SchoolCatPlanVersion).where(
                        m.SchoolCatPlanVersion.public_id == version_public_id,
                        m.SchoolCatPlanVersion.school_id == actor.school_id,
                    )
                )
                if version is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan result is unavailable"
                    )
                row = await uow.session.scalar(
                    self._select(m.SchoolCatPlan).where(
                        m.SchoolCatPlan.id == version.plan_id,
                        m.SchoolCatPlan.school_id == actor.school_id,
                    )
                )
                if row is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan result is unavailable"
                    )
                result = await self._plan_detail(uow, actor, row)
                result["version_ref"] = _asset_ref("CPVER", version)
                await self._audit_resource(
                    uow,
                    account_id,
                    "school_cat_assets.plan_replayed",
                    _PLAN_RESOURCE,
                    row.public_id,
                    trace_id,
                )
                return result
            bank_version = await self._bank_version(uow, actor, bank_version_ref)
            bank = await uow.session.scalar(
                self._select(m.SchoolCatItemBank)
                .where(
                    m.SchoolCatItemBank.id == bank_version.bank_id,
                    m.SchoolCatItemBank.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if bank is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            if bank.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="archived CAT bank cannot be used by a plan",
                )
            plan = m.SchoolCatPlan(
                school_id=actor.school_id,
                display_name=display_name,
                status="ACTIVE",
                revision=1,
                creator_membership_role_id=role_id,
            )
            uow.session.add(plan)
            await uow.session.flush()
            encrypted = self._encrypt(uow, document, _PLAN_SCHEMA)
            version = m.SchoolCatPlanVersion(
                school_id=actor.school_id,
                plan_id=plan.id,
                version_number=1,
                bank_version_id=bank_version.id,
                creator_membership_role_id=role_id,
                payload_ciphertext=encrypted.ciphertext,
                cipher_format_version=encrypted.cipher_format_version,
                key_version=encrypted.key_version,
                payload_schema_version=encrypted.payload_schema_version,
            )
            uow.session.add(version)
            await uow.session.flush()
            await self._school_idempotency_complete(
                uow, claim, resource_type=_PLAN_VERSION_RESOURCE, result_ref=version.public_id
            )
            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.plan_created",
                _PLAN_RESOURCE,
                plan.public_id,
                trace_id,
            )
            result = await self._plan_detail(uow, actor, plan)
            result["version_ref"] = _asset_ref("CPVER", version)
            return result

    async def school_cat_assets_patch_plan(
        self,
        actor: Actor,
        plan_ref: str,
        *,
        expected_revision: int,
        display_name: str | None,
        status: str | None,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        async with self._uow() as uow:
            account_id, _role_id = await self._authorize(uow, actor, self._utc_now())
            claim = await self._claim_write(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt(uow, claim, _PLAN_RESOURCE)
                row = await self._plan(uow, actor, f"CPLAN_{ref}")
                await self._audit_resource(
                    uow,
                    account_id,
                    "school_cat_assets.plan_replayed",
                    _PLAN_RESOURCE,
                    row.public_id,
                    trace_id,
                )
                return await self._plan_detail(uow, actor, row)
            row = await self._plan(uow, actor, plan_ref, lock=True)
            if row.revision != expected_revision:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan revision changed")
            if display_name is not None:
                row.display_name = display_name
            if status is not None:
                row.status = status
            row.revision += 1
            row.updated_at = self._utc_now()
            await uow.session.flush()
            await self._school_idempotency_complete(
                uow, claim, resource_type=_PLAN_RESOURCE, result_ref=row.public_id
            )
            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.plan_updated",
                _PLAN_RESOURCE,
                row.public_id,
                trace_id,
            )
            return await self._plan_detail(uow, actor, row)

    async def school_cat_assets_create_plan_version(
        self,
        actor: Actor,
        plan_ref: str,
        expected_revision: int,
        bank_version_ref: str,
        document: dict[str, Any],
        *,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._authorize(uow, actor, self._utc_now())
            claim = await self._claim_write(uow, idempotency)
            if claim.replayed:
                version_public_id = await self._receipt(uow, claim, _PLAN_VERSION_RESOURCE)
                version = await uow.session.scalar(
                    self._select(m.SchoolCatPlanVersion).where(
                        m.SchoolCatPlanVersion.public_id == version_public_id,
                        m.SchoolCatPlanVersion.school_id == actor.school_id,
                    )
                )
                if version is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan result is unavailable"
                    )
                plan = await self._plan(uow, actor, plan_ref)
                result = await self._plan_detail(uow, actor, plan)
                result["version_ref"] = _asset_ref("CPVER", version)
                await self._audit_resource(
                    uow,
                    account_id,
                    "school_cat_assets.plan_version_replayed",
                    _PLAN_VERSION_RESOURCE,
                    version.public_id,
                    trace_id,
                )
                return result
            plan = await self._plan(uow, actor, plan_ref, lock=True)
            if plan.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="archived CAT plan cannot be versioned"
                )
            if plan.revision != expected_revision:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan revision changed")
            bank_version = await self._bank_version(uow, actor, bank_version_ref)
            bank = await uow.session.scalar(
                self._select(m.SchoolCatItemBank)
                .where(
                    m.SchoolCatItemBank.id == bank_version.bank_id,
                    m.SchoolCatItemBank.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if bank is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            if bank.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="archived CAT bank cannot be used by a plan",
                )
            latest = await uow.session.scalar(
                self._select(m.SchoolCatPlanVersion.version_number)
                .where(
                    m.SchoolCatPlanVersion.plan_id == plan.id,
                    m.SchoolCatPlanVersion.school_id == actor.school_id,
                )
                .order_by(m.SchoolCatPlanVersion.version_number.desc())
                .limit(1)
            )
            encrypted = self._encrypt(uow, document, _PLAN_SCHEMA)
            version = m.SchoolCatPlanVersion(
                school_id=actor.school_id,
                plan_id=plan.id,
                version_number=(int(latest) if latest is not None else 0) + 1,
                bank_version_id=bank_version.id,
                creator_membership_role_id=role_id,
                payload_ciphertext=encrypted.ciphertext,
                cipher_format_version=encrypted.cipher_format_version,
                key_version=encrypted.key_version,
                payload_schema_version=encrypted.payload_schema_version,
            )
            uow.session.add(version)
            plan.revision += 1
            plan.updated_at = self._utc_now()
            await uow.session.flush()
            await self._school_idempotency_complete(
                uow, claim, resource_type=_PLAN_VERSION_RESOURCE, result_ref=version.public_id
            )
            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.plan_version_created",
                _PLAN_VERSION_RESOURCE,
                version.public_id,
                trace_id,
            )
            result = await self._plan_detail(uow, actor, plan)
            result["version_ref"] = _asset_ref("CPVER", version)
            return result

    async def school_cat_assets_simulate_plan_version(
        self, actor: Actor, version_ref: str, n_examinees: int
    ) -> dict[str, Any]:
        """Run CAT against one immutable saved version without holding a UOW."""

        self._require_actor(actor)
        m = self._db_models
        async with self._uow() as uow:
            await self._authorize(uow, actor, self._utc_now())
            plan_version = await self._plan_version(uow, actor, version_ref)
            plan = await uow.session.scalar(
                self._select(m.SchoolCatPlan).where(
                    m.SchoolCatPlan.id == plan_version.plan_id,
                    m.SchoolCatPlan.school_id == actor.school_id,
                )
            )
            if plan is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            if plan.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="archived CAT plan cannot be simulated",
                )
            bank_version = await uow.session.scalar(
                self._select(m.SchoolCatItemBankVersion).where(
                    m.SchoolCatItemBankVersion.id == plan_version.bank_version_id,
                    m.SchoolCatItemBankVersion.school_id == actor.school_id,
                )
            )
            if bank_version is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            bank = await uow.session.scalar(
                self._select(m.SchoolCatItemBank).where(
                    m.SchoolCatItemBank.id == bank_version.bank_id,
                    m.SchoolCatItemBank.school_id == actor.school_id,
                )
            )
            if bank is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            if bank.status != "ACTIVE":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="archived CAT bank cannot be simulated",
                )
            bank_document = self._decrypt(uow, bank_version, _BANK_SCHEMA)
            config_document = self._decrypt(uow, plan_version, _PLAN_SCHEMA)
            plan_version_id = plan_version.id
            plan_id = plan.id
            bank_version_id = bank_version.id
            resolved_plan_version_ref = _asset_ref("CPVER", plan_version)
            resolved_bank_version_ref = _asset_ref("CBVER", bank_version)

        client = self._require_simulation_client()
        context = get_request_context()
        try:
            result = await client.simulate_saved_assets(
                bank_document,
                config_document,
                n_examinees,
                context=context,
            )
        except Exception:
            # A failed run still must not disclose status to a role or resource
            # scope that was revoked while CAT computation was in progress.
            await self._recheck_simulation_scope(actor, version_ref)
            raise

        async with self._uow() as uow:
            account_id, _role_id = await self._authorize(uow, actor, self._utc_now())
            current_plan_version = await self._plan_version(uow, actor, version_ref)
            if (
                current_plan_version.id != plan_version_id
                or current_plan_version.plan_id != plan_id
                or current_plan_version.bank_version_id != bank_version_id
            ):
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
            await self._require_active_simulation_parents(uow, actor, current_plan_version)
            await self._audit_resource(
                uow,
                account_id,
                "school_cat_assets.saved_simulation_completed",
                _PLAN_VERSION_RESOURCE,
                current_plan_version.public_id,
                context.trace_id,
            )
        return {
            **result,
            "plan_version_ref": resolved_plan_version_ref,
            "bank_version_ref": resolved_bank_version_ref,
        }

    async def _require_active_simulation_parents(
        self, uow: Any, actor: Actor, plan_version: Any
    ) -> tuple[Any, Any]:
        m = self._db_models
        plan = await uow.session.scalar(
            self._select(m.SchoolCatPlan).where(
                m.SchoolCatPlan.id == plan_version.plan_id,
                m.SchoolCatPlan.school_id == actor.school_id,
            )
        )
        if plan is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
        if plan.status != "ACTIVE":
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="archived CAT plan cannot be simulated")
        bank_version = await uow.session.scalar(
            self._select(m.SchoolCatItemBankVersion).where(
                m.SchoolCatItemBankVersion.id == plan_version.bank_version_id,
                m.SchoolCatItemBankVersion.school_id == actor.school_id,
            )
        )
        if bank_version is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
        bank = await uow.session.scalar(
            self._select(m.SchoolCatItemBank).where(
                m.SchoolCatItemBank.id == bank_version.bank_id,
                m.SchoolCatItemBank.school_id == actor.school_id,
            )
        )
        if bank is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail=_NOT_FOUND)
        if bank.status != "ACTIVE":
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="archived CAT bank cannot be simulated")
        return plan, bank

    async def _recheck_simulation_scope(self, actor: Actor, version_ref: str) -> None:
        async with self._uow() as uow:
            await self._authorize(uow, actor, self._utc_now())
            plan_version = await self._plan_version(uow, actor, version_ref)
            await self._require_active_simulation_parents(uow, actor, plan_version)

    async def school_cat_assets_get_plan_version(
        self, actor: Actor, version_ref: str
    ) -> dict[str, Any]:
        async def operation(uow):
            version = await self._plan_version(uow, actor, version_ref)
            bank_version = await uow.session.scalar(
                self._select(self._db_models.SchoolCatItemBankVersion).where(
                    self._db_models.SchoolCatItemBankVersion.id == version.bank_version_id,
                    self._db_models.SchoolCatItemBankVersion.school_id == actor.school_id,
                )
            )
            if bank_version is None:
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="CAT plan version is unavailable"
                )
            return {
                "engineering_only": True,
                "psychological_interpretation_allowed": False,
                "version": self._plan_version_metadata(version),
                "bank_version_ref": _asset_ref("CBVER", bank_version),
                "config_document": self._decrypt(uow, version, _PLAN_SCHEMA),
            }

        return await self._authorized_read(actor, "plan_version_read", operation)


__all__ = ["SchoolCatAssetsPersistenceAdapter"]
