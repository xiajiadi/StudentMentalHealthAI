"""Internal FastAPI app.  It binds to loopback by default and never changes the root API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from safety_engine.domain import (
    ActorRole,
    DisclosurePolicy,
    ReviewStatus,
    SafetyContext,
    SafetyError,
)
from safety_engine.service import SafetyService

from .factory import RuntimeBundle, build_default_bundle


class InputCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: SafetyContext


class OutputCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: SafetyContext
    candidate_text: str = Field(min_length=1, max_length=20_000)


class RetrievalCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: SafetyContext
    chunks: list[dict[str, Any]] = Field(max_length=200)


class ReviewTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: ReviewStatus
    actor_id: str = "synthetic-reviewer-001"


class ReviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=5, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    reason_codes: list[str] = Field(min_length=1, max_length=40)
    actor_role: ActorRole
    disclosure_policy: DisclosurePolicy


def create_app(
    *, service: SafetyService | None = None, bundle: RuntimeBundle | None = None
) -> FastAPI:
    service_is_injected = service is not None
    use_default_bundle = bundle is None and not service_is_injected
    if use_default_bundle:
        bundle = build_default_bundle()
    if service is None:
        service = bundle.service  # type: ignore[union-attr]
    if getattr(getattr(service, "retrieval", None), "integration_status", None) == "RESEARCH_ONLY":
        raise ValueError("research-only retrieval must use its isolated host")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = bundle.opa_manager if bundle else None
        if use_default_bundle and bundle:
            bundle.service.qwen.load()
        if manager:
            try:
                manager.start()
                app.state.opa_start_error = None
            except SafetyError as exc:
                app.state.opa_start_error = exc.code.value
        yield
        if manager:
            manager.stop()

    app = FastAPI(
        title="StudentMentalHealthAI Safety Control Plane",
        version="0.1.0",
        docs_url="/internal/safety/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.safety_service = service

    @app.exception_handler(SafetyError)
    async def safety_error_handler(_: Request, exc: SafetyError):
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": exc.code.value,
                    "retryable": exc.retryable,
                    "message": "safety control plane unavailable",
                }
            },
        )

    @app.get("/health/live")
    async def health_live():
        return {"status": "LIVE", "service": "safety_control_plane", "version": "0.1.0"}

    @app.get("/health/ready")
    async def health_ready():
        health = service.health()
        ready = all(item.ready for item in health.values())
        payload = {"status": "READY" if ready else "NOT_READY", "components": _dump_health(health)}
        if not ready:
            raise HTTPException(status_code=503, detail=payload)
        return payload

    @app.get("/health")
    async def health():
        health = service.health()
        return {
            "status": "READY" if all(item.ready for item in health.values()) else "DEGRADED",
            "components": _dump_health(health),
        }

    @app.post("/internal/safety/check-input")
    async def check_input(request: InputCheckRequest):
        return (await service.precheck(request.context)).model_dump(mode="json")

    @app.post("/internal/safety/decide")
    async def decide(request: InputCheckRequest):
        return (await service.precheck(request.context)).model_dump(mode="json")

    @app.post("/internal/safety/check-output")
    async def check_output(request: OutputCheckRequest):
        return (await service.postcheck(request.context, request.candidate_text)).model_dump(
            mode="json"
        )

    @app.post("/internal/safety/check-retrieval")
    async def check_retrieval(request: RetrievalCheckRequest):
        return (await service.check_retrieval(request.context, request.chunks)).model_dump(
            mode="json"
        )

    @app.get("/internal/safety/reviews/{review_case_id}")
    async def get_review(review_case_id: str):
        case = service.review.repository.get(review_case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="review case not found")
        return case.model_dump(mode="json")

    @app.post("/internal/safety/reviews")
    async def create_review(request: ReviewCreateRequest):
        case = service.review.create(
            decision_id=request.decision_id,
            trace_id=request.trace_id,
            reason_codes=request.reason_codes,
            actor_role=request.actor_role,
            disclosure_policy=request.disclosure_policy,
        )
        return case.model_dump(mode="json")

    @app.post("/internal/safety/reviews/{review_case_id}/transition")
    async def transition_review(review_case_id: str, request: ReviewTransitionRequest):
        case = service.review.transition(
            review_case_id, request.to_status, actor_id=request.actor_id
        )
        return case.model_dump(mode="json")

    return app


def _dump_health(health: dict[str, Any]) -> dict[str, Any]:
    return {name: item.model_dump(mode="json") for name, item in health.items()}


def main() -> None:
    app = create_app()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8190,
        log_level="info",
        access_log=False,
        server_header=False,
        date_header=False,
    )


if __name__ == "__main__":
    main()
