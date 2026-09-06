"""Stable error types for the RAG module."""

from __future__ import annotations


class RAGEngineError(Exception):
    """Base error with a stable machine-readable code."""

    code = "RAG_ENGINE_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class InvalidConfigurationError(RAGEngineError):
    code = "INVALID_RAG_CONFIG"


class CorpusValidationError(RAGEngineError):
    code = "INVALID_KNOWLEDGE_CORPUS"


class ContractValidationError(RAGEngineError):
    code = "CONTRACT_VALIDATION_FAILED"


class ProviderUnavailableError(RAGEngineError):
    code = "PROVIDER_UNAVAILABLE"
    retryable = True


class UnsafeQueryError(RAGEngineError):
    code = "UNSAFE_QUERY"
