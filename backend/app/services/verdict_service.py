"""Final debate verdict service.

Answers the debate question itself: which position the stored arguments and
verified evidence support. It is deliberately independent from the judge
(debate_judge_service), which ranks how well each agent argued. The judge's
winner is never passed to the verdict prompt, so a best-performing agent is
never mistaken for the correct answer.

The LLM synthesizes the assessment from the stored transcript and stored
claim verifications only. Server-side guards keep it honest:

- citations: the model may only reference claim ids from the supplied list;
  anything else is dropped, so sources and verified claims are never invented;
- inconclusive: when no stored claim has a 'supported' or 'contradicted'
  verification, the position is forced to 'inconclusive';
- confidence: the model's own label is capped by how much of the debate's
  claims the stored evidence actually covers, and the basis is recorded.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.base import (
    LLMMessage,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.llm.factory import get_llm_provider
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.evidence import Evidence
from app.models.fallacy import Fallacy
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.user import User
from app.models.verdict import DebateVerdict

logger = logging.getLogger(__name__)

VERDICT_MAX_TOKENS = 6000
MAX_MESSAGE_EXCERPT = 1200
MAX_PROMPT_CHARS = 24000
MAX_CLAIMS_IN_PROMPT = 60
MAX_TEXT = 2000
MAX_POINT = 600
MAX_ITEMS = 8

CONFIDENCE_ORDER = ("low", "medium", "high")
DECISIVE_VERDICTS = ("supported", "contradicted")


class VerdictError(Exception):
    """Base class for verdict failures."""


class VerdictNotFoundError(VerdictError):
    """Debate does not exist or belongs to another user."""


class VerdictNotCompletedError(VerdictError):
    """The debate has not finished running yet."""


class VerdictDataUnavailableError(VerdictError):
    """There is nothing stored to base a verdict on."""


class VerdictLLMError(VerdictError):
    """The LLM provider failed or returned unusable output."""


def _clip(value, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[:limit].rstrip() + " [...]"
    return text


def _text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    out = [_clip(item, MAX_POINT) for item in value if str(item or "").strip()]
    return out[:MAX_ITEMS]


class LLMArgument(BaseModel):
    point: str = Field(min_length=1)
    agent: str | None = None
    impact: str | None = None
    claim_refs: list[str] = []

    @field_validator("point", mode="before")
    @classmethod
    def _point(cls, value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("point is required")
        return _clip(value, MAX_POINT)

    @field_validator("agent", "impact", mode="before")
    @classmethod
    def _optional_text(cls, value):
        if value is None or not str(value).strip():
            return None
        return _clip(value, MAX_POINT)

    @field_validator("claim_refs", mode="before")
    @classmethod
    def _refs(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, int)):
            value = [value]
        if not isinstance(value, list):
            return []
        return [str(item).strip().upper() for item in value if str(item).strip()]


class VerdictLLMOutput(BaseModel):
    position: Literal["supports", "opposes", "mixed", "inconclusive"]
    answer: str = Field(min_length=1)
    preferred_position: str | None = None
    summary: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    supporting_arguments: list[LLMArgument] = []
    counterarguments: list[LLMArgument] = []
    confidence: Literal["low", "medium", "high"] = "low"
    limitations: list[str] = []
    unresolved_questions: list[str] = []
    question_assumptions: list[dict] = []
    sub_verdicts: list[dict] = []

    @field_validator("question_assumptions", mode="before")
    @classmethod
    def _assumptions(cls, value) -> list[dict]:
        items = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict) or not str(item.get("assumption") or "").strip():
                continue
            status = str(item.get("status") or "unclear").strip().lower()
            items.append({
                "assumption": _clip(item.get("assumption"), MAX_POINT),
                "assessment": _clip(item.get("assessment"), MAX_POINT),
                "status": status if status in ("supported", "contested", "unsupported", "unclear") else "unclear",
            })
        return items[:MAX_ITEMS]

    @field_validator("sub_verdicts", mode="before")
    @classmethod
    def _sub_verdicts(cls, value) -> list[dict]:
        items = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict) or not str(item.get("question") or "").strip():
                continue
            position = str(item.get("position") or "inconclusive").strip().lower()
            items.append({
                "question": _clip(item.get("question"), MAX_POINT),
                "position": position if position in ("supports", "opposes", "mixed", "inconclusive") else "inconclusive",
                "answer": _clip(item.get("answer"), MAX_POINT),
            })
        return items[:4]

    @field_validator("position", "confidence", mode="before")
    @classmethod
    def _lower(cls, value):
        if isinstance(value, str):
            return value.strip().lower().rstrip(".! ")
        return value

    @field_validator("answer", "summary", "reasoning", mode="before")
    @classmethod
    def _required_text(cls, value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("text fields must be non-empty strings")
        return _clip(value)

    @field_validator("preferred_position", mode="before")
    @classmethod
    def _preferred(cls, value):
        if value is None or not str(value).strip():
            return None
        if str(value).strip().lower() in ("null", "none", "n/a"):
            return None
        return _clip(value, MAX_POINT)

    @field_validator("limitations", "unresolved_questions", mode="before")
    @classmethod
    def _lists(cls, value) -> list[str]:
        return _text_list(value)

    @field_validator("supporting_arguments", "counterarguments", mode="before")
    @classmethod
    def _arg_lists(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("arguments must be a list")
        return value[:MAX_ITEMS]


SYSTEM_PROMPT = (
    "You write the FINAL VERDICT of an AI debate: a reasoned answer to the "
    "debate question itself, based on the stored debate material.\n"
    "Rules:\n"
    "- Answer the question that was debated. Do NOT pick a winning agent; "
    "how well an agent argued is not evidence that its position is correct.\n"
    "- Established evidence = only claims whose stored verification is "
    "'supported' or 'contradicted'. 'insufficient_evidence' means unknown "
    "(not true, not false). Unverified claims and agent statements are "
    "opinions, not evidence.\n"
    "- A 'published fact-check' rating is an external publisher's view of "
    "the claim they reviewed; the MAVES verification status of the claim is "
    "what counts. Never let an external rating override it.\n"
    "- Never invent facts, statistics, sources or citations. To cite stored "
    "claims use ONLY the ids given (e.g. \"C3\") in claim_refs.\n"
    "- position: 'supports' if the material favours the proposition / a yes "
    "answer, 'opposes' if it favours no, 'mixed' if the answer genuinely "
    "depends on conditions, 'inconclusive' if the evidence is insufficient, "
    "contradictory or incomplete. Prefer 'inconclusive' over forcing a side.\n"
    "- preferred_position: the better-supported position in a short phrase, "
    "or null when inconclusive.\n"
    "- supporting_arguments: strongest points for your verdict. "
    "counterarguments: strongest opposing points, with 'impact' explaining "
    "how each affects the conclusion. Attribute points to the agent name "
    "that made them when applicable.\n"
    "- confidence: low/medium/high, reflecting evidence strength, not tone.\n"
    "- Bias awareness: the question may be loaded or leading. List the "
    "assumptions it builds in (e.g. that something 'does more harm than "
    "good', or that 'strict' regulation is the remedy) in "
    "question_assumptions and assess each against the evidence and "
    "arguments instead of accepting it as fact (status supported, contested, "
    "unsupported or unclear).\n"
    "- If the question bundles several propositions (e.g. 'X is harmful AND "
    "governments should strictly regulate X'), judge each one separately in "
    "sub_verdicts; the overall position may then be 'mixed'.\n"
    "- Use whatever verified evidence exists; you do not need every claim "
    "verified. Say 'inconclusive' only when the available material really "
    "does not support a stronger conclusion. If the evidence analysis was "
    "incomplete or failed (see 'Analysis status'), say so in limitations - "
    "a failed search is not evidence about the question.\n"
    "- Be concise: answer 1 sentence, summary 2-3 sentences, reasoning up to "
    "6 sentences, at most 5 items per list. No markdown.\n"
    "Respond with ONLY a JSON object:\n"
    '{"position": "supports|opposes|mixed|inconclusive", "answer": "...", '
    '"preferred_position": "..." or null, "summary": "...", '
    '"reasoning": "...", "supporting_arguments": [{"point": "...", '
    '"agent": "...", "claim_refs": ["C1"]}], "counterarguments": '
    '[{"point": "...", "agent": "...", "impact": "...", "claim_refs": []}], '
    '"confidence": "low|medium|high", "limitations": ["..."], '
    '"unresolved_questions": ["..."], '
    '"question_assumptions": [{"assumption": "...", "assessment": "...", '
    '"status": "supported|contested|unsupported|unclear"}], '
    '"sub_verdicts": [{"question": "...", "position": "supports|opposes|mixed|inconclusive", '
    '"answer": "..."}]}'
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_verdict_payload(raw: str) -> VerdictLLMOutput:
    if not isinstance(raw, str) or not raw.strip():
        raise VerdictLLMError("The language model returned an empty response")
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise VerdictLLMError("The language model did not return a verdict object")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VerdictLLMError("The language model returned malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise VerdictLLMError("The language model did not return a verdict object")
    try:
        return VerdictLLMOutput(**parsed)
    except ValidationError as exc:
        raise VerdictLLMError("The language model returned an invalid verdict") from exc


def _cap_confidence(llm_label: str, cap: str) -> str:
    return CONFIDENCE_ORDER[
        min(CONFIDENCE_ORDER.index(llm_label), CONFIDENCE_ORDER.index(cap))
    ]


def evidence_snapshot(claims: list[Claim]) -> dict:
    snapshot = {
        "partially_supported": 0,
        "total_claims": len(claims),
        "factual_claims": sum(getattr(c, "claim_type", "factual") == "factual" for c in claims),
        "non_factual_claims": sum(getattr(c, "claim_type", "factual") != "factual" for c in claims),
        "supported": 0,
        "contradicted": 0,
        "insufficient_evidence": 0,
        "unverified": 0,
        "evidence_sources": 0,
    }
    for claim in claims:
        snapshot["evidence_sources"] += len(claim.evidence)
        if getattr(claim, "claim_type", "factual") != "factual":
            continue
        verdict = claim.verification.verdict if claim.verification else None
        if verdict in snapshot:
            snapshot[verdict] += 1
        else:
            snapshot["unverified"] += 1
    return snapshot


def confidence_cap(snapshot: dict) -> tuple[str, str]:
    """Highest confidence the stored evidence can justify, and why."""
    decisive = snapshot["supported"] + snapshot["contradicted"]
    total = snapshot.get("factual_claims", snapshot["total_claims"])
    if decisive == 0:
        return "low", (
            "No stored claim has a supporting or contradicting verification, "
            "so confidence cannot exceed low."
        )
    coverage = decisive / total if total else 0.0
    if decisive >= 3 and coverage >= 0.5:
        return "high", (
            f"{decisive} of {total} factual claims have a supporting or contradicting "
            "verification."
        )
    return "medium", (
        f"Only {decisive} of {total} factual claims have a supporting or contradicting "
        "verification, so confidence cannot exceed medium."
    )


async def load_debate_material(db: AsyncSession, debate: Debate):
    rows = (
        await db.execute(
            select(DebateMessage, DebateRound.round_number)
            .join(DebateRound, DebateMessage.round_id == DebateRound.id)
            .where(DebateMessage.debate_id == debate.id)
            .options(selectinload(DebateMessage.agent))
            .order_by(DebateRound.round_number, DebateMessage.turn_number)
        )
    ).all()
    claims = list(
        (
            await db.execute(
                select(Claim)
                .where(Claim.debate_id == debate.id)
                .options(
                    selectinload(Claim.verification),
                    selectinload(Claim.evidence),
                    selectinload(Claim.agent),
                )
                .order_by(Claim.created_at, Claim.position, Claim.id)
            )
        ).scalars().all()
    )
    fallacies = list(
        (await db.execute(select(Fallacy).where(Fallacy.debate_id == debate.id))).scalars().all()
    )
    evaluations = list(
        (
            await db.execute(
                select(ArgumentEvaluation).where(ArgumentEvaluation.debate_id == debate.id)
            )
        ).scalars().all()
    )
    return rows, claims, fallacies, evaluations


def _turn_text(message) -> str:
    data = message.structured
    if not data:
        return _clip(message.content, MAX_MESSAGE_EXCERPT)
    parts = [f"position: {data.get('position', '')}"]
    rebuttal = data.get("rebuttal_to") or {}
    if rebuttal.get("argument"):
        parts.append(f"responds to {rebuttal.get('ref') or 'an earlier argument'}: {rebuttal['argument']}")
    parts.append(f"main argument: {data.get('main_argument', '')}")
    parts.append(f"reasoning: {data.get('reasoning', '')}")
    if data.get("concession"):
        parts.append(f"concedes: {data['concession']}")
    if data.get("uncertainties"):
        parts.append("uncertain: " + "; ".join(data["uncertainties"]))
    return _clip(" | ".join(parts), MAX_MESSAGE_EXCERPT * 2)


def build_verdict_prompt(
    debate: Debate,
    rows,
    claims: list[Claim],
    fallacies: list | None = None,
    evaluations: list | None = None,
) -> tuple[str, dict[str, Claim]]:
    """Prompt with the debate question, transcript and numbered stored claims.

    Returns the prompt and the C-number -> Claim map used to resolve
    citations. The judge's agent scores and winner are intentionally absent.
    """
    lines = [f"Debate question: {_clip(debate.topic, 800)}"]
    if debate.context:
        lines.append(f"Context provided by the user: {_clip(debate.context, 1200)}")
    lines.append(
        "Format: pro/con (agents argue opposing sides)"
        if debate.mode == "pro_con"
        else "Format: balanced (each expert gives their own perspective)"
    )
    lines.append(
        "Participants: "
        + ", ".join(f"{agent.name} ({agent.role})" for agent in debate.agents)
    )
    lines.append("")
    lines.append("Transcript (agent opinions, not evidence):")
    for message, round_number in rows:
        name = message.agent.name if message.agent is not None else "Unknown"
        lines.append(
            f"[R{round_number}-{name}, {message.message_type}] {_turn_text(message)}"
        )

    fallacies = fallacies or []
    evaluations = evaluations or []
    lines.append("")
    lines.append("Analysis status:")
    run = debate.analysis_status or {}
    if run:
        failures = run.get("failures") or []
        lines.append(
            f"- Evidence analysis run: {run.get('result_state', run.get('state', 'unknown'))}"
            + (f"; {len(failures)} stage failure(s) (technical, not evidence)" if failures else "")
            + (f"; {run.get('no_sources', 0)} claim(s) had no sources in search" if run.get("no_sources") else "")
        )
        fact_check = run.get("fact_check") or {}
        if fact_check.get("status") in ("unavailable", "failed", "partial"):
            lines.append(
                "- Published fact-check search: "
                + ("not configured" if fact_check["status"] == "unavailable" else "failed for some claims")
                + " (technical; absence of fact-checks is not evidence)"
            )
    else:
        lines.append("- Evidence analysis run: not run")
    verified = sum(1 for c in claims if c.verification is not None)
    lines.append(
        f"- Claims: {len(claims)} extracted, {verified} verified"
        + ("" if claims else " (claim extraction has not been run)")
    )
    real_fallacies = [f for f in fallacies if f.fallacy_type != "no_fallacy"]
    if fallacies:
        kinds = sorted({f.fallacy_type for f in real_fallacies})
        lines.append(
            f"- Fallacy checks: {len(fallacies)} messages checked, "
            f"{len(real_fallacies)} fallacies found" + (f" ({', '.join(kinds)})" if kinds else "")
        )
        for finding in fallacies:
            lines.append(f"  Message {finding.message_id}: {finding.fallacy_type}; "
                         f"{_clip(finding.explanation, 180)}; excerpt: {_clip(finding.evidence_span or '', 120)}")
    else:
        lines.append("- Fallacy checks: not run")
    if evaluations:
        average = sum(e.overall_score for e in evaluations) / len(evaluations)
        lines.append(
            f"- Argument quality: {len(evaluations)} messages scored, average {average:.1f}/10"
        )
        for evaluation in evaluations:
            lines.append(f"  Message {evaluation.message_id}: rubric {evaluation.rubric_version or 'legacy'}; "
                         f"{_clip(evaluation.explanation, 180)}")
    else:
        lines.append("- Argument quality: not run")

    refs: dict[str, Claim] = {}
    lines.append("")
    lines.append("Stored claims with their stored verification:")
    if not claims:
        lines.append("- none extracted")
    for index, claim in enumerate(claims, start=1):
        ref = f"C{index}"
        refs[ref] = claim
        verification = claim.verification
        status = (
            f"{verification.verdict} (confidence {verification.confidence})"
            if verification
            else "not verified"
        )
        agent_name = claim.agent.name if claim.agent is not None else "Unknown"
        line = f'- {ref} [{agent_name}] "{_clip(claim.text, 300)}" -> {status}'
        if verification and verification.explanation:
            line += f"; note: {_clip(verification.explanation, 250)}"
        if claim.evidence:
            titles = "; ".join(_clip(e.title, 90) for e in claim.evidence[:3] if e.title)
            line += f"; {len(claim.evidence)} stored source(s)" + (f": {titles}" if titles else "")
            ratings = [
                f"{_clip(e.publisher or e.source_name, 40)} rated '{_clip(e.external_rating, 40)}'"
                for e in claim.evidence
                if e.source_type == "google_fact_check" and e.external_rating
            ][:3]
            if ratings:
                line += "; published fact-checks (external ratings): " + "; ".join(ratings)
        lines.append(line)
        for source in claim.evidence:
            lines.append(f"  Source ({source.source_type}, relevance {source.relevance_score}): "
                         f"{_clip(source.url, 250)}; {_clip(source.snippet, 160)}")

    lines.append("")
    lines.append("Write the final verdict JSON exactly as specified.")
    prompt = "\n".join(lines)
    if len(prompt) > MAX_PROMPT_CHARS:
        # Keep the claim list (it carries the evidence); trim the transcript.
        head_end = prompt.find("Stored claims with their stored verification:")
        claim_part = prompt[head_end:]
        budget = max(MAX_PROMPT_CHARS - len(claim_part), 2000)
        prompt = prompt[:budget] + "\n[transcript truncated]\n\n" + claim_part
    return prompt, refs


class VerdictService:
    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    async def _owned_debate(self, db: AsyncSession, user: User, debate_id: UUID) -> Debate:
        debate = (
            await db.execute(select(Debate).where(Debate.id == debate_id))
        ).scalar_one_or_none()
        if debate is None or debate.user_id != user.id:
            raise VerdictNotFoundError("Debate not found")
        return debate

    async def get_verdict(
        self, db: AsyncSession, user: User, debate_id: UUID
    ) -> DebateVerdict | None:
        await self._owned_debate(db, user, debate_id)
        return (
            await db.execute(
                select(DebateVerdict).where(DebateVerdict.debate_id == debate_id)
            )
        ).scalar_one_or_none()

    async def _generate(self, prompt: str) -> VerdictLLMOutput:
        try:
            response = await self.provider.generate(
                [
                    LLMMessage(role="system", content=SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=VERDICT_MAX_TOKENS,
            )
        except LLMProviderError as exc:
            logger.error("Verdict LLM call failed: %s: %s", type(exc).__name__, exc)
            if isinstance(exc, (LLMProviderAPIError, LLMTimeoutError)):
                raise VerdictLLMError(
                    # Keep the provider's specific, user-safe reason (e.g. which
                    # rate limit or quota) instead of a generic "did not respond".
                    f"The verdict failed: {exc.user_message}"
                ) from exc
            raise VerdictLLMError(
                "The verdict failed because the language model returned no "
                "usable output"
            ) from exc
        except Exception as exc:
            logger.error("Verdict LLM call failed: %s: %s", type(exc).__name__, exc)
            raise VerdictLLMError(
                "The verdict failed because the language model provider did "
                "not respond"
            ) from exc
        self.last_model = getattr(response, "model", None)
        return parse_verdict_payload(response.content)

    async def generate_verdict(
        self,
        db: AsyncSession,
        user: User,
        debate_id: UUID,
        regenerate: bool = False,
        on_generated=None,
    ) -> DebateVerdict:
        """Generate (or return the stored) verdict for a completed debate.

        Idempotent unless regenerate=True, which replaces the stored verdict
        (e.g. after more claims were verified). A failed regeneration keeps
        the previous verdict.
        """
        debate = await self._owned_debate(db, user, debate_id)
        from app.services.argument_analysis_service import _message_lock
        await _message_lock(db, debate_id)
        existing = (
            await db.execute(
                select(DebateVerdict).where(DebateVerdict.debate_id == debate.id)
            )
        ).scalar_one_or_none()
        if existing is not None and not regenerate:
            return existing
        if debate.status != "completed":
            raise VerdictNotCompletedError(
                "The debate must be completed before a verdict can be generated"
            )

        input_snapshot = await current_evidence_snapshot(db, debate_id)
        rows, claims, fallacies, evaluations = await load_debate_material(db, debate)
        if not rows:
            raise VerdictDataUnavailableError("The debate has no messages to evaluate")

        prompt, refs = build_verdict_prompt(debate, rows, claims, fallacies, evaluations)
        output = await self._generate(prompt)

        participant_names = {agent.name.casefold(): agent.name for agent in debate.agents}
        dropped_refs = 0

        def resolve(arguments: list[LLMArgument], with_impact: bool) -> list[dict]:
            nonlocal dropped_refs
            resolved = []
            for argument in arguments:
                claim_ids = []
                for ref in argument.claim_refs:
                    claim = refs.get(ref)
                    if claim is None:
                        dropped_refs += 1
                        continue
                    if str(claim.id) not in claim_ids:
                        claim_ids.append(str(claim.id))
                agent = (
                    participant_names.get(argument.agent.casefold())
                    if argument.agent
                    else None
                )
                item = {"point": argument.point, "agent_name": agent, "claim_ids": claim_ids}
                if with_impact:
                    item["impact"] = argument.impact
                resolved.append(item)
            return resolved

        supporting = resolve(output.supporting_arguments, with_impact=False)
        counter = resolve(output.counterarguments, with_impact=True)

        snapshot = dict(input_snapshot)
        run = debate.analysis_status or {}
        snapshot["analysis_state"] = run.get("result_state") or run.get("state") or "not_run"
        snapshot["analysis_failures"] = len(run.get("failures") or [])
        # Which model wrote this verdict (a quota fallback may differ from
        # the configured primary model).
        snapshot["model"] = getattr(self, "last_model", None)
        limitations = list(output.limitations)
        for failure in run.get("failures") or []:
            limitations.append(f"Incomplete stage: {failure.get('stage', 'analysis')}. {failure.get('error', 'Retry this stage.')}")
        for key, stage in (run.get("stages") or {}).items():
            if stage.get("state") == "skipped" and stage.get("error"):
                limitations.append(f"Skipped stage: {key}. {stage['error']}")
        position = output.position
        preferred = output.preferred_position

        # Compound questions: the overall label follows from the parts (all
        # agree -> that position; they differ -> mixed), so it does not drift
        # between runs that reach the same part-by-part conclusions.
        part_positions = {item["position"] for item in output.sub_verdicts}
        if len(output.sub_verdicts) >= 2:
            derived = part_positions.pop() if len(part_positions) == 1 else "mixed"
            if derived != position:
                limitations.append(
                    f"Overall position set to '{derived}' from the separate verdicts "
                    "on each part of the question."
                )
                position = derived

        decisive = snapshot["supported"] + snapshot["contradicted"]
        if decisive == 0 and position != "inconclusive":
            position = "inconclusive"
            preferred = None
            limitations.insert(
                0,
                "No stored claim has a supporting or contradicting "
                "verification, so the verdict is inconclusive. Extract and "
                "verify claims, then regenerate the verdict.",
            )
        if position == "inconclusive":
            preferred = None
        if dropped_refs:
            limitations.append(
                f"{dropped_refs} citation(s) produced by the model did not "
                "match a stored claim and were removed."
            )
        if snapshot["unverified"]:
            limitations.append(
                f"{snapshot['unverified']} of {snapshot.get('factual_claims', snapshot['total_claims'])} "
                "factual claims have not been verified."
            )

        cap, basis = confidence_cap(snapshot)
        confidence = _cap_confidence(output.confidence, cap)
        confidence_basis = (
            f"Model self-assessment: {output.confidence}. {basis}"
            if confidence != output.confidence
            else f"{basis} The model's own assessment ({output.confidence}) was kept."
        )

        values = dict(
            position=position,
            answer=output.answer,
            preferred_position=preferred,
            summary=output.summary,
            reasoning=output.reasoning,
            supporting_arguments=supporting,
            counterarguments=counter,
            confidence=confidence,
            confidence_basis=confidence_basis,
            limitations=limitations[: MAX_ITEMS + 3],
            unresolved_questions=output.unresolved_questions,
            evidence_snapshot=snapshot,
            assumptions=output.question_assumptions,
            sub_verdicts=output.sub_verdicts,
        )
        if on_generated:
            await on_generated()
        if existing is not None:
            for key, value in values.items():
                setattr(existing, key, value)
            verdict = existing
        else:
            verdict = DebateVerdict(debate_id=debate.id, **values)
            db.add(verdict)
        await db.commit()
        await db.refresh(verdict)
        logger.info(
            "Verdict for debate %s: position=%s confidence=%s",
            debate.id,
            position,
            confidence,
        )
        return verdict


async def verdict_claim_refs(db: AsyncSession, verdict: DebateVerdict) -> dict[str, Claim]:
    """Load every stored claim cited by the verdict (for responses/reports)."""
    ids = {
        claim_id
        for item in (verdict.supporting_arguments or []) + (verdict.counterarguments or [])
        for claim_id in item.get("claim_ids", [])
    }
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Claim)
            .where(Claim.id.in_([UUID(i) for i in ids]))
            .where(Claim.debate_id == verdict.debate_id)
            .options(
                selectinload(Claim.verification),
                selectinload(Claim.evidence),
                selectinload(Claim.agent),
            )
        )
    ).scalars().all()
    return {str(claim.id): claim for claim in rows}


def claim_ref_payload(claim: Claim) -> dict:
    verification = claim.verification
    return {
        "id": claim.id,
        "text": claim.text,
        "agent_name": claim.agent.name if claim.agent is not None else "Unknown",
        "verdict": verification.verdict if verification else None,
        "confidence": verification.confidence if verification else None,
        "sources": [
            {
                "title": e.title,
                "url": e.url,
                "source_name": e.source_name,
                "source_type": e.source_type,
                "publisher": e.publisher,
                "external_rating": e.external_rating,
            }
            for e in claim.evidence
        ],
    }


def evidence_basis(snapshot: dict) -> str:
    decisive = snapshot.get("supported", 0) + snapshot.get("contradicted", 0)
    total = snapshot.get("factual_claims", snapshot.get("total_claims", 0))
    if decisive == 0:
        return "none"
    return "substantial" if total and decisive / total >= 0.5 else "partial"


def inconclusive_reason(position: str, snapshot: dict) -> str | None:
    if position != "inconclusive":
        return None
    if snapshot.get("analysis_state") in ("failed", "partial") and (
        snapshot.get("supported", 0) + snapshot.get("contradicted", 0) == 0
        or snapshot.get("analysis_failures", 0)
    ):
        # Technical failure (search or LLM), not proof the question is open.
        return "analysis_incomplete"
    if snapshot.get("supported", 0) + snapshot.get("contradicted", 0) == 0:
        return "no_verified_evidence"
    if snapshot.get("supported", 0) and snapshot.get("contradicted", 0):
        return "conflicting_evidence"
    return "incomplete_evidence"


async def current_evidence_snapshot(db: AsyncSession, debate_id) -> dict:
    claims = list(
        (
            await db.execute(
                select(Claim)
                .where(Claim.debate_id == debate_id)
                .options(selectinload(Claim.verification), selectinload(Claim.evidence))
            )
        ).scalars().all()
    )
    snapshot = evidence_snapshot(claims)
    snapshot["material_fingerprint"] = await material_fingerprint(db, debate_id)
    return snapshot


async def material_fingerprint(db, debate_id):
    """Hash actual persisted inputs: same counts can still contain new findings."""
    import hashlib
    material = []
    for model in (DebateMessage, Claim, Fallacy, ArgumentEvaluation):
        result = await db.execute(select(*model.__table__.columns).where(model.debate_id == debate_id).order_by(model.id))
        material.append([list(row) for row in result])
    for model in (Evidence, ClaimVerification):
        result = await db.execute(select(*model.__table__.columns).where(model.claim_id.in_(
            select(Claim.id).where(Claim.debate_id == debate_id))).order_by(model.id))
        material.append([list(row) for row in result])
    return hashlib.sha256(json.dumps(material, default=str, sort_keys=True).encode()).hexdigest()


async def verdict_response_payload(db: AsyncSession, verdict: DebateVerdict) -> dict:
    claims = await verdict_claim_refs(db, verdict)
    snapshot = verdict.evidence_snapshot or {}
    current = await current_evidence_snapshot(db, verdict.debate_id)

    def expand(items: list[dict]) -> list[dict]:
        return [
            {
                "point": item.get("point", ""),
                "agent_name": item.get("agent_name"),
                "impact": item.get("impact"),
                "claims": [
                    claim_ref_payload(claims[cid])
                    for cid in item.get("claim_ids", [])
                    if cid in claims
                ],
            }
            for item in items or []
        ]

    return {
        "id": verdict.id,
        "debate_id": verdict.debate_id,
        "position": verdict.position,
        "answer": verdict.answer,
        "preferred_position": verdict.preferred_position,
        "summary": verdict.summary,
        "reasoning": verdict.reasoning,
        "supporting_arguments": expand(verdict.supporting_arguments),
        "counterarguments": expand(verdict.counterarguments),
        "confidence": verdict.confidence,
        "confidence_basis": verdict.confidence_basis,
        "limitations": verdict.limitations or [],
        "unresolved_questions": verdict.unresolved_questions or [],
        "assumptions": verdict.assumptions or [],
        "sub_verdicts": verdict.sub_verdicts or [],
        "evidence_snapshot": snapshot,
        "evidence_basis": evidence_basis(snapshot),
        "inconclusive_reason": inconclusive_reason(verdict.position, snapshot),
        # Only evidence counts decide staleness; run metadata (analysis
        # state, model) is not an evidence change.
        "stale": bool(snapshot)
        and {k: snapshot.get(k) for k in current} != current,
        "created_at": verdict.created_at,
        "updated_at": verdict.updated_at,
    }
