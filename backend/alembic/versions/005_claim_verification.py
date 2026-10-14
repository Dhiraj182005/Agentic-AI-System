"""claim verification

Revision ID: 005
Revises: 004
Create Date: 2026-10-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claim_verifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "verdict",
            sa.Enum(
                "supported",
                "contradicted",
                "insufficient_evidence",
                name="claim_verdict_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="verification_confidence_enum",
            ),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column(
            "evidence_summary",
            sa.Text,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "evidence_ids",
            JSON,
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
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
        sa.UniqueConstraint("claim_id", name="uq_claim_verifications_claim_id"),
    )


def downgrade() -> None:
    op.drop_table("claim_verifications")
    op.execute("DROP TYPE IF EXISTS claim_verdict_enum")
    op.execute("DROP TYPE IF EXISTS verification_confidence_enum")
