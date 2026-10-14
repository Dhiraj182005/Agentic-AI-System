from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.debate_round import DebateRound

OPENING = "opening"
ARGUMENT = "argument"
REBUTTAL = "rebuttal"
CLOSING = "closing"

TASK_INSTRUCTIONS = {
    OPENING: "Present your strongest reasoned position on the topic.",
    REBUTTAL: (
        "Respond to the arguments presented by the other participants. "
        "Identify disagreements and provide your reasoning."
    ),
    CLOSING: (
        "Provide your final position after considering the preceding discussion."
    ),
}

MAX_TRANSCRIPT_MESSAGES = 12
MAX_TRANSCRIPT_MESSAGE_CHARS = 500
MAX_PROMPT_CHARS = 6000

TRANSCRIPT_HEADING = "Previous debate transcript:"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def message_type_for_round(round_number: int, total_rounds: int) -> str:
    if round_number <= 1:
        return OPENING
    if round_number >= total_rounds:
        return CLOSING
    return REBUTTAL


def format_transcript(
    transcript: list[tuple[int, str, str]],
) -> str:
    """Format ``(round_number, agent_name, content)`` rows as transcript text.

    Applies size limits so a long debate cannot grow the prompt without
    bound: only the most recent messages are kept and each message is
    truncated.
    """
    if not transcript:
        return ""
    recent = transcript[-MAX_TRANSCRIPT_MESSAGES:]
    lines = []
    for round_number, agent_name, content in recent:
        snippet = content.strip()
        if len(snippet) > MAX_TRANSCRIPT_MESSAGE_CHARS:
            snippet = snippet[:MAX_TRANSCRIPT_MESSAGE_CHARS].rstrip() + " ..."
        lines.append(f"Round {round_number} - {agent_name}: {snippet}")
    return "\n".join(lines)


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
        transcript: list[tuple[int, str, str]],
    ) -> str:
        message_type = message_type_for_round(round_number, total_rounds)
        head = ["You are participating in a debate.", "", f"Debate topic: {topic}"]
        tail = [
            "",
            f"Current round: {round_number} of {total_rounds} "
            f"({message_type} statement).",
            "",
            "Your task:",
            TASK_INSTRUCTIONS[message_type],
        ]
        prompt = "\n".join(head + tail)
        if not transcript:
            return prompt
        # Keep the most recent transcript content without ever pushing the
        # prompt past MAX_PROMPT_CHARS (head/tail text stays intact).
        transcript_text = format_transcript(transcript)
        budget = MAX_PROMPT_CHARS - len(prompt) - len(TRANSCRIPT_HEADING)
        if budget <= 0:
            return prompt
        if len(transcript_text) > budget:
            transcript_text = "..." + transcript_text[-budget:]
        parts = head + [TRANSCRIPT_HEADING, transcript_text] + tail
        return "\n".join(parts)
