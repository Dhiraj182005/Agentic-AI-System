import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


SOURCE_WEB = "web"
SOURCE_FACT_CHECK = "google_fact_check"


class Evidence(Base):
    """Evidence stored for a claim.

    ``web`` rows are neutral search results (Tavily). ``google_fact_check``
    rows are published fact-checks: ``external_rating`` is the publisher's
    rating of the claim *they* reviewed (``claim_reviewed``), an external
    opinion that is never treated as MAVES's own verdict.
    """

    __tablename__ = "evidence"
    __table_args__ = (
        # A published fact-check is stored at most once per claim.
        Index(
            "uq_evidence_claim_fact_check_url",
            "claim_id",
            "url",
            unique=True,
            postgresql_where=text("source_type = 'google_fact_check'"),
        ),
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
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    source_type: Mapped[str] = mapped_column(
        Text, nullable=False, default=SOURCE_WEB, server_default=SOURCE_WEB
    )
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_rating: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_reviewed: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimant: Mapped[str | None] = mapped_column(Text, nullable=True)

    claim = relationship("Claim", back_populates="evidence")
