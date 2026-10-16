"""Independent research education release endpoints (not the frozen shared API)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from smhai_backend.core.errors import ErrorCode, error, problem_responses
from smhai_backend.core.idempotency import request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)

from .schemas import (
    EducationReviewStateRequest,
    IndependentEducationReviewerListDto,
    IndependentEducationReviewPageDto,
    IndependentEducationStaffDetailDto,
    IndependentEducationStaffPageDto,
    SaveEducationReviewDraftRequest,
    ShareEducationReviewRequest,
)

student_router = APIRouter(
    prefix="/student/research-conversations",
    tags=["student-independent-education-reviews"],
)
staff_router = APIRouter(
    prefix="/school/independent-education-reviews",
    tags=["school-independent-education-reviews"],
)
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.CSRF_FAILED,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
)


def _service(request: Request):
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "independent_education_reviews", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="independent education reviews are unavailable",
            retryable=True,
        )
    return service


def _key(request: Request) -> str:
    value = request_key(request)
    if value is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
    return value


def _response(request: Request, value, *, status: int = 200):
    context = current_request_context(request)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(value),
        },
        status_code=status,
    )


@student_router.get(
    "/{conversation_id}/education-reviews",
    response_model=None,
    responses=_ERRORS,
)
async def student_reviews(
    request: Request,
    conversation_id: Annotated[str, Path(min_length=1, max_length=128)],
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    value = await _service(request).student_list(actor, conversation_id, offset=offset, limit=limit)
    return _response(request, IndependentEducationReviewPageDto.model_validate(value, strict=True))


@student_router.get(
    "/{conversation_id}/education-reviewers",
    responses=_ERRORS,
)
async def student_reviewers(
    request: Request,
    conversation_id: Annotated[str, Path(min_length=1, max_length=128)],
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    value = await _service(request).student_reviewers(
        actor, conversation_id, offset=offset, limit=limit
    )
    return _response(
        request, IndependentEducationReviewerListDto.model_validate(value, strict=True)
    )


@student_router.post(
    "/{conversation_id}/education-reviews/{review_ref}/share",
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def share_review(
    request: Request,
    conversation_id: Annotated[str, Path(min_length=1, max_length=128)],
    review_ref: Annotated[str, Path(pattern=r"^EDUREV_[0-9a-f]{32}$")],
    payload: ShareEducationReviewRequest,
    actor: CsrfActor,
):
    review = await _service(request).share(
        actor,
        conversation_id,
        review_ref,
        payload=payload,
        idempotency_key=_key(request),
        context=current_request_context(request),
    )
    return _response(request, {"education_review": review.model_dump(mode="json")})


@student_router.post(
    "/{conversation_id}/education-reviews/{review_ref}/withdraw",
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def withdraw_review(
    request: Request,
    conversation_id: Annotated[str, Path(min_length=1, max_length=128)],
    review_ref: Annotated[str, Path(pattern=r"^EDUREV_[0-9a-f]{32}$")],
    payload: EducationReviewStateRequest,
    actor: CsrfActor,
):
    review = await _service(request).withdraw(
        actor,
        conversation_id,
        review_ref,
        payload=payload,
        idempotency_key=_key(request),
        context=current_request_context(request),
    )
    return _response(request, {"education_review": review.model_dump(mode="json")})


@staff_router.get("", responses=_ERRORS)
async def staff_reviews(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    value = await _service(request).staff_list(actor, offset=offset, limit=limit)
    return _response(request, IndependentEducationStaffPageDto.model_validate(value, strict=True))


@staff_router.get("/{review_ref}", responses=_ERRORS)
async def staff_review_detail(
    request: Request,
    review_ref: Annotated[str, Path(pattern=r"^EDUREV_[0-9a-f]{32}$")],
    actor: CurrentActor,
):
    value = await _service(request).staff_detail(actor, review_ref)
    return _response(request, IndependentEducationStaffDetailDto.model_validate(value, strict=True))


@staff_router.post(
    "/{review_ref}/draft",
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def save_review_draft(
    request: Request,
    review_ref: Annotated[str, Path(pattern=r"^EDUREV_[0-9a-f]{32}$")],
    payload: SaveEducationReviewDraftRequest,
    actor: CsrfActor,
):
    value = await _service(request).save_draft(
        actor,
        review_ref,
        payload=payload,
        idempotency_key=_key(request),
        context=current_request_context(request),
    )
    return _response(request, {"education_review": value.model_dump(mode="json")})


@staff_router.post(
    "/{review_ref}/publish",
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def publish_review(
    request: Request,
    review_ref: Annotated[str, Path(pattern=r"^EDUREV_[0-9a-f]{32}$")],
    payload: EducationReviewStateRequest,
    actor: CsrfActor,
):
    value = await _service(request).publish(
        actor,
        review_ref,
        payload=payload,
        idempotency_key=_key(request),
        context=current_request_context(request),
    )
    return _response(request, {"education_review": value.model_dump(mode="json")})


@staff_router.post(
    "/{review_ref}/revoke",
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def revoke_review(
    request: Request,
    review_ref: Annotated[str, Path(pattern=r"^EDUREV_[0-9a-f]{32}$")],
    payload: EducationReviewStateRequest,
    actor: CsrfActor,
):
    value = await _service(request).revoke(
        actor,
        review_ref,
        payload=payload,
        idempotency_key=_key(request),
        context=current_request_context(request),
    )
    return _response(request, {"education_review": value.model_dump(mode="json")})
