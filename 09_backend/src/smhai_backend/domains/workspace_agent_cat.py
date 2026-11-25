"""CAT plan authoring through the school asset services and explicit approvals."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.cat_assets.schemas import (
    ActivationListDto,
    ActivationResponseDto,
    BankWriteResponseDto,
    PlanWriteResponseDto,
    TemplateResponseDto,
)
from smhai_backend.domains.models import Actor, BackendRole

from .workspace_agent_history import workspace_owner

MAX_CAT_UPLOAD = 240 * 1024
REF = r"^[a-f0-9]{32}$"


class CatDraftProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    plan_name: str = Field(min_length=1, max_length=100)
    class_designation: str = Field(min_length=1, max_length=128)
    opens_at: AwareDatetime | None = None
    due_at: AwareDatetime
    configuration: Literal["attachment", "school_template"]


class CatDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_ref: str = Field(pattern=REF)


class CatHandoffSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handoff_ref: str = Field(pattern=REF)


def _specialist(actor: Actor):
    if actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST:
        raise error(ErrorCode.FORBIDDEN, detail="CAT authoring requires a specialist")


def _admin(actor: Actor):
    if actor.role is not BackendRole.ADMIN:
        raise error(ErrorCode.FORBIDDEN, detail="CAT publication requires an administrator")


def _assets(request: Request):
    assets = request.app.state.container.cat_assets
    if assets is None:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="school CAT is unavailable")
    return assets


def _store(request: Request):
    return request.app.state.workspace_history.cat


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate JSON fields")
    return fields


async def upload(request: Request, actor: Actor) -> str:
    _specialist(actor)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_CAT_UPLOAD:
            raise error(ErrorCode.VALIDATION_FAILED, detail="CAT upload exceeds the size limit")
        body.extend(chunk)
    try:
        value = json.loads(body.decode("utf-8-sig"), object_pairs_hook=_unique_fields)
        if not isinstance(value, dict):
            raise ValueError
        if "bank_document" in value:
            if set(value) - {"bank_document", "config_document"}:
                raise ValueError
            bank, config = value["bank_document"], value.get("config_document")
        else:
            bank, config = value, None
        if not isinstance(bank, dict) or (config is not None and not isinstance(config, dict)):
            raise ValueError
        metadata = bank.get("metadata")
        if (
            bank.get("measurement_model") != "GRM"
            or not isinstance(metadata, dict)
            or metadata.get("synthetic") is not True
            or metadata.get("intended_use") != "engineering_test_only"
            or metadata.get("psychological_interpretation_allowed") is not False
        ):
            raise ValueError
        document = {"bank_document": bank, "config_document": config}
        # Reject non-finite numbers and any JSON input too deep to normalize.
        json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError):
        raise error(
            ErrorCode.VALIDATION_FAILED, detail="Expected a synthetic school GRM JSON document"
        ) from None
    return _store(request).upload(workspace_owner(actor), document)


async def inspect(request: Request, actor: Actor, attachment_ref: str | None):
    _specialist(actor)
    _, document = _store(request).attachment(workspace_owner(actor), attachment_ref)
    validated = await _assets(request).validate_documents(
        actor, document["bank_document"], config_document=document["config_document"]
    )
    summary = {
        "item_count": validated.item_count,
        "dimension_count": validated.dimension_count,
        "attachment_has_config": document["config_document"] is not None,
        "engineering_only": True,
    }
    return {"kind": "cat_inspection", **summary}, summary


def _draft_view(ref: str, state: str, data: dict) -> dict:
    return {
        "kind": "cat_draft",
        "draft_ref": ref,
        "state": state,
        **{
            key: data[key]
            for key in (
                "plan_name",
                "class_designation",
                "opens_at",
                "due_at",
                "configuration",
                "item_count",
                "min_items",
                "max_items",
            )
        },
    }


async def prepare(
    request: Request, actor: Actor, proposal: CatDraftProposal, attachment_ref: str | None
):
    _specialist(actor)
    owner = workspace_owner(actor)
    store = _store(request)
    ref, document = store.attachment(owner, attachment_ref)
    bank = document["bank_document"]
    if proposal.due_at <= max(
        datetime.now(UTC), proposal.opens_at or datetime.min.replace(tzinfo=UTC)
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="CAT draft deadline must follow opening")
    assets = _assets(request)
    config = document["config_document"]
    if proposal.configuration == "school_template":
        config = TemplateResponseDto.model_validate(await assets.template(actor)).config_document
    if config is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="CAT configuration is missing")
    validated = await assets.validate_documents(actor, bank, config_document=config)
    config = validated.config_document
    if config is None:
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="CAT configuration was not validated"
        )
    data = {
        **proposal.model_dump(mode="json"),
        "attachment": ref,
        "config_document": config,
        "item_count": validated.item_count,
        "min_items": config["min_items"],
        "max_items": config["max_items"],
    }
    draft_ref = fingerprint({"owner": owner, "draft": data})[:32]
    if data["opens_at"] is None:
        data["opens_at"] = datetime.now(UTC).isoformat()
    state, data = store.create_draft(draft_ref, owner, actor.school_ref, data)
    return _draft_view(draft_ref, state, data), {
        "draft_ref": draft_ref,
        "state": state,
        "item_count": data["item_count"],
        "due_at": data["due_at"],
        "needs_confirmation": state == "PREVIEW",
    }


def _idempotency(owner: str, action: str, ref: str, payload: dict):
    return (
        f"workspace-cat-{action}-{ref}",
        fingerprint(payload),
        fingerprint({"owner": owner, "action": action}),
    )


async def save(request: Request, actor: Actor, draft_ref: str) -> dict:
    _specialist(actor)
    store = _store(request)
    owner = workspace_owner(actor)
    state, data = store.draft(owner, draft_ref)
    if state != "PREVIEW":
        return _draft_view(draft_ref, state, data)
    if datetime.fromisoformat(data["due_at"]) <= datetime.now(UTC):
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT draft deadline has passed")
    _, document = store.attachment(owner, data["attachment"])
    bank = document["bank_document"]
    assets = _assets(request)
    context = current_request_context(request)
    bank_input = {
        "display_name": f"智能体题库 {fingerprint(bank)[:12]}",
        "bank_document": bank,
    }
    bank_result = BankWriteResponseDto.model_validate(
        await assets.create_bank(
            actor,
            payload=bank_input,
            idempotency=_idempotency(owner, "bank", fingerprint(bank)[:32], bank_input),
            trace_id=context.trace_id,
        )
    )
    plan_input = {
        "display_name": data["plan_name"],
        "bank_version_ref": bank_result.version_ref,
        "config_document": data["config_document"],
    }
    plan = PlanWriteResponseDto.model_validate(
        await assets.create_plan(
            actor,
            payload=plan_input,
            idempotency=_idempotency(owner, "plan", draft_ref, plan_input),
            trace_id=context.trace_id,
        )
    )
    data.pop("config_document")
    data.pop("attachment")
    data.update(plan_version_ref=plan.version_ref, bank_version_ref=bank_result.version_ref)
    state, data = store.advance(owner, draft_ref, "PREVIEW", "SAVED", data)
    return _draft_view(draft_ref, state, data)


async def approve(request: Request, actor: Actor, draft_ref: str) -> dict:
    _specialist(actor)
    store = _store(request)
    owner = workspace_owner(actor)
    state, data = store.draft(owner, draft_ref)
    if state == "PREVIEW":
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="Save the CAT plan before approving")
    if state in {"APPROVED", "PUBLISHED"}:
        return _draft_view(draft_ref, state, data)
    if datetime.fromisoformat(data["due_at"]) <= datetime.now(UTC):
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT handoff deadline has passed")
    result = ActivationResponseDto.model_validate(
        await _assets(request).create_activation(
            actor,
            data["plan_version_ref"],
            payload={},
            idempotency=_idempotency(owner, "activation", draft_ref, {}),
            trace_id=current_request_context(request).trace_id,
        )
    )
    if (
        result.activation.bank_version_ref != data["bank_version_ref"]
        or result.activation.plan_version_ref != data["plan_version_ref"]
        or result.activation.status != "ACTIVE"
    ):
        raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="CAT approval version mismatch")
    data["activation_ref"] = result.activation.activation_ref
    state, data = store.advance(owner, draft_ref, "SAVED", "APPROVED", data)
    return _draft_view(draft_ref, state, data)


def drafts(request: Request, actor: Actor):
    _specialist(actor)
    rows = _store(request).specialist_drafts(workspace_owner(actor))
    return (
        {
            "kind": "cat_drafts",
            "drafts": [_draft_view(ref, state, data) for ref, state, data in rows],
        },
        {"drafts": [{"draft_ref": ref, "state": state} for ref, state, _ in rows]},
    )


def handoffs(request: Request, actor: Actor):
    _admin(actor)
    rows = _store(request).handoffs(actor.school_ref)
    return (
        {
            "kind": "cat_handoffs",
            "drafts": [_draft_view(ref, "APPROVED", data) for ref, data in rows],
        },
        {"handoffs": [{"handoff_ref": ref, "due_at": data["due_at"]} for ref, data in rows]},
    )


async def authorized_handoff(
    request: Request, actor: Actor, handoff_ref: str, *, replay: bool = False
) -> dict:
    _admin(actor)
    rows = _store(request).handoffs(actor.school_ref, handoff_ref)
    if len(rows) != 1:
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="CAT handoff unavailable")
    _, handoff = rows[0]
    if handoff.get("published_task_ref"):
        if replay:
            return handoff
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT handoff was already published")
    assets = _assets(request)
    for skip in range(0, 1000, 100):
        approvals = ActivationListDto.model_validate(
            await assets.list_activations(actor, limit=100, skip=skip)
        )
        for approval in approvals.items:
            if (
                approval.activation_ref == handoff["activation_ref"]
                and approval.plan_version_ref == handoff["plan_version_ref"]
                and approval.bank_version_ref == handoff["bank_version_ref"]
                and approval.status == "ACTIVE"
            ):
                return handoff
        if not approvals.has_more:
            break
    raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT plan approval is no longer available")
