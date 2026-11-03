"""post-debate analysis pipeline and bias-aware verdicts

Revision ID: 012
Revises: 011
Create Date: 2026-10-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # State of the automatic claim extraction / evidence / verification run.
    op.add_column("debates", sa.Column("analysis_status", JSON, nullable=True))
    # When an evidence search was last attempted for the claim (NULL = never),
    # so "searched, nothing found" differs from "never searched".
    op.add_column(
        "claims",
        sa.Column("evidence_retrieved_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Bias-aware verdicts: assumptions embedded in the question and separate
    # verdicts for each proposition a compound question bundles together.
    op.add_column("debate_verdicts", sa.Column("assumptions", JSON, nullable=True))
    op.add_column("debate_verdicts", sa.Column("sub_verdicts", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("debate_verdicts", "sub_verdicts")
    op.drop_column("debate_verdicts", "assumptions")
    op.drop_column("claims", "evidence_retrieved_at")
    op.drop_column("debates", "analysis_status")
