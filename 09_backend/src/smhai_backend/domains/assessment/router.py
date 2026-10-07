"""HTTP adapter for assessment lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.idempotency import (
    fingerprint,
    prior_result_async,
    remember_result_async,
    request_key,
)
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)

from .schemas import (
    AssessmentDto,
    AssessmentStartRequest,
    AssessmentStateDto,
    CompleteRequest,
    ResponseEvent,
)

router = APIRouter(prefix="/assessments", tags=["assessment"])


def envelope(request: Request, data: object) -> dict[str, object]:
    context = current_request_context(request)
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": data.model_dump(mode="json") if isinstance(data, BaseModel) else data,
    }


@router.get(
    "",
    operation_id="listAssessments",
    response_model=ApiEnvelope[list[AssessmentDto]],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED),
    summary="List assessments in the authenticated subject scope",
)
async def list_assessments(request: Request, actor: CurrentActor) -> JSONResponse:
    records = await request.app.state.container.assessments.list_for_actor(actor)
    return JSONResponse(
        envelope(
            request,
            [
                AssessmentDto.model_validate(record.assessment).model_dump(mode="json")
                for record in records
            ],
        )
    )


@router.post(
    "",
    status_code=201,
    operation_id="createAssessment",
    response_model=ApiEnvelope[AssessmentDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
    summary="Start an assessment session",
)
async def create_assessment(
    request: Request, payload: AssessmentStartRequest, actor: CsrfActor
) -> JSONResponse:
    container = request.app.state.container
    context = current_request_context(request)
    key = request_key(request)
    body_fingerprint = fingerprint(payload.model_dump(mode="json"))
    if key:
        prior = await prior_result_async(
            container.idempotency,
            scope=f"{actor.user_id}:assessment:create",
            key=key,
            request_fingerprint=body_fingerprint,
        )
        if prior is not None:
            return JSONResponse(prior, status_code=201)
    record = await container.assessments.create(
        actor, payload, request_id=context.request_id, trace_id=context.trace_id
    )
    body = envelope(request, AssessmentDto.model_validate(record.assessment))
    await remember_result_async(
        container.idempotency,
        scope=f"{actor.user_id}:assessment:create",
        key=key,
        request_fingerprint=body_fingerprint,
        status_code=201,
        body=body,
    )
    return JSONResponse(body, status_code=201)


@router.post(
    "/{assessment_id}/responses",
    operation_id="recordAssessmentResponse",
    response_model=ApiEnvelope[AssessmentStateDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
    summary="Record an assessment response",
)
async def record_response(
    request: Request, assessment_id: str, payload: ResponseEvent, actor: CsrfActor
) -> JSONResponse:
    container = request.app.state.container
    context = current_request_context(request)
    key = request_key(request)
    body_fingerprint = fingerprint(
        {"assessment_id": assessment_id, **payload.model_dump(mode="json")}
    )
    scope = f"{actor.user_id}:assessment:response:{assessment_id}"
    if key:
        prior = await prior_result_async(
            container.idempotency, scope=scope, key=key, request_fingerprint=body_fingerprint
        )
        if prior is not None:
            return JSONResponse(prior)
    record = await container.assessments.submit(
        actor, assessment_id, payload, request_id=context.request_id, trace_id=context.trace_id
    )
    body = envelope(
        request,
        AssessmentStateDto(
            assessment_id=record.assessment_id,
            subject_id=record.subject_id,
            status=record.assessment["status"],
            selected_item_id=record.selected_item_id,
            current_item=record.current_item,
            current_index=record.current_index,
            answered_count=record.answered_count,
            administered_count=record.administered_count,
            can_complete=record.can_complete,
            max_items=record.max_items,
            cat_provider_version=record.cat_provider_version,
            cat_item_bank_version=record.cat_item_bank_version,
            cat_config_version=record.cat_config_version,
        ),
    )
    await remember_result_async(
        container.idempotency,
        scope=scope,
        key=key,
        request_fingerprint=body_fingerprint,
        status_code=200,
        body=body,
    )
    return JSONResponse(body)


@router.post(
    "/{assessment_id}/complete",
    operation_id="completeAssessment",
    response_model=ApiEnvelope[AssessmentDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
    summary="Complete an assessment",
)
async def complete_assessment(
    request: Request, assessment_id: str, payload: CompleteRequest, actor: CsrfActor
) -> JSONResponse:
    container = request.app.state.container
    context = current_request_context(request)
    key = request_key(request)
    body_fingerprint = fingerprint({"assessment_id": assessment_id})
    scope = f"{actor.user_id}:assessment:complete:{assessment_id}"
    if key:
        prior = await prior_result_async(
            container.idempotency, scope=scope, key=key, request_fingerprint=body_fingerprint
        )
        if prior is not None:
            return JSONResponse(prior)
    record = await container.assessments.complete(
        actor, assessment_id, request_id=context.request_id, trace_id=context.trace_id
    )
    body = envelope(request, AssessmentDto.model_validate(record.assessment))
    await remember_result_async(
        container.idempotency,
        scope=scope,
        key=key,
        request_fingerprint=body_fingerprint,
        status_code=200,
        body=body,
    )
    return JSONResponse(body)


@router.get(
    "/{assessment_id}/state",
    operation_id="getAssessmentState",
    response_model=ApiEnvelope[AssessmentStateDto],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.RESOURCE_NOT_FOUND),
    summary="Read CAT presentation state",
)
async def get_assessment_state(
    request: Request, assessment_id: str, actor: CurrentActor
) -> JSONResponse:
    context = current_request_context(request)
    record = await request.app.state.container.assessments.state_for_actor(
        actor,
        assessment_id,
        action="assessment:read",
        request_id=context.request_id,
        trace_id=context.trace_id,
    )
    data = AssessmentStateDto(
        assessment_id=record.assessment_id,
        subject_id=record.subject_id,
        status=record.assessment["status"],
        selected_item_id=record.selected_item_id,
        current_item=record.current_item,
        current_index=record.current_index,
        answered_count=record.answered_count,
        administered_count=record.administered_count,
        can_complete=record.can_complete,
        max_items=record.max_items,
        cat_provider_version=record.cat_provider_version,
        cat_item_bank_version=record.cat_item_bank_version,
        cat_config_version=record.cat_config_version,
    )
    return JSONResponse(envelope(request, data))


@router.get(
    "/{assessment_id}",
    operation_id="getAssessment",
    response_model=ApiEnvelope[AssessmentDto],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.RESOURCE_NOT_FOUND),
    summary="Read an authorized assessment",
)
async def get_assessment(request: Request, assessment_id: str, actor: CurrentActor) -> JSONResponse:
    context = current_request_context(request)
    record = await request.app.state.container.assessments.get_for_actor(
        actor,
        assessment_id,
        action="assessment:read",
        request_id=context.request_id,
        trace_id=context.trace_id,
    )
    return JSONResponse(envelope(request, AssessmentDto.model_validate(record.assessment)))
