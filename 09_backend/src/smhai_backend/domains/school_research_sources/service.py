"""Projection service over the existing hash-validated R3 student package."""

from __future__ import annotations

import hmac
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from rag_engine.research.student_education import (
    CONSUMER_AGE_MAX,
    CONSUMER_AGE_MIN,
    PACKAGE_STATUS,
    REVIEW_STATUS,
    SchoolStudentPackage,
)

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import (
    ResearchSourceCatalogPageDto,
    ResearchSourceDetailDto,
    ResearchSourcePackageReviewDto,
    ResearchSourceSummaryDto,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_LAYERS = {"policy", "theory", "intervention"}
_LAYER_ORDER = ("policy", "theory", "intervention")
_RIGHTS_STATUSES = {"VERIFIED_WITH_CONDITIONS", "PENDING"}
_SCHEMA_VERSION = "school.research-source-catalog.v1"
_REVIEW = ResearchSourcePackageReviewDto(
    package_status=PACKAGE_STATUS,
    reviewer_kind="AI_ENGINEERING",
    review_status=REVIEW_STATUS,
    professional_approval=False,
    ethics_approval=False,
    clinical_approval=False,
    psychometric_approval=False,
    publication_eligible=False,
    production_use=False,
)


class SchoolResearchSourcesService:
    """Expose only source metadata from a package validated by the RAG loader."""

    def __init__(
        self,
        *,
        package: SchoolStudentPackage,
        expected_school_id: int,
        expected_manifest_sha256: str,
        expected_study_ref: str,
        clock=None,
    ) -> None:
        if type(expected_school_id) is not int or expected_school_id <= 0:
            raise TypeError("research source catalog requires a pinned school")
        if type(expected_manifest_sha256) is not str or not _SHA256.fullmatch(
            expected_manifest_sha256
        ):
            raise TypeError("research source catalog requires a pinned manifest hash")
        if type(expected_study_ref) is not str or not expected_study_ref:
            raise TypeError("research source catalog requires a pinned study")
        self.package = package
        self.expected_school_id = expected_school_id
        self.expected_manifest_sha256 = expected_manifest_sha256
        self.expected_study_ref = expected_study_ref
        self._clock = clock or (lambda: datetime.now(UTC))

    def list_sources(
        self, actor: Actor, *, limit: int = 20, offset: int = 0
    ) -> ResearchSourceCatalogPageDto:
        self._authorize(actor)
        sources = self._validated_sources()
        if type(limit) is not int or not 1 <= limit <= 50:
            raise error(ErrorCode.VALIDATION_FAILED, detail="source catalog limit is invalid")
        if type(offset) is not int or not 0 <= offset <= 10_000:
            raise error(ErrorCode.VALIDATION_FAILED, detail="source catalog offset is invalid")
        ordered = sorted(sources, key=lambda item: item.source_id)
        page = ordered[offset : offset + limit]
        layers_by_source = self._layers_by_source()
        return ResearchSourceCatalogPageDto(
            schema_version=_SCHEMA_VERSION,
            source_package_ref=self.package.package_id,
            manifest_sha256=self.package.manifest_sha256,
            study_ref=self.package.study_ref,
            consumer_age_min=CONSUMER_AGE_MIN,
            consumer_age_max=CONSUMER_AGE_MAX,
            review=_REVIEW,
            items=[self._summary(source, layers_by_source) for source in page],
            total=len(ordered),
            limit=limit,
            offset=offset,
            has_more=offset + len(page) < len(ordered),
        )

    def get_source(self, actor: Actor, source_ref: str) -> ResearchSourceDetailDto:
        self._authorize(actor)
        sources = self._validated_sources()
        if type(source_ref) is not str or not source_ref:
            raise error(ErrorCode.VALIDATION_FAILED, detail="source reference is invalid")
        source = next((item for item in sources if item.source_id == source_ref), None)
        if source is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="research source was not found")
        values = self._summary(source, self._layers_by_source()).model_dump()
        return ResearchSourceDetailDto(
            **values,
            license=source.license,
            license_url=source.license_url,
            attribution=source.attribution,
            rights_evidence_url=source.rights_evidence_url,
            rights_evidence_sha256=source.rights_evidence_sha256,
            rights_scope_note=source.rights_scope_note,
            source_capture_sha256=source.source_capture_sha256,
            review=_REVIEW,
        )

    def _authorize(self, actor: Actor) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
            or type(actor.school_id) is not int
            or actor.school_id != self.expected_school_id
            or type(actor.school_ref) is not str
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    def _validated_sources(self) -> tuple[Any, ...]:
        package = self.package
        if (
            type(package) is not SchoolStudentPackage
            or type(package.manifest_sha256) is not str
            or not hmac.compare_digest(
                package.manifest_sha256, self.expected_manifest_sha256
            )
            or package.study_ref != self.expected_study_ref
            or type(package.package_id) is not str
            or not package.package_id
            or REVIEW_STATUS != "pending"
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="validated research source package is unavailable",
            )
        checked_at = self._clock()
        if (
            not isinstance(checked_at, datetime)
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
            or not isinstance(package.valid_through, datetime)
            or package.valid_through.tzinfo is None
            or package.valid_through.utcoffset() is None
            or checked_at.astimezone(UTC) > package.valid_through.astimezone(UTC)
        ):
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="pinned research source package is expired or unavailable",
                retryable=False,
            )
        sources = package.sources
        if type(sources) is not tuple or not sources or len(sources) > 100:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="validated research source package is unavailable",
            )
        identifiers: set[str] = set()
        for source in sources:
            source_id = getattr(source, "source_id", None)
            rights_status = getattr(source, "rights_status", None)
            retrieval_eligible = getattr(source, "student_retrieval_eligible", None)
            if (
                type(source_id) is not str
                or not _SAFE_ID.fullmatch(source_id)
                or source_id in identifiers
                or rights_status not in _RIGHTS_STATUSES
                or type(retrieval_eligible) is not bool
                or (
                    retrieval_eligible
                    and rights_status != "VERIFIED_WITH_CONDITIONS"
                )
            ):
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="validated research source package is unavailable",
                )
            identifiers.add(source_id)
        records = package.records
        if type(records) is not tuple or not records or len(records) > 100:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="validated research source package is unavailable",
            )
        for record in records:
            source_ref = getattr(record, "source_id", None)
            layer = getattr(record, "layer", None)
            if (
                type(source_ref) is not str
                or source_ref not in identifiers
                or type(layer) is not str
                or layer not in _LAYERS
            ):
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="validated research source package is unavailable",
                )
        if not _SHA256.fullmatch(package.manifest_sha256):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="validated research source package is unavailable",
            )
        return sources

    def _layers_by_source(self) -> dict[str, list[str]]:
        layers: dict[str, set[str]] = defaultdict(set)
        for record in self.package.records:
            source_ref = getattr(record, "source_id", None)
            layer = getattr(record, "layer", None)
            if (
                type(source_ref) is not str
                or not _SAFE_ID.fullmatch(source_ref)
                or type(layer) is not str
                or layer not in _LAYERS
            ):
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="validated research source package is unavailable",
                )
            layers[source_ref].add(layer)
        return {
            source_ref: [layer for layer in _LAYER_ORDER if layer in values]
            for source_ref, values in layers.items()
        }

    @staticmethod
    def _summary(source: Any, layers_by_source: dict[str, list[str]]):
        return ResearchSourceSummaryDto(
            source_ref=source.source_id,
            title=source.title,
            organization=source.publisher,
            publication_date=source.publication_date,
            canonical_url=source.canonical_url,
            source_population_scope=source.source_population_scope,
            source_language=source.source_language,
            layers=layers_by_source.get(source.source_id, []),
            rights_status=source.rights_status,
            retrieval_eligible=source.student_retrieval_eligible,
        )
