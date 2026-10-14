import asyncio
import importlib
import inspect
import os

import httpx
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.analyst import AnalystAgent
from app.agents.base_agent import BaseAgent
from app.agents.doctor import DoctorAgent
from app.agents.economist import EconomistAgent
from app.agents.ethicist import EthicistAgent
from app.agents.factory import (
    SUPPORTED_AGENT_ROLES,
    UnsupportedAgentError,
    get_agent_by_role,
)
from app.agents.lawyer import LawyerAgent
from app.agents.prompts.analyst import ANALYST_SYSTEM_PROMPT
from app.agents.prompts.doctor import DOCTOR_SYSTEM_PROMPT
from app.agents.prompts.economist import ECONOMIST_SYSTEM_PROMPT
from app.agents.prompts.ethicist import ETHICIST_SYSTEM_PROMPT
from app.agents.prompts.lawyer import LAWYER_SYSTEM_PROMPT
from app.agents.prompts.scientist import SCIENTIST_SYSTEM_PROMPT
from app.agents.role_based import RoleBasedAgent
from app.agents.scientist import ScientistAgent
from app.core.config import get_settings
from app.llm.base import (
    BaseLLMProvider,
    LLMConfigurationError,
    LLMMessage,
    LLMProviderAPIError,
    LLMResponse,
    LLMTimeoutError,
)
from app.llm.providers.groq_provider import GroqProvider

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test",
)

_test_engine = None
_test_session = None

AGENT_CLASSES = {
    "economist": (EconomistAgent, ECONOMIST_SYSTEM_PROMPT),
    "lawyer": (LawyerAgent, LAWYER_SYSTEM_PROMPT),
    "doctor": (DoctorAgent, DOCTOR_SYSTEM_PROMPT),
    "scientist": (ScientistAgent, SCIENTIST_SYSTEM_PROMPT),
    "ethicist": (EthicistAgent, ETHICIST_SYSTEM_PROMPT),
    "analyst": (AnalystAgent, ANALYST_SYSTEM_PROMPT),
}

AGENT_MODULES = [
    "app.agents.base_agent",
    "app.agents.role_based",
    "app.agents.factory",
    "app.agents.economist",
    "app.agents.lawyer",
    "app.agents.doctor",
    "app.agents.scientist",
    "app.agents.ethicist",
    "app.agents.analyst",
]

AGENT_PROMPT_MODULES = [
    "app.agents.prompts.economist",
    "app.agents.prompts.lawyer",
    "app.agents.prompts.doctor",
    "app.agents.prompts.scientist",
    "app.agents.prompts.ethicist",
    "app.agents.prompts.analyst",
]


def set_env(provider, api_key, model):
    os.environ["LLM_PROVIDER"] = provider
    os.environ["GROQ_API_KEY"] = api_key
    os.environ["GROQ_MODEL"] = model
    get_settings.cache_clear()


def clear_env():
    for var in ("LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL"):
        os.environ.pop(var, None)
    get_settings.cache_clear()


class FakeProvider(BaseLLMProvider):
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, error: Exception | None = None, response: str = "mock answer"):
        self.error = error
        self.response = response
        self.messages: list[LLMMessage] | None = None

    async def generate(self, messages, temperature=None, max_tokens=None):
        self.messages = list(messages)
        if self.error is not None:
            raise self.error
        return LLMResponse(
            content=self.response,
            provider=self.provider_name,
            model=self.model_name,
        )


async def test_each_agent_uses_its_system_prompt():
    for role, (agent_class, expected_prompt) in AGENT_CLASSES.items():
        provider = FakeProvider()
        agent = agent_class(llm_provider=provider)
        await agent.generate_response("Please analyze this topic.")
        assert provider.messages[0].content == expected_prompt, role
        assert provider.messages[1].content == "Please analyze this topic."
        print(f"{role} uses its role system prompt: PASSED")


async def test_each_agent_declares_identifier_role_name():
    for role, (agent_class, _) in AGENT_CLASSES.items():
        agent = agent_class(llm_provider=FakeProvider())
        assert agent.identifier == role
        assert agent.role == role.capitalize()
        assert agent.name == role.capitalize()
        print(f"{role} declares stable identifier and display values: PASSED")


async def test_factory_returns_each_agent():
    for role, (agent_class, _) in AGENT_CLASSES.items():
        agent = get_agent_by_role(role)
        assert isinstance(agent, agent_class)
        assert isinstance(agent, RoleBasedAgent)
        assert isinstance(agent, BaseAgent)
        print(f"factory returns {role.title()}Agent: PASSED")


async def test_factory_normalizes_role_input():
    agent = get_agent_by_role("  Economist ")
    assert isinstance(agent, EconomistAgent)
    print("factory normalizes role input case/whitespace: PASSED")


async def test_factory_rejects_unsupported_role():
    for bad in ("accountant", "judge", "other", "", "  "):
        try:
            get_agent_by_role(bad)
            assert False, f"expected UnsupportedAgentError for {bad!r}"
        except UnsupportedAgentError:
            pass
    print("unsupported role is rejected: PASSED")


async def test_factory_supported_roles_match_seed_roles():
    expected = {"economist", "lawyer", "doctor", "scientist", "ethicist", "analyst"}
    assert set(SUPPORTED_AGENT_ROLES) == expected
    print("factory supported roles match the six core agents: PASSED")


async def test_agents_use_base_agent_and_provider_abstraction():
    for role in SUPPORTED_AGENT_ROLES:
        agent = get_agent_by_role(role)
        assert isinstance(agent, BaseAgent)
        agent.llm_provider = FakeProvider()
        result = await agent.generate_response("Hello")
        assert isinstance(result, LLMResponse)
    print("agents communicate through BaseAgent / BaseLLMProvider abstraction: PASSED")


async def test_no_agent_imports_groq_sdk():
    for module_name in AGENT_MODULES + AGENT_PROMPT_MODULES:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module).lower()
        assert "groq" not in source, module_name
        print(f"{module_name}: no Groq SDK reference: PASSED")

    base_agent_source = inspect.getsource(
        importlib.import_module("app.agents.base_agent")
    )
    assert "app.llm.base" in base_agent_source
    print("app.agents.base_agent: uses provider abstraction (app.llm.base): PASSED")


async def test_responses_are_normalized():
    provider = FakeProvider()
    agent = get_agent_by_role("analyst")
    agent.llm_provider = provider
    result = await agent.generate_response("Analyze this.")
    assert isinstance(result, LLMResponse)
    assert result.content == "mock answer"
    assert result.provider == "fake"
    assert result.model == "fake-model"
    print("agent responses are normalized LLMResponse objects: PASSED")


async def test_base_agent_default_provider_from_factory():
    set_env("groq", "test-key", "llama-test")
    try:
        agent = get_agent_by_role("economist")
        assert isinstance(agent.llm_provider, GroqProvider)
    finally:
        clear_env()
    print("default provider resolves through the LLM factory (GroqProvider): PASSED")


async def setup_db():
    """Create a clean schema in the dedicated `aidebate_test` DB and override deps."""
    global _test_engine, _test_session

    _test_engine = create_async_engine(TEST_DB_URL)
    _test_session = async_sessionmaker(_test_engine, expire_on_commit=False)

    async with _test_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    from app.db.database import Base
    import app.models  # noqa: F401

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.db.database import get_db
    from app.main import app

    async def override_get_db():
        async with _test_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    return app


async def teardown_db():
    from app.main import app

    app.dependency_overrides.clear()
    if _test_engine is not None:
        await _test_engine.dispose()


def client_for(app):
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def register_and_login(client, email, password):
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    return resp.json()["access_token"]


def patch_llm_provider(provider):
    import app.agents.base_agent as base_agent_module

    original = base_agent_module.get_llm_provider
    base_agent_module.get_llm_provider = lambda: provider
    return original


def restore_llm_provider(original):
    import app.agents.base_agent as base_agent_module

    base_agent_module.get_llm_provider = original


async def test_endpoint_rejects_unauthenticated(client):
    resp = await client.post(
        "/api/v1/agents/test", json={"agent": "economist", "message": "Hello"}
    )
    assert resp.status_code == 401, resp.text
    print("endpoint rejects unauthenticated requests (401): PASSED")


async def test_endpoint_rejects_invalid_token(client):
    resp = await client.post(
        "/api/v1/agents/test",
        json={"agent": "economist", "message": "Hello"},
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert resp.status_code == 401, resp.text
    print("endpoint rejects invalid token (401): PASSED")


async def test_endpoint_works_with_authenticated_user(client):
    token = await register_and_login(client, "agent@example.com", "securepassword")
    provider = FakeProvider()
    original = patch_llm_provider(provider)
    try:
        resp = await client.post(
            "/api/v1/agents/test",
            json={"agent": "economist", "message": "Economic effects of EVs?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["agent"] == "economist"
    assert data["role"] == "Economist"
    assert data["response"] == "mock answer"
    assert data["provider"] == "fake"
    assert data["model"] == "fake-model"
    assert provider.messages is not None
    assert provider.messages[0].role == "system"
    assert provider.messages[0].content == ECONOMIST_SYSTEM_PROMPT
    assert provider.messages[1].content == "Economic effects of EVs?"
    print("endpoint executes exactly one agent with mocked provider: PASSED")


async def test_endpoint_rejects_empty_message(client):
    token = await register_and_login(client, "agent2@example.com", "securepassword")
    original = patch_llm_provider(FakeProvider())
    try:
        resp = await client.post(
            "/api/v1/agents/test",
            json={"agent": "economist", "message": "   "},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 422, resp.text
    print("endpoint rejects empty message (422): PASSED")


async def test_endpoint_rejects_missing_message(client):
    token = await register_and_login(client, "agent3@example.com", "securepassword")
    original = patch_llm_provider(FakeProvider())
    try:
        resp = await client.post(
            "/api/v1/agents/test",
            json={"agent": "economist"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 422, resp.text
    print("endpoint rejects missing message (422): PASSED")


async def test_endpoint_rejects_invalid_agent(client):
    token = await register_and_login(client, "agent4@example.com", "securepassword")
    original = patch_llm_provider(FakeProvider())
    try:
        resp = await client.post(
            "/api/v1/agents/test",
            json={"agent": "astrologer", "message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 404, resp.text
    print("endpoint rejects invalid agent (404): PASSED")


async def test_endpoint_provider_error_handled(client):
    token = await register_and_login(client, "agent5@example.com", "securepassword")
    original = patch_llm_provider(FakeProvider(error=LLMProviderAPIError("api-error")))
    try:
        resp = await client.post(
            "/api/v1/agents/test",
            json={"agent": "lawyer", "message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 502, resp.text
    assert "api-error" not in resp.text
    print("endpoint handles provider errors safely (502): PASSED")


async def main():
    print("Running Core Role-Based AI Agent tests...")

    await test_each_agent_uses_its_system_prompt()
    await test_each_agent_declares_identifier_role_name()
    await test_factory_returns_each_agent()
    await test_factory_normalizes_role_input()
    await test_factory_rejects_unsupported_role()
    await test_factory_supported_roles_match_seed_roles()
    await test_agents_use_base_agent_and_provider_abstraction()
    await test_no_agent_imports_groq_sdk()
    await test_responses_are_normalized()
    await test_base_agent_default_provider_from_factory()

    print("Setting up isolated test DB (aidebate_test)...")
    app = await setup_db()
    async with client_for(app) as client:
        await test_endpoint_rejects_unauthenticated(client)
        await test_endpoint_rejects_invalid_token(client)
        await test_endpoint_works_with_authenticated_user(client)
        await test_endpoint_rejects_empty_message(client)
        await test_endpoint_rejects_missing_message(client)
        await test_endpoint_rejects_invalid_agent(client)
        await test_endpoint_provider_error_handled(client)
    await teardown_db()

    clear_env()
    print("\nAll Core Role-Based AI Agent tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())