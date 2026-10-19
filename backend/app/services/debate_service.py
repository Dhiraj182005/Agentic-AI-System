from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.debate import Debate
from app.models.debate_agent import DebateAgent
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.user import User
from app.orchestration.debate_engine import DebateEngine
from app.schemas.debate import MIN_AGENTS, DebateCreateRequest
from app.services.agent_selection import AgentSelectionService, InsufficientAgentsError

# The existing `debate_status_enum` defines the lifecycle states for a debate.
# "pending" is the initial state of a freshly created debate: it is stored,
# configured and waiting, but has not started executing yet.
INITIAL_DEBATE_STATUS = "pending"

# AUTO selection rule: use the agents from the topic-aware recommendation that
# the client already received (validated against the database). When no
# recommendation ids are supplied (direct API calls), fall back to the same
# deterministic topic/keyword selector — still topic-aware, never "all agents"
# and never an LLM call during creation.
AUTO_SELECTION_RULE = "topic_aware_recommended_agents"


class DebateServiceError(Exception):
    """Base class for debate service errors."""


class DebateValidationError(DebateServiceError):
    """Raised when a debate request does not satisfy the business rules."""


class DebateNotFoundError(DebateServiceError):
    """Raised when a debate does not exist or does not belong to the user."""


class DebateConflictError(DebateServiceError):
    """Raised when the debate is not in a state that allows the operation."""


async def resolve_selected_agents(
    db: AsyncSession, agent_roles: list[str]
) -> list[Agent]:
    """Resolve requested role identifiers to active core Agent rows.

    Rejects unknown, inactive and non-core agents. The request order is kept.
    """
    if len(agent_roles) < MIN_AGENTS:
        raise DebateValidationError(
            f"At least {MIN_AGENTS} agents are required to create a debate"
        )

    result = await db.execute(select(Agent).where(Agent.role.in_(agent_roles)))
    found = {agent.role: agent for agent in result.scalars().all()}

    unknown = [role for role in agent_roles if role not in found]
    if unknown:
        raise DebateValidationError("Unknown agent(s): " + ", ".join(unknown))

    inactive = [role for role in agent_roles if not found[role].is_active]
    if inactive:
        raise DebateValidationError("Inactive agent(s): " + ", ".join(inactive))

    non_core = [role for role in agent_roles if not found[role].is_core]
    if non_core:
        raise DebateValidationError("Non-core agent(s): " + ", ".join(non_core))

    agents = [found[role] for role in agent_roles]
    if len(agents) < MIN_AGENTS:
        raise DebateValidationError(
            f"At least {MIN_AGENTS} agents are required to create a debate"
        )
    return agents


async def select_auto_agents(
    db: AsyncSession, topic: str, agent_roles: list[str]
) -> list[Agent]:
    """Resolve AUTO selection without running a second LLM round.

    When the client supplies the recommended agent roles, they are validated
    against the database and used as-is so the stored debate-agent
    relationships match what the user was shown. Otherwise the deterministic
    topic-aware fallback builds the selection from the topic.
    """
    if agent_roles:
        return await resolve_selected_agents(db, agent_roles)
    try:
        return await AgentSelectionService().select_fallback(db, topic)
    except InsufficientAgentsError as exc:
        raise DebateValidationError(str(exc)) from exc


async def _add_agent_links(db: AsyncSession, debate: Debate, agents: list[Agent]) -> None:
    # The selection order becomes the speaking order of the debate.
    for position, agent in enumerate(agents, start=1):
        db.add(
            DebateAgent(debate_id=debate.id, agent_id=agent.id, position=position)
        )
    await db.flush()


async def create_debate(
    db: AsyncSession, user: User, data: DebateCreateRequest
) -> Debate:
    """Create a debate and its agent associations in a single transaction.

    The debate is stored with INITIAL_DEBATE_STATUS and never executed here:
    no runtime agent, provider or LLM call happens during creation.
    """
    if data.expert_selection_mode == "manual":
        agents = await resolve_selected_agents(db, data.agent_ids)
    else:
        agents = await select_auto_agents(db, data.topic, data.agent_ids)

    debate = Debate(
        user_id=user.id,
        topic=data.topic,
        expert_selection_mode=data.expert_selection_mode,
        domain_tags=data.domain_tags,
        status=INITIAL_DEBATE_STATUS,
        mode=data.mode,
        total_rounds=data.total_rounds,
        verify_evidence=data.verify_evidence,
    )

    try:
        db.add(debate)
        await db.flush()
        await _add_agent_links(db, debate, agents)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_debate(db, user, debate.id)


async def list_debates(db: AsyncSession, user: User) -> list[Debate]:
    """Return only the debates owned by the given user."""
    result = await db.execute(
        select(Debate)
        .where(Debate.user_id == user.id)
        .order_by(Debate.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def get_debate(db: AsyncSession, user: User, debate_id: UUID) -> Debate:
    """Return a single debate when it exists and belongs to the user."""
    result = await db.execute(select(Debate).where(Debate.id == debate_id))
    debate = result.scalar_one_or_none()
    if debate is None or debate.user_id != user.id:
        raise DebateNotFoundError("Debate not found")
    return debate


async def start_debate(db: AsyncSession, user: User, debate_id: UUID) -> Debate:
    """Execute a debate from start to finish.

    Only a debate in INITIAL_DEBATE_STATUS may be started; every other state
    raises DebateConflictError. The engine persists rounds, messages and the
    final status.
    """
    debate = await get_debate(db, user, debate_id)
    if debate.status != INITIAL_DEBATE_STATUS:
        raise DebateConflictError(
            f"Debate cannot be started while its status is '{debate.status}'"
        )

    engine = DebateEngine(db)
    await engine.execute(debate)

    return await get_debate(db, user, debate_id)


async def get_debate_transcript(
    db: AsyncSession, user: User, debate_id: UUID
) -> list[tuple[DebateMessage, int]]:
    """Return all persisted messages ordered by round, then turn."""
    debate = await get_debate(db, user, debate_id)
    result = await db.execute(
        select(DebateMessage, DebateRound.round_number)
        .join(DebateRound, DebateRound.id == DebateMessage.round_id)
        .where(DebateMessage.debate_id == debate.id)
        .order_by(DebateRound.round_number, DebateMessage.turn_number)
    )
    return [(message, round_number) for message, round_number in result.all()]


async def get_debate_rounds(
    db: AsyncSession, user: User, debate_id: UUID
) -> list[DebateRound]:
    """Return the rounds of a debate in round order."""
    debate = await get_debate(db, user, debate_id)
    result = await db.execute(
        select(DebateRound)
        .where(DebateRound.debate_id == debate.id)
        .order_by(DebateRound.round_number)
    )
    return list(result.scalars().all())
