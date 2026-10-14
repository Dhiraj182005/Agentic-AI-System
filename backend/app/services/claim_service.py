import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence import get_evidence_provider
from app.evidence.base import MAX_QUERY_LENGTH
from app.models.agent import Agent
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.models.user import User
from app.services.claim_extraction import (
    ClaimExtractionService,
    MessageContext,
)
from app.services.debate_service import get_debate
from app.services.verification_service import (
    ClaimVerificationService,
)

logger = logging.getLogger(__name__)

MAX_EVIDENCE_PER_CLAIM = 5

NO_EVIDENCE_EXPLANATION = (
    "No retrieved sources are available for this claim, so the available "
    "evidence is insufficient to evaluate it."
)


class ClaimServiceError(Exception):
    """Base class for claim/evidence service failures."""


class ClaimNotFoundError(ClaimServiceError):
    """Raised when a claim does not exist or is not owned by the user."""


class ClaimValidationError(ClaimServiceError):
    """Raised when a claim/evidence request is invalid."""


async def _load_message_contexts(
    db: AsyncSession, debate_id: UUID
) -> list[MessageContext]:
    rows = await db.execute(
        select(DebateMessage, Agent.name)
        .join(Agent, Agent.id == DebateMessage.agent_id)
        .join(DebateRound, DebateRound.id == DebateMessage.round_id)
        .where(DebateMessage.debate_id == debate_id)
        .order_by(DebateRound.round_number, DebateMessage.turn_number)
    )
    return [
        MessageContext(
            message_id=message.id,
            agent_id=message.agent_id,
            agent_name=agent_name,
            content=message.content,
        )
        for message, agent_name in rows
    ]


async def extract_claims(
    db: AsyncSession, user: User, debate_id: UUID
) -> list[tuple[Claim, str]]:
    """Extract claims from a debate's messages and persist them.

    Extraction runs at most once per debate: once claims exist they are
    returned as-is, so repeated requests can never duplicate claims (and do
    not spend another LLM call).
    """
    debate = await get_debate(db, user, debate_id)

    existing = await _load_claims(db, debate.id)
    if existing:
        return existing

    contexts = await _load_message_contexts(db, debate.id)
    if not contexts:
        raise ClaimValidationError("Debate has no messages to extract claims from")

    extracted = await ClaimExtractionService().extract(contexts)

    agent_by_message = {ctx.message_id: ctx.agent_id for ctx in contexts}
    known_keys: set[tuple[UUID, str]] = set()
    next_position: dict[UUID, int] = {}

    added = 0
    for item in extracted:
        message_id = UUID(item.message_id)
        key = (message_id, item.claim.strip().lower())
        if key in known_keys:
            continue
        db.add(
            Claim(
                debate_id=debate.id,
                message_id=message_id,
                agent_id=agent_by_message[message_id],
                text=item.claim,
                claim_type=item.claim_type,
                position=next_position.get(message_id, 0),
            )
        )
        next_position[message_id] = next_position.get(message_id, 0) + 1
        known_keys.add(key)
        added += 1

    if added:
        await db.flush()
    await db.commit()

    return await list_claims(db, user, debate.id)


async def _load_claims(
    db: AsyncSession, debate_id: UUID
) -> list[tuple[Claim, str]]:
    rows = await db.execute(
        select(Claim, Agent.name)
        .join(DebateMessage, DebateMessage.id == Claim.message_id)
        .join(DebateRound, DebateRound.id == DebateMessage.round_id)
        .join(Agent, Agent.id == Claim.agent_id)
        .where(Claim.debate_id == debate_id)
        .order_by(
            DebateRound.round_number,
            DebateMessage.turn_number,
            Claim.position,
            Claim.created_at,
            Claim.id,
        )
    )
    return [(claim, agent_name) for claim, agent_name in rows.all()]


async def list_claims(
    db: AsyncSession, user: User, debate_id: UUID
) -> list[tuple[Claim, str]]:
    """Return the debate's claims with agent names in deterministic order."""
    debate = await get_debate(db, user, debate_id)
    return await _load_claims(db, debate.id)


async def get_claim_for_user(
    db: AsyncSession, user: User, claim_id: UUID
) -> Claim:
    """Return a claim only when its debate belongs to the given user."""
    result = await db.execute(
        select(Claim, Debate.user_id)
        .join(Debate, Debate.id == Claim.debate_id)
        .where(Claim.id == claim_id)
    )
    row = result.first()
    if row is None or row[1] != user.id:
        raise ClaimNotFoundError("Claim not found")
    return row[0]


async def _load_evidence(db: AsyncSession, claim_id: UUID) -> list[Evidence]:
    rows = await db.execute(
        select(Evidence)
        .where(Evidence.claim_id == claim_id)
        .order_by(Evidence.position, Evidence.retrieved_at, Evidence.id)
    )
    return list(rows.scalars().all())


async def get_evidence(
    db: AsyncSession, user: User, claim_id: UUID
) -> list[Evidence]:
    """Return stored evidence for a claim. Never calls the provider."""
    claim = await get_claim_for_user(db, user, claim_id)
    return await _load_evidence(db, claim.id)


async def retrieve_evidence(
    db: AsyncSession, user: User, claim_id: UUID
) -> list[Evidence]:
    """Retrieve search results for a claim and persist them.

    Stored evidence is returned as-is so repeated requests do not call the
    provider again. Results are neutral search results: they never state
    whether the claim is true or false.
    """
    claim = await get_claim_for_user(db, user, claim_id)

    existing = await _load_evidence(db, claim.id)
    if existing:
        return existing

    query = (claim.text or "").strip()
    if not query:
        raise ClaimValidationError("Claim text cannot be empty")
    query = query[:MAX_QUERY_LENGTH]

    provider = get_evidence_provider()
    results = await provider.search(query, max_results=MAX_EVIDENCE_PER_CLAIM)

    for position, item in enumerate(results):
        db.add(
            Evidence(
                claim_id=claim.id,
                title=item.title,
                url=item.url,
                snippet=item.snippet,
                source_name=item.source_name,
                relevance_score=item.relevance_score,
                position=position,
            )
        )
    await db.commit()

    return await _load_evidence(db, claim.id)


async def _load_verification(
    db: AsyncSession, claim_id: UUID
) -> ClaimVerification | None:
    rows = await db.execute(
        select(ClaimVerification)
        .where(ClaimVerification.claim_id == claim_id)
        .limit(1)
    )
    return rows.scalars().first()


async def verify_claim(
    db: AsyncSession, user: User, claim_id: UUID
) -> ClaimVerification:
    """Evaluate a claim against its stored evidence and persist the result.

    Uses evidence already retrieved by Module 8 - it never calls the search
    provider. Claims without evidence get a structured insufficient_evidence
    result without calling the LLM. Each claim keeps exactly one current
    result: re-verification updates the existing row.
    """
    claim = await get_claim_for_user(db, user, claim_id)
    evidence = await _load_evidence(db, claim.id)
    existing = await _load_verification(db, claim.id)

    if not evidence:
        verdict_data = {
            "verdict": "insufficient_evidence",
            "confidence": "low",
            "explanation": NO_EVIDENCE_EXPLANATION,
            "evidence_summary": "",
            "evidence_ids": [],
        }
    else:
        output = await ClaimVerificationService().verify(claim, evidence)
        verdict_data = {
            "verdict": output.verdict,
            "confidence": output.confidence,
            "explanation": output.explanation,
            "evidence_summary": output.evidence_summary,
            "evidence_ids": [str(item.id) for item in evidence],
        }

    if existing is None:
        existing = ClaimVerification(claim_id=claim.id, **verdict_data)
        db.add(existing)
    else:
        for key, value in verdict_data.items():
            setattr(existing, key, value)
    await db.commit()
    await db.refresh(existing)

    return existing


async def get_verification(
    db: AsyncSession, user: User, claim_id: UUID
) -> ClaimVerification:
    """Return the latest stored verification result. Never calls the LLM."""
    claim = await get_claim_for_user(db, user, claim_id)
    verification = await _load_verification(db, claim.id)
    if verification is None:
        raise ClaimNotFoundError("No verification found for this claim")
    return verification
