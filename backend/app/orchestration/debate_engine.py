import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dynamic import DynamicSpecialistAgent
from app.agents.factory import get_agent_by_role
from app.core.observability import reset_llm_context, set_llm_context
from app.core.config import get_settings
from app.llm.base import LLMProviderError, LLMTimeoutError
from app.models.agent import Agent
from app.models.debate import Debate
from app.models.debate_agent import DebateAgent
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.orchestration.round_manager import (
    RoundManager,
    message_type_for_round,
    utcnow,
)
from app.orchestration.turn_format import TranscriptEntry, parse_turn, resolve_turn
from app.orchestration.turn_manager import TurnManager
from app.websocket.events import DebateEventManager

logger = logging.getLogger(__name__)

# Default output budget for one debate turn; DEBATE_MAX_RESPONSE_TOKENS
# overrides it. Reasoning models spend part of it on hidden reasoning, so it
# must leave room for the visible answer (1024 was too small for
# openai/gpt-oss-20b on rebuttal rounds).
MAX_RESPONSE_TOKENS = 2048


class DebateExecutionError(Exception):
    """Raised when a debate cannot be executed successfully."""

    def __init__(
        self, message: str, *, provider: bool = False, timeout: bool = False
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.timeout = timeout


class DebateEngine:
    """Runs a debate from start to finish.

    Responsibilities:
    - move the debate through running/completed/failed states,
    - create the configured rounds in order,
    - let every agent speak sequentially in a stable order,
    - persist every message immediately.
    """

    def __init__(
        self,
        db: AsyncSession,
        agent_factory=None,
        events: DebateEventManager | None = None,
    ) -> None:
        self.db = db
        self.round_manager = RoundManager(db)
        self._agent_factory = agent_factory or get_agent_by_role
        # Observation channel only: the engine never depends on WebSocket state.
        self.events = events if events is not None else DebateEventManager(bind=getattr(db, "bind", None))

    async def execute(self, debate: Debate, resume: bool = False) -> None:
        """Run the debate. With resume=True, continue a failed debate: rounds
        that completed are skipped, and inside the interrupted round only the
        turns without a stored message are generated (the unique
        (round_id, turn_number) constraint backs this up), so no turn is ever
        duplicated."""
        debate_id = debate.id
        topic = debate.topic
        debate_context = debate.context
        total_rounds = debate.total_rounds

        agents = await self._ordered_agents(debate_id)
        if not agents:
            raise DebateExecutionError(
                "The debate has no participating agents.", provider=False
            )
        turn_manager = TurnManager(agents)

        settings = get_settings()
        max_tokens = settings.DEBATE_MAX_RESPONSE_TOKENS or MAX_RESPONSE_TOKENS
        word_limits = {
            "opening": settings.DEBATE_OPENING_WORD_LIMIT,
            "rebuttal": settings.DEBATE_REBUTTAL_WORD_LIMIT,
            "closing": settings.DEBATE_CLOSING_WORD_LIMIT,
        }
        existing_rounds = await self._existing_rounds(debate_id) if resume else {}

        active_round_id = None
        position: tuple[int, int, str] | None = None
        try:
            await self._set_status(
                debate_id,
                "running",
                started_at=None if resume and debate.started_at else utcnow(),
                reset_failure=True,
            )
            await self._broadcast(self.events.debate_started(debate_id))
            runtime_agents = {agent.id: self._runtime_agent(agent) for agent in agents}
            for round_number in range(1, total_rounds + 1):
                stored_round = existing_rounds.get(round_number)
                if stored_round is not None and stored_round.status == "completed":
                    continue
                done_turns: set[int] = set()
                if stored_round is not None:
                    debate_round = stored_round
                    done_turns = await self._stored_turns(debate_round.id)
                else:
                    debate_round = await self.round_manager.create_round(
                        debate, round_number
                    )
                active_round_id = debate_round.id
                await self.round_manager.mark_running(active_round_id)
                await self._broadcast(
                    self.events.round_started(debate_id, round_number)
                )
                message_type = message_type_for_round(round_number, total_rounds)
                for turn_number, agent in turn_manager.turns_for_round(round_number):
                    if turn_number in done_turns:
                        continue
                    position = (round_number, turn_number, agent.name)
                    await self._broadcast(
                        self.events.agent_turn_started(
                            debate_id, round_number, turn_number, agent
                        )
                    )
                    transcript = await self._transcript(debate_id)
                    prompt = self.round_manager.build_user_prompt(
                        topic,
                        round_number,
                        total_rounds,
                        transcript,
                        context=debate_context,
                        agent_name=agent.name,
                        word_limit=word_limits.get(message_type),
                    )
                    context_token = set_llm_context(
                        debate=str(debate_id)[:8],
                        round=round_number,
                        turn=turn_number,
                        agent=agent.role,
                    )
                    try:
                        response = await runtime_agents[agent.id].generate_response(
                            prompt, max_tokens=max_tokens
                        )
                    finally:
                        reset_llm_context(context_token)
                    content, structured = self._shape_turn(
                        response.content, transcript, agent.name, position
                    )
                    message = await self._persist_message(
                        debate_id=debate_id,
                        round_id=active_round_id,
                        agent=agent,
                        turn_number=turn_number,
                        message_type=message_type,
                        content=content,
                        structured=structured,
                    )
                    await self._broadcast(
                        self.events.agent_message(
                            debate_id=debate_id,
                            round_number=round_number,
                            turn_number=turn_number,
                            message_type=message_type,
                            message_id=message.id,
                            agent=agent,
                            content=message.content,
                            structured=message.structured,
                        )
                    )
                    await self._broadcast(
                        self.events.agent_turn_completed(
                            debate_id, round_number, turn_number, agent
                        )
                    )
                await self.round_manager.mark_completed(active_round_id)
                await self._broadcast(
                    self.events.round_completed(debate_id, round_number)
                )
                active_round_id = None
        except Exception as exc:
            error = self._as_error(exc, position)
            await self._fail(debate_id, active_round_id, error)
            raise error from exc

        await self._set_status(debate_id, "completed", completed_at=utcnow())
        await self._broadcast(self.events.debate_completed(debate_id))

    def _runtime_agent(self, agent: Agent):
        """Built-ins come from the role registry; debate-scoped specialists
        are rebuilt from their stored, validated definition. Both use the
        same shared LLM provider."""
        if getattr(agent, "source", "builtin") == "dynamic" and agent.definition:
            return DynamicSpecialistAgent(agent.definition, identifier=agent.role)
        return self._agent_factory(agent.role)

    async def _broadcast(self, event_coro) -> None:
        """Publish one event; broadcast problems never break the debate."""
        try:
            await event_coro
        except Exception:
            logger.warning("Could not broadcast debate event", exc_info=True)

    async def _ordered_agents(self, debate_id) -> list[Agent]:
        result = await self.db.execute(
            select(Agent)
            .join(DebateAgent, DebateAgent.agent_id == Agent.id)
            .where(DebateAgent.debate_id == debate_id)
            .order_by(DebateAgent.position, DebateAgent.agent_id)
        )
        return list(result.scalars().all())

    async def _transcript(self, debate_id) -> list[TranscriptEntry]:
        result = await self.db.execute(
            select(DebateMessage, DebateRound.round_number, Agent.name, Agent.role)
            .join(DebateRound, DebateRound.id == DebateMessage.round_id)
            .join(Agent, Agent.id == DebateMessage.agent_id)
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateRound.round_number, DebateMessage.turn_number)
        )
        return [
            TranscriptEntry(
                round_number=round_number,
                agent_name=agent_name,
                content=message.content,
                structured=message.structured,
                message_id=str(message.id),
                message_type=message.message_type,
                agent_role=agent_role,
            )
            for message, round_number, agent_name, agent_role in result.all()
        ]

    def _shape_turn(self, raw: str, transcript, speaker: str, position):
        """Structured turn when the reply follows the schema; otherwise the
        model's real text, stored unstructured (never invented content)."""
        turn = parse_turn(raw)
        if turn is None:
            logger.warning(
                "Turn %s by %s did not follow the structured format; stored as text",
                position,
                speaker,
            )
            return raw, None
        resolved = resolve_turn(turn, transcript, speaker)
        for note in resolved.notes:
            logger.info("Turn %s by %s: %s", position, speaker, note)
        return resolved.content, resolved.structured

    async def _persist_message(
        self,
        *,
        debate_id,
        round_id,
        agent: Agent,
        turn_number: int,
        message_type: str,
        content: str,
        structured: dict | None = None,
    ) -> DebateMessage:
        message = DebateMessage(
            debate_id=debate_id,
            round_id=round_id,
            agent_id=agent.id,
            turn_number=turn_number,
            message_type=message_type,
            content=content,
            structured=structured,
        )
        self.db.add(message)
        await self.db.commit()
        return message

    async def _set_status(
        self,
        debate_id,
        status: str,
        started_at=None,
        completed_at=None,
        reset_failure: bool = False,
    ) -> Debate:
        debate = await self._get_debate(debate_id)
        debate.status = status
        if started_at is not None:
            debate.started_at = started_at
        if completed_at is not None:
            debate.completed_at = completed_at
        if reset_failure:
            debate.completed_at = None
            debate.failure_reason = None
        await self.db.commit()
        return debate

    async def _existing_rounds(self, debate_id) -> dict[int, DebateRound]:
        result = await self.db.execute(
            select(DebateRound).where(DebateRound.debate_id == debate_id)
        )
        return {r.round_number: r for r in result.scalars().all()}

    async def _stored_turns(self, round_id) -> set[int]:
        result = await self.db.execute(
            select(DebateMessage.turn_number).where(DebateMessage.round_id == round_id)
        )
        return set(result.scalars().all())

    async def _fail(self, debate_id, round_id, error: DebateExecutionError) -> None:
        try:
            await self.db.rollback()
        except Exception:
            logger.exception("Rollback before debate failure handling failed")
        try:
            await self.round_manager.mark_failed(round_id)
            debate = await self._get_debate(debate_id)
            debate.status = "failed"
            debate.completed_at = utcnow()
            debate.failure_reason = str(error)[:1000]
            await self.db.commit()
        except Exception:
            logger.exception("Could not persist the failed debate state")
            try:
                await self.db.rollback()
            except Exception:
                pass
        # The safe, user-facing message only; internals stay in the logs.
        await self._broadcast(self.events.debate_failed(debate_id, str(error)))

    async def _get_debate(self, debate_id) -> Debate:
        result = await self.db.execute(select(Debate).where(Debate.id == debate_id))
        return result.scalar_one()

    def _as_error(
        self, exc: Exception, position: tuple[int, int, str] | None = None
    ) -> DebateExecutionError:
        if isinstance(exc, DebateExecutionError):
            return exc
        where = (
            f"Round {position[0]}, turn {position[1]} ({position[2]}): "
            if position
            else ""
        )
        if isinstance(exc, LLMProviderError):
            # Logs keep the normalized error class; users get the safe
            # per-class message (never provider payloads or credentials).
            logger.warning(
                "Debate generation failed at %s%s",
                where or "an unknown turn: ",
                type(exc).__name__,
            )
            return DebateExecutionError(
                f"{where}{exc.user_message}",
                provider=True,
                timeout=isinstance(exc, LLMTimeoutError),
            )
        logger.error("Unexpected debate execution error", exc_info=exc)
        return DebateExecutionError(
            "The debate failed because of an unexpected internal error.",
            provider=False,
        )
