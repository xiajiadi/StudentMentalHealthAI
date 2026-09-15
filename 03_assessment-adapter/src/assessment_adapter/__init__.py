"""D3-2 deterministic assessment interpretation boundary.

The package is deliberately local and data-driven.  It validates a completed
``assessment.v1`` object, selects one exact policy pack, and returns a
role-neutral structured result.  It does not import CAT, Safety, RAG, Prompt
Engine, Backend or an LLM runtime.
"""

from .adapter import (
    DEFAULT_POLICY_PATH,
    InterpretationAdapter,
    interpret,
    interpret_assessment,
    load_shipped_registry,
    validate_assessment_v1,
)
from .models import (
    Claim,
    ConstructPolicy,
    ExecutionMode,
    InterpretationPolicyPack,
    InterpretationRequest,
    InterpretationResult,
    InterpretationStatus,
    PolicyRef,
    PolicyReference,
    ReasonCode,
    SafetyAction,
    TrustedInterpretationContext,
    TypedClaim,
)
from .policy import (
    PolicyRegistry,
    PolicyRegistryError,
    canonical_policy_hash,
    load_policy_registry,
)

__all__ = [
    "Claim",
    "ConstructPolicy",
    "DEFAULT_POLICY_PATH",
    "ExecutionMode",
    "InterpretationAdapter",
    "InterpretationPolicyPack",
    "InterpretationRequest",
    "InterpretationResult",
    "InterpretationStatus",
    "PolicyReference",
    "PolicyRef",
    "PolicyRegistry",
    "PolicyRegistryError",
    "ReasonCode",
    "SafetyAction",
    "TypedClaim",
    "TrustedInterpretationContext",
    "canonical_policy_hash",
    "interpret",
    "interpret_assessment",
    "load_policy_registry",
    "load_shipped_registry",
    "validate_assessment_v1",
]
