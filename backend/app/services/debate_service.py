import logging
import asyncio
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings

from app.models.agent import AGENT_SOURCE_DYNAMIC, Agent
from app.models.debate import Debate
from app.models.debate_agent import DebateAgent
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.judge import DebateJudgment
from app.models.user import User
from app.models.verdict import DebateVerdict
from app.orchestration import liveness
from app.orchestration.debate_engine import DebateEngine
from app.websocket.events import DebateEventManager
from app.schemas.debate import MIN_AGENTS, DebateCreateRequest
from app.services.agent_selection import AgentSelectionService, InsufficientAgentsError
from app.services.topic_analysis import specialist_record, validate_specialists

# Rough per-turn prompt size used for the token budget estimate.
PROMPT_TOKEN_ESTIMATE = 2000

# The existing `debate_status_enum` defines the lifecycle states for a debate.
# "pending" is the initial state of a freshly created debate: it is stored,
# configured and waiting, but has not started executing yet.
INITIAL_DEBATE_STATUS = "pending"

INTERRUPTED_REASON = (
    "The debate was interrupted before it finished (the server stopped while "
    "it was running). Completed rounds and stored messages are kept; resume "
    "it to continue."
)

logger = logging.getLogger(__name__)
_execution_tasks: set[asyncio.Task] = set()


async def schedule_execution(db, user, debate_id, *, resume=False):
    """Claim before replying, then run on an independent session, never a request session."""
    debate = await get_debate(db, user, debate_id)
    if debate.status == "running":
        return  # idempotent attach to the existing run
    expected = "failed" if resume else INITIAL_DEBATE_STATUS
    if debate.status != expected:
        raise DebateConflictError("This debate cannot be started in its current state")
    try:
        await _claim(db, debate, expected)
    except DebateConflictError:
        await db.refresh(debate)
        await db.refresh(user)
        if debate.status == "running":
            return
        raise
    user_id = user.id
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def runner():
        async with factory() as session:
            owner = await session.get(User, user_id)
            current = await session.get(Debate, debate_id)
            try:
                async with liveness.DebateHeartbeat(debate_id):
                    await DebateEngine(session).execute(current, resume=resume)
                await session.refresh(current)
                _schedule_post_debate_analysis(session, current, owner)
            except Exception:
                logger.exception("Background debate execution failed for %s", debate_id)
    task = asyncio.create_task(runner())
    _execution_tasks.add(task)
    task.add_done_callback(_execution_tasks.discard)


async def wait_for_execution():
    while _execution_tasks:
        await asyncio.gather(*list(_execution_tasks), return_exceptions=True)

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
    db: AsyncSession, agent_roles: list[str], min_agents: int = MIN_AGENTS
) -> list[Agent]:
    """Resolve requested role identifiers to active core Agent rows.

    Rejects unknown, inactive and non-core agents. The request order is kept.
    """
    if len(agent_roles) < min_agents:
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
    if len(agents) < min_agents:
        raise DebateValidationError(
            f"At least {MIN_AGENTS} agents are required to create a debate"
        )
    return agents


async def select_auto_agents(
    db: AsyncSession, topic: str, agent_roles: list[str], min_agents: int = MIN_AGENTS
) -> list[Agent]:
    """Resolve AUTO selection without running a second LLM round.

    When the client supplies the recommended agent roles, they are validated
    against the database and used as-is so the stored debate-agent
    relationships match what the user was shown. Otherwise the deterministic
    topic-aware fallback builds the selection from the topic.
    """
    if agent_roles:
        return await resolve_selected_agents(db, agent_roles, min_agents)
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
    settings = get_settings()
    specialists = []
    if data.specialists:
        if data.expert_selection_mode == "manual":
            # Manual selection is respected as-is; nothing is added to it.
            raise DebateValidationError(
                "AI specialist roles are only added with automatic selection"
            )
        specialists, rejected = validate_specialists(
            data.specialists,
            await AgentSelectionService().builtin_agents(db),
            relevance_text=None,
            limit=settings.DEBATE_MAX_SPECIALISTS,
        )
        if rejected:
            raise DebateValidationError(
                "Invalid specialist role(s): "
                + "; ".join(f"{r['name']}: {r['reason']}" for r in rejected)
            )

    min_builtins = max(0, MIN_AGENTS - len(specialists))
    if data.expert_selection_mode == "manual":
        agents = await resolve_selected_agents(db, data.agent_ids)
    else:
        agents = await select_auto_agents(db, data.topic, data.agent_ids, min_builtins)

    total_agents = len(agents) + len(specialists)
    if total_agents > settings.DEBATE_MAX_AGENTS:
        raise DebateValidationError(
            f"A debate can have at most {settings.DEBATE_MAX_AGENTS} agents "
            f"({total_agents} selected)"
        )
    turns = total_agents * data.total_rounds
    if turns > settings.DEBATE_MAX_TURNS:
        raise DebateValidationError(
            f"{total_agents} agents x {data.total_rounds} rounds = {turns} turns "
            f"exceeds the limit of {settings.DEBATE_MAX_TURNS}; use fewer agents or rounds"
        )
    estimate = turns * (PROMPT_TOKEN_ESTIMATE + settings.DEBATE_MAX_RESPONSE_TOKENS)
    if estimate > settings.DEBATE_TOKEN_BUDGET:
        raise DebateValidationError(
            f"Estimated {estimate:,} tokens exceeds the debate budget of "
            f"{settings.DEBATE_TOKEN_BUDGET:,}; use fewer agents or rounds"
        )

    debate = Debate(
        user_id=user.id,
        topic=data.topic,
        context=data.context,
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
        for spec in specialists:
            slug = re.sub(r"[^a-z0-9]+", "-", spec.name.lower()).strip("-")[:60]
            agent = Agent(
                name=spec.name,
                role=f"specialist-{slug}-{str(debate.id)[:8]}",
                description=spec.expertise,
                is_core=False,
                is_active=True,
                source=AGENT_SOURCE_DYNAMIC,
                definition=specialist_record(spec, source="topic_analysis", model=None),
                debate_id=debate.id,
            )
            db.add(agent)
            await db.flush()
            agents.append(agent)
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
    debates = list(result.scalars().unique().all())
    for debate in debates:
        await reconcile_interrupted(db, debate)
    return debates


async def get_debate(db: AsyncSession, user: User, debate_id: UUID) -> Debate:
    """Return a single debate when it exists and belongs to the user."""
    result = await db.execute(select(Debate).where(Debate.id == debate_id))
    debate = result.scalar_one_or_none()
    if debate is None or debate.user_id != user.id:
        raise DebateNotFoundError("Debate not found")
    await reconcile_interrupted(db, debate)
    return debate


async def reconcile_interrupted(db: AsyncSession, debate: Debate) -> bool:
    """Mark a 'running' debate whose worker is gone as failed (interrupted).

    Interrupted = no live heartbeat AND no database update for one heartbeat
    TTL (the grace window covers the instant between claiming a debate and
    its first heartbeat). Without Redis, a longer elapsed-time threshold is
    used. The update is conditional on status='running', so it is safe to run
    concurrently with anything else. Returns True when the debate changed.
    """
    if debate.status != "running":
        return False
    settings = get_settings()
    alive = await liveness.is_alive(debate.id)
    if alive:
        return False
    grace = (
        settings.DEBATE_HEARTBEAT_TTL_SECONDS
        if alive is False
        else settings.DEBATE_STALE_AFTER_SECONDS
    )
    last_update = debate.updated_at or debate.started_at or debate.created_at
    if last_update is not None:
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_update < timedelta(seconds=grace):
            return False

    changed = await db.execute(
        update(Debate)
        .where(Debate.id == debate.id, Debate.status == "running")
        .values(
            status="failed",
            failure_reason=INTERRUPTED_REASON,
            completed_at=func.now(),
        )
        .returning(Debate.id)
    )
    if changed.scalar_one_or_none() is None:
        await db.rollback()
        await db.refresh(debate)
        return False
    await db.execute(
        update(DebateRound)
        .where(DebateRound.debate_id == debate.id, DebateRound.status.in_(("running", "pending")))
        .values(status="failed", completed_at=func.now())
    )
    await db.commit()
    await db.refresh(debate)
    logger.warning("Debate %s was interrupted; marked failed", debate.id)
    try:
        await DebateEventManager().debate_failed(debate.id, INTERRUPTED_REASON)
    except Exception:
        logger.warning("Could not broadcast interrupted debate", exc_info=True)
    return True


async def _claim(db: AsyncSession, debate: Debate, expected: str) -> None:
    """Atomically move a debate from `expected` to 'running'.

    The conditional UPDATE means two concurrent start/resume requests can
    never both run the same debate: the second one gets a conflict.
    """
    claimed = await db.execute(
        update(Debate)
        .where(Debate.id == debate.id, Debate.status == expected)
        .values(status="running", execution_state="starting")
        .returning(Debate.id)
    )
    if claimed.scalar_one_or_none() is None:
        await db.rollback()
        await db.refresh(debate)
        raise DebateConflictError(
            f"Debate cannot be {'started' if expected == INITIAL_DEBATE_STATUS else 'resumed'} "
            f"while its status is '{debate.status}'"
        )
    await db.commit()
    await db.refresh(debate)


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
    await _claim(db, debate, INITIAL_DEBATE_STATUS)

    async with liveness.DebateHeartbeat(debate.id):
        engine = DebateEngine(db)
        await engine.execute(debate)
    finished = await get_debate(db, user, debate_id)
    _schedule_post_debate_analysis(db, finished, user)
    return finished


def _schedule_post_debate_analysis(db: AsyncSession, debate: Debate, user: User) -> None:
    """Start claim extraction / evidence / verification / verdict in the
    background once a debate completes (only for debates created with
    "verify evidence"). Never blocks or fails the debate response."""
    from app.services import analysis_pipeline

    try:
        if (
            debate.status == "completed"
            and debate.verify_evidence
            and analysis_pipeline.auto_analysis_enabled()
        ):
            analysis_pipeline.schedule_analysis(db.bind, debate.id, user.id)
    except Exception:
        logger.exception("Could not schedule post-debate analysis for %s", debate.id)


async def resume_debate(db: AsyncSession, user: User, debate_id: UUID) -> Debate:
    """Continue a failed debate from the turn that failed.

    Completed rounds and every stored message are kept; only missing turns
    are generated. Only 'failed' debates can be resumed. A failed debate can
    never have been judged or given a verdict (both require 'completed'), so
    no stale analysis survives the resume.
    """
    debate = await get_debate(db, user, debate_id)
    if debate.status != "failed":
        raise DebateConflictError(
            f"Only failed debates can be resumed (status is '{debate.status}')"
        )
    await _claim(db, debate, "failed")

    # New messages will be added, so any conclusion drawn from the earlier
    # transcript is stale. Judgment and verdict require a completed debate,
    # so none should exist - remove defensively all the same.
    await db.execute(delete(DebateJudgment).where(DebateJudgment.debate_id == debate.id))
    await db.execute(delete(DebateVerdict).where(DebateVerdict.debate_id == debate.id))
    await db.commit()

    async with liveness.DebateHeartbeat(debate.id):
        engine = DebateEngine(db)
        await engine.execute(debate, resume=True)
    finished = await get_debate(db, user, debate_id)
    _schedule_post_debate_analysis(db, finished, user)
    return finished


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
