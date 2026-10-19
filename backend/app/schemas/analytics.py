"""Response schemas for the analytics dashboard (Module 12)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# Modelled debate lifecycle states (mirrors debate_status_enum).
DEBATE_STATUSES = ("pending", "running", "completed", "failed", "cancelled")

# Claim verdicts and confidence levels (mirrors the verification enums).
CLAIM_VERDICTS = ("supported", "contradicted", "insufficient_evidence")
CONFIDENCE_LEVELS = ("low", "medium", "high")

# Module 11 rubric dimensions plus the Module 10 overall score.
RUBRIC_DIMENSIONS = (
    "logical_soundness",
    "evidence_quality",
    "factual_support",
    "relevance",
    "effectiveness",
    "completeness",
    "fallacy_risk",
)
EVALUATION_DIMENSIONS = (
    "logical_soundness",
    "evidence_score",
    "relevance_score",
    "effectiveness_score",
    "overall_score",
)


class StatusCount(BaseModel):
    status: str
    count: int


class SummaryResponse(BaseModel):
    total_debates: int
    completed_debates: int
    running_debates: int
    failed_debates: int
    pending_debates: int
    cancelled_debates: int
    total_messages: int
    total_claims: int
    verified_claims: int
    unverified_claims: int
    debates_with_judgment: int
    completion_rate: float | None = None
    status_distribution: list[StatusCount] = Field(default_factory=list)


class ActivityBucket(BaseModel):
    date: str
    count: int


class DebateActivityResponse(BaseModel):
    days: int
    start_date: str
    end_date: str
    bucket: str = "day"
    buckets: list[ActivityBucket] = Field(default_factory=list)
    total_debates_in_range: int


class NamedCount(BaseModel):
    name: str
    count: int


class ClaimVerificationResponse(BaseModel):
    total_verifications: int
    verdict_counts: list[NamedCount] = Field(default_factory=list)
    confidence_counts: list[NamedCount] = Field(default_factory=list)
    verified_claims: int
    unverified_claims: int
    scope: str


class DimensionAverage(BaseModel):
    dimension: str
    average: float | None


class AgentPerformanceItem(BaseModel):
    agent_id: str
    agent_name: str
    agent_role: str
    appearances: int
    average_score: float | None
    dimension_averages: list[DimensionAverage] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class AgentPerformanceResponse(BaseModel):
    agents: list[AgentPerformanceItem] = Field(default_factory=list)
    judgments_analyzed: int
    available: bool


class ArgumentQualityResponse(BaseModel):
    available: bool
    fallacy_available: bool
    evaluation_available: bool
    fallacy_total: int
    fallacy_type_counts: list[NamedCount] = Field(default_factory=list)
    severity_counts: list[NamedCount] = Field(default_factory=list)
    fallacy_analyzed_message_count: int = 0
    evaluation_total: int
    evaluated_message_count: int
    unevaluated_message_count: int | None
    dimension_averages: list[DimensionAverage] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RecentDebateItem(BaseModel):
    id: str
    topic: str
    created_at: datetime
    status: str
    agent_count: int
    round_count: int
    message_count: int
    has_verification: bool
    has_judgment: bool


class RecentDebatesResponse(BaseModel):
    debates: list[RecentDebateItem] = Field(default_factory=list)
    page: int
    page_size: int
    total: int
    total_pages: int
