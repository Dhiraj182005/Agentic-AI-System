import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.database import async_session
from app.services.seed import seed_agents


async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        print(f"Health check: {data}")
        assert "status" in data
        assert "database" in data
        assert "redis" in data


async def test_database_connection():
    async with async_session() as db:
        result = await db.execute(__import__("sqlalchemy").text("SELECT 1"))
        assert result.scalar() == 1
        print("Database connection test: PASSED")


async def test_seed_agents():
    async with async_session() as db:
        await seed_agents(db)
        from sqlalchemy import select
        from app.models.agent import Agent
        result = await db.execute(select(Agent))
        agents = result.scalars().all()
        print(f"Seeded agents: {[a.name for a in agents]}")
        assert len(agents) == 6


async def main():
    print("Running tests...")
    await test_database_connection()
    await test_seed_agents()
    await test_health_endpoint()
    print("\nAll tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
