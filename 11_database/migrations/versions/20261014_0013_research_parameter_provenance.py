"""Distinguish local calibration fits from published rounded parameters.

Revision ID: 20261014_0013
Revises: 20261014_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0013"
down_revision: str | None = "20261014_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_PROFILE_TABLE = "school_research_profile_versions"
_RESEARCH_TABLES = (
    "school_research_profile_versions",
    "school_research_task_bindings",
    "school_research_sessions",
)


def _ascii_id(length: int) -> sa.String:
    return sa.String(length=length, collation="ascii_bin")


def upgrade() -> None:
    op.alter_column(
        _PROFILE_TABLE,
        "fit_sha256",
        existing_type=_ascii_id(64),
        existing_nullable=False,
        nullable=True,
    )
    op.alter_column(
        _PROFILE_TABLE,
        "calibration_sha256",
        existing_type=_ascii_id(64),
        existing_nullable=False,
        nullable=True,
    )

    # MySQL ADD COLUMN AFTER preserves the established model column order while
    # keeping the migration additive and leaving all encrypted payloads intact.
    op.execute(
        sa.text(
            "ALTER TABLE school_research_profile_versions "
            "ADD COLUMN parameter_origin VARCHAR(32) CHARACTER SET ascii "
            "COLLATE ascii_bin NOT NULL DEFAULT 'LOCAL_RESEARCH_FIT' AFTER disabled_at"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE school_research_profile_versions "
            "ADD COLUMN published_parameter_crosswalk_sha256 VARCHAR(64) "
            "CHARACTER SET ascii COLLATE ascii_bin NULL AFTER parameter_origin"
        )
    )
    op.create_check_constraint(
        "parameter_origin_allowed",
        _PROFILE_TABLE,
        "parameter_origin IN ('LOCAL_RESEARCH_FIT', 'PUBLISHED_ROUNDED_REFERENCE')",
    )
    op.create_check_constraint(
        "parameter_provenance_shape",
        _PROFILE_TABLE,
        "(parameter_origin = 'LOCAL_RESEARCH_FIT' "
        "AND fit_sha256 IS NOT NULL AND calibration_sha256 IS NOT NULL "
        "AND published_parameter_crosswalk_sha256 IS NULL) OR "
        "(parameter_origin = 'PUBLISHED_ROUNDED_REFERENCE' "
        "AND fit_sha256 IS NULL AND calibration_sha256 IS NULL "
        "AND published_parameter_crosswalk_sha256 IS NOT NULL)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    counts = []
    for table_name in _RESEARCH_TABLES:
        counts.append(
            connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        )
    task_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM measurement_tasks WHERE cat_binding_mode = 'RESEARCH_PROFILE'"
        )
    ).scalar_one()
    if any(counts) or task_count:
        raise RuntimeError(
            "cannot downgrade research parameter provenance while research rows or tasks exist"
        )

    op.drop_constraint("parameter_provenance_shape", _PROFILE_TABLE, type_="check")
    op.drop_constraint("parameter_origin_allowed", _PROFILE_TABLE, type_="check")
    op.drop_column(_PROFILE_TABLE, "published_parameter_crosswalk_sha256")
    op.drop_column(_PROFILE_TABLE, "parameter_origin")
    op.alter_column(
        _PROFILE_TABLE,
        "calibration_sha256",
        existing_type=_ascii_id(64),
        existing_nullable=True,
        nullable=False,
    )
    op.alter_column(
        _PROFILE_TABLE,
        "fit_sha256",
        existing_type=_ascii_id(64),
        existing_nullable=True,
        nullable=False,
    )
