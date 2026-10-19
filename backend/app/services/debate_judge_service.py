"""Debate judge service (Module 11).

Loads a completed debate plus all stored analysis records (claims,
verifications, evidence, fallacies, argument evaluations), asks the shared
LLM provider for qualitative assessments of each participant, then computes
final scores deterministically with judge_rubric's fixed formula and
persists one judgment per debate.

The judge evaluates argument quality and evidence use under the documented
rubric - it never establishes objective truth and never rewards confident
language or message count on its own.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field as dataclass_field
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.llm.base import (
    LLMMessage,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.llm.factory import get_llm_provider
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.fallacy import Fallacy
from app.models.judge import DebateJudgment
from app.models.user import User
from app.services import judge_rubric

logger = logging.getLogger(__name__)

# Reasoning tokens count against max_tokens (see claim_extraction); the judge
# prompt is the largest in the project, so keep generous headroom.
JUDGE_MAX_TOKENS = 16000
MAX_MESSAGE_EXCERPT = 600
MAX_PROMPT_CONTENT_CHARS = 14000
MAX_TEXT_FIELD = 700
MAX_SUMMARY_FIELD = 2000
MAX_LIST_ITEMS = 20


class JudgeError(Exception):
    """Base class for judge failures."""


class JudgeNotFoundError(JudgeError):
    """Debate does not exist or belongs to another user."""


class JudgeNotCompletedError(JudgeError):
    """The debate has not finished running yet."""


class JudgeDataUnavailableError(JudgeError):
    """There is nothing meaningful in the database to judge."""


class JudgeLLMError(JudgeError):
    """The LLM provider failed or returned unusable output."""


def _bounded_text(value: str, limit: int = MAX_TEXT_FIELD) -> str:
    value = (value or "").strip()
    if len(value) > limit:
        return value[:limit].rstrip() + " [...]"
    return value


def _bounded_list(values: list[str] | None, limit: int = MAX_LIST_ITEMS) -> list[str]:
    cleaned: list[str] = []
    for raw in values or []:
        text = (raw or "").strip()
        if not text:
            continue
        cleaned.append(_bounded_text(text))
        if len(cleaned) >= limit:
            break
    return cleaned


class DimensionScores(BaseModel):
    """LLM-assessed rubric dimensions (0-10). Factual support and fallacy risk
    are intentionally absent: those come from stored database records."""

    logical_soundness: float = Field(ge=0.0, le=10.0)
    evidence_quality: float = Field(ge=0.0, le=10.0)
    relevance: float = Field(ge=0.0, le=10.0)
    effectiveness: float = Field(ge=0.0, le=10.0)
    completeness: float = Field(ge=0.0, le=10.0)

    @field_validator(
        "logical_soundness",
        "evidence_quality",
        "relevance",
        "effectiveness",
        "completeness",
        mode="before",
    )
    @classmethod
    def _coerce_number(cls, value) -> float:
        if isinstance(value, bool):
            raise ValueError("dimension scores must be numbers between 0 and 10")
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError as exc:
                raise ValueError("dimension scores must be numbers between 0 and 10") from exc
        if not isinstance(value, (int, float)):
            raise ValueError("dimension scores must be numbers between 0 and 10")
        return float(value)


class AgentAssessment(BaseModel):
    """One participant's qualitative assessment as produced by the LLM."""

    agent_name: str = Field(min_length=1)
    dimensions: DimensionScores
    strengths: list[str] = []
    weaknesses: list[str] = []
    reasoning_quality: str = Field(min_length=1)
    evidence_quality_explanation: str = Field(min_length=1)
    factual_support_explanation: str = Field(min_length=1)
    completeness_assessment: str = Field(min_length=1)
    fallacy_impact_assessment: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator("agent_name", mode="before")
    @classmethod
    def _clean_name(cls, value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("agent_name is required")
        return value.strip()

    @field_validator(
        "strengths",
        "weaknesses",
        mode="before",
    )
    @classmethod
    def _clean_str_list(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("strengths and weaknesses must be lists of strings")
        return [str(item) for item in value]

    @field_validator(
        "reasoning_quality",
        "evidence_quality_explanation",
        "factual_support_explanation",
        "completeness_assessment",
        "fallacy_impact_assessment",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("assessment fields must be non-empty strings")
        return _bounded_text(str(value))

    @field_validator("confidence", mode="before")
    @classmethod
    def _clean_confidence(cls, value) -> str:
        if not isinstance(value, str):
            raise ValueError("confidence must be low, medium or high")
        normalized = value.strip().lower().rstrip(".! ")
        if normalized not in ("low", "medium", "high"):
            raise ValueError("confidence must be low, medium or high")
        return normalized


class JudgeLLMOutput(BaseModel):
    """Validated structured output for a whole debate judgment."""

    agents: list[AgentAssessment] = Field(min_length=1)
    summary: str = Field(min_length=1)
    limitations: list[str] = []

    @field_validator("summary", mode="before")
    @classmethod
    def _clean_summary(cls, value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("summary must be a non-empty string")
        return _bounded_text(str(value), MAX_SUMMARY_FIELD)

    @field_validator("limitations", mode="before")
    @classmethod
    def _clean_limitations(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("limitations must be a list of strings")
        return [str(item) for item in value]

    @model_validator(mode="after")
    def _unique_agents(self) -> "JudgeLLMOutput":
        names = [agent.agent_name for agent in self.agents]
        if len(set(names)) != len(names):
            raise ValueError("each participant may only appear once")
        return self


SYSTEM_PROMPT = (
    "You are the judge of an AI debate. You evaluate ARGUMENT QUALITY and "
    "EVIDENCE USE for each participating agent under a fixed rubric.\n"
    "Rules:\n"
    "- Use ONLY the supplied debate material. Never invent evidence, sources, "
    "statistics, citations, verdicts or events.\n"
    "- Stored verification verdicts are results of an earlier evidence check. "
    "'insufficient_evidence' means unknown: not true and not false. "
    "'contradicted' means the stored evidence conflicts with the claim.\n"
    "- If fallacy analysis, evidence or evaluations are marked unavailable, "
    "acknowledge that in your text; do not fabricate results.\n"
    "- Score only these dimensions for each agent, each 0-10: "
    "logical_soundness, evidence_quality, relevance, effectiveness, "
    "completeness. Scale: 0-2 very weak, 3-4 weak, 5-6 moderate, 7-8 strong, "
    "9-10 excellent.\n"
    "- Do not reward message count, length, confidence or assertive language. "
    "A short well-evidenced argument can outscore a long unsupported one.\n"
    "- Judge the argument text neutrally: never penalize a political, "
    "economic or social position for being controversial.\n"
    "- High scores mean strong reasoning quality only. Never state or imply "
    "that a high-scoring argument is factually true.\n"
    "- agent_name in your response must equal one of the provided "
    "participant names, once each, preserving capitalization exactly as "
    "given (for example 'Economist', not 'economist').\n"
    "- strengths/weaknesses: 1-4 short bullet strings each. Explanations: 1-3 "
    "sentences. No chain-of-thought, no essays.\n"
    "Respond with ONLY a JSON object (no markdown, no commentary):\n"
    '{"agents": [{"agent_name": "...", "dimensions": {"logical_soundness": 0, '
    '"evidence_quality": 0, "relevance": 0, "effectiveness": 0, '
    '"completeness": 0}, "strengths": ["..."], "weaknesses": ["..."], '
    '"reasoning_quality": "...", "evidence_quality_explanation": "...", '
    '"factual_support_explanation": "...", "completeness_assessment": "...", '
    '"fallacy_impact_assessment": "...", "confidence": "medium"}], '
    '"summary": "...", "limitations": ["..."]}'
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_judge_payload(raw: str) -> JudgeLLMOutput:
    """Parse and validate raw LLM output into a judgment assessment.

    Raises JudgeLLMError when the output cannot be used; invalid results are
    never persisted.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise JudgeLLMError("The language model returned an empty response")

    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise JudgeLLMError(
            "The language model did not return a JSON object for the judgment"
        )
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeLLMError(
            "The language model returned malformed JSON for the judgment"
        ) from exc
    if not isinstance(parsed, dict):
        raise JudgeLLMError(
            "The language model did not return a JSON object for the judgment"
        )
    try:
        return JudgeLLMOutput(**parsed)
    except ValidationError as exc:
        raise JudgeLLMError(
            "The language model returned an invalid judgment result"
        ) from exc


@dataclass
class AgentJudgeContext:
    """Everything the judge knows about one participant, from the database."""

    agent_id: UUID
    name: str
    role: str
    messages: list[dict] = dataclass_field(default_factory=list)
    claims: list[dict] = dataclass_field(default_factory=list)
    fallacies: list[dict] = dataclass_field(default_factory=list)
    evaluations: list[dict] = dataclass_field(default_factory=list)
    evidence_count: int = 0

    @property
    def verdicts(self) -> list[str]:
        return [c["verdict"] for c in self.claims if c.get("verdict")]


async def load_judge_contexts(
    db: AsyncSession, debate: Debate
) -> list[AgentJudgeContext]:
    """Collect stored analysis records per debate participant.

    Only agents that actually posted at least one message are returned
    (participation is message-based).
    """
    message_rows = (
        await db.execute(
            select(DebateMessage, DebateRound.round_number)
            .join(DebateRound, DebateMessage.round_id == DebateRound.id)
            .where(DebateMessage.debate_id == debate.id)
            .order_by(DebateRound.round_number, DebateMessage.turn_number)
        )
    ).all()

    contexts: dict[UUID, AgentJudgeContext] = {}
    for message, _round_number in message_rows:
        context = contexts.get(message.agent_id)
        if context is None:
            agent = next((a for a in debate.agents if a.id == message.agent_id), None)
            if agent is None:
                continue
            context = AgentJudgeContext(
                agent_id=agent.id, name=agent.name, role=agent.role
            )
            contexts[message.agent_id] = context
        excerpt = (message.content or "").strip()
        if len(excerpt) > MAX_MESSAGE_EXCERPT:
            excerpt = excerpt[:MAX_MESSAGE_EXCERPT].rstrip() + " [...]"
        context.messages.append({"type": message.message_type, "content": excerpt})

    claim_rows = (
        await db.execute(
            select(Claim)
            .where(Claim.debate_id == debate.id)
            .options(
                selectinload(Claim.verification),
                selectinload(Claim.evidence),
            )
        )
    ).scalars().all()
    for claim in claim_rows:
        context = contexts.get(claim.agent_id)
        if context is None:
            continue
        verification = claim.verification
        evidence_count = len(claim.evidence)
        context.evidence_count += evidence_count
        context.claims.append(
            {
                "text": claim.text,
                "verdict": verification.verdict if verification else None,
                "confidence": verification.confidence if verification else None,
                "evidence_count": evidence_count,
            }
        )

    fallacy_rows = (
        await db.execute(select(Fallacy).where(Fallacy.debate_id == debate.id))
    ).scalars().all()
    seen: set[tuple[UUID, str]] = set()
    for fallacy in fallacy_rows:
        if fallacy.fallacy_type == "no_fallacy":
            continue
        dedupe_key = (fallacy.message_id, fallacy.fallacy_type)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        context = contexts.get(fallacy.agent_id)
        if context is None:
            continue
        context.fallacies.append(
            {
                "type": fallacy.fallacy_type,
                "severity": fallacy.severity,
                "confidence": float(fallacy.confidence),
            }
        )

    evaluation_rows = (
        await db.execute(
            select(ArgumentEvaluation).where(ArgumentEvaluation.debate_id == debate.id)
        )
    ).scalars().all()
    for evaluation in evaluation_rows:
        context = contexts.get(evaluation.agent_id)
        if context is None:
            continue
        context.evaluations.append(
            {
                "logical_soundness": float(evaluation.logical_soundness),
                "evidence_score": float(evaluation.evidence_score),
                "relevance": float(evaluation.relevance_score),
                "effectiveness": float(evaluation.effectiveness_score),
                "overall": float(evaluation.overall_score),
            }
        )

    # Keep the debate's agent ordering for stable prompts and tables.
    ordered = [
        contexts[agent.id] for agent in debate.agents if agent.id in contexts
    ]
    return ordered


def build_judge_prompt(topic: str, contexts: list[AgentJudgeContext]) -> str:
    """Build the user prompt carrying the debate material and stored records."""
    lines = [f"Debate topic: {(topic or '').strip()[:500]}", ""]
    lines.append(
        "Participants: " + ", ".join(f"{c.name} ({c.role})" for c in contexts)
    )
    total_claims = sum(len(c.claims) for c in contexts)
    total_verified = sum(len(c.verdicts) for c in contexts)
    total_evidence = sum(c.evidence_count for c in contexts)
    total_fallacies = sum(len(c.fallacies) for c in contexts)
    total_evals = sum(len(c.evaluations) for c in contexts)
    lines.append(
        f"Stored data: {total_claims} claims, {total_verified} verified, "
        f"{total_evidence} evidence rows, {total_fallacies} fallacy analyses, "
        f"{total_evals} argument evaluations."
    )

    content_budget = MAX_PROMPT_CONTENT_CHARS
    for context in contexts:
        lines.append("")
        lines.append(f"== {context.name} ==")
        lines.append("Messages:")
        for message in context.messages:
            lines.append(f"- [{message['type']}] {message['content']}")
        lines.append("Extracted claims:")
        if context.claims:
            for claim in context.claims:
                if claim["verdict"]:
                    lines.append(
                        f'- "{_bounded_text(claim["text"], 300)}" '
                        f'[verdict: {claim["verdict"]}, '
                        f'confidence: {claim["confidence"]}, '
                        f'evidence rows: {claim["evidence_count"]}]'
                    )
                else:
                    lines.append(
                        f'- "{_bounded_text(claim["text"], 300)}" '
                        "[no verification record]"
                    )
        else:
            lines.append("- none extracted")
        if context.fallacies:
            lines.append("Stored fallacy analyses:")
            for fallacy in context.fallacies:
                lines.append(
                    f"- {fallacy['type']} ({fallacy['severity']}, "
                    f"confidence {fallacy['confidence']})"
                )
        else:
            lines.append("Stored fallacy analyses: unavailable (not run)")
        if context.evaluations:
            count = len(context.evaluations)
            avg = {
                key: round(sum(e[key] for e in context.evaluations) / count, 2)
                for key in (
                    "logical_soundness",
                    "evidence_score",
                    "relevance",
                    "effectiveness",
                    "overall",
                )
            }
            lines.append(
                f"Stored argument evaluations (avg of {count}): "
                f"logical {avg['logical_soundness']}, evidence "
                f"{avg['evidence_score']}, relevance {avg['relevance']}, "
                f"effectiveness {avg['effectiveness']}, overall "
                f"{avg['overall']} (0-10)."
            )
        else:
            lines.append("Stored argument evaluations: unavailable (not run)")
        if context.evidence_count == 0:
            lines.append("Retrieved evidence: unavailable (none stored).")

    lines.append("")
    lines.append(
        "Assess every participant listed above on the rubric dimensions and "
        "return the JSON object exactly as specified."
    )
    prompt = "\n".join(lines)
    if len(prompt) > MAX_PROMPT_CONTENT_CHARS + 4000:
        prompt = prompt[: MAX_PROMPT_CONTENT_CHARS + 4000] + "\n[truncated]"
    return prompt


class DebateJudgeService:
    """Orchestrates judging one completed debate via the shared LLM provider."""

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def _assess(self, prompt: str) -> JudgeLLMOutput:
        try:
            response = await self.provider.generate(
                [
                    LLMMessage(role="system", content=SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=JUDGE_MAX_TOKENS,
            )
        except JudgeLLMError:
            raise
        except LLMProviderError as exc:
            logger.error(
                "Debate judge LLM call failed: %s: %s", type(exc).__name__, exc
            )
            if isinstance(exc, (LLMProviderAPIError, LLMTimeoutError)):
                raise JudgeLLMError(
                    "Judgment failed because the language model provider "
                    "did not respond"
                ) from exc
            raise JudgeLLMError(
                "Judgment failed because the language model returned no "
                "usable output"
            ) from exc
        except Exception as exc:
            logger.error(
                "Debate judge LLM call failed: %s: %s", type(exc).__name__, exc
            )
            raise JudgeLLMError(
                "Judgment failed because the language model provider did "
                "not respond"
            ) from exc
        return parse_judge_payload(response.content)

    async def get_existing(self, db: AsyncSession, debate_id: UUID) -> DebateJudgment | None:
        result = await db.execute(
            select(DebateJudgment).where(DebateJudgment.debate_id == debate_id)
        )
        return result.scalar_one_or_none()

    async def judge_debate(
        self, db: AsyncSession, user: User, debate_id: UUID
    ) -> DebateJudgment:
        """Validate, assess, score and persist the judgment for one debate.

        Judging is idempotent: when a judgment already exists it is returned
        as-is without calling the LLM again (one row per debate).
        """
        debate = (
            await db.execute(select(Debate).where(Debate.id == debate_id))
        ).scalar_one_or_none()
        if debate is None or debate.user_id != user.id:
            raise JudgeNotFoundError("Debate not found")

        existing = await self.get_existing(db, debate_id)
        if existing is not None:
            return existing

        if debate.status != "completed":
            raise JudgeNotCompletedError(
                "The debate must be completed before it can be judged"
            )

        contexts = await load_judge_contexts(db, debate)
        if not contexts:
            raise JudgeDataUnavailableError(
                "The debate has no messages to evaluate"
            )

        # Essential stored analysis data: at least one of claim
        # verifications, fallacy analyses or argument evaluations exists.
        data_sufficient = any(c.verdicts for c in contexts) or any(
            c.fallacies for c in contexts
        ) or any(c.evaluations for c in contexts)

        output = await self._assess(build_judge_prompt(debate.topic, contexts))

        # Match participants case-insensitively: models sometimes echo names
        # in lowercase, but the stored canonical name always comes from the
        # database.
        def _norm(name: str) -> str:
            return " ".join(name.strip().casefold().split())

        expected_by_key = {_norm(c.name): c.name for c in contexts}
        provided_by_key = {_norm(a.agent_name): a for a in output.agents}
        if (
            set(provided_by_key) != set(expected_by_key)
            or len(provided_by_key) != len(output.agents)
        ):
            logger.error(
                "Judge LLM agent mismatch: expected %s, got %s",
                sorted(c.name for c in contexts),
                [a.agent_name for a in output.agents],
            )
            raise JudgeLLMError(
                "The language model returned assessments for the wrong "
                "participants"
            )
        assessments = {
            expected_by_key[key]: provided_by_key[key]
            for key in expected_by_key
        }

        min_gap = get_settings().JUDGE_MIN_SCORE_GAP
        data_notes: list[str] = []
        agent_scores: list[dict] = []

        if not any(c.fallacies for c in contexts):
            data_notes.append(
                "Fallacy analysis has not been run for this debate; the "
                "fallacy-risk dimension is unavailable."
            )
        if not any(c.verdicts for c in contexts):
            data_notes.append(
                "No claim verification results exist for this debate; the "
                "factual-support dimension is unavailable."
            )
        if not any(c.evaluations for c in contexts):
            data_notes.append(
                "No stored argument evaluations exist for this debate."
            )
        if not any(c.evidence_count for c in contexts):
            data_notes.append(
                "No retrieved evidence is stored for this debate; the "
                "evidence-quality dimension is unavailable."
            )

        for context in contexts:
            assessment = assessments[context.name]
            verdicts = context.verdicts
            unverified = sum(1 for c in context.claims if not c.get("verdict"))
            dimensions: dict[str, float | None] = {
                "logical_soundness": assessment.dimensions.logical_soundness,
                "evidence_quality": (
                    assessment.dimensions.evidence_quality
                    if context.evidence_count > 0
                    else None
                ),
                "factual_support": judge_rubric.compute_factual_support(verdicts),
                "relevance": assessment.dimensions.relevance,
                "effectiveness": assessment.dimensions.effectiveness,
                "completeness": assessment.dimensions.completeness,
                "fallacy_risk": judge_rubric.compute_fallacy_risk(
                    [(f["severity"], f["confidence"]) for f in context.fallacies],
                    len(context.messages),
                ),
            }
            unavailable = [
                judge_rubric.DIMENSION_LABELS[dim]
                for dim, value in dimensions.items()
                if value is None
            ]

            final_raw = judge_rubric.compute_agent_score(dimensions)
            final_score = judge_rubric.round_final(final_raw)

            agent_notes: list[str] = []
            if context.evidence_count == 0:
                agent_notes.append(
                    "No retrieved evidence available for this agent's claims."
                )
            if not context.claims:
                agent_notes.append("No claims were extracted from this agent's messages.")
            elif not verdicts:
                agent_notes.append(
                    "No verification records exist for this agent's claims."
                )
            elif unverified:
                agent_notes.append(
                    f"{unverified} of {len(context.claims)} claims have no "
                    "verification record."
                )
            if not context.fallacies:
                agent_notes.append(
                    "Fallacy analysis has not been run for this agent's messages."
                )
            if not context.evaluations:
                agent_notes.append(
                    "No stored argument evaluations for this agent's messages."
                )

            agent_scores.append(
                {
                    "agent_id": str(context.agent_id),
                    "agent_name": context.name,
                    "agent_role": context.role,
                    "dimensions": dimensions,
                    "unavailable_dimensions": unavailable,
                    "final_score": final_score,
                    "strengths": _bounded_list(assessment.strengths),
                    "weaknesses": _bounded_list(assessment.weaknesses),
                    "reasoning_quality": assessment.reasoning_quality,
                    "evidence_quality_assessment": assessment.evidence_quality_explanation,
                    "factual_support_assessment": assessment.factual_support_explanation,
                    "fallacy_impact_assessment": assessment.fallacy_impact_assessment,
                    "confidence": assessment.confidence,
                    "limitations": agent_notes,
                }
            )

        # Overall debate score: mean of participating agents' final scores.
        overall_score = judge_rubric.round_final(
            sum(a["final_score"] for a in agent_scores) / len(agent_scores)
        )

        ranked = sorted(
            (
                (UUID(a["agent_id"]), a["final_score"])
                for a in agent_scores
            ),
            key=lambda pair: (-pair[1], str(pair[0])),
        )
        outcome, winner_agent_id = judge_rubric.decide_outcome(
            ranked, min_gap, data_sufficient
        )
        if len(agent_scores) < 2:
            outcome = "inconclusive"
            winner_agent_id = None
            data_notes.append(
                "Fewer than two agents posted messages; no comparison is "
                "possible."
            )
        if not data_sufficient:
            data_notes.append(
                "No stored claim verifications, fallacy analyses or argument "
                "evaluations exist; the outcome is inconclusive rather than "
                "a manufactured winner."
            )

        limitations = _bounded_list(output.limitations) + data_notes

        judgment = DebateJudgment(
            debate_id=debate.id,
            status="completed",
            overall_score=overall_score,
            winner_agent_id=winner_agent_id,
            outcome=outcome,
            summary=output.summary,
            scoring_rubric=judge_rubric.rubric_snapshot(min_gap),
            agent_scores=agent_scores,
            limitations=limitations or None,
        )
        db.add(judgment)
        await db.commit()
        await db.refresh(judgment)
        logger.info(
            "Judged debate %s: outcome=%s overall=%.2f agents=%d",
            debate.id,
            outcome,
            overall_score,
            len(agent_scores),
        )
        return judgment
