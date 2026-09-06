"""Parser adapter contract and shared metadata conversion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from ..config import PipelineConfig
from ..domain.document import CanonicalDocument, DocumentMetadata
from ..domain.source import SourceRecord


class ParserError(RuntimeError):
    """A document-level parse error that is safe to report in a manifest."""

    code = "PARSE_FAILED"


class ParserUnavailableError(ParserError):
    """A selected optional parser is not installed or cannot run locally."""

    code = "PARSER_UNAVAILABLE"


class DocumentParser(ABC):
    name = "abstract"

    @property
    @abstractmethod
    def version(self) -> str:
        """Return the concrete parser version recorded in provenance."""

    @abstractmethod
    def parse(self, source: SourceRecord, config: PipelineConfig) -> CanonicalDocument:
        """Parse one source into the canonical internal representation."""


def _as_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value.year
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2200 else None


def metadata_from_mapping(
    values: Mapping[str, Any] | None,
    *,
    config: PipelineConfig,
    input_mode: str,
    fallback_language: str | None = None,
) -> DocumentMetadata:
    """Build metadata only from declared fields; no knowledge claims are guessed."""

    source_values: Mapping[str, Any] = values or {}
    nested_source = source_values.get("source")
    if isinstance(nested_source, Mapping):
        merged = dict(source_values)
        for key, value in nested_source.items():
            merged.setdefault(key, value)
        source_values = merged
    language = source_values.get("language") or fallback_language or config.default_language
    population = source_values.get("population_scope", source_values.get("target_population", []))
    if isinstance(population, str):
        population = [population]
    roles = source_values.get("role_scope", ["student", "teacher", "parent"])
    if isinstance(roles, str):
        roles = [roles]
    risks = source_values.get("risk_scope", ["normal", "attention"])
    if isinstance(risks, str):
        risks = [risks]
    known = {
        "organization",
        "author",
        "published_year",
        "year",
        "language",
        "population_scope",
        "target_population",
        "category",
        "rights_status",
        "review_status",
        "role_scope",
        "risk_scope",
        "topic",
        "authority_level",
        "source_url",
        "url",
        "human_curated",
        "source",
        "title",
    }
    extra = {key: value for key, value in source_values.items() if key not in known}
    return DocumentMetadata(
        organization=source_values.get("organization"),
        author=source_values.get("author"),
        published_year=_as_year(source_values.get("published_year", source_values.get("year"))),
        language=str(language) if language else None,
        population_scope=[str(item) for item in population if item is not None],
        category=str(source_values.get("category", "other")),
        rights_status=str(source_values.get("rights_status", "unknown")),
        review_status=str(source_values.get("review_status", "pending")),
        role_scope=[str(item) for item in roles if item is not None],
        risk_scope=[str(item) for item in risks if item is not None],
        topic=source_values.get("topic"),
        authority_level=source_values.get("authority_level"),
        source_url=source_values.get("source_url", source_values.get("url")),
        human_curated=bool(source_values.get("human_curated", input_mode == "curated")),
        extra={**extra, "input_mode": input_mode},
    )

