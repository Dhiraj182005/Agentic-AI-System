"""Align historical timestamp nullability with ORM metadata, without data changes."""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None

TIMESTAMPS = {
    "agents": ("created_at", "updated_at"),
    "argument_evaluations": ("created_at",),
    "claim_verifications": ("created_at", "updated_at"),
    "claims": ("created_at",), "debate_agents": ("created_at",),
    "debate_judgments": ("created_at", "updated_at"),
    "debate_messages": ("created_at",), "debate_rounds": ("created_at",),
    "debate_verdicts": ("created_at", "updated_at"), "debates": ("created_at", "updated_at"),
    "evidence": ("retrieved_at",), "fallacies": ("created_at",),
    "users": ("created_at", "updated_at"),
}


def upgrade():
    bind = op.get_bind()
    # Never invent a timestamp to satisfy a constraint. Fail before changing
    # any columns if a different installation contains unknown historical dates.
    for table, columns in TIMESTAMPS.items():
        for column in columns:
            if bind.execute(sa.text(f'SELECT 1 FROM "{table}" WHERE "{column}" IS NULL LIMIT 1')).first():
                raise RuntimeError(f"Historical {table}.{column} contains NULL; recover original dates before applying 017")
    for table, columns in TIMESTAMPS.items():
        for column in columns:
            op.alter_column(table, column, existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade():
    for table, columns in TIMESTAMPS.items():
        for column in columns:
            op.alter_column(table, column, existing_type=sa.DateTime(timezone=True), nullable=True)
