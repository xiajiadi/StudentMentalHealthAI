"""Add nullable retrieval identity fields to support evidence.

Revision ID: 20260906_0002
Revises: 20260905_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0002"
down_revision: str | None = "20260905_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "support_evidence",
        sa.Column("chunk_id", sa.String(length=128, collation="ascii_bin"), nullable=True),
    )
    op.add_column(
        "support_evidence",
        sa.Column("document_id", sa.String(length=128, collation="ascii_bin"), nullable=True),
    )
    op.add_column(
        "support_evidence",
        sa.Column("citation_title", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "support_evidence",
        sa.Column("citation_organization", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("support_evidence", "citation_organization")
    op.drop_column("support_evidence", "citation_title")
    op.drop_column("support_evidence", "document_id")
    op.drop_column("support_evidence", "chunk_id")
