import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session
from app.services.seed import seed_agents


async def run_seed():
    async with async_session() as db:
        result = await db.execute(text("SELECT 1"))
        print("Database connection: OK")
        await seed_agents(db)
        print("Core agents seeded successfully")


if __name__ == "__main__":
    asyncio.run(run_seed())
