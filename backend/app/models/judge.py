import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Float, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# A judgment exists in one stored state ("completed"); outcome carries the
# winner/tie/inconclusive distinction instead.
JUDGMENT_STATUSES = ("completed",)
JUDGMENT_OUTCOMES = ("winner", "tie", "inconclusive")


class DebateJudgment(Base):
    """The stored result of judging one completed debate.

    One row per debate (unique debate_id): judging an already-judged debate
    returns the existing row instead of appending duplicates. The judgment is
    a rubric-based recommendation about argument quality - never an objective
    truth value for any claim made in the debate.
    """

    __tablename__ = "debate_judgments"
    __table_args__ = (
        UniqueConstraint("debate_id", name="uq_debate_judgments_debate_id"),
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
    status: Mapped[str] = mapped_column(
        Enum(*JUDGMENT_STATUSES, name="judgment_status_enum", validate_strings=True),
        nullable=False,
        default="completed",
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    winner_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    outcome: Mapped[str] = mapped_column(
        Enum(*JUDGMENT_OUTCOMES, name="judgment_outcome_enum", validate_strings=True),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Snapshot of the rubric used: weights, formula and minimum score gap at
    # judgment time, so stored results stay interpretable after config changes.
    scoring_rubric: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Per-agent records: identity, seven dimensions (null = unavailable),
    # final score, strengths/weaknesses, assessments and limitations.
    agent_scores: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    limitations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    debate = relationship("Debate", back_populates="judgment")
    winner = relationship("Agent")
