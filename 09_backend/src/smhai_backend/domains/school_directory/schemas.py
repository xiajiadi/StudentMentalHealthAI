"""Strict, module-local DTOs for school directory operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class SchoolDirectoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _clean_display_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("display_name must not be blank")
    return value


class DisplayNameRequest(SchoolDirectoryRequest):
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        return _clean_display_name(value)


class AccountImportRow(SchoolDirectoryRequest):
    row_no: int = Field(gt=0)
    login_name: str = Field(min_length=1, max_length=112)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["student", "teacher"]

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        return _clean_display_name(value)


class AccountBatchRequest(SchoolDirectoryRequest):
    class_ref: str | None = Field(default=None, min_length=1, max_length=128)
    rows: list[AccountImportRow] = Field(min_length=1, max_length=100)

    @field_validator("class_ref")
    @classmethod
    def trim_class_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("class_ref must not be blank")
        return value


class AccountImportErrorDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_no: int = Field(gt=0)
    code: Literal[
        "INVALID_ROW_NUMBER",
        "DUPLICATE_ROW_NUMBER",
        "INVALID_LOGIN_NAME",
        "BLANK_DISPLAY_NAME",
        "DUPLICATE_LOGIN_NAME",
        "LOGIN_UNAVAILABLE",
        "CLASS_UNAVAILABLE",
    ]


class AccountImportPreviewDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    row_count: int = Field(ge=0, le=100)
    errors: list[AccountImportErrorDto]


class DirectorySchoolDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school_ref: str
    display_name: str | None


class DirectoryClassDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_ref: str
    display_name: str | None
    status: str
    active_student_count: int = Field(ge=0)
    active_teacher_count: int = Field(ge=0)


class DirectoryMemberDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    display_name: str | None
    role: Literal["student", "teacher"]
    account_status: Literal["ACTIVE", "SUSPENDED", "DISABLED"]
    provisioning_status: Literal["PENDING_ACTIVATION", "ACTIVE"] | None


class SchoolDirectoryDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school: DirectorySchoolDto
    classes: list[DirectoryClassDto]
    members: list[DirectoryMemberDto]


class AccountBatchMemberDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_no: int = Field(gt=0)
    user_id: str
    display_name: str
    role: Literal["student", "teacher"]
    status: Literal["PENDING_ACTIVATION", "ACTIVE"]


class AccountBatchDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_ref: str
    created_count: int = Field(ge=0, le=100)
    accounts: list[AccountBatchMemberDto]


class AccountActivationRequest(SchoolDirectoryRequest):
    new_password: SecretStr = Field(min_length=12, max_length=256)

    @field_validator("new_password")
    @classmethod
    def require_strong_password(cls, value: SecretStr) -> SecretStr:
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
