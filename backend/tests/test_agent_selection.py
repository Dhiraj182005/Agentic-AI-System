"""Topic-aware automatic agent selection tests.

The LLM is always mocked (FakeLLM or a failing provider) — no real Groq API
key is required. Covers the 15 cases from the improvement spec: domain
quality via the deterministic fallback, validation of LLM output against the
database, dedupe, minimum-agent rules, fallback on failure, authentication,
creation persistence and manual selection. Frontend behavior is covered by
the companion E2E script (agent_selection.e2e.js).
"""

import asyncio
import json
import os
import unittest.mock
import uuid

from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.llm.base import LLMProviderAPIError, LLMResponse
from app.models.agent import Agent

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test",
)

_test_engine = None
_test_session = None


async def setup():
    """Create a clean schema in the dedicated `aidebate_test` DB and override deps."""
    global _test_engine, _test_session

    _test_engine = create_async_engine(TEST_DB_URL)
    _test_session = async_sessionmaker(_test_engine, expire_on_commit=False)

    async with _test_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    from app.db.database import Base
    import app.models  # noqa: F401  (register models)

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.services.seed import seed_agents

    async with _test_session() as session:
        await seed_agents(session)

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


async def teardown():
    from app.main import app

    app.dependency_overrides.clear()
    if _test_engine is not None:
        await _test_engine.dispose()


def client_for(app):
    transport = ASGITransport(app=app)
    import httpx

    return httpx.AsyncClient(transport=transport, base_url="http://test")


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def register_and_login(client, email, password="securepassword"):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


class FakeLLM:
    """LLM provider stand-in returning a fixed content string."""

    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    async def generate(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        return LLMResponse(content=self.content, provider="fake", model="fake-model")


class FailingLLM:
    """Provider stand-in that fails like a broken Groq connection."""

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        raise LLMProviderAPIError("provider unavailable")


def patch_provider(provider):
    return unittest.mock.patch(
        "app.services.agent_selection.get_llm_provider", return_value=provider
    )


async def recommend(client, token, topic):
    return await client.post(
        "/api/v1/debates/recommend-agents",
        json={"topic": topic},
        headers=auth(token),
    )


async def agent_index(client, token) -> dict:
    """Map role -> id for the active core agents."""
    resp = await client.get("/api/v1/agents", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return {agent["role"]: agent["id"] for agent in resp.json()}


async def set_agent_active(role: str, active: bool) -> None:
    async with _test_session() as session:
        result = await session.execute(select(Agent).where(Agent.role == role))
        agent = result.scalar_one()
        agent.is_active = active
        await session.commit()


def selection_payload(entries: list[dict]) -> str:
    return json.dumps({"agents": entries})


# ---------------------------------------------------------------------------
# 1-5. Domain quality of the deterministic fallback (LLM down)
# ---------------------------------------------------------------------------

MEDICAL_TOPIC = (
    "Should hospitals use AI to diagnose patients when the medical evidence "
    "is uncertain?"
)
LEGAL_TOPIC = "Do data privacy laws and court rulings regulate technology companies?"
ECON_TOPIC = "Will inflation and tax policy hurt the housing market and jobs?"
TECH_TOPIC = (
    "Should algorithmic software and digital automation run public "
    "technology services?"
)
BROAD_TOPIC = "Should governments do more?"


async def _fallback_roles(client, token, topic) -> tuple[list[str], str, int]:
    provider = FailingLLM()
    with patch_provider(provider):
        resp = await recommend(client, token, topic)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert provider.calls == 1, "the provider must be tried before falling back"
    assert data["selection_source"] == "fallback", data
    roles = [agent["role"] for agent in data["agents"]]
    return roles, data["selection_source"], len(data["agents"])


async def test_medical_topic_selects_relevant_agents(client):
    token = await register_and_login(client, unique_email("med"))
    roles, _, _ = await _fallback_roles(client, token, MEDICAL_TOPIC)
    assert "doctor" in roles, roles
    assert "scientist" in roles, roles
    assert roles[0] == "doctor", roles
    print("medical topic selects doctor + scientist: PASSED")


async def test_legal_topic_prioritizes_legal_expertise(client):
    token = await register_and_login(client, unique_email("legal"))
    roles, _, _ = await _fallback_roles(client, token, LEGAL_TOPIC)
    assert roles[0] == "lawyer", roles
    assert "lawyer" in roles, roles
    print("legal topic prioritizes the lawyer: PASSED")


async def test_economic_topic_prioritizes_economic_expertise(client):
    token = await register_and_login(client, unique_email("econ"))
    roles, _, _ = await _fallback_roles(client, token, ECON_TOPIC)
    assert roles[0] == "economist", roles
    assert len(roles) < 6, roles
    print("economic topic prioritizes the economist: PASSED")


async def test_technology_topic_selects_technical_experts(client):
    token = await register_and_login(client, unique_email("tech"))
    roles, _, _ = await _fallback_roles(client, token, TECH_TOPIC)
    assert "scientist" in roles, roles
    assert roles[0] == "scientist", roles
    print("technology topic selects the scientist: PASSED")


async def test_broad_topic_selects_balanced_experts(client):
    token = await register_and_login(client, unique_email("broad"))
    roles, _, count = await _fallback_roles(client, token, BROAD_TOPIC)
    assert count >= 2, roles
    assert "analyst" in roles and "ethicist" in roles, roles
    assert count < 6, "a broad topic must not silently select every agent"
    print("broad topic selects a balanced minimum pair: PASSED")


# ---------------------------------------------------------------------------
# 6-7. Endpoint validation and authentication
# ---------------------------------------------------------------------------


async def test_invalid_topic_rejected(client):
    token = await register_and_login(client, unique_email("badtopic"))
    for bad in ("", "   "):
        resp = await recommend(client, token, bad)
        assert resp.status_code == 422, (bad, resp.status_code, resp.text)
    print("invalid topics rejected with 422: PASSED")


async def test_recommendation_requires_authentication(client):
    resp = await client.post(
        "/api/v1/debates/recommend-agents", json={"topic": ECON_TOPIC}
    )
    assert resp.status_code == 401, resp.text
    print("recommendation requires authentication: PASSED")


# ---------------------------------------------------------------------------
# 8-10. Validation of LLM output against the database
# ---------------------------------------------------------------------------


async def test_inactive_agents_never_selected(client):
    token = await register_and_login(client, unique_email("inactive"))
    ids = await agent_index(client, token)
    try:
        await set_agent_active("doctor", False)
        fake = FakeLLM(
            selection_payload(
                [
                    {"id": ids["doctor"], "role": "doctor", "reason": "Still here?"},
                    {"id": ids["lawyer"], "role": "lawyer", "reason": "Liability."},
                    {"id": ids["economist"], "role": "economist", "reason": "Costs."},
                ]
            )
        )
        with patch_provider(fake):
            resp = await recommend(client, token, "A debate about medical liability.")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        roles = {agent["role"] for agent in data["agents"]}
        assert "doctor" not in roles, roles
        assert roles == {"lawyer", "economist"}, roles
        assert data["selection_source"] == "llm", data
    finally:
        await set_agent_active("doctor", True)
    print("inactive agents are never selected: PASSED")


async def test_unknown_and_mismatched_ids_rejected(client):
    token = await register_and_login(client, unique_email("unknown"))
    ids = await agent_index(client, token)
    fake = FakeLLM(
        selection_payload(
            [
                {
                    "id": str(uuid.uuid4()),
                    "role": "lawyer",
                    "reason": "Wrong id on purpose.",
                },
                {"id": ids["doctor"], "role": "doctor", "reason": "Patient care."},
                {"id": ids["scientist"], "role": "scientist", "reason": "Evidence."},
                {
                    "id": ids["economist"],
                    "role": "astronaut",
                    "reason": "Unknown role.",
                },
            ]
        )
    )
    with patch_provider(fake):
        resp = await recommend(client, token, "Hospital research costs.")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    roles = [agent["role"] for agent in data["agents"]]
    assert roles == ["doctor", "scientist"], roles
    print("unknown roles and mismatched agent ids are rejected: PASSED")


async def test_duplicate_selections_are_removed(client):
    token = await register_and_login(client, unique_email("dupe"))
    ids = await agent_index(client, token)
    fake = FakeLLM(
        selection_payload(
            [
                {"id": ids["lawyer"], "role": "lawyer", "reason": "First."},
                {"id": ids["lawyer"], "role": "LAWYER", "reason": "Duplicate."},
                {"id": ids["economist"], "role": "economist", "reason": "Costs."},
            ]
        )
    )
    with patch_provider(fake):
        resp = await recommend(client, token, "Legal costs of regulation.")
    assert resp.status_code == 200, resp.text
    roles = [agent["role"] for agent in resp.json()["agents"]]
    assert roles == ["lawyer", "economist"], roles
    print("duplicate selections are removed: PASSED")


# ---------------------------------------------------------------------------
# 11. Minimum-agent validation
# ---------------------------------------------------------------------------


async def test_insufficient_active_agents_returns_clear_error(client):
    token = await register_and_login(client, unique_email("few"))
    deactivated = ["economist", "lawyer", "doctor", "scientist", "ethicist"]
    try:
        for role in deactivated:
            await set_agent_active(role, False)
        resp = await recommend(client, token, ECON_TOPIC)
        assert resp.status_code == 400, (resp.status_code, resp.text)
        detail = resp.json()["detail"]
        assert "Not enough active core agents" in detail, detail
    finally:
        for role in deactivated:
            await set_agent_active(role, True)
    print("insufficient active agents returns a clear 400: PASSED")


# ---------------------------------------------------------------------------
# 12-13. Fallback on provider failure and invalid structured output
# ---------------------------------------------------------------------------


async def test_deterministic_fallback_when_llm_fails(client):
    token = await register_and_login(client, unique_email("fb"))
    roles, source, count = await _fallback_roles(client, token, ECON_TOPIC)
    assert source == "fallback"
    assert "economist" in roles, roles
    assert count < 6, "the fallback must not select every agent"
    print("deterministic fallback when the LLM fails: PASSED")


async def test_invalid_structured_output_falls_back(client):
    token = await register_and_login(client, unique_email("badjson"))
    payloads = [
        "this is not json at all",
        '{"agents": "not-a-list"}',
        '{"agents": [{"role": "nobody"}, {"role": "ghost"}]}',
    ]
    for payload in payloads:
        fake = FakeLLM(payload)
        with patch_provider(fake):
            resp = await recommend(client, token, "Should cities ban private cars?")
        assert resp.status_code == 200, (payload, resp.status_code, resp.text)
        data = resp.json()
        assert data["selection_source"] == "fallback", (payload, data)
        assert len(data["agents"]) >= 2, (payload, data)
        assert all(
            agent["role"] in {"economist", "lawyer", "doctor", "scientist", "ethicist", "analyst"}
            for agent in data["agents"]
        ), data
    print("invalid structured LLM output falls back safely: PASSED")


# ---------------------------------------------------------------------------
# 13-14. Creation integration and manual selection
# ---------------------------------------------------------------------------


async def test_debate_creation_persists_recommended_agents(client):
    token = await register_and_login(client, unique_email("persist"))
    ids = await agent_index(client, token)
    fake = FakeLLM(
        selection_payload(
            [
                {"id": ids["economist"], "role": "economist", "reason": "Costs."},
                {"id": ids["lawyer"], "role": "lawyer", "reason": "Regulation."},
            ]
        )
    )
    with patch_provider(fake):
        resp = await recommend(client, token, "Who should pay for regulation?")
    assert resp.status_code == 200, resp.text
    recommended = [agent["role"] for agent in resp.json()["agents"]]
    assert recommended == ["economist", "lawyer"], recommended

    create = await client.post(
        "/api/v1/debates",
        json={
            "topic": "Who should pay for regulation?",
            "expert_selection_mode": "auto",
            "agent_ids": recommended,
            "mode": "balanced",
            "total_rounds": 1,
            "verify_evidence": False,
        },
        headers=auth(token),
    )
    assert create.status_code == 201, create.text
    stored = [agent["role"] for agent in create.json()["agents"]]
    assert stored == recommended, (stored, recommended)
    print("debate creation persists exactly the recommended agents: PASSED")


async def test_manual_selection_still_works(client):
    token = await register_and_login(client, unique_email("manual"))
    create = await client.post(
        "/api/v1/debates",
        json={
            "topic": "Manual selection must keep working.",
            "expert_selection_mode": "manual",
            "agent_ids": ["economist", "lawyer"],
            "mode": "balanced",
            "total_rounds": 1,
            "verify_evidence": False,
        },
        headers=auth(token),
    )
    assert create.status_code == 201, create.text
    roles = {agent["role"] for agent in create.json()["agents"]}
    assert roles == {"economist", "lawyer"}, roles
    print("manual selection still works: PASSED")


async def test_creation_fallback_never_calls_the_llm(client):
    calls: list[str] = []

    def guard(*args, **kwargs):
        calls.append("get_llm_provider")
        raise RuntimeError("LLM must not be used during debate creation")

    token = await register_and_login(client, unique_email("nollm2"))
    with unittest.mock.patch(
        "app.services.agent_selection.get_llm_provider", side_effect=guard
    ):
        create = await client.post(
            "/api/v1/debates",
            json={
                "topic": "Should budget spending increase?",
                "expert_selection_mode": "auto",
                "agent_ids": [],
                "mode": "balanced",
                "total_rounds": 1,
                "verify_evidence": False,
            },
            headers=auth(token),
        )
    assert create.status_code == 201, create.text
    assert calls == [], f"creation must not call the LLM: {calls}"
    roles = {agent["role"] for agent in create.json()["agents"]}
    assert len(roles) >= 2, roles
    print("creation-time fallback never calls the LLM: PASSED")


async def main():
    print("Setting up isolated test DB (aidebate_test)...")
    app = await setup()

    async with client_for(app) as client:
        await test_medical_topic_selects_relevant_agents(client)
        await test_legal_topic_prioritizes_legal_expertise(client)
        await test_economic_topic_prioritizes_economic_expertise(client)
        await test_technology_topic_selects_technical_experts(client)
        await test_broad_topic_selects_balanced_experts(client)
        await test_invalid_topic_rejected(client)
        await test_recommendation_requires_authentication(client)
        await test_inactive_agents_never_selected(client)
        await test_unknown_and_mismatched_ids_rejected(client)
        await test_duplicate_selections_are_removed(client)
        await test_insufficient_active_agents_returns_clear_error(client)
        await test_deterministic_fallback_when_llm_fails(client)
        await test_invalid_structured_output_falls_back(client)
        await test_debate_creation_persists_recommended_agents(client)
        await test_manual_selection_still_works(client)
        await test_creation_fallback_never_calls_the_llm(client)

    await teardown()
    print("\nAll topic-aware agent selection tests PASSED!")

    print("\nRegression: Module 3 (debate creation + agent selection)...")
    from tests import test_debates

    await test_debates.main()


if __name__ == "__main__":
    asyncio.run(main())
