from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent


async def list_active_core_agents(db: AsyncSession) -> list[Agent]:
    """Return every active core agent ordered by name."""
    result = await db.execute(
        select(Agent)
        .where(Agent.is_core.is_(True), Agent.is_active.is_(True))
        .order_by(Agent.name)
    )
    return list(result.scalars().all())
