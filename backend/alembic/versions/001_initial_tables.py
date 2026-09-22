"""initial tables

Revision ID: 001
Revises: 
Create Date: 2026-09-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "debates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("expert_selection_mode", sa.Enum("auto", "manual", name="expert_selection_mode_enum"), nullable=False, server_default="manual"),
        sa.Column("domain_tags", JSON, nullable=True),
        sa.Column("status", sa.Enum("pending", "running", "completed", "failed", "cancelled", name="debate_status_enum"), nullable=False, server_default="pending"),
        sa.Column("mode", sa.Enum("balanced", "pro_con", name="debate_mode_enum"), nullable=False, server_default="balanced"),
        sa.Column("total_rounds", sa.Integer, nullable=False, server_default="3"),
        sa.Column("verify_evidence", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("is_core", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("agents")
    op.drop_table("debates")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS expert_selection_mode_enum")
    op.execute("DROP TYPE IF EXISTS debate_mode_enum")
    op.execute("DROP TYPE IF EXISTS debate_status_enum")
