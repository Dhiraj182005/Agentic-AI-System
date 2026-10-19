"""debate judgments

Revision ID: 007
Revises: 006
Create Date: 2026-10-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "debate_judgments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "debate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            sa.Enum("completed", name="judgment_status_enum"),
            nullable=False,
        ),
        sa.Column("overall_score", sa.Float, nullable=False),
        sa.Column(
            "winner_agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "outcome",
            sa.Enum("winner", "tie", "inconclusive", name="judgment_outcome_enum"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("scoring_rubric", JSON, nullable=False),
        sa.Column("agent_scores", JSON, nullable=False),
        sa.Column("limitations", JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("debate_id", name="uq_debate_judgments_debate_id"),
    )


def downgrade() -> None:
    op.drop_table("debate_judgments")
    op.execute("DROP TYPE IF EXISTS judgment_status_enum")
    op.execute("DROP TYPE IF EXISTS judgment_outcome_enum")
