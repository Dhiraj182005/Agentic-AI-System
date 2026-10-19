from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AgentDimensionScores(BaseModel):
    """The seven rubric dimensions; null means the dimension's data was
    unavailable (its weight is excluded, see scoring_rubric)."""

    logical_soundness: float | None = None
    evidence_quality: float | None = None
    factual_support: float | None = None
    relevance: float | None = None
    effectiveness: float | None = None
    completeness: float | None = None
    fallacy_risk: float | None = None


class AgentScoreCard(BaseModel):
    agent_id: str
    agent_name: str
    agent_role: str
    dimensions: AgentDimensionScores
    unavailable_dimensions: list[str] = []
    final_score: float
    strengths: list[str] = []
    weaknesses: list[str] = []
    reasoning_quality: str = ""
    evidence_quality_assessment: str = ""
    factual_support_assessment: str = ""
    fallacy_impact_assessment: str = ""
    confidence: str = "medium"
    limitations: list[str] = []


class JudgmentResponse(BaseModel):
    id: UUID
    debate_id: UUID
    status: str
    overall_score: float
    outcome: Literal["winner", "tie", "inconclusive"]
    winner_agent_id: UUID | None = None
    winner_name: str | None = None
    summary: str
    limitations: list[str] | None = None
    scoring_rubric: dict = {}
    agent_scores: list[AgentScoreCard] = []
    created_at: datetime
    updated_at: datetime
