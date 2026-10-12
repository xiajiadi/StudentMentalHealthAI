"""Authorization and orchestration for school-scoped CAT asset documents."""

from __future__ import annotations

import json

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.cat_assets.schemas import (
    BankCreateRequest,
    BankPatchRequest,
    BankVersionRequest,
    PlanCreateRequest,
    PlanPatchRequest,
    PlanVersionRequest,
)
from smhai_backend.domains.models import Actor, BackendRole

MAX_ASSET_DOCUMENT_BYTES = 256 * 1024


class SchoolCatAssetService:
    """Only active synthetic-school specialists can author CAT assets."""

    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    @staticmethod
    def _require_specialist(actor: Actor) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
            or actor.school_id is None
            or actor.school_id <= 0
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @staticmethod
    def _bounded_document(document: dict, *, field: str) -> dict:
        try:
            encoded = json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise error(ErrorCode.VALIDATION_FAILED, detail=f"{field} is invalid") from exc
        if len(encoded) > MAX_ASSET_DOCUMENT_BYTES:
            raise error(ErrorCode.VALIDATION_FAILED, detail=f"{field} exceeds the size limit")
        return document

    @staticmethod
    def _request(dto_type, **values):
        try:
            return dto_type.model_validate(values, strict=True)
        except ValidationError as exc:
            raise error(ErrorCode.VALIDATION_FAILED, detail="CAT asset request is invalid") from exc

    async def _replay(self, actor: Actor, idempotency):
        resolver = getattr(self.persistence, "school_cat_assets_replay", None)
        if resolver is None:
            return None
        return await resolver(actor, idempotency)

    async def template(self, actor: Actor):
        self._require_specialist(actor)
        return await self.persistence.school_cat_assets_template(actor)

    async def list_banks(self, actor: Actor, *, limit: int, skip: int):
        self._require_specialist(actor)
        return await self.persistence.school_cat_assets_list_banks(actor, limit=limit, skip=skip)

    async def get_bank(self, actor: Actor, bank_ref: str):
        self._require_specialist(actor)
        return await self.persistence.school_cat_assets_get_bank(actor, bank_ref)

    async def create_bank(self, actor: Actor, *, payload, idempotency, trace_id: str):
        self._require_specialist(actor)
        request = self._request(BankCreateRequest, **payload)
        document = self._bounded_document(request.bank_document, field="bank_document")
        replay = await self._replay(actor, idempotency)
        if replay is not None:
            return replay
        validated = await self.persistence.school_cat_assets_validate(
            actor, document, config_document=None
        )
        return await self.persistence.school_cat_assets_create_bank(
            actor,
            request.display_name,
            validated["bank_document"],
            item_count=validated["item_count"],
            dimension_count=validated["dimension_count"],
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def patch_bank(self, actor: Actor, bank_ref: str, *, payload, idempotency, trace_id: str):
        self._require_specialist(actor)
        request = self._request(BankPatchRequest, **payload)
        return await self.persistence.school_cat_assets_patch_bank(
            actor,
            bank_ref,
            expected_revision=request.expected_revision,
            display_name=request.display_name,
            status=request.status,
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def create_bank_version(
        self, actor: Actor, bank_ref: str, *, payload, idempotency, trace_id: str
    ):
        self._require_specialist(actor)
        request = self._request(BankVersionRequest, **payload)
        document = self._bounded_document(request.bank_document, field="bank_document")
        replay = await self._replay(actor, idempotency)
        if replay is not None:
            return replay
        await self.persistence.school_cat_assets_preflight_bank_version(
            actor, bank_ref, request.expected_revision
        )
        validated = await self.persistence.school_cat_assets_validate(
            actor, document, config_document=None
        )
        return await self.persistence.school_cat_assets_create_bank_version(
            actor,
            bank_ref,
            request.expected_revision,
            validated["bank_document"],
            item_count=validated["item_count"],
            dimension_count=validated["dimension_count"],
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def get_bank_version(self, actor: Actor, version_ref: str):
        self._require_specialist(actor)
        return await self.persistence.school_cat_assets_get_bank_version(actor, version_ref)

    async def list_plans(self, actor: Actor, *, limit: int, skip: int):
        self._require_specialist(actor)
        return await self.persistence.school_cat_assets_list_plans(actor, limit=limit, skip=skip)

    async def get_plan(self, actor: Actor, plan_ref: str):
        self._require_specialist(actor)
        return await self.persistence.school_cat_assets_get_plan(actor, plan_ref)

    async def create_plan(self, actor: Actor, *, payload, idempotency, trace_id: str):
        self._require_specialist(actor)
        request = self._request(PlanCreateRequest, **payload)
        document = self._bounded_document(request.config_document, field="config_document")
        replay = await self._replay(actor, idempotency)
        if replay is not None:
            return replay
        await self.persistence.school_cat_assets_preflight_plan(actor, request.bank_version_ref)
        validated = await self.persistence.school_cat_assets_validate_plan(
            actor, request.bank_version_ref, document
        )
        return await self.persistence.school_cat_assets_create_plan(
            actor,
            request.display_name,
            request.bank_version_ref,
            validated["config_document"],
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def patch_plan(self, actor: Actor, plan_ref: str, *, payload, idempotency, trace_id: str):
        self._require_specialist(actor)
        request = self._request(PlanPatchRequest, **payload)
        return await self.persistence.school_cat_assets_patch_plan(
            actor,
            plan_ref,
            expected_revision=request.expected_revision,
            display_name=request.display_name,
            status=request.status,
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def create_plan_version(
        self, actor: Actor, plan_ref: str, *, payload, idempotency, trace_id: str
    ):
        self._require_specialist(actor)
        request = self._request(PlanVersionRequest, **payload)
        document = self._bounded_document(request.config_document, field="config_document")
        replay = await self._replay(actor, idempotency)
        if replay is not None:
            return replay
        await self.persistence.school_cat_assets_preflight_plan_version(
            actor,
            plan_ref,
            request.expected_revision,
            request.bank_version_ref,
        )
        validated = await self.persistence.school_cat_assets_validate_plan(
            actor, request.bank_version_ref, document
        )
        return await self.persistence.school_cat_assets_create_plan_version(
            actor,
            plan_ref,
            request.expected_revision,
            request.bank_version_ref,
            validated["config_document"],
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def get_plan_version(self, actor: Actor, version_ref: str):
        self._require_specialist(actor)
        return await self.persistence.school_cat_assets_get_plan_version(actor, version_ref)


__all__ = ["MAX_ASSET_DOCUMENT_BYTES", "SchoolCatAssetService"]
