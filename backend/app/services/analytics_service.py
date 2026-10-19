"""Analytics aggregation for the dashboard (Module 12).

All figures are computed from the authenticated user's own persisted records:
debates, messages, claims, claim verifications, fallacies, argument
evaluations and debate judgments. No metric is fabricated, no new table is
written, and no result depends on an external service.

Counting rules:
- Debate counts use the Debate table and its persisted ``status`` field.
- Message counts use stored debate messages (one row per posted message).
- Claim counts use the claims table; a claim counts as verified only when a
  claim_verifications row exists for it (unverified != insufficient_evidence).
- Agent performance aggregates the Module 11 judgment ``agent_scores`` JSON
  exactly as stored (the judge's own rubric); agents without appearances are
  reported with average None, never 0.
- Fallacy and evaluation statistics come only from stored Module 10 rows;
  messages without a stored analysis are counted as not-analyzed, never as
  clean or fallacy-free.

Timestamps are stored timezone-aware; activity buckets are grouped by UTC
calendar day (``created_at AT TIME ZONE 'UTC'``).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import CONFIDENCE_LEVELS, VERDICTS, ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.fallacy import FALLACY_SEVERITIES, FALLACY_TYPES, Fallacy
from app.models.judge import DebateJudgment
from app.schemas.analytics import (
    DEBATE_STATUSES,
    EVALUATION_DIMENSIONS,
    RUBRIC_DIMENSIONS,
    ActivityBucket,
    AgentPerformanceItem,
    DimensionAverage,
    NamedCount,
)

MAX_STRENGTHS = 5
MAX_WEAKNESSES = 5


async def _count_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Debate.id)).where(Debate.user_id == user_id)
    )
    return int(result.scalar_one())


async def summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    total = await _count_for_user(db, user_id)

    status_rows = await db.execute(
        select(Debate.status, func.count(Debate.id))
        .where(Debate.user_id == user_id)
        .group_by(Debate.status)
    )
    counts_by_status = {status: int(count) for status, count in status_rows.all()}

    messages = int(
        (
            await db.execute(
                select(func.count(DebateMessage.id))
                .join(Debate, DebateMessage.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )
    claims = int(
        (
            await db.execute(
                select(func.count(Claim.id))
                .join(Debate, Claim.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )
    # One verification row per claim (unique constraint), so a plain join
    # cannot inflate the count.
    verified = int(
        (
            await db.execute(
                select(func.count(ClaimVerification.id))
                .join(Claim, ClaimVerification.claim_id == Claim.id)
                .join(Debate, Claim.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )
    with_judgment = int(
        (
            await db.execute(
                select(func.count(DebateJudgment.id))
                .join(Debate, DebateJudgment.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )

    completed = counts_by_status.get("completed", 0)
    return {
        "total_debates": total,
        "completed_debates": completed,
        "running_debates": counts_by_status.get("running", 0),
        "failed_debates": counts_by_status.get("failed", 0),
        "pending_debates": counts_by_status.get("pending", 0),
        "cancelled_debates": counts_by_status.get("cancelled", 0),
        "total_messages": messages,
        "total_claims": claims,
        "verified_claims": verified,
        "unverified_claims": max(claims - verified, 0),
        "debates_with_judgment": with_judgment,
        "completion_rate": (
            round(completed / total, 4) if total > 0 else None
        ),
        "status_distribution": [
            {"status": status, "count": counts_by_status.get(status, 0)}
            for status in DEBATE_STATUSES
        ],
    }


async def debate_activity(db: AsyncSession, user_id: uuid.UUID, days: int) -> dict:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)

    # Group by explicit UTC calendar day so results do not depend on the
    # database session timezone.
    day_expr = func.to_char(
        Debate.created_at.op("AT TIME ZONE")("UTC"), "YYYY-MM-DD"
    )
    rows = await db.execute(
        select(day_expr, func.count(Debate.id))
        .where(
            Debate.user_id == user_id,
            Debate.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
            Debate.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
        )
        .group_by(day_expr)
    )
    counts = {str(day): int(count) for day, count in rows.all()}

    buckets: list[ActivityBucket] = []
    total_in_range = 0
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        count = counts.get(key, 0)
        total_in_range += count
        buckets.append(ActivityBucket(date=key, count=count))
        cursor += timedelta(days=1)

    return {
        "days": days,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "bucket": "day",
        "buckets": buckets,
        "total_debates_in_range": total_in_range,
    }


async def claim_verification(db: AsyncSession, user_id: uuid.UUID) -> dict:
    verdict_rows = await db.execute(
        select(ClaimVerification.verdict, func.count(ClaimVerification.id))
        .join(Claim, ClaimVerification.claim_id == Claim.id)
        .join(Debate, Claim.debate_id == Debate.id)
        .where(Debate.user_id == user_id)
        .group_by(ClaimVerification.verdict)
    )
    verdict_map = {verdict: int(count) for verdict, count in verdict_rows.all()}

    confidence_rows = await db.execute(
        select(ClaimVerification.confidence, func.count(ClaimVerification.id))
        .join(Claim, ClaimVerification.claim_id == Claim.id)
        .join(Debate, Claim.debate_id == Debate.id)
        .where(Debate.user_id == user_id)
        .group_by(ClaimVerification.confidence)
    )
    confidence_map = {
        level: int(count) for level, count in confidence_rows.all()
    }

    claims = int(
        (
            await db.execute(
                select(func.count(Claim.id))
                .join(Debate, Claim.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )
    verified = sum(verdict_map.values())

    return {
        "total_verifications": verified,
        "verdict_counts": [
            NamedCount(name=verdict, count=verdict_map.get(verdict, 0))
            for verdict in VERDICTS
        ],
        "confidence_counts": [
            NamedCount(name=level, count=confidence_map.get(level, 0))
            for level in CONFIDENCE_LEVELS
        ],
        "verified_claims": verified,
        "unverified_claims": max(claims - verified, 0),
        "scope": (
            "Counts cover stored claim-verification results for all of your "
            "debates (every time period). Unverified claims are listed "
            "separately and are never counted as insufficient evidence. A "
            "supported share is not a factual-accuracy measurement."
        ),
    }


async def agent_performance(db: AsyncSession, user_id: uuid.UUID) -> dict:
    result = await db.execute(
        select(DebateJudgment.agent_scores)
        .join(Debate, DebateJudgment.debate_id == Debate.id)
        .where(Debate.user_id == user_id)
    )
    judgment_cards = [row[0] for row in result.all() if row[0]]

    stats: dict[str, dict] = {}
    for cards in judgment_cards:
        for card in cards:
            agent_id = str(card.get("agent_id"))
            if not agent_id:
                continue
            entry = stats.setdefault(
                agent_id,
                {
                    "name": str(card.get("agent_name") or agent_id),
                    "role": str(card.get("agent_role") or ""),
                    "appearances": 0,
                    "score_sum": 0.0,
                    "dim_sum": defaultdict(float),
                    "dim_count": defaultdict(int),
                    "strengths": [],  # insertion-ordered unique
                    "weaknesses": [],
                },
            )
            entry["appearances"] += 1
            final = card.get("final_score")
            if final is not None:
                entry["score_sum"] += float(final)
            dimensions = card.get("dimensions") or {}
            for dim in RUBRIC_DIMENSIONS:
                value = dimensions.get(dim)
                if value is not None:
                    entry["dim_sum"][dim] += float(value)
                    entry["dim_count"][dim] += 1
            for key, cap in (("strengths", MAX_STRENGTHS), ("weaknesses", MAX_WEAKNESSES)):
                existing = entry[key]
                for text in card.get(key) or []:
                    text = str(text).strip()
                    if text and text not in existing and len(existing) < cap:
                        existing.append(text)

    # Every core agent is listed; those without judged appearances are shown
    # as unavailable (average None), never as zero.
    core_rows = await db.execute(
        select(Agent).where(Agent.is_core.is_(True)).order_by(Agent.name)
    )
    items: list[AgentPerformanceItem] = []
    for agent in core_rows.scalars().all():
        entry = stats.pop(str(agent.id), None)
        items.append(_performance_item(str(agent.id), agent.name, agent.role, entry))
    for agent_id, entry in stats.items():
        items.append(
            _performance_item(agent_id, entry["name"], entry["role"], entry)
        )

    items.sort(
        key=lambda item: (
            -item.appearances,
            -(item.average_score if item.average_score is not None else -1.0),
            item.agent_name,
        )
    )
    judgments_analyzed = len(judgment_cards)
    return {
        "agents": items,
        "judgments_analyzed": judgments_analyzed,
        "available": judgments_analyzed > 0,
    }


def _performance_item(
    agent_id: str, name: str, role: str, entry: dict | None
) -> AgentPerformanceItem:
    if not entry:
        return AgentPerformanceItem(
            agent_id=agent_id,
            agent_name=name,
            agent_role=role,
            appearances=0,
            average_score=None,
            dimension_averages=[
                DimensionAverage(dimension=dim, average=None)
                for dim in RUBRIC_DIMENSIONS
            ],
            strengths=[],
            weaknesses=[],
        )
    appearances = entry["appearances"]
    average = (
        round(entry["score_sum"] / appearances, 2) if appearances else None
    )
    return AgentPerformanceItem(
        agent_id=agent_id,
        agent_name=entry["name"],
        agent_role=entry["role"],
        appearances=appearances,
        average_score=average,
        dimension_averages=[
            DimensionAverage(
                dimension=dim,
                average=(
                    round(entry["dim_sum"][dim] / entry["dim_count"][dim], 2)
                    if entry["dim_count"].get(dim)
                    else None
                ),
            )
            for dim in RUBRIC_DIMENSIONS
        ],
        strengths=list(entry["strengths"]),
        weaknesses=list(entry["weaknesses"]),
    )


async def argument_quality(db: AsyncSession, user_id: uuid.UUID) -> dict:
    fallacy_rows = await db.execute(
        select(Fallacy.fallacy_type, func.count(Fallacy.id))
        .join(Debate, Fallacy.debate_id == Debate.id)
        .where(Debate.user_id == user_id)
        .group_by(Fallacy.fallacy_type)
    )
    fallacy_map = {name: int(count) for name, count in fallacy_rows.all()}

    severity_rows = await db.execute(
        select(Fallacy.severity, func.count(Fallacy.id))
        .join(Debate, Fallacy.debate_id == Debate.id)
        .where(Debate.user_id == user_id)
        .group_by(Fallacy.severity)
    )
    severity_map = {name: int(count) for name, count in severity_rows.all()}

    fallacy_total = sum(fallacy_map.values())
    fallacy_messages = int(
        (
            await db.execute(
                select(func.count(distinct(Fallacy.message_id)))
                .join(Debate, Fallacy.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )

    evaluation_total = int(
        (
            await db.execute(
                select(func.count(ArgumentEvaluation.id))
                .join(Debate, ArgumentEvaluation.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )
    evaluated_messages = int(
        (
            await db.execute(
                select(func.count(distinct(ArgumentEvaluation.message_id)))
                .join(Debate, ArgumentEvaluation.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )
    total_messages = int(
        (
            await db.execute(
                select(func.count(DebateMessage.id))
                .join(Debate, DebateMessage.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).scalar_one()
    )

    averages: list[DimensionAverage] = [
        DimensionAverage(dimension=dim, average=None)
        for dim in EVALUATION_DIMENSIONS
    ]
    if evaluation_total > 0:
        avg_row = (
            await db.execute(
                select(
                    func.avg(ArgumentEvaluation.logical_soundness),
                    func.avg(ArgumentEvaluation.evidence_score),
                    func.avg(ArgumentEvaluation.relevance_score),
                    func.avg(ArgumentEvaluation.effectiveness_score),
                    func.avg(ArgumentEvaluation.overall_score),
                )
                .join(Debate, ArgumentEvaluation.debate_id == Debate.id)
                .where(Debate.user_id == user_id)
            )
        ).one()
        averages = [
            DimensionAverage(
                dimension=dim,
                average=round(float(value), 2) if value is not None else None,
            )
            for dim, value in zip(EVALUATION_DIMENSIONS, avg_row)
        ]

    notes: list[str] = []
    if fallacy_total == 0:
        notes.append(
            "No fallacy rows are stored for your debates. This does not mean "
            "the debates are fallacy-free: analysis may simply not have been "
            "run, and clean analyses are never persisted."
        )
    if evaluation_total == 0:
        notes.append(
            "No argument evaluations are stored for your debates yet."
        )
    notes.append(
        "'Not yet analyzed' counts messages without a stored argument "
        "evaluation; fallacy coverage cannot be computed because no-fallacy "
        "results are not persisted."
    )

    return {
        "available": fallacy_total > 0 or evaluation_total > 0,
        "fallacy_available": fallacy_total > 0,
        "evaluation_available": evaluation_total > 0,
        "fallacy_total": fallacy_total,
        "fallacy_type_counts": [
            NamedCount(name=name, count=fallacy_map.get(name, 0))
            for name in FALLACY_TYPES
            if name != "no_fallacy" and fallacy_map.get(name, 0) > 0
        ],
        "severity_counts": [
            NamedCount(name=name, count=severity_map.get(name, 0))
            for name in FALLACY_SEVERITIES
            if severity_map.get(name, 0) > 0
        ],
        "fallacy_analyzed_message_count": fallacy_messages,
        "evaluation_total": evaluation_total,
        "evaluated_message_count": evaluated_messages,
        "unevaluated_message_count": (
            max(total_messages - evaluated_messages, 0)
            if total_messages > 0
            else None
        ),
        "dimension_averages": averages,
        "notes": notes,
    }


async def recent_debates(
    db: AsyncSession, user_id: uuid.UUID, page: int, page_size: int
) -> dict:
    total = await _count_for_user(db, user_id)
    total_pages = max((total + page_size - 1) // page_size, 1)

    rows = await db.execute(
        select(Debate)
        .where(Debate.user_id == user_id)
        .order_by(Debate.created_at.desc(), Debate.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    debates = list(rows.scalars().all())
    debate_ids = [debate.id for debate in debates]

    message_counts: dict[uuid.UUID, int] = {}
    verified_debates: set[uuid.UUID] = set()
    judged_debates: set[uuid.UUID] = set()
    if debate_ids:
        msg_rows = await db.execute(
            select(DebateMessage.debate_id, func.count(DebateMessage.id))
            .where(DebateMessage.debate_id.in_(debate_ids))
            .group_by(DebateMessage.debate_id)
        )
        message_counts = {rid: int(count) for rid, count in msg_rows.all()}

        ver_rows = await db.execute(
            select(distinct(Claim.debate_id))
            .join(ClaimVerification, ClaimVerification.claim_id == Claim.id)
            .where(Claim.debate_id.in_(debate_ids))
        )
        verified_debates = {rid for (rid,) in ver_rows.all()}

        judg_rows = await db.execute(
            select(distinct(DebateJudgment.debate_id)).where(
                DebateJudgment.debate_id.in_(debate_ids)
            )
        )
        judged_debates = {rid for (rid,) in judg_rows.all()}

    items = [
        {
            "id": str(debate.id),
            "topic": debate.topic,
            "created_at": debate.created_at,
            "status": debate.status,
            "agent_count": len(debate.agents),
            "round_count": len(debate.rounds),
            "message_count": message_counts.get(debate.id, 0),
            "has_verification": debate.id in verified_debates,
            "has_judgment": debate.id in judged_debates,
        }
        for debate in debates
    ]

    return {
        "debates": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


def utc_today() -> date:
    return datetime.now(timezone.utc).date()
