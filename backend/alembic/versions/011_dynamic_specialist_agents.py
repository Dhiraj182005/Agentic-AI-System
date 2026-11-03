"""debate-scoped dynamic specialist agents

Revision ID: 011
Revises: 010
Create Date: 2026-10-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("source", sa.String(20), nullable=False, server_default="builtin"),
    )
    op.add_column("agents", sa.Column("definition", JSON, nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "debate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_agents_debate_id", "agents", ["debate_id"])
    # Specialist names may repeat across debates; built-in names stay unique.
    op.drop_constraint("agents_name_key", "agents", type_="unique")
    op.create_index(
        "uq_agents_builtin_name",
        "agents",
        ["name"],
        unique=True,
        postgresql_where=sa.text("debate_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agents_builtin_name", table_name="agents")
    op.execute("DELETE FROM agents WHERE debate_id IS NOT NULL")
    op.create_unique_constraint("agents_name_key", "agents", ["name"])
    op.drop_index("ix_agents_debate_id", table_name="agents")
    op.drop_column("agents", "debate_id")
    op.drop_column("agents", "definition")
    op.drop_column("agents", "source")
