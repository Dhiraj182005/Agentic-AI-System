"""debate failure reason

Revision ID: 009
Revises: 008
Create Date: 2026-10-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safe, user-facing reason a debate failed (no provider payloads).
    op.add_column("debates", sa.Column("failure_reason", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("debates", "failure_reason")
