"""Bounded, synthetic-only Prompt assembly for the D3-1 engineering slice.

The package assembles a versioned generation request and a rendered Prompt. It
does not call RAG, Safety, an LLM, or Backend and it does not interpret
assessment measurements.
"""

from .engine import (
    RenderedPrompt,
    TrustedPromptContext,
    render,
    render_projected,
    render_prompt,
)
from .errors import PromptRefusal
from .registry import PolicyRecord, TemplateRecord, resolve_policy, resolve_template

__all__ = [
    "PolicyRecord",
    "PromptRefusal",
    "RenderedPrompt",
    "TrustedPromptContext",
    "TemplateRecord",
    "render",
    "render_projected",
    "render_prompt",
    "resolve_policy",
    "resolve_template",
]
