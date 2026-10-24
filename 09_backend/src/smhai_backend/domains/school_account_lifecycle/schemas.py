"""Strict API DTOs for invitations, recovery and account status."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _password_strength(value: SecretStr) -> SecretStr:
    password = value.get_secret_value()
    categories = (
        any(char.islower() for char in password),
        any(char.isupper() for char in password),
        any(char.isdigit() for char in password),
        any(not char.isalnum() for char in password),
    )
    if sum(categories) < 3:
        raise ValueError("password does not meet strength requirements")
    return value


class LifecycleAccountSummaryDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_accounts: int = Field(ge=0)
    active_accounts: int = Field(ge=0)
    pending_activation: int = Field(ge=0)
    suspended_accounts: int = Field(ge=0)
    classes: int = Field(ge=0)
    invitations_issued: int = Field(ge=0)
    invitations_accepted: int = Field(ge=0)
    invitations_expired: int = Field(ge=0)
    invitations_revoked: int = Field(ge=0)
    recovery_queue_count: int = Field(ge=0)


class StaffInvitationRequest(RequestModel):
    employee_ref: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["teacher", "psychological_specialist"]
    work_contact: str = Field(min_length=5, max_length=160)
    verified: Literal[True]
    class_refs: list[str] = Field(max_length=50)
    delivery_channel: Literal["MANUAL"] = "MANUAL"

    @field_validator("employee_ref", "display_name", "work_contact")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be blank")
        return normalized

    @field_validator("class_refs")
    @classmethod
    def require_unique_classes(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("class_refs must be nonblank and unique")
        return normalized

    @model_validator(mode="after")
    def require_role_scoped_classes(self):
        if self.role == "teacher" and not self.class_refs:
            raise ValueError("teacher invitations require at least one class")
        if self.role == "psychological_specialist" and self.class_refs:
            raise ValueError("specialist invitations cannot grant class data access")
        return self


class StaffInvitationResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_ref: str
    status: Literal["ISSUED"]
    delivery_channel: Literal["MANUAL_HANDOFF_REQUIRED"]
    user_id: str
    login_name: str
    credential: str
    expires_at: datetime


class StaffInvitationDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_ref: str
    user_id: str
    login_name: str
    display_name: str | None
    employee_ref: str
    role: Literal["teacher", "psychological_specialist"]
    status: Literal["ISSUED", "ACCEPTED", "EXPIRED", "REVOKED"]
    delivery_channel: Literal["MANUAL"]
    class_refs: list[str]
    created_at: datetime
    expires_at: datetime


class AcceptInvitationRequest(RequestModel):
    invitation_ref: str = Field(min_length=1, max_length=128)
    credential: SecretStr = Field(min_length=20, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)
    confirm_password: SecretStr = Field(min_length=12, max_length=256)

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        return _password_strength(value)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password.get_secret_value() != self.confirm_password.get_secret_value():
            raise ValueError("password confirmation does not match")
        return self


class PublicCredentialCompletionRequest(RequestModel):
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
            raise ValueError("field must not be blank")
        return value

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        return _password_strength(value)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password.get_secret_value() != self.confirm_password.get_secret_value():
            raise ValueError("password confirmation does not match")
        return self


class RecoveryRequest(RequestModel):
    school_ref: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    class_ref: str = Field(min_length=1, max_length=128)
    reason_code: Literal["CREDENTIAL_LOST", "ACCOUNT_LOCKED", "ACCESS_PROBLEM", "OTHER"]

    @field_validator("school_ref", "username", "class_ref")
    @classmethod
    def trim_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be blank")
        return value


class RecoverySubmissionResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["REQUEST_RECEIVED"] = "REQUEST_RECEIVED"


class RecoveryActionRequest(RequestModel):
    reason_code: str = Field(min_length=2, max_length=80)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str) -> str:
        value = value.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", value) is None:
            raise ValueError("reason_code is invalid")
        return value


class StaffRecoveryCredentialRequest(RequestModel):
    reason_code: str = Field(min_length=2, max_length=80)
    verification_method: Literal["IN_PERSON", "VERIFIED_WORK_CONTACT"]
    identity_verified: Literal[True]

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str) -> str:
        value = value.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", value) is None:
            raise ValueError("reason_code is invalid")
        return value


class StaffInvitationActionRequest(RequestModel):
    reason_code: str = Field(min_length=2, max_length=80)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str) -> str:
        value = value.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", value) is None:
            raise ValueError("reason_code is invalid")
        return value


class RecoveryTicketDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_ref: str
    user_id: str
    username: str
    display_name: str | None
    class_ref: str | None
    role: Literal["student"]
    status: Literal["REQUESTED", "TEACHER_VERIFIED", "APPROVED", "REJECTED", "COMPLETED", "EXPIRED"]
    created_at: datetime


class RecoveryCredentialDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: str
    expires_at: datetime


class StaffRecoveryCredentialResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    login_name: str
    status: Literal["ISSUED"]
    delivery_channel: Literal["MANUAL_HANDOFF_REQUIRED"]
    credential: str
    expires_at: datetime


class RecoveryActionResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["TEACHER_VERIFIED", "APPROVED"]
    credential: str | None = None
    expires_at: datetime | None = None


class AccountStatusRequest(RequestModel):
    status: Literal["ACTIVE", "DISABLED"]
    reason_code: str = Field(min_length=2, max_length=80)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str) -> str:
        value = value.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", value) is None:
            raise ValueError("reason_code is invalid")
        return value


class LifecycleStatusResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
