from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent


CORE_AGENTS = [
    {
        "name": "Economist",
        "role": "economist",
        "description": "Focuses on economic impact, costs, benefits, markets, incentives, and financial feasibility.",
        "is_core": True,
    },
    {
        "name": "Lawyer",
        "role": "lawyer",
        "description": "Focuses on laws, regulations, rights, legal constraints, compliance, and policy implications.",
        "is_core": True,
    },
    {
        "name": "Scientist",
        "role": "scientist",
        "description": "Focuses on scientific research, evidence, methodology, causality, and uncertainty.",
        "is_core": True,
    },
    {
        "name": "Doctor",
        "role": "doctor",
        "description": "Focuses on health effects, medical evidence, public health, risks, and human impact.",
        "is_core": True,
    },
    {
        "name": "Ethicist",
        "role": "ethicist",
        "description": "Focuses on ethical implications, fairness, rights, moral principles, and social consequences.",
        "is_core": True,
    },
    {
        "name": "Analyst",
        "role": "analyst",
        "description": "Focuses on cross-domain comparison, trade-offs, risks, decision criteria, and synthesis.",
        "is_core": True,
    },
]


async def seed_agents(db: AsyncSession) -> None:
    for agent_data in CORE_AGENTS:
        result = await db.execute(select(Agent).where(Agent.name == agent_data["name"]))
        if not result.scalar_one_or_none():
            agent = Agent(**agent_data)
            db.add(agent)
    await db.commit()
