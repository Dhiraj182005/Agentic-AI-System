import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# Controlled vocabulary for detected fallacies. "no_fallacy" is the value the
# analysis model must prefer when the evidence for a fallacy is weak; real
# fallacy rows are never stored with it (see argument_analysis_service).
FALLACY_TYPES = (
    "ad_hominem",
    "straw_man",
    "false_dilemma",
    "slippery_slope",
    "appeal_to_authority",
    "appeal_to_emotion",
    "hasty_generalization",
    "circular_reasoning",
    "red_herring",
    "false_cause",
    "bandwagon",
    "loaded_question",
    "tu_quoque",
    "no_fallacy",
)

# Severity describes how much the fallacy undermines the argument's
# reasoning - it never means the underlying claim is false.
FALLACY_SEVERITIES = ("low", "medium", "high")


class Fallacy(Base):
    """A detected logical/rhetorical fallacy in one debate message.

    Only real fallacies are persisted (never "no_fallacy"), at most one row
    per message and fallacy type. A detected fallacy is a statement about the
    argument's reasoning structure - it is not a truth value for any claim.
    """

    __tablename__ = "fallacies"
    __table_args__ = (
        UniqueConstraint("message_id", "fallacy_type", name="uq_fallacies_message_type"),
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
    fallacy_type: Mapped[str] = mapped_column(
        Enum(
            *FALLACY_TYPES,
            name="fallacy_type_enum",
            validate_strings=True,
        ),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        Enum(
            *FALLACY_SEVERITIES,
            name="fallacy_severity_enum",
            validate_strings=True,
        ),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    debate = relationship("Debate", back_populates="fallacies")
    message = relationship("DebateMessage")
    agent = relationship("Agent", lazy="selectin")
