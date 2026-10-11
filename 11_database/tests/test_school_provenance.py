from __future__ import annotations

from typing import Any, cast

import pytest
from database_layer.enums import DataOrigin
from database_layer.provenance import (
    PROVENANCE_REGISTRY,
    SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
)
from database_layer.repositories import (
    SYNTHETIC_SCHOOL_PROVENANCE_REF,
    SchoolMembershipRepository,
)


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1


async def test_school_creator_requires_synthetic_origin_and_opaque_provenance_token():
    session = _Session()
    repository = SchoolMembershipRepository(cast(Any, session))
    provenance_ref = SYNTHETIC_SCHOOL_PROVENANCE_REF

    school = await repository.create_school(
        school_ref="SCHOOL_synthetic_fixture",
        data_origin=DataOrigin.SYNTHETIC,
        provenance_ref=provenance_ref,
    )

    assert school.data_origin == DataOrigin.SYNTHETIC.value
    assert school.provenance_ref == provenance_ref
    assert session.added == [school]
    assert session.flush_count == 1


async def test_school_creator_accepts_registered_seed_provenance():
    session = _Session()
    repository = SchoolMembershipRepository(cast(Any, session))
    school = await repository.create_school(
        school_ref="SYNTHETIC_SCHOOL_SEED_ALPHA_V1",
        data_origin=DataOrigin.SYNTHETIC,
        provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
    )
    assert school.provenance_ref == SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
    assert PROVENANCE_REGISTRY[SYNTHETIC_SCHOOL_PROVENANCE_REF].startswith(
        "11_database/tests/test_mysql_integration.py::"
    )
    assert PROVENANCE_REGISTRY[SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF] == (
        "11_database/database_layer/school_seed.py::seed_synthetic_school_contexts"
    )


@pytest.mark.parametrize("origin", [DataOrigin.PRODUCTION_PENDING, "REAL"])
async def test_school_creator_rejects_non_synthetic_origins(origin: DataOrigin | str):
    session = _Session()
    repository = SchoolMembershipRepository(cast(Any, session))

    with pytest.raises(ValueError, match="requires SYNTHETIC"):
        await repository.create_school(
            school_ref="SCHOOL_synthetic_fixture",
            data_origin=cast(DataOrigin, origin),
            provenance_ref=SYNTHETIC_SCHOOL_PROVENANCE_REF,
        )

    assert session.added == []
    assert session.flush_count == 0


@pytest.mark.parametrize(
    "provenance_ref",
    [
        "FREEFORM_REFERENCE_TEXT",
        "NAME_SENTINEL",
        "CREDENTIAL_SENTINEL",
        "MEMBER_IDENTIFIER_SENTINEL",
        "SYNTHETIC_REF_UNREGISTERED_FIXTURE_V1",
    ],
)
async def test_school_creator_rejects_free_text_names_and_malformed_provenance(
    provenance_ref: str,
):
    session = _Session()
    repository = SchoolMembershipRepository(cast(Any, session))

    with pytest.raises(ValueError, match="opaque synthetic reference token"):
        await repository.create_school(
            school_ref="SCHOOL_synthetic_fixture",
            data_origin=DataOrigin.SYNTHETIC,
            provenance_ref=provenance_ref,
        )

    assert session.added == []
    assert session.flush_count == 0
