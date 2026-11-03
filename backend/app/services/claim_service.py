import asyncio
from datetime import datetime, timezone
import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence import get_evidence_provider
from app.core.config import get_settings
from app.evidence.base import MAX_QUERY_LENGTH, EvidenceConfigurationError, EvidenceProviderError
from app.evidence.google_fact_check import (
    FactCheckResult,
    get_fact_check_client,
    normalize_query,
)
from app.models.agent import Agent
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import SOURCE_FACT_CHECK, SOURCE_WEB, Evidence
from app.models.user import User
from app.services.claim_extraction import (
    EXTRACTION_BATCH_SIZE,
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


# Claim.fact_check_status values. Only matched/no_match mean a search ran.
FACT_CHECK_MATCHED = "matched"
FACT_CHECK_NO_MATCH = "no_match"
FACT_CHECK_UNAVAILABLE = "unavailable"  # no API key configured
FACT_CHECK_FAILED = "failed"  # HTTP error, quota, timeout, bad response


def normalized_claim(value: str) -> str:
    """Conservative grouping: preserve negations, quantities, dates and scope.

    Fuzzy semantic merging could turn conflicting assertions into one fact.
    Only typographical differences are collapsed automatically.
    """
    import unicodedata
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip().rstrip(".!?")

_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "that", "this", "with", "from",
    "has", "have", "had", "not", "but", "its", "than", "into", "more", "most",
    "will", "would", "can", "could", "their", "they", "them", "been", "being",
}


def _tokens(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(word) >= 3 and word not in _STOPWORDS
    }


def fact_check_relevance(claim_text: str, reviewed_text: str) -> float | None:
    """Word-overlap (Jaccard) between the debate claim and the claim the
    publisher reviewed: a rough signal that the fact-check is about the same
    statement, shown next to it. None when either side has no words."""
    a, b = _tokens(claim_text), _tokens(reviewed_text)
    if not a or not b:
        return None
    return round(len(a & b) / len(a | b), 2)


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
    db: AsyncSession, user: User, debate_id: UUID, *, progress=None
) -> list[tuple[Claim, str]]:
    """Extract claims from a debate's messages and persist them.

    Completed message extractions are reused, including empty results.
    Successful batches survive later failures; retries fill missing messages.
    """
    debate = await get_debate(db, user, debate_id)

    debate_id = debate.id
    contexts = await _load_message_contexts(db, debate_id)
    if not contexts:
        raise ClaimValidationError("Debate has no messages to extract claims from")
    service = ClaimExtractionService()
    # Lock before checking progress, including concurrent manual requests. Commit
    # each batch so later provider failures preserve both claims and empty results.
    from sqlalchemy import text
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(debate_id.bytes[:8], "big", signed=True)})
    # Link historical repeated assertions too. This changes only grouping
    # metadata, preserving every claim, source and original message reference.
    groups = {}
    for claim, _ in await _load_claims(db, debate_id):
        group = (normalized_claim(claim.text), claim.claim_type)
        if group in groups and claim.canonical_claim_id is None:
            claim.canonical_claim_id = groups[group]
        groups.setdefault(group, claim.canonical_claim_id or claim.id)
    await db.commit()
    for start in range(0, len(contexts), EXTRACTION_BATCH_SIZE):
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(debate_id.bytes[:8], "big", signed=True)})
        batch = contexts[start:start + EXTRACTION_BATCH_SIZE]
        completed = set((await db.execute(select(DebateMessage.id).where(
            DebateMessage.id.in_([c.message_id for c in batch]),
            DebateMessage.claims_extracted_at.is_not(None)))).scalars())
        pending = [ctx for ctx in batch if ctx.message_id not in completed]
        if not pending:
            await db.commit()
            continue
        extracted = await service.extract(pending)
        existing = await _load_claims(db, debate_id)
        normalize = normalized_claim
        known = {(c.message_id, normalize(c.text)) for c, _ in existing}
        canonical = {(normalize(c.text), c.claim_type): c.canonical_claim_id or c.id for c, _ in existing}
        positions = {}
        for claim, _ in existing:
            positions[claim.message_id] = max(positions.get(claim.message_id, 0), claim.position + 1)
        agents = {ctx.message_id: ctx.agent_id for ctx in pending}
        for item in extracted:
            mid = UUID(item.message_id)
            key = (mid, normalize(item.claim))
            if mid not in agents or key in known:
                continue
            import uuid
            claim_id = uuid.uuid4()
            group_key = (normalize(item.claim), item.claim_type)
            db.add(Claim(id=claim_id, debate_id=debate_id, message_id=mid, agent_id=agents[mid],
                         text=item.claim, claim_type=item.claim_type, position=positions.get(mid, 0),
                         canonical_claim_id=canonical.get(group_key)))
            canonical.setdefault(group_key, claim_id)
            positions[mid] = positions.get(mid, 0) + 1
            known.add(key)
        for ctx in pending:
            message = await db.get(DebateMessage, ctx.message_id)
            message.claims_extracted_at = datetime.now(timezone.utc)
        await db.commit()
        if progress:
            from sqlalchemy import func
            completed_count = await db.scalar(select(func.count()).select_from(DebateMessage).where(
                DebateMessage.debate_id == debate_id, DebateMessage.claims_extracted_at.is_not(None)))
            await progress({"messages_completed": completed_count, "messages_total": len(contexts),
                            "claims": len(await _load_claims(db, debate_id))})
    return await list_claims(db, user, debate_id)


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


async def _store_fact_checks(
    db: AsyncSession, claim: Claim, results: list[FactCheckResult]
) -> int:
    """Persist new fact-checks for a claim (skipping stored review URLs) and
    mark the claim as searched. Returns the number of rows added."""
    existing = await _load_evidence(db, claim.id)
    stored_urls = {e.url for e in existing if e.source_type == SOURCE_FACT_CHECK}
    position = max((e.position for e in existing), default=-1) + 1
    added = 0
    for item in results:
        if item.review_url in stored_urls:
            continue
        stored_urls.add(item.review_url)
        db.add(
            Evidence(
                claim_id=claim.id,
                source_type=SOURCE_FACT_CHECK,
                title=item.review_title or item.claim_text or item.review_url,
                url=item.review_url,
                snippet=item.claim_text,
                source_name=item.publisher_site or item.publisher_name,
                publisher=item.publisher_name,
                external_rating=item.textual_rating or None,
                review_date=item.review_date,
                claim_reviewed=item.claim_text or None,
                claimant=item.claimant,
                relevance_score=fact_check_relevance(claim.text, item.claim_text),
                position=position,
            )
        )
        position += 1
        added += 1
    has_matches = added > 0 or len(stored_urls) > 0
    claim.fact_check_status = FACT_CHECK_MATCHED if has_matches else FACT_CHECK_NO_MATCH
    claim.fact_check_searched_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request stored the same fact-checks first.
        await db.rollback()
        return 0
    return added


async def run_fact_check_stage(
    db: AsyncSession, user: User, claim_ids: list[UUID], client=None
) -> dict:
    """Search Google Fact Check for claims never searched successfully.

    Identical claim texts share one request and at most
    GOOGLE_FACT_CHECK_CONCURRENCY requests run at once; results are then
    stored one claim at a time (one DB session). Failures never raise: they
    are recorded on the claim (retried next run) and in the summary, so the
    Tavily search and verification continue without fact-checks.
    """
    settings = get_settings()
    summary = {
        "status": "ok", "searched": 0, "matched": 0, "no_match": 0,
        "failed": 0, "new_items": 0, "error": None, "new_claim_ids": [],
    }
    claims = [await get_claim_for_user(db, user, cid) for cid in claim_ids]
    pending = [c for c in claims if c.fact_check_searched_at is None]
    if not pending:
        summary["status"] = "up_to_date"
        return summary

    client = client or get_fact_check_client()
    if not client.configured:
        for claim in pending:
            claim.fact_check_status = FACT_CHECK_UNAVAILABLE
        await db.commit()
        summary["status"] = "unavailable"
        summary["error"] = "Google Fact Check is not configured, so only web search was used."
        return summary

    pending_ids = [c.id for c in pending]
    queries = {c.id: normalize_query(c.text) for c in pending}
    semaphore = asyncio.Semaphore(max(1, settings.GOOGLE_FACT_CHECK_CONCURRENCY))

    async def search(query: str):
        async with semaphore:
            try:
                return await client.search(query, max_results=settings.GOOGLE_FACT_CHECK_MAX_RESULTS)
            except EvidenceProviderError as exc:
                return exc

    grouped = {normalized_claim(q): q for q in queries.values() if q}
    searched = await asyncio.gather(*(search(q) for q in grouped.values()))
    outcomes = dict(zip(grouped, searched))

    for claim_id in pending_ids:
        claim = await db.get(Claim, claim_id)
        outcome = outcomes.get(normalized_claim(queries[claim_id]), [])
        if isinstance(outcome, EvidenceProviderError):
            claim.fact_check_status = FACT_CHECK_FAILED
            await db.commit()
            summary["failed"] += 1
            summary["error"] = str(outcome) or "The fact-check service failed."
            continue
        added = await _store_fact_checks(db, claim, outcome)
        claim = await db.get(Claim, claim_id)
        summary["searched"] += 1
        summary["new_items"] += added
        if added:
            summary["new_claim_ids"].append(claim_id)
        if claim.fact_check_status == FACT_CHECK_MATCHED:
            summary["matched"] += 1
        else:
            summary["no_match"] += 1
    if summary["failed"]:
        summary["status"] = "failed" if summary["failed"] == len(pending_ids) else "partial"
    return summary


async def retrieve_evidence(
    db: AsyncSession, user: User, claim_id: UUID, *, fact_check: bool = True, force: bool = False
) -> list[Evidence]:
    """Retrieve published fact-checks and web search results for a claim.

    Google Fact Check runs first (best effort - a missing key or failure is
    recorded on the claim and never blocks web search), then Tavily. Stored
    web results are returned as-is so repeated requests do not call Tavily
    again. Web results are neutral: they never state whether the claim is
    true or false; fact-check ratings are the publisher's, not MAVES's.
    """
    claim = await get_claim_for_user(db, user, claim_id)
    if fact_check:
        await run_fact_check_stage(db, user, [claim.id])
        claim = await get_claim_for_user(db, user, claim_id)

    from app.services.argument_analysis_service import _message_lock
    await _message_lock(db, claim_id)
    await db.refresh(claim)
    existing = await _load_evidence(db, claim.id)
    if not force and (any(e.source_type == SOURCE_WEB for e in existing) or claim.evidence_retrieved_at is not None):
        return existing

    # Reuse the same normalized assertion's web search, retaining evidence
    # foreign keys for every message occurrence.
    if not force and claim.canonical_claim_id:
        canonical = await db.get(Claim, claim.canonical_claim_id)
        if canonical and canonical.evidence_retrieved_at is not None:
            for source in await _load_evidence(db, canonical.id):
                if source.source_type == SOURCE_WEB:
                    db.add(Evidence(claim_id=claim.id, source_type=SOURCE_WEB,
                        title=source.title, url=source.url, snippet=source.snippet,
                        source_name=source.source_name, relevance_score=source.relevance_score,
                        position=len(existing)))
            claim.evidence_retrieved_at = canonical.evidence_retrieved_at
            await db.commit()
            return await _load_evidence(db, claim.id)

    query = (claim.text or "").strip()
    if not query:
        raise ClaimValidationError("Claim text cannot be empty")
    query = query[:MAX_QUERY_LENGTH]

    provider = get_evidence_provider()
    results = await provider.search(query, max_results=MAX_EVIDENCE_PER_CLAIM)
    claim.evidence_retrieved_at = datetime.now(timezone.utc)

    offset = max((e.position for e in existing), default=-1) + 1
    existing_urls = {e.url for e in existing if e.source_type == SOURCE_WEB}
    for position, item in enumerate(results, start=offset):
        if item.url in existing_urls:
            continue
        existing_urls.add(item.url)
        db.add(
            Evidence(
                claim_id=claim.id,
                source_type=SOURCE_WEB,
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
    from app.services.argument_analysis_service import _message_lock
    await _message_lock(db, claim_id)
    await db.refresh(claim)
    evidence = await _load_evidence(db, claim.id)
    if claim.claim_type != "factual":
        raise ClaimValidationError("Only factual claims can receive an evidence verification verdict")
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
