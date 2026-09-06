"""Strict authentication DTOs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from smhai_backend.domains.models import BackendRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class ActorDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    username: str
    role: BackendRole
    subject_id: str | None


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    actor: ActorDto
    csrf_token: str
    synthetic_fixture_only: bool = True


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    logged_out: bool = True


class CsrfResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    csrf_token: str
