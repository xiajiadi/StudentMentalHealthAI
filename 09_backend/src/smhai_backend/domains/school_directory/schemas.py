"""Strict, module-local DTOs for school directory operations."""

from __future__ import annotations

import re
from datetime import datetime
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


class SchoolRosterImportRow(SchoolDirectoryRequest):
    row_no: int = Field(gt=0, le=200)
    student_number: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    class_ref: str = Field(min_length=1, max_length=128)
    grade_level: str | None = Field(default=None, min_length=1, max_length=32)

    @field_validator("student_number")
    @classmethod
    def normalize_student_number(cls, value: str) -> str:
        import unicodedata

        value = unicodedata.normalize("NFKC", value).strip().upper()
        return value

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        return _clean_display_name(value)

    @field_validator("class_ref", "grade_level")
    @classmethod
    def trim_roster_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("reference must not be blank")
        return value


class SchoolRosterImportRequest(SchoolDirectoryRequest):
    rows: list[SchoolRosterImportRow] = Field(min_length=1, max_length=200)
    source_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("source_sha256")
    @classmethod
    def validate_source_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if re.fullmatch(r"[A-Fa-f0-9]{64}", value) is None:
            raise ValueError("source_sha256 must be a SHA-256 digest")
        return value.casefold()


class SchoolRosterImportErrorDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_no: int = Field(gt=0, le=200)
    code: Literal[
        "DUPLICATE_ROW_NUMBER",
        "INVALID_STUDENT_NUMBER",
        "DUPLICATE_STUDENT_NUMBER",
        "STUDENT_NUMBER_UNAVAILABLE",
        "BLANK_DISPLAY_NAME",
        "FORMULA_LIKE_VALUE",
        "CLASS_UNAVAILABLE",
        "GRADE_LEVEL_MISMATCH",
    ]


class SchoolRosterClassGroupDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_ref: str = Field(min_length=1, max_length=128)
    row_count: int = Field(ge=0, le=200)


class SchoolRosterImportPreviewDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    row_count: int = Field(ge=0, le=200)
    errors: list[SchoolRosterImportErrorDto]
    class_groups: list[SchoolRosterClassGroupDto] = Field(default_factory=list, max_length=200)


class SchoolRosterImportMemberDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_no: int = Field(gt=0, le=200)
    user_id: str
    display_name: str
    class_ref: str
    status: Literal["PENDING_ACTIVATION", "ACTIVE"]


class SchoolRosterImportDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_ref: str
    row_count: int = Field(ge=1, le=200)
    created_count: int = Field(ge=0, le=200)
    skipped_count: int = Field(ge=0, le=200)
    status: Literal["COMPLETED"]
    class_groups: list[SchoolRosterClassGroupDto] = Field(default_factory=list, max_length=200)
    child_batch_refs: list[str]
    summary: dict[str, int]
    accounts: list[SchoolRosterImportMemberDto]


class AccountImportErrorDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_no: int = Field(gt=0)
    code: Literal[
        "INVALID_ROW_NUMBER",
        "DUPLICATE_ROW_NUMBER",
        "INVALID_LOGIN_NAME",
        "BLANK_DISPLAY_NAME",
        "FORMULA_LIKE_VALUE",
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
    class_refs: list[str] = Field(default_factory=list, max_length=200)


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


class InitialCredentialIssueRequest(SchoolDirectoryRequest):
    user_ids: list[str] = Field(min_length=1, max_length=200)

    @field_validator("user_ids")
    @classmethod
    def require_unique_user_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("user_ids must be unique")
        return value


class InitialCredentialDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    login_name: str
    display_name: str | None
    class_ref: str | None
    credential: str
    expires_at: datetime


class InitialCredentialIssueDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credentials: list[InitialCredentialDto] = Field(min_length=1, max_length=200)
    delivery_status: Literal["MANUAL_HANDOFF_REQUIRED"]
