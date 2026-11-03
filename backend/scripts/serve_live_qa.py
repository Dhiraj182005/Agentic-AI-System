"""Local browser QA only: isolated test database, deliberately mocked providers.

Never imported by the application. Run migrations first and explicitly enable
the local demo account. Refuses application databases and configured API keys.
"""
import asyncio
from urllib.parse import urlparse
from unittest.mock import patch

import httpx
import uvicorn

from app.core.config import get_settings
from app.db.database import async_session, engine
from app.llm.base import LLMResponse
from app.main import app
from app.services.demo_account import ensure_demo_account
from app.services.seed import seed_agents
from tests.test_analysis_pipeline import ExtractionLLM, providers


class SlowClaims(ExtractionLLM):
    async def generate(self, *args, **kwargs):
        await asyncio.sleep(5)
        return await super().generate(*args, **kwargs)


class TurnProvider:
    async def generate(self, messages, **kwargs):
        await asyncio.sleep(5)
        return LLMResponse(content="[QA mock] Teen social media use rose 10 percent. "
            "Regulation merits scrutiny, while free expression and implementation costs require consideration.",
            provider="local-qa-mock", model="local-qa-mock")


async def prepare():
    async with async_session() as db:
        await seed_agents(db)
        await ensure_demo_account(db)
    settings = get_settings()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://qa") as client:
        login = await client.post('/api/v1/auth/login', json={"email": settings.DEMO_ACCOUNT_EMAIL,
                                                            "password": settings.DEMO_ACCOUNT_PASSWORD})
        login.raise_for_status()
        response = await client.post('/api/v1/debates', headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={"topic": "[QA MOCK] Should governments regulate social media?", "agent_ids": ["economist", "lawyer"],
                  "total_rounds": 3, "mode": "balanced", "expert_selection_mode": "manual", "verify_evidence": True})
        response.raise_for_status()
        print("Isolated QA debate:", response.json()["id"], flush=True)
    await engine.dispose()


if __name__ == '__main__':
    settings = get_settings()
    if not urlparse(settings.DATABASE_URL).path.lstrip('/').startswith('maves_audit_test_'):
        raise SystemExit('Refusing a non-test database')
    if any((settings.GROQ_API_KEY, settings.TAVILY_API_KEY, settings.GOOGLE_FACT_CHECK_API_KEY)):
        raise SystemExit('Blank external API keys for browser QA')
    asyncio.run(prepare())
    with providers(extraction=SlowClaims()), patch('app.agents.base_agent.get_llm_provider', return_value=TurnProvider()):
        uvicorn.run(app, host='0.0.0.0', port=8000)
