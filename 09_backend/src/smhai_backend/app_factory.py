"""Application factory with no network work at import time."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from smhai_backend.container import BackendContainer, build_container
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.errors import (
    BackendError,
    backend_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from smhai_backend.domains.assessment.router import router as assessment_router
from smhai_backend.domains.auth.router import router as auth_router
from smhai_backend.domains.cat_assets.router import router as cat_assets_router
from smhai_backend.domains.cat_management.router import router as cat_management_router
from smhai_backend.domains.conversations.router import router as conversations_router
from smhai_backend.domains.health.router import router as health_router
from smhai_backend.domains.professional_reviews.router import router as professional_reviews_router
from smhai_backend.domains.school_directory.router import router as school_directory_router
from smhai_backend.domains.school_feedback.router import router as school_feedback_router
from smhai_backend.domains.school_tasks.router import router as school_tasks_router
from smhai_backend.domains.support.router import router as support_router
from smhai_backend.domains.teacher.router import router as teacher_router
from smhai_backend.lifespan import make_lifespan


def create_app(
    *,
    settings: BackendSettings | None = None,
    container: BackendContainer | None = None,
) -> FastAPI:
    settings = settings or BackendSettings()
    container = container or build_container(settings)
    app = FastAPI(
        title="StudentMentalHealthAI Backend Orchestrator",
        version="0.1.0",
        description=(
            "MODULE-LOCAL PROVISIONAL API for safe education-support orchestration. "
            "This service does not provide diagnosis or treatment."
        ),
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=make_lifespan(container),
    )
    app.state.container = container
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-CSRF-Token",
            "X-Request-ID",
            "X-Trace-ID",
            "Idempotency-Key",
        ],
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware, settings=settings)
    app.include_router(health_router)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(assessment_router, prefix=settings.api_prefix)
    app.include_router(support_router, prefix=settings.api_prefix)
    # These endpoints are a local M0 projection extension, not a change to the
    # frozen shared api.v1 OpenAPI contract.
    app.include_router(teacher_router, prefix=settings.api_prefix, include_in_schema=False)
    app.include_router(school_tasks_router, prefix=settings.api_prefix, include_in_schema=False)
    app.include_router(school_directory_router, prefix=settings.api_prefix, include_in_schema=False)
    app.include_router(school_feedback_router, prefix=settings.api_prefix, include_in_schema=False)
    app.include_router(conversations_router, prefix=settings.api_prefix, include_in_schema=False)
    app.include_router(
        professional_reviews_router, prefix=settings.api_prefix, include_in_schema=False
    )
    app.include_router(cat_management_router, prefix=settings.api_prefix, include_in_schema=False)
    app.include_router(cat_assets_router, prefix=settings.api_prefix, include_in_schema=False)
    return app
