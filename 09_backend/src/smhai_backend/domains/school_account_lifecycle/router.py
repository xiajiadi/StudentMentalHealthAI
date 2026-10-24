"""HTTP routes for scoped school account lifecycle tasks."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.request_context import current_request_context
from smhai_backend.core.security import credential_identity, validate_mutation_origin
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    PUBLIC_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
    RecentReauthenticatedCsrfActor,
)

from .schemas import (
    AcceptInvitationRequest,
    AccountStatusRequest,
    LifecycleAccountSummaryDto,
    LifecycleStatusResponseDto,
    PublicCredentialCompletionRequest,
    RecoveryActionRequest,
    RecoveryActionResponseDto,
    RecoveryRequest,
    RecoverySubmissionResponseDto,
    RecoveryTicketDto,
    StaffInvitationActionRequest,
    StaffInvitationDto,
    StaffInvitationRequest,
    StaffInvitationResponseDto,
    StaffRecoveryCredentialRequest,
    StaffRecoveryCredentialResponseDto,
)

router = APIRouter(tags=["school-account-lifecycle"])


def _trace_id(request: Request) -> str:
    return current_request_context(request).trace_id


def _body(request: Request, data: object) -> dict[str, object]:
    value = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    context = current_request_context(request)
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": jsonable_encoder(value),
    }


def _no_store(data: dict[str, object], status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=data,
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _public_rate_limit(request: Request, username: str) -> None:
    container = request.app.state.container
    host = request.client.host if request.client else "unknown"
    container.rate_limiter.check("login", f"{host}:{credential_identity(username)}")


@router.get(
    "/school/admin/accounts/summary",
    response_model=ApiEnvelope[LifecycleAccountSummaryDto],
    include_in_schema=False,
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def account_summary(request: Request, actor: CurrentActor):
    result = await request.app.state.container.school_account_lifecycle.account_summary(actor)
    return JSONResponse(_body(request, LifecycleAccountSummaryDto.model_validate(result)))


@router.post(
    "/school/admin/staff/invitations",
    response_model=ApiEnvelope[StaffInvitationResponseDto],
    status_code=201,
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
)
async def create_staff_invitation(
    request: Request,
    payload: StaffInvitationRequest,
    actor: RecentReauthenticatedCsrfActor,
):
    container = request.app.state.container
    result = await container.school_account_lifecycle.create_staff_invitation(
        actor,
        payload,
        ttl_seconds=container.settings.auth.staff_invitation_ttl_seconds,
        trace_id=_trace_id(request),
    )
    return _no_store(_body(request, StaffInvitationResponseDto.model_validate(result)), 201)


@router.get(
    "/school/admin/staff/invitations",
    response_model=ApiEnvelope[list[StaffInvitationDto]],
    include_in_schema=False,
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_staff_invitations(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.school_account_lifecycle.list_staff_invitations(actor)
    return JSONResponse(_body(request, [StaffInvitationDto.model_validate(row) for row in rows]))


@router.post(
    "/school/admin/staff/invitations/{invitation_ref}/revoke",
    response_model=ApiEnvelope[LifecycleStatusResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def revoke_staff_invitation(
    request: Request,
    invitation_ref: str,
    payload: StaffInvitationActionRequest,
    actor: RecentReauthenticatedCsrfActor,
):
    result = await request.app.state.container.school_account_lifecycle.revoke_staff_invitation(
        actor,
        invitation_ref,
        reason_code=payload.reason_code,
        trace_id=_trace_id(request),
    )
    return JSONResponse(_body(request, LifecycleStatusResponseDto.model_validate(result)))


@router.post(
    "/school/admin/staff/invitations/{invitation_ref}/reissue",
    response_model=ApiEnvelope[StaffInvitationResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def reissue_staff_invitation(
    request: Request,
    invitation_ref: str,
    payload: StaffInvitationActionRequest,
    actor: RecentReauthenticatedCsrfActor,
):
    container = request.app.state.container
    result = await container.school_account_lifecycle.reissue_staff_invitation(
        actor,
        invitation_ref,
        reason_code=payload.reason_code,
        ttl_seconds=container.settings.auth.staff_invitation_ttl_seconds,
        trace_id=_trace_id(request),
    )
    return _no_store(_body(request, StaffInvitationResponseDto.model_validate(result)))


@router.post(
    "/school/admin/staff/{user_id}/recovery-credential",
    response_model=ApiEnvelope[StaffRecoveryCredentialResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def issue_staff_recovery_credential(
    request: Request,
    user_id: str,
    payload: StaffRecoveryCredentialRequest,
    actor: RecentReauthenticatedCsrfActor,
):
    container = request.app.state.container
    result = await container.school_account_lifecycle.issue_staff_recovery_credential(
        actor,
        user_id,
        reason_code=payload.reason_code,
        verification_method=payload.verification_method,
        ttl_seconds=container.settings.auth.password_reset_ttl_seconds,
        trace_id=_trace_id(request),
    )
    return _no_store(_body(request, StaffRecoveryCredentialResponseDto.model_validate(result)))


@router.post(
    "/auth/staff-invitations/accept",
    response_model=ApiEnvelope[LifecycleStatusResponseDto],
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_INVALID_CREDENTIALS,
        ErrorCode.RATE_LIMITED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.CSRF_FAILED,
    ),
)
async def accept_staff_invitation(request: Request, payload: AcceptInvitationRequest):
    container = request.app.state.container
    validate_mutation_origin(request, container.settings)
    _public_rate_limit(request, payload.invitation_ref)
    result = await container.school_account_lifecycle.accept_staff_invitation(
        invitation_ref=payload.invitation_ref,
        token_hash=hashlib.sha256(payload.credential.get_secret_value().encode("utf-8")).digest(),
        new_password=payload.new_password.get_secret_value(),
        trace_id=_trace_id(request),
    )
    return _no_store(_body(request, LifecycleStatusResponseDto.model_validate(result)))


@router.post(
    "/auth/recovery-requests",
    response_model=ApiEnvelope[RecoverySubmissionResponseDto],
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.RATE_LIMITED,
        ErrorCode.CSRF_FAILED,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
    ),
)
async def submit_recovery_request(request: Request, payload: RecoveryRequest):
    container = request.app.state.container
    validate_mutation_origin(request, container.settings)
    _public_rate_limit(request, payload.username)
    result = await container.school_account_lifecycle.create_recovery_request(
        school_ref=payload.school_ref,
        username=payload.username,
        class_ref=payload.class_ref,
        reason_code=payload.reason_code,
        trace_id=_trace_id(request),
    )
    return _no_store(_body(request, RecoverySubmissionResponseDto.model_validate(result)))


@router.get(
    "/school/admin/recovery-requests",
    response_model=ApiEnvelope[list[RecoveryTicketDto]],
    include_in_schema=False,
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_recovery_requests(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.school_account_lifecycle.list_recovery_requests(actor)
    return JSONResponse(_body(request, [RecoveryTicketDto.model_validate(row) for row in rows]))


@router.post(
    "/school/teacher/recovery-requests/{ticket_ref}/verify",
    response_model=ApiEnvelope[RecoveryActionResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def verify_recovery_request(
    request: Request,
    ticket_ref: str,
    payload: RecoveryActionRequest,
    actor: CsrfActor,
):
    result = await request.app.state.container.school_account_lifecycle.verify_recovery_request(
        actor, ticket_ref, reason_code=payload.reason_code, trace_id=_trace_id(request)
    )
    return JSONResponse(_body(request, RecoveryActionResponseDto.model_validate(result)))


@router.post(
    "/school/admin/recovery-requests/{ticket_ref}/approve",
    response_model=ApiEnvelope[RecoveryActionResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def approve_recovery_request(
    request: Request,
    ticket_ref: str,
    payload: RecoveryActionRequest,
    actor: RecentReauthenticatedCsrfActor,
):
    container = request.app.state.container
    result = await container.school_account_lifecycle.approve_recovery_request(
        actor,
        ticket_ref,
        reason_code=payload.reason_code,
        ttl_seconds=container.settings.auth.password_reset_ttl_seconds,
        trace_id=_trace_id(request),
    )
    return _no_store(_body(request, RecoveryActionResponseDto.model_validate(result)))


@router.post(
    "/auth/password/reset/complete",
    response_model=ApiEnvelope[LifecycleStatusResponseDto],
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_INVALID_CREDENTIALS,
        ErrorCode.RATE_LIMITED,
        ErrorCode.CSRF_FAILED,
    ),
)
async def complete_password_reset(request: Request, payload: PublicCredentialCompletionRequest):
    container = request.app.state.container
    validate_mutation_origin(request, container.settings)
    _public_rate_limit(request, payload.username)
    result = await container.school_account_lifecycle.complete_password_reset(
        school_ref=payload.school_ref,
        username=payload.username,
        token_hash=hashlib.sha256(payload.credential.get_secret_value().encode("utf-8")).digest(),
        new_password=payload.new_password.get_secret_value(),
        trace_id=_trace_id(request),
    )
    return _no_store(_body(request, LifecycleStatusResponseDto.model_validate(result)))


@router.post(
    "/school/admin/accounts/{user_id}/status",
    response_model=ApiEnvelope[LifecycleStatusResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    include_in_schema=False,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def set_account_status(
    request: Request,
    user_id: str,
    payload: AccountStatusRequest,
    actor: RecentReauthenticatedCsrfActor,
):
    result = await request.app.state.container.school_account_lifecycle.set_account_status(
        actor,
        user_id,
        status=payload.status,
        reason_code=payload.reason_code,
        trace_id=_trace_id(request),
    )
    return JSONResponse(_body(request, LifecycleStatusResponseDto.model_validate(result)))
