"""Same-origin registration for the public synthetic school instance."""

from __future__ import annotations

import hashlib
import re
from time import perf_counter

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.rate_limit import InMemoryRateLimiter
from smhai_backend.core.security import validate_mutation_origin

from .router import envelope

ACTION = "psynova_demo_signup"
SITEVERIFY = "http://127.0.0.1:8189/turnstile/v0/siteverify"
NO_STORE = {"Cache-Control": "no-store"}
LOGIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{3,127}")
EMAIL_LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

router = APIRouter(prefix="/auth/public-demo", include_in_schema=False)


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: str = Field(min_length=4, max_length=128)
    password: SecretStr = Field(min_length=8, max_length=128)
    turnstile_token: SecretStr = Field(min_length=1, max_length=2048)
    synthetic_only: StrictBool

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if value.lower().startswith(("seed.", "demo.", "synthetic_")) or not (
            LOGIN_NAME.fullmatch(value) or EMAIL_LOGIN.fullmatch(value)
        ):
            raise ValueError("enter a valid username or email address")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("password cannot be blank")
        return value


async def verify_turnstile(token: str, secret: str, hostname: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.post(SITEVERIFY, json={"secret": secret, "response": token})
            response.raise_for_status()
            verdict = response.json()
    except (httpx.HTTPError, ValueError):
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="verification unavailable") from None
    if (
        not isinstance(verdict, dict)
        or verdict.get("success") is not True
        or verdict.get("hostname") != hostname
        or verdict.get("action") != ACTION
    ):
        raise error(ErrorCode.FORBIDDEN, detail="verification rejected")


@router.get("")
async def public_demo_options(request: Request) -> JSONResponse:
    config = request.app.state.container.settings.public_demo
    return JSONResponse(
        envelope(request, {"site_key": config.site_key, "action": ACTION}), headers=NO_STORE
    )


@router.post("")
async def register_public_demo(request: Request, payload: Registration) -> JSONResponse:
    container = request.app.state.container
    config = container.settings.public_demo
    assert config.secret_key is not None and config.hostname is not None
    validate_mutation_origin(request, container.settings)
    if request.headers.get("Origin") != f"https://{config.hostname}":
        raise error(ErrorCode.CSRF_FAILED, detail="browser origin is required")
    if payload.synthetic_only is not True:
        raise error(ErrorCode.VALIDATION_FAILED, detail="synthetic demo acknowledgement required")
    limiter: InMemoryRateLimiter = request.app.state.public_demo_limiter
    limiter.check("registration", "all")

    token = payload.turnstile_token.get_secret_value()
    started = perf_counter()
    await verify_turnstile(token, config.secret_key.get_secret_value(), config.hostname)
    verified_at = perf_counter()
    # Siteverify can accept nearly concurrent replays. The derived unique school
    # reference also prevents a second claim in the database transaction.
    claim = hashlib.sha256(token.encode("utf-8")).hexdigest()
    async with request.app.state.public_demo_writes:
        acquired_at = perf_counter()
        await container.persistence.provision_public_demo_school(
            payload.username,
            payload.password.get_secret_value(),
            claim,
            capacity=config.capacity,
        )
    finished_at = perf_counter()
    timing = (
        f"verification;dur={(verified_at - started) * 1000:.1f}, "
        f"queue;dur={(acquired_at - verified_at) * 1000:.1f}, "
        f"provision;dur={(finished_at - acquired_at) * 1000:.1f}"
    )
    return JSONResponse(
        envelope(request, {"username": payload.username}),
        status_code=201,
        headers={**NO_STORE, "Server-Timing": timing},
    )
