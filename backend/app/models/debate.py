import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.debate_agent import DebateAgent


class Debate(BaseModel):
    __tablename__ = "debates"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    expert_selection_mode: Mapped[str] = mapped_column(
        Enum("auto", "manual", name="expert_selection_mode_enum"), nullable=False, default="manual"
    )
    domain_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "running", "completed", "failed", "cancelled",
            name="debate_status_enum",
        ),
        nullable=False,
        default="pending",
    )
    mode: Mapped[str] = mapped_column(
        Enum("balanced", "pro_con", name="debate_mode_enum"),
        nullable=False,
        default="balanced",
    )
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    verify_evidence: Mapped[bool] = mapped_column(default=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", back_populates="debates")
    agents = relationship(
        "Agent",
        secondary="debate_agents",
        back_populates="debates",
        lazy="selectin",
        order_by=DebateAgent.position,
    )
    rounds = relationship(
        "DebateRound",
        back_populates="debate",
        cascade="all, delete-orphan",
        order_by="DebateRound.round_number",
        lazy="selectin",
    )
    messages = relationship(
        "DebateMessage",
        back_populates="debate",
        cascade="all, delete-orphan",
    )
    claims = relationship(
        "Claim",
        back_populates="debate",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    fallacies = relationship(
        "Fallacy",
        back_populates="debate",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    argument_evaluations = relationship(
        "ArgumentEvaluation",
        back_populates="debate",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def round_count(self) -> int:
        """Number of persisted rounds for this debate."""
        return len(self.rounds)
