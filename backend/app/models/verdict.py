import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# Position of the verdict relative to the debate question as asked:
# supports = the evidence favours "yes" / the proposition, opposes = "no",
# mixed = it depends / partly, inconclusive = the stored evidence does not
# settle the question.
VERDICT_POSITIONS = ("supports", "opposes", "mixed", "inconclusive")
VERDICT_CONFIDENCES = ("low", "medium", "high")


class DebateVerdict(Base):
    """The final debate verdict: an answer to the debate question itself.

    Separate from DebateJudgment on purpose. The judgment ranks how well each
    agent argued; the verdict states which position the stored evidence and
    arguments support. A best-performing agent is never treated as the
    correct answer. One row per debate.
    """

    __tablename__ = "debate_verdicts"
    __table_args__ = (
        UniqueConstraint("debate_id", name="uq_debate_verdicts_debate_id"),
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
    position: Mapped[str] = mapped_column(
        Enum(*VERDICT_POSITIONS, name="verdict_position_enum", validate_strings=True),
        nullable=False,
    )
    # One-sentence answer to the debate question.
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # The better-supported position in plain words; null when inconclusive.
    preferred_position: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"point", "agent_name" | null, "claim_ids": [uuid str]}]
    supporting_arguments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # [{"point", "agent_name" | null, "impact", "claim_ids": [uuid str]}]
    counterarguments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[str] = mapped_column(
        Enum(*VERDICT_CONFIDENCES, name="verdict_confidence_enum", validate_strings=True),
        nullable=False,
    )
    # Server-written explanation of how the confidence label was capped.
    confidence_basis: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    unresolved_questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Claim verification counts at generation time (supported, contradicted,
    # insufficient_evidence, unverified, total, evidence_sources).
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # [{"assumption", "assessment", "status": supported|contested|unsupported|unclear}]
    assumptions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{"question", "position", "answer"}] for compound questions.
    sub_verdicts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    debate = relationship("Debate", back_populates="verdict")
