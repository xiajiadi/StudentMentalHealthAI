"""Explicit server-owned population routing for the D3 support path.

The product support population, RAG taxonomy, evidence eligibility scope, and
D3-1 content identity are separate names.  This versioned mapping is the only
approved bridge between them; request data and CAT provenance never select it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from smhai_backend.domains.assessment.binding import D3_RAG_POPULATION


class PopulationMappingError(ValueError):
    """No approved server-owned mapping exists for the selected population."""

    code = "POPULATION_MAPPING_REQUIRED"


@dataclass(frozen=True, slots=True)
class ServerOwnedPopulationMapping:
    mapping_id: str
    mapping_version: str
    product_policy_id: str
    product_population: str
    rag_query_taxonomy: str
    evidence_eligibility_population: str
    d3_content_population: str
    approved: bool = True

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "mapping_id": self.mapping_id,
            "mapping_version": self.mapping_version,
            "product_policy_id": self.product_policy_id,
            "product_population": self.product_population,
            "rag_query_taxonomy": self.rag_query_taxonomy,
            "evidence_eligibility_population": self.evidence_eligibility_population,
            "d3_content_population": self.d3_content_population,
            "approved": self.approved,
        }


UNIVERSITY_FRESHMAN_SYNTHETIC_MAPPING = ServerOwnedPopulationMapping(
    mapping_id="MAP_UNIVERSITY_FRESHMAN_SUPPORT_TO_RAG_D3_V1",
    mapping_version="1.0.0",
    product_policy_id="POLICY_synthetic_engineering_university_freshmen",
    product_population=D3_RAG_POPULATION,
    # These values are grounded in the approved D4 corpus metadata and the
    # RAG query planner's exact target_population filter.
    rag_query_taxonomy="university_freshman",
    evidence_eligibility_population="university_freshman",
    d3_content_population=D3_RAG_POPULATION,
)

_MAPPINGS_BY_PRODUCT_POPULATION = MappingProxyType(
    {
        UNIVERSITY_FRESHMAN_SYNTHETIC_MAPPING.product_population:
            UNIVERSITY_FRESHMAN_SYNTHETIC_MAPPING,
    }
)


def resolve_population_mapping(product_population: str) -> ServerOwnedPopulationMapping:
    """Resolve an exact server-owned product population or fail closed."""

    if not isinstance(product_population, str) or not product_population:
        raise PopulationMappingError("product population is missing")
    mapping = _MAPPINGS_BY_PRODUCT_POPULATION.get(product_population)
    if mapping is None or not mapping.approved:
        raise PopulationMappingError("no approved population mapping exists")
    return mapping


__all__ = [
    "PopulationMappingError",
    "ServerOwnedPopulationMapping",
    "UNIVERSITY_FRESHMAN_SYNTHETIC_MAPPING",
    "resolve_population_mapping",
]
