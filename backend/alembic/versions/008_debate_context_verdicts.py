"""debate context and final verdicts

Revision ID: 008
Revises: 007
Create Date: 2026-10-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("debates", sa.Column("context", sa.Text, nullable=True))

    op.create_table(
        "debate_verdicts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "debate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "position",
            sa.Enum(
                "supports", "opposes", "mixed", "inconclusive",
                name="verdict_position_enum",
            ),
            nullable=False,
        ),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("preferred_position", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("supporting_arguments", JSON, nullable=False),
        sa.Column("counterarguments", JSON, nullable=False),
        sa.Column(
            "confidence",
            sa.Enum("low", "medium", "high", name="verdict_confidence_enum"),
            nullable=False,
        ),
        sa.Column("confidence_basis", sa.Text, nullable=False),
        sa.Column("limitations", JSON, nullable=False),
        sa.Column("unresolved_questions", JSON, nullable=False),
        sa.Column("evidence_snapshot", JSON, nullable=False),
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
        sa.UniqueConstraint("debate_id", name="uq_debate_verdicts_debate_id"),
    )


def downgrade() -> None:
    op.drop_table("debate_verdicts")
    op.execute("DROP TYPE IF EXISTS verdict_position_enum")
    op.execute("DROP TYPE IF EXISTS verdict_confidence_enum")
    op.drop_column("debates", "context")
