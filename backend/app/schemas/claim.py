from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ClaimType = Literal["factual", "opinion", "prediction", "definition", "other"]


class ClaimResponse(BaseModel):
    id: UUID
    debate_id: UUID
    message_id: UUID
    agent_id: UUID
    agent_name: str
    text: str
    claim_type: ClaimType
    position: int
    created_at: datetime
    # Google Fact Check outcome: matched / no_match / unavailable / failed,
    # or None when no fact-check search was attempted yet.
    fact_check_status: str | None = None
    canonical_claim_id: UUID | None = None


class ClaimListResponse(BaseModel):
    debate_id: UUID
    claims: list[ClaimResponse]


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    title: str
    url: str
    snippet: str
    source_name: str
    relevance_score: float | None = None
    retrieved_at: datetime
    # "web" (Tavily search result) or "google_fact_check" (published
    # fact-check). external_rating is the publisher's rating, not MAVES's.
    source_type: str = "web"
    publisher: str | None = None
    external_rating: str | None = None
    review_date: datetime | None = None
    claim_reviewed: str | None = None
    claimant: str | None = None


class EvidenceListResponse(BaseModel):
    claim_id: UUID
    evidence: list[EvidenceResponse]
    fact_check_status: str | None = None


VerdictType = Literal["supported", "contradicted", "partially_supported", "insufficient_evidence"]
ConfidenceType = Literal["low", "medium", "high"]


class ClaimVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    verdict: VerdictType
    confidence: ConfidenceType
    explanation: str
    evidence_summary: str
    evidence_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
