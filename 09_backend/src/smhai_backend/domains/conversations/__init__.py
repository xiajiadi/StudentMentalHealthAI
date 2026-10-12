"""Independent, owner-private student education-support conversations."""

from .schemas import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessageRequest,
    ConversationProjection,
    ConversationTurnResult,
)
from .service import IndependentConversationService

__all__ = [
    "ConversationCreateRequest",
    "ConversationDetailResponse",
    "ConversationListResponse",
    "ConversationMessageRequest",
    "ConversationProjection",
    "ConversationTurnResult",
    "IndependentConversationService",
]
