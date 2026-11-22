"""Allowlisted, non-sensitive origins for persisted synthetic schools."""

from __future__ import annotations

import re
from types import MappingProxyType

SYNTHETIC_SCHOOL_TEST_PROVENANCE_REF = "SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1"
SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF = "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1"
PUBLIC_DEMO_SCHOOL_PREFIX = "PUBLICDEMO_"
_PUBLIC_DEMO_SCHOOL_REF = re.compile(rf"{PUBLIC_DEMO_SCHOOL_PREFIX}[a-f0-9]{{64}}\Z")

PROVENANCE_REGISTRY = MappingProxyType(
    {
        SYNTHETIC_SCHOOL_TEST_PROVENANCE_REF: (
            "11_database/tests/test_mysql_integration.py::"
            "test_school_contexts_grants_and_sessions_are_same_school_and_fail_closed"
        ),
        SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF: (
            "11_database/database_layer/school_seed.py::seed_synthetic_school_contexts"
        ),
    }
)

REGISTERED_SCHOOL_PROVENANCE_REFS = frozenset(PROVENANCE_REGISTRY)
SCHOOL_PROVENANCE_CHECK_VALUES = ", ".join(
    f"'{token}'" for token in PROVENANCE_REGISTRY
)


def is_registered_school_provenance_ref(value: object) -> bool:
    return isinstance(value, str) and value in REGISTERED_SCHOOL_PROVENANCE_REFS


def is_public_demo_school_ref(value: str) -> bool:
    return _PUBLIC_DEMO_SCHOOL_REF.fullmatch(value) is not None
