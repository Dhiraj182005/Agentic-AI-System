from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ArgumentEvaluationResponse(BaseModel):
    id: UUID
    debate_id: UUID
    message_id: UUID
    agent_id: UUID
    agent_name: str
    logical_soundness: float
    evidence_score: float
    relevance_score: float
    effectiveness_score: float
    overall_score: float
    explanation: str
    created_at: datetime


class EvaluationListResponse(BaseModel):
    debate_id: UUID
    evaluations: list[ArgumentEvaluationResponse]
