"""Link repeated claims while retaining every original message reference."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("claims", sa.Column("canonical_claim_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_claim_canonical", "claims", "claims", ["canonical_claim_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_claims_canonical_claim_id", "claims", ["canonical_claim_id"])


def downgrade():
    op.drop_index("ix_claims_canonical_claim_id", "claims")
    op.drop_constraint("fk_claim_canonical", "claims", type_="foreignkey")
    op.drop_column("claims", "canonical_claim_id")
