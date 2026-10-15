"""Closed metadata-only response schemas for school operations audit."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuditCategory = Literal[
    "organization",
    "class",
    "member",
    "account_batch",
    "account",
    "task",
]

AuditAction = Literal[
    "school_directory.rename_school",
    "school_directory.rename_class",
    "school_directory.rename_member",
    "school_directory.import_accounts",
    "school_directory.activate_account",
    "school_tasks.task.published",
]


class SchoolOperationsAuditEventDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_ref: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    created_at: datetime
    action: AuditAction
    result: Literal["SUCCESS", "FAILURE", "DENIED"]
    resource_category: AuditCategory
    record_count: int | None = Field(default=None, ge=1, le=100)


class SchoolOperationsAuditPageDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SchoolOperationsAuditEventDto]
    offset: int = Field(ge=0, le=10_000)
    limit: int = Field(ge=1, le=50)
    has_more: bool
