"""Register the controlled synthetic school seed recipe provenance token.

Revision ID: 20261011_0004
Revises: 20261011_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0004"
down_revision: str | None = "20261011_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEST_PROVENANCE = "SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1"
_SEED_PROVENANCE = "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1"
_CONSTRAINT = "ck_schools_provenance_ref_token"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "schools", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "schools",
        f"provenance_ref IN ('{_TEST_PROVENANCE}', '{_SEED_PROVENANCE}')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    seed_rows = connection.execute(
        sa.text("SELECT COUNT(*) FROM schools WHERE provenance_ref = :provenance_ref"),
        {"provenance_ref": _SEED_PROVENANCE},
    ).scalar_one()
    if seed_rows:
        raise RuntimeError(
            "cannot downgrade school seed provenance while registered seed rows exist"
        )

    op.drop_constraint(_CONSTRAINT, "schools", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "schools",
        f"provenance_ref = '{_TEST_PROVENANCE}'",
    )
