"""HTTP adapter for retrieval, support, generation, reports, and reviews."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.idempotency import (
    fingerprint,
    prior_result_async,
    remember_result_async,
    request_key,
)
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CsrfActor, CurrentActor
from smhai_backend.domains.models import BackendRole

from .schemas import (
    GenerationRequest,
    ReportDto,
    RetrievalRequest,
    ReviewProjectionDto,
    ReviewRequest,
    SafetyRequest,
    SupportRequest,
)

router = APIRouter(tags=["support", "retrieval", "generation", "report"])


def review_dto(item) -> ReviewProjectionDto:
    return ReviewProjectionDto.model_validate(
        {
            "review_id": item.review_id,
            "report_id": item.report_id,
            "assessment_id": item.assessment_id,
            "generation_id": item.generation_id,
            "status": item.status,
            "reason_codes": item.reason_codes,
            "safety_action": item.safety_action,
            "safety_review_case_id": item.safety_review_case_id,
        }
    )


def envelope(request: Request, data: object) -> dict[str, object]:
    context = current_request_context(request)
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": data.model_dump(mode="json") if isinstance(data, BaseModel) else data,
    }


@router.post("/retrievals", summary="Retrieve contract-shaped citations")
async def create_retrieval(
    request: Request, payload: RetrievalRequest, actor: CsrfActor
) -> JSONResponse:
    container = request.app.state.container
    result = await container.support.retrieve(
        actor, payload, context=current_request_context(request)
    )
    data = {
        "retrieval_id": result.retrieval_id,
        "chunks": [chunk.model_dump(mode="json") for chunk in result.chunks],
    }
    return JSONResponse(envelope(request, data))


@router.post("/safety/checks", summary="Run a Safety decision")
async def check_safety(request: Request, payload: SafetyRequest, actor: CsrfActor) -> JSONResponse:
    candidate = payload.generation_candidate
    candidate_text = None
    if isinstance(candidate, dict):
        value = candidate.get("text")
        if isinstance(value, str):
            candidate_text = value
    check = await request.app.state.container.support.safety_check(
        actor,
        payload.assessment_id,
        candidate_text,
        context=current_request_context(request),
    )
    decision_map = {
        "PROCEED": "allow",
        "PROCEED_WITH_BOUNDARY": "warn",
        "BLOCK": "block",
        "REVIEW_REQUIRED": "needs_review",
        "CRISIS_ROUTE": "needs_review",
    }
    data = {
        "decision": decision_map[check.decision.action],
        "reason_codes": check.decision.reason_codes,
        "human_review_required": check.decision.requires_human,
        "safety_action": check.decision.action,
    }
    return JSONResponse(envelope(request, data))


@router.post("/support/requests", status_code=202, summary="Create a buffered support result")
async def create_support(
    request: Request, payload: SupportRequest, actor: CsrfActor
) -> JSONResponse:
    container = request.app.state.container
    container.rate_limiter.check("support", actor.user_id)
    context = current_request_context(request)
    key = request_key(request)
    body_fingerprint = fingerprint(payload.model_dump(mode="json"))
    scope = f"{actor.user_id}:support:create"
    if key:
        prior = await prior_result_async(
            container.idempotency, scope=scope, key=key, request_fingerprint=body_fingerprint
        )
        if prior is not None:
            return JSONResponse(prior, status_code=202)
    result = await container.support.create(actor, payload, context=context)
    body = envelope(request, result)
    await remember_result_async(
        container.idempotency,
        scope=scope,
        key=key,
        request_fingerprint=body_fingerprint,
        status_code=202,
        body=body,
    )
    return JSONResponse(body, status_code=202)


@router.post("/generations", status_code=202, summary="Create a frozen generation result")
async def create_generation(
    request: Request, payload: GenerationRequest, actor: CsrfActor
) -> JSONResponse:
    container = request.app.state.container
    container.rate_limiter.check("support", actor.user_id)
    context = current_request_context(request)
    key = request_key(request)
    body_fingerprint = fingerprint(payload.model_dump(mode="json"))
    scope = f"{actor.user_id}:generation:create"
    if key:
        prior = await prior_result_async(
            container.idempotency, scope=scope, key=key, request_fingerprint=body_fingerprint
        )
        if prior is not None:
            return JSONResponse(prior, status_code=202)
    support_payload = SupportRequest(
        assessment_id=payload.assessment_id,
        target_role=payload.target_role,
        message="Synthetic structured generation request",
        language=payload.language,
    )
    result = await container.support.create(
        actor,
        support_payload,
        context=context,
        generation_id=payload.generation_id,
        retrieval_id_hint=payload.retrieval.retrieval_id,
        prompt_id=payload.prompt_ref.prompt_id,
        prompt_version=payload.prompt_ref.prompt_version,
        model_id=payload.model_policy.model_id,
        provider_class=payload.model_policy.provider_class,
        message_override="Synthetic structured generation request",
    )
    body = envelope(request, result.generation)
    await remember_result_async(
        container.idempotency,
        scope=scope,
        key=key,
        request_fingerprint=body_fingerprint,
        status_code=202,
        body=body,
    )
    return JSONResponse(body, status_code=202)


@router.get("/reports/{report_id}", summary="Read an authorized report projection")
async def get_report(request: Request, report_id: str, actor: CurrentActor) -> JSONResponse:
    report = await request.app.state.container.support.report_for_actor(actor, report_id)
    expose_generation = actor.role in {
        BackendRole.STUDENT,
        BackendRole.REVIEWER,
        BackendRole.ADMIN,
    }
    data = ReportDto(
        report_id=report.report_id,
        assessment_id=report.assessment_id,
        status=report.status,
        generation_ids=[report.generation_id],
        review_status=report.review_status,
        review_id=report.review_id,
        generation=report.generation
        if expose_generation and report.status == "generated"
        else None,
    )
    return JSONResponse(envelope(request, data))


@router.post("/reports/{report_id}/reviews", summary="Action a review projection")
async def review_report(
    request: Request, report_id: str, payload: ReviewRequest, actor: CsrfActor
) -> JSONResponse:
    if actor.role not in {BackendRole.REVIEWER, BackendRole.ADMIN}:
        from smhai_backend.core.errors import ErrorCode, error

        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    projection = await request.app.state.container.support.review(
        actor,
        report_id,
        payload.decision,
        context=current_request_context(request),
    )
    data = {
        "report_id": report_id,
        "review_status": projection.status,
        "review_id": projection.review_id,
    }
    return JSONResponse(envelope(request, data))


@router.get("/reviews", summary="List pending review projections")
async def list_reviews(request: Request, actor: CurrentActor) -> JSONResponse:
    projections = await request.app.state.container.support.pending_reviews(actor)
    data = [review_dto(item).model_dump(mode="json") for item in projections]
    return JSONResponse(envelope(request, data))


@router.get("/reviews/{review_id}", summary="Read a review projection")
async def get_review(request: Request, review_id: str, actor: CurrentActor) -> JSONResponse:
    projection = await request.app.state.container.support.review_detail(actor, review_id)
    return JSONResponse(envelope(request, review_dto(projection)))
