import asyncio
import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from groq import APIConnectionError, APITimeoutError, APIError
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.base_agent import BaseAgent, GENERIC_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.security import create_access_token
from app.llm.base import (
    BaseLLMProvider,
    LLMConfigurationError,
    LLMMessage,
    LLMProviderAPIError,
    LLMResponse,
    LLMTimeoutError,
)
from app.llm.factory import get_llm_provider, SUPPORTED_PROVIDERS
from app.llm.providers.groq_provider import GroqProvider

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test",
)

_test_engine = None
_test_session = None

_API_ERROR_MSG = "boom"
_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def set_env(provider, api_key, model, timeout="60"):
    os.environ["LLM_PROVIDER"] = provider
    os.environ["GROQ_API_KEY"] = api_key
    os.environ["GROQ_MODEL"] = model
    os.environ["LLM_TIMEOUT_SECONDS"] = timeout
    get_settings.cache_clear()


def clear_env():
    for var in ("LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "LLM_TIMEOUT_SECONDS"):
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


async def test_factory_returns_groq_provider():
    set_env("groq", "test-key", "llama-3.3-70b-versatile")
    try:
        provider = get_llm_provider()
        assert isinstance(provider, GroqProvider)
        assert provider.provider_name == "groq"
        assert provider.model_name == "llama-3.3-70b-versatile"
    finally:
        clear_env()
    print("factory returns GroqProvider for groq: PASSED")


async def test_factory_unsupported_provider():
    set_env("gemini", "test-key", "test-model")
    try:
        try:
            get_llm_provider()
            assert False, "expected LLMConfigurationError"
        except LLMConfigurationError as exc:
            assert "Unsupported LLM_PROVIDER" in str(exc)
            assert "groq" in str(exc)
    finally:
        clear_env()
    print("unsupported provider raises clear error: PASSED")


async def test_factory_unsupported_provider_empty():
    set_env("", "", "")
    try:
        try:
            get_llm_provider()
            assert False, "expected LLMConfigurationError"
        except LLMConfigurationError:
            pass
    finally:
        clear_env()
    print("empty LLM_PROVIDER raises clear error: PASSED")


async def test_missing_groq_api_key():
    set_env("groq", "", "llama-3.3-70b-versatile")
    try:
        try:
            GroqProvider()
            assert False, "expected LLMConfigurationError"
        except LLMConfigurationError as exc:
            assert "GROQ_API_KEY" in str(exc)
    finally:
        clear_env()
    print("missing GROQ_API_KEY is handled: PASSED")


async def test_missing_groq_model():
    set_env("groq", "test-key", "")
    try:
        try:
            GroqProvider()
            assert False, "expected LLMConfigurationError"
        except LLMConfigurationError as exc:
            assert "GROQ_MODEL" in str(exc)
    finally:
        clear_env()
    print("missing GROQ_MODEL is handled: PASSED")


class FakeChoices:
    pass


async def test_provider_returns_normalized_response():
    provider = GroqProvider(api_key="test-key", model="llama-test", timeout=30)

    class FakeMessage:
        content = "Hello from Groq."

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    create = AsyncMock(return_value=FakeCompletion())
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    result = await provider.generate([LLMMessage(role="user", content="hi")])
    assert result.content == "Hello from Groq."
    assert result.provider == "groq"
    assert result.model == "llama-test"

    sent = create.call_args.kwargs["messages"]
    assert sent == [{"role": "user", "content": "hi"}]
    assert create.call_args.kwargs["model"] == "llama-test"
    print("provider returns normalized LLMResponse: PASSED")


async def test_provider_timeout_handled():
    provider = GroqProvider(api_key="test-key", model="llama-test", timeout=1)
    create = AsyncMock(side_effect=APITimeoutError(request=_REQUEST))
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    try:
        await provider.generate([LLMMessage(role="user", content="hi")])
        assert False, "expected LLMTimeoutError"
    except LLMTimeoutError:
        pass
    print("provider timeout is handled safely: PASSED")


async def test_provider_api_error_handled():
    provider = GroqProvider(api_key="test-key", model="llama-test", timeout=1)
    create = AsyncMock(side_effect=APIError(_API_ERROR_MSG, request=_REQUEST, body=None))
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    try:
        await provider.generate([LLMMessage(role="user", content="hi")])
        assert False, "expected LLMProviderAPIError"
    except LLMProviderAPIError:
        pass
    print("provider API error is handled safely: PASSED")


async def test_provider_connection_error_handled():
    provider = GroqProvider(api_key="test-key", model="llama-test", timeout=1)
    create = AsyncMock(side_effect=APIConnectionError(request=_REQUEST))
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    try:
        await provider.generate([LLMMessage(role="user", content="hi")])
        assert False, "expected LLMProviderAPIError"
    except LLMProviderAPIError:
        pass
    print("provider connection error is handled safely: PASSED")


async def test_base_agent_sends_system_prompt_and_user_message():
    provider = FakeProvider()
    agent = BaseAgent(llm_provider=provider)
    await agent.generate_response("Please explain.")
    roles = [m.role for m in provider.messages]
    assert roles == ["system", "user"]
    assert provider.messages[0].content == GENERIC_SYSTEM_PROMPT
    assert provider.messages[1].content == "Please explain."
    print("BaseAgent sends system prompt and user message: PASSED")


async def test_base_agent_custom_system_prompt():
    provider = FakeProvider()
    agent = BaseAgent(llm_provider=provider, system_prompt="Custom system prompt here.")
    await agent.generate_response("Hello")
    assert provider.messages[0].content == "Custom system prompt here."
    print("BaseAgent supports custom system prompt: PASSED")


async def test_base_agent_uses_provider_abstraction():
    provider = FakeProvider()
    agent = BaseAgent(llm_provider=provider)
    result = await agent.generate_response("Hello")
    assert isinstance(result, LLMResponse)
    assert provider.messages is not None
    print("BaseAgent communicates through BaseLLMProvider abstraction: PASSED")


async def test_base_agent_does_not_depend_on_groq_sdk():
    import app.agents.base_agent as base_agent_module

    source = inspect.getsource(base_agent_module).lower()
    assert "groq" not in source
    assert "app.llm.base" in inspect.getsource(base_agent_module)
    print("BaseAgent does not require Groq SDK: PASSED")


async def test_base_agent_default_provider_from_factory():
    set_env("groq", "test-key", "llama-test")
    try:
        agent = BaseAgent()
        assert isinstance(agent.llm_provider, GroqProvider)
    finally:
        clear_env()
    print("BaseAgent resolves provider via factory: PASSED")


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
    resp = await client.post("/api/v1/ai/test", json={"message": "Hello"})
    assert resp.status_code == 401, resp.text
    print("endpoint rejects unauthenticated users (401): PASSED")


async def test_endpoint_rejects_invalid_token(client):
    resp = await client.post(
        "/api/v1/ai/test",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert resp.status_code == 401, resp.text
    print("endpoint rejects invalid token (401): PASSED")


async def test_endpoint_accepts_authenticated_user(client):
    token = await register_and_login(client, "ai@example.com", "securepassword")
    provider = FakeProvider()
    original = patch_llm_provider(provider)
    try:
        resp = await client.post(
            "/api/v1/ai/test",
            json={"message": "Explain renewable energy."},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["response"] == "mock answer"
    assert data["provider"] == "fake"
    assert data["model"] == "fake-model"
    assert provider.messages is not None
    assert provider.messages[0].role == "system"
    assert provider.messages[1].content == "Explain renewable energy."
    print("endpoint accepts authenticated user with mocked provider: PASSED")


async def test_endpoint_rejects_invalid_input(client):
    token = await register_and_login(client, "ai2@example.com", "securepassword")
    provider = FakeProvider()
    original = patch_llm_provider(provider)
    try:
        resp = await client.post(
            "/api/v1/ai/test",
            json={"message": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 422, resp.text
    print("endpoint rejects invalid request input (422): PASSED")


async def test_endpoint_missing_body(client):
    token = await register_and_login(client, "ai3@example.com", "securepassword")
    original = patch_llm_provider(FakeProvider())
    try:
        resp = await client.post(
            "/api/v1/ai/test",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 422, resp.text
    print("endpoint rejects missing message body (422): PASSED")


async def test_endpoint_provider_api_error(client):
    token = await register_and_login(client, "ai4@example.com", "securepassword")
    original = patch_llm_provider(FakeProvider(error=LLMProviderAPIError("api-error")))
    try:
        resp = await client.post(
            "/api/v1/ai/test",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 502, resp.text
    assert "GROQ_API_KEY" not in resp.text and "api-error" not in resp.text
    print("provider API error handled safely (502): PASSED")


async def test_endpoint_provider_timeout(client):
    token = await register_and_login(client, "ai5@example.com", "securepassword")
    original = patch_llm_provider(FakeProvider(error=LLMTimeoutError("timeout")))
    try:
        resp = await client.post(
            "/api/v1/ai/test",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        restore_llm_provider(original)
    assert resp.status_code == 504, resp.text
    print("provider timeout handled safely (504): PASSED")


async def test_endpoint_configuration_error(client):
    token = await register_and_login(client, "ai6@example.com", "securepassword")

    import app.agents.base_agent as base_agent_module

    original = base_agent_module.get_llm_provider

    def raise_config_error():
        raise LLMConfigurationError("cfg")

    base_agent_module.get_llm_provider = raise_config_error
    try:
        resp = await client.post(
            "/api/v1/ai/test",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        base_agent_module.get_llm_provider = original
    assert resp.status_code == 500, resp.text
    data = resp.json()
    assert data["detail"] == "The LLM provider is not configured correctly."
    print("provider configuration error handled safely (500): PASSED")


async def main():
    print("Running LLM / BaseAgent tests...")

    await test_factory_returns_groq_provider()
    await test_factory_unsupported_provider()
    await test_factory_unsupported_provider_empty()
    await test_missing_groq_api_key()
    await test_missing_groq_model()
    await test_provider_returns_normalized_response()
    await test_provider_timeout_handled()
    await test_provider_api_error_handled()
    await test_provider_connection_error_handled()
    await test_base_agent_sends_system_prompt_and_user_message()
    await test_base_agent_custom_system_prompt()
    await test_base_agent_uses_provider_abstraction()
    await test_base_agent_does_not_depend_on_groq_sdk()
    await test_base_agent_default_provider_from_factory()

    print("Setting up isolated test DB (aidebate_test)...")
    app = await setup_db()
    async with client_for(app) as client:
        await test_endpoint_rejects_unauthenticated(client)
        await test_endpoint_rejects_invalid_token(client)
        await test_endpoint_accepts_authenticated_user(client)
        await test_endpoint_rejects_invalid_input(client)
        await test_endpoint_missing_body(client)
        await test_endpoint_provider_api_error(client)
        await test_endpoint_provider_timeout(client)
        await test_endpoint_configuration_error(client)
    await teardown_db()

    clear_env()
    print("\nAll LLM / BaseAgent tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())