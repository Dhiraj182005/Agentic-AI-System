import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# All scores use a 0-10 numeric scale:
# 0-2 very weak, 3-4 weak, 5-6 moderate, 7-8 strong, 9-10 excellent.
# Scores describe reasoning and presentation quality only - never truth.


class ArgumentEvaluation(Base):
    """Quality scores for one debate message's argument.

    One row per message: re-evaluation updates the existing row. A high score
    never means a claim is true; a low score never means it is false.
    """

    __tablename__ = "argument_evaluations"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_argument_evaluations_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    debate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("debates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("debate_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    logical_soundness: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    effectiveness_score: Mapped[float] = mapped_column(Float, nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    debate = relationship("Debate", back_populates="argument_evaluations")
    message = relationship("DebateMessage")
    agent = relationship("Agent", lazy="selectin")
