import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session
from app.services.demo_account import DemoAccountError, ensure_demo_account
from app.services.seed import seed_agents


async def run_seed(with_demo: bool = False):
    async with async_session() as db:
        result = await db.execute(text("SELECT 1"))
        print("Database connection: OK")
        await seed_agents(db)
        print("Core agents seeded successfully")
        if with_demo:
            try:
                user = await ensure_demo_account(db)
            except DemoAccountError as exc:
                print(f"Demo account not created: {exc}")
                sys.exit(1)
            print(f"Demo account ready: {user.email}")


if __name__ == "__main__":
    # `python seed.py --demo` also creates/updates the optional demo account
    # (requires DEMO_ACCOUNT_ENABLED=true and the demo credentials).
    asyncio.run(run_seed(with_demo="--demo" in sys.argv[1:]))
