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


class EvidenceListResponse(BaseModel):
    claim_id: UUID
    evidence: list[EvidenceResponse]


VerdictType = Literal["supported", "contradicted", "insufficient_evidence"]
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
