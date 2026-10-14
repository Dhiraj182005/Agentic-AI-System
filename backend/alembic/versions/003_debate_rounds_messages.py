"""debate rounds and messages

Revision ID: 003
Revises: 002
Create Date: 2026-09-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "debate_rounds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "debate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("round_number", sa.Integer, nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                name="debate_round_status_enum",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("debate_id", "round_number", name="uq_debate_round_debate_number"),
    )
    op.create_index("ix_debate_rounds_round_number", "debate_rounds", ["round_number"])

    op.create_table(
        "debate_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "debate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "round_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debate_rounds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("turn_number", sa.Integer, nullable=False),
        sa.Column(
            "message_type",
            sa.Enum(
                "opening",
                "argument",
                "rebuttal",
                "closing",
                name="debate_message_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("round_id", "turn_number", name="uq_debate_message_round_turn"),
    )

    op.add_column(
        "debate_agents",
        sa.Column(
            "position",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.execute(
        """
        UPDATE debate_agents AS da
        SET position = ranked.rn
        FROM (
            SELECT inner_da.debate_id,
                   inner_da.agent_id,
                   row_number() OVER (
                       PARTITION BY inner_da.debate_id
                       ORDER BY agents.name
                   ) AS rn
            FROM debate_agents AS inner_da
            JOIN agents ON agents.id = inner_da.agent_id
        ) AS ranked
        WHERE da.debate_id = ranked.debate_id
          AND da.agent_id = ranked.agent_id
        """
    )

    op.add_column(
        "debates",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "debates",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("debates", "completed_at")
    op.drop_column("debates", "started_at")
    op.drop_column("debate_agents", "position")
    op.drop_table("debate_messages")
    op.drop_index("ix_debate_rounds_round_number", table_name="debate_rounds")
    op.drop_table("debate_rounds")
    op.execute("DROP TYPE IF EXISTS debate_message_type_enum")
    op.execute("DROP TYPE IF EXISTS debate_round_status_enum")
