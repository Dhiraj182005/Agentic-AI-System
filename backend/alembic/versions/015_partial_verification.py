"""Add explicit partially-supported claim status, retaining existing verdicts."""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE claim_verdict_enum ADD VALUE IF NOT EXISTS 'partially_supported'")


def downgrade():
    # PostgreSQL enum removal is destructive; retain historical values.
    pass
