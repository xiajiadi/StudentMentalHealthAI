"""Strict authentication DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from smhai_backend.domains.models import BackendRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class RoleContextDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: BackendRole
    school_ref: str


class ActorDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    username: str
    role: BackendRole
    subject_id: str | None
    authorized_roles: list[BackendRole] = Field(default_factory=list)
    available_contexts: list[RoleContextDto] = Field(default_factory=list)
    active_context: RoleContextDto | None = None


class ActiveContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal[
        BackendRole.STUDENT,
        BackendRole.TEACHER,
        BackendRole.PSYCHOLOGICAL_SPECIALIST,
        BackendRole.ADMIN,
    ]
    school_ref: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    actor: ActorDto
    csrf_token: str
    synthetic_fixture_only: bool = True


class ReauthenticateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=256)


class ReauthenticateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reauthenticated_at: datetime


class CompleteInitialLoginRequest(BaseModel):
    """One-time credential exchange; secrets stay masked in model reprs."""

    model_config = ConfigDict(extra="forbid")

    school_ref: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    credential: SecretStr = Field(min_length=20, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)
    confirm_password: SecretStr = Field(min_length=12, max_length=256)

    @field_validator("school_ref", "username")
    @classmethod
    def trim_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("identity fields must not be blank")
        return value

    @field_validator("new_password")
    @classmethod
    def require_password_strength(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        categories = (
            any(char.islower() for char in password),
            any(char.isupper() for char in password),
            any(char.isdigit() for char in password),
            any(not char.isalnum() for char in password),
        )
        if sum(categories) < 3:
            raise ValueError("new_password does not meet strength requirements")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password.get_secret_value() != self.confirm_password.get_secret_value():
            raise ValueError("password confirmation does not match")
        return self


class CompleteInitialLoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "PASSWORD_SET"


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    logged_out: bool = True


class CsrfResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    csrf_token: str
