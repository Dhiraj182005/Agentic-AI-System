"""Persist complete message evaluation metadata without changing old scores.

Revision ID: 014
Revises: 013
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL enum additions cannot be used until committed.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE fallacy_type_enum ADD VALUE IF NOT EXISTS 'cherry_picking'")
    for name in ("responsiveness", "completeness", "factual_support", "fallacy_risk"):
        op.add_column("argument_evaluations", sa.Column(name, sa.Float(), nullable=True))
    op.add_column("argument_evaluations", sa.Column("rubric_version", sa.Integer(), nullable=True))
    for name in ("criterion_scores", "strengths", "weaknesses"):
        op.add_column("argument_evaluations", sa.Column(name, sa.JSON(), nullable=True))
    op.add_column("argument_evaluations", sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("debate_messages", sa.Column("claims_extracted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("debate_messages", "claims_extracted_at")
    for name in ("responsiveness", "completeness", "factual_support", "fallacy_risk", "rubric_version",
                 "criterion_scores", "strengths", "weaknesses", "evaluated_at"):
        op.drop_column("argument_evaluations", name)
    # Retain the enum label: removing it would destroy historical analyses.
