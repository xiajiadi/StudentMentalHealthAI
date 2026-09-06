"""Provider-neutral retrieval and context engine for StudentMentalHealthAI."""

from .domain import (
    Citation,
    CitationBundle,
    ContextBundle,
    IndexManifest,
    KnowledgeRecord,
    LayerBudget,
    MetadataFilter,
    RetrievalHit,
    RetrievalPlan,
    RetrievalResult,
    RetrievalTrace,
)
from .exceptions import (
    ContractValidationError,
    CorpusValidationError,
    InvalidConfigurationError,
    ProviderUnavailableError,
    RAGEngineError,
    UnsafeQueryError,
)

__all__ = [
    "Citation",
    "CitationBundle",
    "ContextBundle",
    "ContractValidationError",
    "CorpusValidationError",
    "IndexManifest",
    "InvalidConfigurationError",
    "KnowledgeRecord",
    "LayerBudget",
    "MetadataFilter",
    "ProviderUnavailableError",
    "RAGEngineError",
    "RetrievalHit",
    "RetrievalPlan",
    "RetrievalResult",
    "RetrievalTrace",
    "UnsafeQueryError",
]

__version__ = "0.1.0"
