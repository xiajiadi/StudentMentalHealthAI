"""Strict DTOs for the assessment-free student conversation service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConversationCreateRequest(_StrictDto):
    """Conversation creation accepts no client-selected owner or AI settings."""


class ConversationMessageRequest(_StrictDto):
    text: StrictStr = Field(min_length=1, max_length=20_000)


class ConversationProjection(_StrictDto):
    conversation_id: StrictStr = Field(pattern=r"^CONV_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$")
    status: Literal["open", "active", "closed", "archived"]
    created_at: StrictStr
    updated_at: StrictStr


class ConversationListRequest(_StrictDto):
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=20, ge=1, le=50)


class ConversationListResponse(_StrictDto):
    items: list[ConversationProjection]
    total: StrictInt = Field(ge=0)
    has_more: bool


class ConversationDetailResponse(_StrictDto):
    conversation: ConversationProjection
    messages: list[dict[str, Any]]
    turns: list[dict[str, Any]]
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=50)
    total_turns: StrictInt = Field(ge=0)
    has_more: bool


class ConversationTurnResult(_StrictDto):
    turn_id: StrictStr = Field(pattern=r"^TURN_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$")
    status: Literal["requested", "completed", "blocked", "failed"]
    replayed: bool = False
    action: StrictStr | None = None
    completed_at: StrictStr | None = None
    user_message_sequence: StrictInt | None = Field(default=None, ge=1)
    assistant_message_sequence: StrictInt | None = Field(default=None, ge=1)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)
    content: dict[str, Any] | None = None
