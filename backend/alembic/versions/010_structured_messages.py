"""structured debate turns

Revision ID: 010
Revises: 009
Create Date: 2026-10-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Validated structured turn (position, main argument, rebuttal target,
    # concession, ...). NULL for messages stored before structured turns or
    # when a model ignored the format; `content` stays the readable text.
    op.add_column("debate_messages", sa.Column("structured", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("debate_messages", "structured")
