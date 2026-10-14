"""fallacies + argument evaluations

Revision ID: 006
Revises: 005
Create Date: 2026-10-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fallacies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "debate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debate_messages.id", ondelete="CASCADE"),
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
        sa.Column(
            "fallacy_type",
            sa.Enum(
                "ad_hominem",
                "straw_man",
                "false_dilemma",
                "slippery_slope",
                "appeal_to_authority",
                "appeal_to_emotion",
                "hasty_generalization",
                "circular_reasoning",
                "red_herring",
                "false_cause",
                "bandwagon",
                "loaded_question",
                "tu_quoque",
                "no_fallacy",
                name="fallacy_type_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="fallacy_severity_enum",
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("evidence_span", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("message_id", "fallacy_type", name="uq_fallacies_message_type"),
    )

    op.create_table(
        "argument_evaluations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "debate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("debate_messages.id", ondelete="CASCADE"),
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
        sa.Column("logical_soundness", sa.Float, nullable=False),
        sa.Column("evidence_score", sa.Float, nullable=False),
        sa.Column("relevance_score", sa.Float, nullable=False),
        sa.Column("effectiveness_score", sa.Float, nullable=False),
        sa.Column("overall_score", sa.Float, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("message_id", name="uq_argument_evaluations_message_id"),
    )


def downgrade() -> None:
    op.drop_table("argument_evaluations")
    op.drop_table("fallacies")
    op.execute("DROP TYPE IF EXISTS fallacy_type_enum")
    op.execute("DROP TYPE IF EXISTS fallacy_severity_enum")
