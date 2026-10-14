from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

FallacyType = Literal[
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
]

SeverityType = Literal["low", "medium", "high"]


class FallacyResponse(BaseModel):
    """One fallacy analysis result.

    id is null only for a no_fallacy analysis response, which is never
    persisted as a row.
    """

    id: UUID | None = None
    debate_id: UUID
    message_id: UUID
    agent_id: UUID
    agent_name: str
    fallacy_type: FallacyType
    severity: SeverityType
    confidence: float
    explanation: str
    evidence_span: str | None = None
    created_at: datetime | None = None


class FallacyListResponse(BaseModel):
    debate_id: UUID
    fallacies: list[FallacyResponse]


class FallacyAnalysisListResponse(BaseModel):
    debate_id: UUID
    analyzed_count: int
    fallacies: list[FallacyResponse]
