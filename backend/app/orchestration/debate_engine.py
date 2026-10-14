import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.factory import get_agent_by_role
from app.llm.base import LLMProviderError
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
from app.orchestration.turn_manager import TurnManager
from app.websocket.events import DebateEventManager

logger = logging.getLogger(__name__)

# Bounded debate messages keep transcripts readable and keep each generation
# inside the provider's per-minute token budget. Large enough that a reasoning
# model can finish its answer within the budget.
MAX_RESPONSE_TOKENS = 1024


class DebateExecutionError(Exception):
    """Raised when a debate cannot be executed successfully."""

    def __init__(self, message: str, *, provider: bool = False) -> None:
        super().__init__(message)
        self.provider = provider


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
        self.events = events if events is not None else DebateEventManager()

    async def execute(self, debate: Debate) -> None:
        debate_id = debate.id
        topic = debate.topic
        total_rounds = debate.total_rounds

        agents = await self._ordered_agents(debate_id)
        if not agents:
            raise DebateExecutionError(
                "The debate has no participating agents.", provider=False
            )
        turn_manager = TurnManager(agents)

        active_round_id = None
        try:
            await self._set_status(debate_id, "running", started_at=utcnow())
            await self._broadcast(self.events.debate_started(debate_id))
            runtime_agents = {
                agent.id: self._agent_factory(agent.role) for agent in agents
            }
            for round_number in range(1, total_rounds + 1):
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
                    await self._broadcast(
                        self.events.agent_turn_started(
                            debate_id, round_number, turn_number, agent
                        )
                    )
                    transcript = await self._transcript(debate_id)
                    prompt = self.round_manager.build_user_prompt(
                        topic, round_number, total_rounds, transcript
                    )
                    response = await runtime_agents[agent.id].generate_response(
                        prompt, max_tokens=MAX_RESPONSE_TOKENS
                    )
                    message = await self._persist_message(
                        debate_id=debate_id,
                        round_id=active_round_id,
                        agent=agent,
                        turn_number=turn_number,
                        message_type=message_type,
                        content=response.content,
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
            error = self._as_error(exc)
            await self._fail(debate_id, active_round_id, error)
            raise error from exc

        await self._set_status(debate_id, "completed", completed_at=utcnow())
        await self._broadcast(self.events.debate_completed(debate_id))

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

    async def _transcript(self, debate_id) -> list[tuple[int, str, str]]:
        result = await self.db.execute(
            select(DebateMessage, DebateRound.round_number, Agent.name)
            .join(DebateRound, DebateRound.id == DebateMessage.round_id)
            .join(Agent, Agent.id == DebateMessage.agent_id)
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateRound.round_number, DebateMessage.turn_number)
        )
        return [
            (round_number, agent_name, message.content)
            for message, round_number, agent_name in result.all()
        ]

    async def _persist_message(
        self,
        *,
        debate_id,
        round_id,
        agent: Agent,
        turn_number: int,
        message_type: str,
        content: str,
    ) -> DebateMessage:
        message = DebateMessage(
            debate_id=debate_id,
            round_id=round_id,
            agent_id=agent.id,
            turn_number=turn_number,
            message_type=message_type,
            content=content,
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
    ) -> Debate:
        debate = await self._get_debate(debate_id)
        debate.status = status
        if started_at is not None:
            debate.started_at = started_at
        if completed_at is not None:
            debate.completed_at = completed_at
        await self.db.commit()
        return debate

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

    def _as_error(self, exc: Exception) -> DebateExecutionError:
        if isinstance(exc, DebateExecutionError):
            return exc
        if isinstance(exc, LLMProviderError):
            # Log safely on the server only; the raw reason never reaches the API.
            logger.warning(
                "Debate generation failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            return DebateExecutionError(
                "The language model provider failed while the debate was running.",
                provider=True,
            )
        logger.error("Unexpected debate execution error", exc_info=exc)
        return DebateExecutionError(
            "The debate failed because of an unexpected internal error.",
            provider=False,
        )
