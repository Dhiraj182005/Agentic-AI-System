"""published fact-checks (Google Fact Check Tools) stored as evidence

Revision ID: 013
Revises: 012
Create Date: 2026-10-27
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows are Tavily web results.
    op.add_column(
        "evidence",
        sa.Column("source_type", sa.Text(), nullable=False, server_default="web"),
    )
    op.add_column("evidence", sa.Column("publisher", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("external_rating", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("review_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("evidence", sa.Column("claim_reviewed", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("claimant", sa.Text(), nullable=True))
    # A published fact-check is stored at most once per claim.
    op.create_index(
        "uq_evidence_claim_fact_check_url",
        "evidence",
        ["claim_id", "url"],
        unique=True,
        postgresql_where=sa.text("source_type = 'google_fact_check'"),
    )
    op.add_column("claims", sa.Column("fact_check_status", sa.Text(), nullable=True))
    op.add_column(
        "claims",
        sa.Column("fact_check_searched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("claims", "fact_check_searched_at")
    op.drop_column("claims", "fact_check_status")
    op.drop_index("uq_evidence_claim_fact_check_url", table_name="evidence")
    for column in ("claimant", "claim_reviewed", "review_date", "external_rating", "publisher", "source_type"):
        op.drop_column("evidence", column)
