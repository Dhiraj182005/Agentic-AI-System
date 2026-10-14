import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

CLAIM_TYPES = ("factual", "opinion", "prediction", "definition", "other")


class Claim(Base):
    """A factual or examinable claim extracted from a debate message.

    Claims are extracted claims only: no truth value is ever stored here.
    """

    __tablename__ = "claims"

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
    text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(
        Enum(
            *CLAIM_TYPES,
            name="claim_type_enum",
            validate_strings=True,
        ),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    debate = relationship("Debate", back_populates="claims")
    message = relationship("DebateMessage")
    agent = relationship("Agent", lazy="selectin")
    evidence = relationship(
        "Evidence", back_populates="claim", cascade="all, delete-orphan"
    )
    verification = relationship(
        "ClaimVerification",
        back_populates="claim",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
    )
