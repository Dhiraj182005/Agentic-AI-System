import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


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

    user = relationship("User", back_populates="debates")
