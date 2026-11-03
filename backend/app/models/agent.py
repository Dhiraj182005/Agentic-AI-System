import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

AGENT_SOURCE_BUILTIN = "builtin"
AGENT_SOURCE_DYNAMIC = "dynamic"


class Agent(BaseModel):
    """A debate participant.

    Built-in agents (Economist, Lawyer, ...) are shared rows with
    ``source='builtin'``. Topic-specific AI specialist roles are created for
    one debate only (``source='dynamic'``, ``debate_id`` set): they keep
    messages, claims and judgments referentially intact and make a finished
    debate reproducible, are deleted with their debate, and are never listed
    or reused elsewhere.
    """

    __tablename__ = "agents"
    __table_args__ = (
        # Built-in names stay unique; specialist names may repeat across debates.
        Index(
            "uq_agents_builtin_name",
            "name",
            unique=True,
            postgresql_where=text("debate_id IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_core: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AGENT_SOURCE_BUILTIN,
        server_default=AGENT_SOURCE_BUILTIN,
    )
    # Validated specialist definition (see services/topic_analysis.py) plus
    # provenance; NULL for built-in agents.
    definition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    debate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("debates.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    debates = relationship(
        "Debate",
        secondary="debate_agents",
        back_populates="agents",
    )
