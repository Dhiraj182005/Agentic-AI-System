import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

VERDICTS = ("supported", "contradicted", "insufficient_evidence")
CONFIDENCE_LEVELS = ("low", "medium", "high")


class ClaimVerification(Base):
    """The current evidence-based evaluation of a single claim.

    One row per claim (Option A): re-verification updates the existing row
    instead of appending duplicates. Verdicts describe what the retrieved
    evidence indicates - never an absolute truth value.
    """

    __tablename__ = "claim_verifications"
    __table_args__ = (
        UniqueConstraint("claim_id", name="uq_claim_verifications_claim_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verdict: Mapped[str] = mapped_column(
        Enum(
            *VERDICTS,
            name="claim_verdict_enum",
            validate_strings=True,
        ),
        nullable=False,
    )
    confidence: Mapped[str] = mapped_column(
        Enum(
            *CONFIDENCE_LEVELS,
            name="verification_confidence_enum",
            validate_strings=True,
        ),
        nullable=False,
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    evidence_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    claim = relationship("Claim", back_populates="verification")
