"""Overall lifecycle and persisted execution events, preserving transcript status."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("debates", sa.Column("execution_state", sa.String(40), nullable=False, server_default="created"))
    op.execute("""UPDATE debates SET execution_state = CASE
      WHEN status::text = 'pending' THEN 'created'
      WHEN status::text IN ('failed','cancelled','running') THEN status::text
      WHEN EXISTS(SELECT 1 FROM debate_verdicts v WHERE v.debate_id=debates.id) THEN 'completed'
      ELSE 'analyzing' END""")
    op.create_table("execution_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("debate_id", UUID(as_uuid=True), sa.ForeignKey("debates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_execution_events_debate_id", "execution_events", ["debate_id"])


def downgrade():
    op.drop_table("execution_events")
    op.drop_column("debates", "execution_state")
