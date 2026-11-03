from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

VerdictPosition = Literal["supports", "opposes", "mixed", "inconclusive"]
VerdictConfidence = Literal["low", "medium", "high"]


class VerdictSource(BaseModel):
    title: str
    url: str
    source_name: str
    source_type: str = "web"
    publisher: str | None = None
    external_rating: str | None = None


class VerdictClaimRef(BaseModel):
    """A stored claim the verdict cites, with its stored verification."""

    id: UUID
    text: str
    agent_name: str
    verdict: str | None = None  # supported / contradicted / insufficient_evidence
    confidence: str | None = None
    sources: list[VerdictSource] = []


class VerdictArgument(BaseModel):
    point: str
    agent_name: str | None = None
    impact: str | None = None  # counterarguments only
    claims: list[VerdictClaimRef] = []


class EvidenceSnapshot(BaseModel):
    total_claims: int = 0
    factual_claims: int | None = None
    non_factual_claims: int = 0
    partially_supported: int = 0
    supported: int = 0
    contradicted: int = 0
    insufficient_evidence: int = 0
    unverified: int = 0
    evidence_sources: int = 0
    # State of the post-debate analysis run when the verdict was generated.
    analysis_state: str = "not_run"
    analysis_failures: int = 0
    # Model that wrote the verdict (may be a daily-quota fallback model).
    model: str | None = None


class VerdictResponse(BaseModel):
    id: UUID
    debate_id: UUID
    position: VerdictPosition
    answer: str
    preferred_position: str | None = None
    summary: str
    reasoning: str
    supporting_arguments: list[VerdictArgument] = []
    counterarguments: list[VerdictArgument] = []
    confidence: VerdictConfidence
    confidence_basis: str
    limitations: list[str] = []
    unresolved_questions: list[str] = []
    evidence_snapshot: EvidenceSnapshot
    # none: no claim is supported/contradicted by stored evidence;
    # partial: under half of the claims are; substantial: half or more.
    evidence_basis: Literal["none", "partial", "substantial"] = "none"
    # Only for inconclusive verdicts: why the question was not settled.
    inconclusive_reason: Literal[
        "no_verified_evidence",
        "conflicting_evidence",
        "incomplete_evidence",
        "analysis_incomplete",
    ] | None = None
    # Bias awareness: assumptions built into the question, and separate
    # verdicts for the propositions a compound question bundles.
    assumptions: list[dict] = []
    sub_verdicts: list[dict] = []
    # True when claims or verifications changed after the verdict.
    stale: bool = False
    created_at: datetime
    updated_at: datetime
