import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.models.fallacy import Fallacy
from app.models.user import User
from app.services.argument_evaluation import (
    ArgumentEvaluationService,
)
from app.services.debate_service import get_debate
from app.services.fallacy_detection import (
    DetectedFallacy,
    FallacyDetectionService,
)

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 600
MAX_SUPPORTING_CLAIMS = 3
MAX_SUPPORTING_TITLES = 3


class ArgumentAnalysisError(Exception):
    """Base class for fallacy/evaluation service failures."""


class ArgumentAnalysisValidationError(ArgumentAnalysisError):
    """Raised when an analysis request is invalid."""


class MessageNotFoundError(ArgumentAnalysisError):
    """Raised when a message does not exist or is not owned by the user."""


@dataclass
class MessageAnalysis:
    """A debate message prepared for argument analysis."""

    message_id: UUID
    debate_id: UUID
    agent_id: UUID
    agent_name: str
    content: str
    topic: str
    previous_content: str | None


@dataclass
class FallacyAnalysisResult:
    """One message's analysis outcome: the result plus its persisted row.

    Explicit no_fallacy outcomes are persisted with timestamps too.
    """

    analysis: MessageAnalysis
    detected: DetectedFallacy
    fallacy: Fallacy | None


async def _load_previous_content(
    db: AsyncSession, message: DebateMessage
) -> str | None:
    """Return the message immediately before this one, for limited context."""
    round_number = await db.scalar(
        select(DebateRound.round_number).where(DebateRound.id == message.round_id)
    )
    if round_number is None:
        return None
    rows = await db.execute(
        select(DebateMessage.content, DebateRound.round_number)
        .join(DebateRound, DebateRound.id == DebateMessage.round_id)
        .where(
            DebateMessage.debate_id == message.debate_id,
            or_(
                DebateRound.round_number < round_number,
                (DebateRound.round_number == round_number)
                & (DebateMessage.turn_number < message.turn_number),
            ),
        )
        .order_by(DebateRound.round_number.desc(), DebateMessage.turn_number.desc())
        .limit(1)
    )
    row = rows.first()
    if row is None:
        return None
    return (row[0] or "")[:MAX_CONTEXT_CHARS] or None


async def get_message_for_user(
    db: AsyncSession, user: User, message_id: UUID
) -> MessageAnalysis:
    """Return a message for analysis only when its debate belongs to the user."""
    rows = await db.execute(
        select(DebateMessage, Agent.name, Debate.topic, Debate.user_id)
        .join(Agent, Agent.id == DebateMessage.agent_id)
        .join(Debate, Debate.id == DebateMessage.debate_id)
        .where(DebateMessage.id == message_id)
    )
    row = rows.first()
    if row is None or row[3] != user.id:
        raise MessageNotFoundError("Message not found")
    message, agent_name, topic, _ = row
    previous = await _load_previous_content(db, message)
    return MessageAnalysis(
        message_id=message.id,
        debate_id=message.debate_id,
        agent_id=message.agent_id,
        agent_name=agent_name,
        content=message.content,
        topic=topic,
        previous_content=previous,
    )


async def _load_debate_messages(
    db: AsyncSession, debate_id: UUID
) -> list[MessageAnalysis]:
    rows = (
        await db.execute(
            select(DebateMessage, Agent.name, Debate.topic)
            .join(Agent, Agent.id == DebateMessage.agent_id)
            .join(DebateRound, DebateRound.id == DebateMessage.round_id)
            .join(Debate, Debate.id == DebateMessage.debate_id)
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateRound.round_number, DebateMessage.turn_number)
        )
    ).all()

    results: list[MessageAnalysis] = []
    previous: str | None = None
    topic = ""
    for message, agent_name, message_topic in rows:
        topic = message_topic
        results.append(
            MessageAnalysis(
                message_id=message.id,
                debate_id=message.debate_id,
                agent_id=message.agent_id,
                agent_name=agent_name,
                content=message.content,
                topic=topic,
                previous_content=previous,
            )
        )
        previous = (message.content or "")[:MAX_CONTEXT_CHARS] or None
    return results


async def _replace_message_fallacies(
    db: AsyncSession,
    analysis: MessageAnalysis,
    detected: list[DetectedFallacy],
) -> list[Fallacy]:
    """Duplicate protection: recalculate one message's fallacies from scratch.

    Re-running analysis replaces the message's existing rows instead of
    appending, including explicit no_fallacy outcomes, so
    repeated requests cannot create duplicate records.
    """
    await db.execute(
        delete(Fallacy).where(Fallacy.message_id == analysis.message_id)
    )
    created: list[Fallacy] = []
    for item in detected:
        row = Fallacy(
            debate_id=analysis.debate_id,
            message_id=analysis.message_id,
            agent_id=analysis.agent_id,
            fallacy_type=item.fallacy_type,
            severity=item.severity,
            confidence=item.confidence,
            explanation=item.explanation,
            evidence_span=item.evidence_span,
        )
        db.add(row)
        created.append(row)
    return created


async def analyze_debate_fallacies(
    db: AsyncSession, user: User, debate_id: UUID
) -> list[FallacyAnalysisResult]:
    """Compatibility service: resumable batch, with per-message persistence."""
    from app.services.message_pipeline import run_message_batch
    await run_message_batch(db, user, debate_id, stage="fallacy")
    results = []
    for row, _ in await list_fallacies(db, user, debate_id):
        analysis = await get_message_for_user(db, user, row.message_id)
        results.append(FallacyAnalysisResult(analysis, DetectedFallacy(
            fallacy_type=row.fallacy_type, severity=row.severity, confidence=row.confidence,
            explanation=row.explanation, evidence_span=row.evidence_span), row))
    return results



async def analyze_message_fallacy(
    db: AsyncSession, user: User, message_id: UUID, *, force: bool = False
) -> FallacyAnalysisResult:
    """Analyze a single message and persist its explicit outcome."""
    analysis = await get_message_for_user(db, user, message_id)
    await _message_lock(db, message_id)
    existing = (await db.execute(select(Fallacy).where(Fallacy.message_id == message_id))).scalars().first()
    if existing is not None and not force:
        return FallacyAnalysisResult(analysis, DetectedFallacy(
            fallacy_type=existing.fallacy_type, severity=existing.severity,
            confidence=existing.confidence, explanation=existing.explanation,
            evidence_span=existing.evidence_span), existing)
    detected = await FallacyDetectionService().detect(
        analysis.content,
        analysis.agent_name,
        analysis.topic,
        analysis.previous_content,
    )
    created = await _replace_message_fallacies(db, analysis, [detected])
    await db.commit()
    for row in created:
        await db.refresh(row)
    return FallacyAnalysisResult(
        analysis=analysis, detected=detected, fallacy=created[0] if created else None
    )


async def list_fallacies(
    db: AsyncSession, user: User, debate_id: UUID
) -> list[tuple[Fallacy, str]]:
    """Return the debate's stored fallacies in deterministic order."""
    debate = await get_debate(db, user, debate_id)
    rows = (
        await db.execute(
            select(Fallacy, Agent.name).options(selectinload(Fallacy.message))
            .join(DebateMessage, DebateMessage.id == Fallacy.message_id)
            .join(DebateRound, DebateRound.id == DebateMessage.round_id)
            .join(Agent, Agent.id == Fallacy.agent_id)
            .where(Fallacy.debate_id == debate.id)
            .order_by(
                DebateRound.round_number,
                DebateMessage.turn_number,
                Fallacy.created_at,
                Fallacy.id,
            )
        )
    ).all()
    return [(fallacy, agent_name) for fallacy, agent_name in rows]


async def _load_supporting_context(
    db: AsyncSession, message_id: UUID
) -> list[str]:
    """Summarize stored claims/evidence/verification for this message.

    Used as reference context for argument quality scoring. It never
    replaces verification results and never asserts that a claim is true.
    """
    claims = (
        (
            await db.execute(
                select(Claim)
                .where(Claim.message_id == message_id)
                .order_by(Claim.position, Claim.created_at, Claim.id)
                .limit(MAX_SUPPORTING_CLAIMS)
            )
        )
        .scalars()
        .all()
    )

    lines: list[str] = []
    for claim in claims:
        text = (claim.text or "").strip()
        if len(text) > 200:
            text = text[:200] + " [...]"
        lines.append(f'Claim: "{text}"')

        verification = (
            await db.execute(
                select(ClaimVerification)
                .where(ClaimVerification.claim_id == claim.id)
                .limit(1)
            )
        ).scalars().first()
        if verification is not None:
            explanation = (verification.explanation or "").strip()
            if len(explanation) > 200:
                explanation = explanation[:200] + " [...]"
            lines.append(
                f"Stored evidence check: {verification.verdict} - {explanation}"
            )

        titles = (
            (
                await db.execute(
                    select(Evidence.title)
                    .where(Evidence.claim_id == claim.id)
                    .order_by(Evidence.position, Evidence.retrieved_at, Evidence.id)
                    .limit(MAX_SUPPORTING_TITLES)
                )
            )
            .scalars()
            .all()
        )
        titles = [
            (title or "").strip()
            for title in titles
            if isinstance(title, str) and title.strip()
        ]
        if titles:
            lines.append("Retrieved sources: " + "; ".join(titles))

    return lines[:6]


async def evaluate_argument(
    db: AsyncSession, user: User, message_id: UUID, *, force: bool = False
) -> tuple[ArgumentEvaluation, str]:
    """Evaluate one message's argument quality and persist the result.

    One current evaluation per message: re-evaluating updates the existing
    row instead of appending duplicates.
    """
    analysis = await get_message_for_user(db, user, message_id)
    await _message_lock(db, message_id)
    stored = (await db.execute(select(ArgumentEvaluation).where(
        ArgumentEvaluation.message_id == message_id))).scalars().first()
    if stored is not None and not force:
        return stored, analysis.agent_name
    supporting_context = await _load_supporting_context(db, message_id)

    output = await ArgumentEvaluationService().evaluate(
        analysis.content,
        analysis.agent_name,
        analysis.topic,
        analysis.previous_content,
        supporting_context,
    )
    if output.responsiveness is None or output.completeness is None:
        from app.services.argument_evaluation import ArgumentEvaluationError
        raise ArgumentEvaluationError("The model omitted required rubric criteria. Retry evaluation.")

    from app.services import judge_rubric
    verdicts = (await db.execute(select(ClaimVerification.verdict).join(
        Claim, Claim.id == ClaimVerification.claim_id).where(Claim.message_id == message_id))).scalars().all()
    evidence_ids = (await db.execute(select(Evidence.id).join(Claim).where(
        Claim.message_id == message_id))).scalars().all()
    checks = (await db.execute(select(Fallacy).where(Fallacy.message_id == message_id))).scalars().all()
    risk = None if not checks else judge_rubric.compute_fallacy_risk(
        [(f.severity, f.confidence) for f in checks if f.fallacy_type != "no_fallacy"], 1)
    if checks and all(f.fallacy_type == "no_fallacy" for f in checks):
        risk = 0.0
    dimensions = dict(logical_soundness=output.logical_soundness,
        evidence_quality=output.evidence_score if evidence_ids else None,
        factual_support=judge_rubric.compute_factual_support(list(verdicts)),
        responsiveness=output.responsiveness, relevance=output.relevance_score,
        effectiveness=output.effectiveness_score, completeness=output.completeness,
        fallacy_risk=risk)

    values = {
        "logical_soundness": output.logical_soundness,
        "evidence_score": output.evidence_score,
        "relevance_score": output.relevance_score,
        "effectiveness_score": output.effectiveness_score,
        "overall_score": judge_rubric.round_final(judge_rubric.compute_agent_score(dimensions)),
        "explanation": output.explanation,
        "responsiveness": output.responsiveness,
        "completeness": output.completeness,
        "factual_support": dimensions["factual_support"],
        "fallacy_risk": risk,
        "criterion_scores": dimensions,
        "rubric_version": judge_rubric.RUBRIC_VERSION,
        "strengths": output.strengths,
        "weaknesses": output.weaknesses,
        "evaluated_at": datetime.now(timezone.utc),
    }

    existing = (
        (
            await db.execute(
                select(ArgumentEvaluation).where(
                    ArgumentEvaluation.message_id == analysis.message_id
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        existing = ArgumentEvaluation(
            debate_id=analysis.debate_id,
            message_id=analysis.message_id,
            agent_id=analysis.agent_id,
            **values,
        )
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)
    await db.commit()
    await db.refresh(existing)
    return existing, analysis.agent_name


async def _message_lock(db: AsyncSession, message_id: UUID) -> None:
    """Serialize manual and batch changes across workers, before provider calls."""
    message_id = UUID(str(message_id))
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                     {"key": int.from_bytes(message_id.bytes[:8], "big", signed=True)})


async def list_evaluations(
    db: AsyncSession, user: User, debate_id: UUID
) -> list[tuple[ArgumentEvaluation, str]]:
    """Return the debate's stored argument evaluations in deterministic order."""
    debate = await get_debate(db, user, debate_id)
    rows = (
        await db.execute(
            select(ArgumentEvaluation, Agent.name)
            .join(DebateMessage, DebateMessage.id == ArgumentEvaluation.message_id)
            .join(DebateRound, DebateRound.id == DebateMessage.round_id)
            .join(Agent, Agent.id == ArgumentEvaluation.agent_id)
            .where(ArgumentEvaluation.debate_id == debate.id)
            .order_by(
                DebateRound.round_number,
                DebateMessage.turn_number,
                ArgumentEvaluation.created_at,
                ArgumentEvaluation.id,
            )
        )
    ).all()
    return [(evaluation, agent_name) for evaluation, agent_name in rows]
