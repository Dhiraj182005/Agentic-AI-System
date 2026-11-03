from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.debate_round import DebateRound
from app.orchestration.turn_format import TranscriptEntry

OPENING = "opening"
ARGUMENT = "argument"
REBUTTAL = "rebuttal"
CLOSING = "closing"

TASK_INSTRUCTIONS = {
    OPENING: (
        "Present your strongest reasoned position on the topic.\n"
        "- State your position in one sentence.\n"
        "- Give your single most important argument from your specialist "
        "perspective (mention up to two more briefly in the reasoning).\n"
        "- Name the key assumption your argument depends on.\n"
        "- Say what evidence would strengthen or weaken your position."
    ),
    REBUTTAL: (
        "Respond to the arguments presented by the other participants.\n"
        "- Pick ONE specific argument from another participant that you have "
        "not yet addressed and cite it in rebuttal_to by its reference "
        "(e.g. \"R1-Economist\").\n"
        "- Say whether you agree or disagree and why, giving a reason or "
        "evidence-based counterargument.\n"
        "- Acknowledge the strongest opposing point honestly in concession.\n"
        "- If you genuinely agree, say so - do not invent disagreement."
    ),
    CLOSING: (
        "Provide your final position after considering the preceding discussion.\n"
        "- Address the strongest remaining objection to your position "
        "(cite it in rebuttal_to).\n"
        "- Correct or revise anything you said earlier that the discussion "
        "showed was wrong; set position_changed to true if your position moved.\n"
        "- State the strongest conclusion you can defend.\n"
        "- List the uncertainties that remain unresolved."
    ),
}

RESPONSE_RULES = (
    "Rules:\n"
    "- Speak from your specialist perspective. No greetings, no introductions, "
    "no restating the topic, no speeches.\n"
    "- Do not repeat arguments you or others already made; add something new.\n"
    "- Engage with what other participants actually said.\n"
    "- Keep factual claims (checkable statements) separate from reasoning, "
    "opinion and recommendation.\n"
    "- evidence_references: only sources or data you can name with confidence. "
    "Never invent statistics, studies, quotes or URLs. Leave the list empty "
    "if you have none.\n"
    "- You may change your position when the discussion warrants it. You do "
    "not have to agree with the majority."
)

RESPONSE_SCHEMA = (
    "Respond with ONLY a JSON object (no markdown fences, no extra text):\n"
    '{"position": "one sentence", "position_changed": false, '
    '"main_argument": "one concise argument", '
    '"rebuttal_to": {"ref": "R1-AgentName", "argument": "the argument you '
    'respond to, in a few words"} or null, '
    '"reasoning": "why the argument supports your position (1 short paragraph)", '
    '"factual_claims": ["checkable statement"], "evidence_references": [], '
    '"concession": "valid opposing point you accept" or null, '
    '"recommendation": "what should be done" or null, '
    '"uncertainties": ["what remains unclear"]}'
)

MAX_TRANSCRIPT_MESSAGES = 12
MAX_TRANSCRIPT_MESSAGE_CHARS = 500
MAX_PROMPT_CHARS = 9000

TRANSCRIPT_HEADING = "Previous debate transcript:"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def message_type_for_round(round_number: int, total_rounds: int) -> str:
    if round_number <= 1:
        return OPENING
    if round_number >= total_rounds:
        return CLOSING
    return REBUTTAL


def _as_entry(row) -> TranscriptEntry:
    if isinstance(row, TranscriptEntry):
        return row
    round_number, agent_name, content = row
    return TranscriptEntry(round_number=round_number, agent_name=agent_name, content=content)


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + " ..."


def format_entry(entry: TranscriptEntry) -> str:
    """One earlier turn, compact: structured turns show their key fields,
    older free-text turns a truncated excerpt."""
    kind = f" ({entry.message_type})" if entry.message_type else ""
    head = f"[{entry.ref}] Round {entry.round_number} - {entry.agent_name}{kind}:"
    data = entry.structured
    if not data:
        return f"{head} {_short(entry.content, MAX_TRANSCRIPT_MESSAGE_CHARS)}"
    parts = [head, f"  Position: {_short(data.get('position', ''), 200)}"]
    rebuttal = data.get("rebuttal_to")
    if rebuttal and rebuttal.get("argument"):
        target = rebuttal.get("ref") or "an earlier argument"
        parts.append(f"  Responding to {target}: {_short(rebuttal['argument'], 160)}")
    parts.append(f"  Main argument: {_short(data.get('main_argument', ''), 300)}")
    if data.get("concession"):
        parts.append(f"  Concedes: {_short(data['concession'], 160)}")
    return "\n".join(parts)


def format_transcript(transcript) -> str:
    """Format earlier turns (TranscriptEntry or legacy
    ``(round_number, agent_name, content)`` tuples) for the next prompt.

    Applies size limits so a long debate cannot grow the prompt without
    bound: only the most recent messages are kept and each is shortened.
    """
    if not transcript:
        return ""
    recent = [_as_entry(row) for row in transcript][-MAX_TRANSCRIPT_MESSAGES:]
    return "\n".join(format_entry(entry) for entry in recent)


class RoundManager:
    """Owns the lifecycle of a single debate round."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_round(self, debate, round_number: int) -> DebateRound:
        debate_round = DebateRound(
            debate_id=debate.id,
            round_number=round_number,
            status="pending",
        )
        # Keep the in-memory collection of the debate consistent with the DB.
        debate_round.debate = debate
        self.db.add(debate_round)
        await self.db.commit()
        return debate_round

    async def mark_running(self, round_id) -> DebateRound:
        debate_round = await self._get(round_id)
        debate_round.status = "running"
        debate_round.started_at = utcnow()
        debate_round.completed_at = None
        await self.db.commit()
        return debate_round

    async def mark_completed(self, round_id) -> DebateRound:
        debate_round = await self._get(round_id)
        debate_round.status = "completed"
        debate_round.completed_at = utcnow()
        await self.db.commit()
        return debate_round

    async def mark_failed(self, round_id) -> None:
        """Best-effort failure marking: never raises."""
        if round_id is None:
            return
        try:
            await self.db.rollback()
        except Exception:
            pass
        try:
            debate_round = await self._get(round_id)
            debate_round.status = "failed"
            debate_round.completed_at = utcnow()
            await self.db.commit()
        except Exception:
            await self.db.rollback()

    async def _get(self, round_id) -> DebateRound:
        result = await self.db.execute(
            select(DebateRound).where(DebateRound.id == round_id)
        )
        return result.scalar_one()

    def build_user_prompt(
        self,
        topic: str,
        round_number: int,
        total_rounds: int,
        transcript,
        context: str | None = None,
        *,
        agent_name: str | None = None,
        word_limit: int | None = None,
    ) -> str:
        message_type = message_type_for_round(round_number, total_rounds)
        head = ["You are participating in a structured debate.", "", f"Debate topic: {topic}"]
        if context:
            head.append(f"Background provided by the user: {context}")

        entries = [_as_entry(row) for row in transcript or []]
        own = [e for e in entries if agent_name and e.agent_name == agent_name]
        own_lines: list[str] = []
        if own:
            own_lines = ["", "Your earlier turns (do not repeat them; build on or revise them):"]
            for entry in own:
                data = entry.structured or {}
                summary = data.get("main_argument") or entry.content
                own_lines.append(f"- Round {entry.round_number}: {_short(summary, 220)}")

        tail = [
            "",
            f"Current round: {round_number} of {total_rounds} "
            f"({message_type} statement).",
            "",
            "Your task:",
            TASK_INSTRUCTIONS[message_type],
            "",
            RESPONSE_RULES,
        ]
        if word_limit:
            tail.append(
                f"- Length: at most {word_limit} words across all fields. "
                "Short, plain sentences."
            )
        tail += ["", RESPONSE_SCHEMA]

        prompt = "\n".join(head + own_lines + tail)
        if not entries:
            return prompt
        # Keep the most recent transcript content without ever pushing the
        # prompt past MAX_PROMPT_CHARS (head/tail text stays intact).
        transcript_text = format_transcript(entries)
        budget = MAX_PROMPT_CHARS - len(prompt) - len(TRANSCRIPT_HEADING)
        if budget <= 0:
            return prompt
        if len(transcript_text) > budget:
            transcript_text = "..." + transcript_text[-budget:]
        parts = head + ["", TRANSCRIPT_HEADING, transcript_text] + own_lines + tail
        return "\n".join(parts)
