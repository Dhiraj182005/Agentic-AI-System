import asyncio
import os
import uuid

import httpx
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.agent import Agent
from app.models.debate import Debate
from app.models.debate_agent import DebateAgent
from app.services.debate_service import INITIAL_DEBATE_STATUS

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


def base_payload(**overrides) -> dict:
    payload = {
        "topic": "Should governments regulate generative AI?",
        "expert_selection_mode": "manual",
        "agent_ids": ["economist", "lawyer"],
        "domain_tags": ["technology", "policy"],
        "mode": "balanced",
        "total_rounds": 3,
        "verify_evidence": False,
    }
    payload.update(overrides)
    return payload


async def create_debate(client, token, **overrides):
    return await client.post(
        "/api/v1/debates", json=base_payload(**overrides), headers=auth(token)
    )


async def current_user_id(client, token) -> uuid.UUID:
    resp = await client.get("/api/v1/auth/me", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return uuid.UUID(resp.json()["id"])


async def debate_rows(user_id) -> list:
    async with _test_session() as db:
        result = await db.execute(select(Debate).where(Debate.user_id == user_id))
        return list(result.scalars().all())


async def association_rows(debate_id) -> list:
    async with _test_session() as db:
        result = await db.execute(
            select(DebateAgent).where(DebateAgent.debate_id == debate_id)
        )
        return list(result.scalars().all())


async def core_agent_roles() -> set:
    async with _test_session() as db:
        result = await db.execute(
            select(Agent.role).where(Agent.is_core.is_(True), Agent.is_active.is_(True))
        )
        return set(result.scalars().all())


# ---------------------------------------------------------------------------
# 1. authentication
# ---------------------------------------------------------------------------


async def test_create_debate_authenticated(client):
    token = await register_and_login(client, unique_email("auth"))
    resp = await create_debate(client, token)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["topic"] == "Should governments regulate generative AI?"
    assert data["expert_selection_mode"] == "manual"
    assert data["domain_tags"] == ["technology", "policy"]
    assert data["mode"] == "balanced"
    assert data["total_rounds"] == 3
    assert data["verify_evidence"] is False
    assert len(data["agents"]) == 2
    assert {a["role"] for a in data["agents"]} == {"economist", "lawyer"}
    assert "id" in data and "created_at" in data
    assert "password_hash" not in str(data)
    print("authenticated user can create debate (201): PASSED")


async def test_create_debate_unauthenticated(client):
    resp = await client.post("/api/v1/debates", json=base_payload())
    assert resp.status_code == 401, resp.text
    print("unauthenticated user cannot create debate (401): PASSED")


# ---------------------------------------------------------------------------
# 2. topic validation
# ---------------------------------------------------------------------------


async def test_topic_is_required(client):
    token = await register_and_login(client, unique_email("topic"))
    payload = base_payload()
    del payload["topic"]
    resp = await client.post("/api/v1/debates", json=payload, headers=auth(token))
    assert resp.status_code == 422, resp.text
    print("topic is required (422): PASSED")


async def test_empty_topic_rejected(client):
    token = await register_and_login(client, unique_email("emptytopic"))
    resp = await create_debate(client, token, topic="   ")
    assert resp.status_code == 422, resp.text
    resp = await create_debate(client, token, topic="")
    assert resp.status_code == 422, resp.text
    print("empty/whitespace topic rejected (422): PASSED")


# ---------------------------------------------------------------------------
# 3. agent selection validation
# ---------------------------------------------------------------------------


async def test_single_agent_rejected(client):
    token = await register_and_login(client, unique_email("oneagent"))
    resp = await create_debate(client, token, agent_ids=["economist"])
    assert resp.status_code == 422, resp.text
    resp = await create_debate(client, token, agent_ids=[])
    assert resp.status_code == 422, resp.text
    print("one (or zero) selected agent rejected (422): PASSED")


async def test_two_valid_agents_accepted(client):
    token = await register_and_login(client, unique_email("twoagents"))
    resp = await create_debate(client, token, agent_ids=["economist", "lawyer"])
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["agents"]) == 2
    print("two valid agents accepted (201): PASSED")


async def test_duplicate_agent_rejected(client):
    token = await register_and_login(client, unique_email("dupes"))
    resp = await create_debate(
        client, token, agent_ids=["economist", "economist", "lawyer"]
    )
    assert resp.status_code == 422, resp.text
    print("duplicate agent rejected (422): PASSED")


async def test_unknown_agent_rejected(client):
    token = await register_and_login(client, unique_email("unknown"))
    resp = await create_debate(client, token, agent_ids=["economist", "not-an-agent"])
    assert resp.status_code == 400, resp.text
    assert "not-an-agent" in resp.json()["detail"]
    print("unknown agent rejected (400): PASSED")


async def test_inactive_agent_rejected(client):
    token = await register_and_login(client, unique_email("inactive"))
    async with _test_session() as db:
        await db.execute(text("UPDATE agents SET is_active = false WHERE role = 'lawyer'"))
        await db.commit()
    try:
        resp = await create_debate(client, token, agent_ids=["economist", "lawyer"])
        assert resp.status_code == 400, resp.text
        assert "lawyer" in resp.json()["detail"]
    finally:
        async with _test_session() as db:
            await db.execute(text("UPDATE agents SET is_active = true WHERE role = 'lawyer'"))
            await db.commit()
    print("inactive agent rejected (400): PASSED")


async def test_non_core_agent_rejected(client):
    token = await register_and_login(client, unique_email("noncore"))
    async with _test_session() as db:
        db.add(
            Agent(
                name="Guest",
                role="guest",
                description="Not a core agent.",
                is_core=False,
                is_active=True,
            )
        )
        await db.commit()
    try:
        resp = await create_debate(client, token, agent_ids=["economist", "guest"])
        assert resp.status_code == 400, resp.text
        assert "guest" in resp.json()["detail"]
    finally:
        async with _test_session() as db:
            await db.execute(text("DELETE FROM agents WHERE role = 'guest'"))
            await db.commit()
    print("non-core agent rejected (400): PASSED")


# ---------------------------------------------------------------------------
# 4. selection modes
# ---------------------------------------------------------------------------


async def test_manual_selection_stores_selected_agents(client):
    token = await register_and_login(client, unique_email("manual"))
    selected = ["scientist", "ethicist", "analyst"]
    resp = await create_debate(client, token, agent_ids=selected)
    assert resp.status_code == 201, resp.text
    debate_id = uuid.UUID(resp.json()["id"])

    rows = await association_rows(debate_id)
    assert len(rows) == 3
    assert len({row.agent_id for row in rows}) == 3
    assert all(row.debate_id == debate_id for row in rows)

    async with _test_session() as db:
        result = await db.execute(
            select(Agent.role).where(Agent.id.in_([row.agent_id for row in rows]))
        )
        stored = set(result.scalars().all())
    assert stored == set(selected)
    assert {a["role"] for a in resp.json()["agents"]} == set(selected)
    print("manual selection stores selected agents: PASSED")


async def test_auto_mode_selects_all_active_core_agents(client):
    token = await register_and_login(client, unique_email("auto"))
    resp = await create_debate(client, token, expert_selection_mode="auto")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    expected = await core_agent_roles()
    assert len(expected) == 6
    assert {a["role"] for a in data["agents"]} == expected
    assert data["expert_selection_mode"] == "auto"
    print("auto mode selects all active core agents: PASSED")


# ---------------------------------------------------------------------------
# 5. status, associations and LLM isolation
# ---------------------------------------------------------------------------


async def test_debate_status_is_initial_not_started(client):
    token = await register_and_login(client, unique_email("status"))
    resp = await create_debate(client, token)
    assert resp.status_code == 201, resp.text
    status_value = resp.json()["status"]
    # The existing debate_status_enum keeps "pending" for a debate that was
    # created, stored and is waiting, but has not started executing yet.
    assert status_value == INITIAL_DEBATE_STATUS
    assert status_value in {"pending", "created", "draft"}
    assert status_value not in {"running", "completed"}
    print(f"debate status is the initial not-started state ({status_value}): PASSED")


async def test_debate_creation_does_not_call_llm(client):
    import app.agents.base_agent as base_agent_module
    import app.agents.factory as agents_factory
    import app.llm.factory as llm_factory
    import app.llm.providers.groq_provider as groq_provider

    calls: list[str] = []

    def guard(name):
        def _guarded(*args, **kwargs):
            calls.append(name)
            raise RuntimeError(f"unexpected LLM call during debate creation: {name}")

        return _guarded

    originals = {
        (agents_factory, "get_agent_by_role"): agents_factory.get_agent_by_role,
        (base_agent_module, "get_llm_provider"): base_agent_module.get_llm_provider,
        (llm_factory, "get_llm_provider"): llm_factory.get_llm_provider,
        (groq_provider, "AsyncGroq"): groq_provider.AsyncGroq,
    }
    for (module, attr) in originals:
        setattr(module, attr, guard(f"{module.__name__}.{attr}"))

    try:
        token = await register_and_login(client, unique_email("nollm"))
        resp = await create_debate(client, token, expert_selection_mode="auto")
        assert resp.status_code == 201, resp.text
        detail = await client.get(
            f"/api/v1/debates/{resp.json()['id']}", headers=auth(token)
        )
        assert detail.status_code == 200, detail.text
        listing = await client.get("/api/v1/debates", headers=auth(token))
        assert listing.status_code == 200, listing.text
    finally:
        for (module, attr), value in originals.items():
            setattr(module, attr, value)

    assert calls == [], f"LLM/agent access happened during debate creation: {calls}"
    print("debate creation does NOT call Groq / any LLM: PASSED")


async def test_debate_agent_associations_are_stored(client):
    token = await register_and_login(client, unique_email("assoc"))
    resp = await create_debate(client, token, agent_ids=["economist", "doctor"])
    assert resp.status_code == 201, resp.text
    debate_id = uuid.UUID(resp.json()["id"])

    rows = await association_rows(debate_id)
    assert len(rows) == 2
    pairs = [(row.debate_id, row.agent_id) for row in rows]
    assert len(pairs) == len(set(pairs)) == 2
    assert all(row.debate_id == debate_id for row in rows)

    user_id = await current_user_id(client, token)
    stored = await debate_rows(user_id)
    assert len(stored) == 1
    assert stored[0].id == debate_id
    print("debate-agent associations stored correctly (no duplicates): PASSED")


# ---------------------------------------------------------------------------
# 6. ownership
# ---------------------------------------------------------------------------


async def test_user_lists_own_debates(client):
    token_a = await register_and_login(client, unique_email("owner"))
    await create_debate(client, token_a, topic="First topic")
    await create_debate(client, token_a, topic="Second topic")

    resp = await client.get("/api/v1/debates", headers=auth(token_a))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    assert {item["topic"] for item in items} == {"First topic", "Second topic"}
    for item in items:
        assert item["status"] in {"pending", "created", "draft"}
        assert len(item["agents"]) >= 2
        assert "id" in item and "created_at" in item
    print("user can list own debates: PASSED")


async def test_user_cannot_list_other_users_debates(client):
    token_a = await register_and_login(client, unique_email("secreta"))
    token_b = await register_and_login(client, unique_email("secretb"))
    await create_debate(client, token_a, topic="Private topic")

    resp = await client.get("/api/v1/debates", headers=auth(token_b))
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    print("user cannot see another user's debates: PASSED")


async def test_user_retrieves_own_debate(client):
    token = await register_and_login(client, unique_email("detail"))
    created = await create_debate(client, token, total_rounds=4, verify_evidence=True)
    debate_id = created.json()["id"]

    resp = await client.get(f"/api/v1/debates/{debate_id}", headers=auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == debate_id
    assert data["topic"] == created.json()["topic"]
    assert data["total_rounds"] == 4
    assert data["verify_evidence"] is True
    assert len(data["agents"]) == 2
    print("user can retrieve own debate: PASSED")


async def test_user_cannot_retrieve_other_users_debate(client):
    token_a = await register_and_login(client, unique_email("mine"))
    token_b = await register_and_login(client, unique_email("yours"))
    created = await create_debate(client, token_a)
    debate_id = created.json()["id"]

    resp = await client.get(f"/api/v1/debates/{debate_id}", headers=auth(token_b))
    assert resp.status_code == 404, resp.text

    own = await client.get(f"/api/v1/debates/{debate_id}", headers=auth(token_a))
    assert own.status_code == 200, own.text
    print("user cannot retrieve another user's debate (404): PASSED")


async def test_invalid_debate_id_handled(client):
    token = await register_and_login(client, unique_email("badid"))
    resp = await client.get(f"/api/v1/debates/{uuid.uuid4()}", headers=auth(token))
    assert resp.status_code == 404, resp.text

    resp = await client.get("/api/v1/debates/not-a-uuid", headers=auth(token))
    assert resp.status_code == 422, resp.text
    print("invalid debate id handled correctly (404/422): PASSED")


# ---------------------------------------------------------------------------
# 7. transaction safety
# ---------------------------------------------------------------------------


async def test_transaction_rollback_when_assignment_fails(client):
    import app.services.debate_service as debate_service

    original = debate_service._add_agent_links

    async def failing_link(db, debate, agents):
        raise RuntimeError("simulated association failure")

    debate_service._add_agent_links = failing_link
    try:
        token = await register_and_login(client, unique_email("rollback"))
        user_id = await current_user_id(client, token)
        resp = await create_debate(client, token)
        assert resp.status_code == 500, resp.text
        assert "Could not create the debate" in resp.json()["detail"]
    finally:
        debate_service._add_agent_links = original

    rows = await debate_rows(user_id)
    assert rows == [], f"partial debate left behind: {[r.id for r in rows]}"
    print("transaction rollback leaves no incomplete debate: PASSED")


# ---------------------------------------------------------------------------
# 8. protected routes and core agent discovery
# ---------------------------------------------------------------------------


async def test_list_and_detail_require_authentication(client):
    resp = await client.get("/api/v1/debates")
    assert resp.status_code == 401, resp.text
    resp = await client.get(f"/api/v1/debates/{uuid.uuid4()}")
    assert resp.status_code == 401, resp.text
    resp = await client.get("/api/v1/agents")
    assert resp.status_code == 401, resp.text
    print("list/detail/agents endpoints require Bearer auth (401): PASSED")


async def test_core_agents_endpoint_returns_active_core_agents(client):
    token = await register_and_login(client, unique_email("agents"))
    resp = await client.get("/api/v1/agents", headers=auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    roles = {agent["role"] for agent in data}
    assert roles == {
        "economist",
        "lawyer",
        "doctor",
        "scientist",
        "ethicist",
        "analyst",
    }
    for agent in data:
        assert agent["name"] and agent["description"]
        assert "is_active" not in agent and "is_core" not in agent
    print("GET /api/v1/agents returns the six active core agents: PASSED")


async def main():
    print("Setting up isolated test DB (aidebate_test)...")
    app = await setup()

    async with client_for(app) as client:
        await test_create_debate_authenticated(client)
        await test_create_debate_unauthenticated(client)
        await test_topic_is_required(client)
        await test_empty_topic_rejected(client)
        await test_single_agent_rejected(client)
        await test_two_valid_agents_accepted(client)
        await test_duplicate_agent_rejected(client)
        await test_unknown_agent_rejected(client)
        await test_inactive_agent_rejected(client)
        await test_non_core_agent_rejected(client)
        await test_manual_selection_stores_selected_agents(client)
        await test_auto_mode_selects_all_active_core_agents(client)
        await test_debate_status_is_initial_not_started(client)
        await test_debate_creation_does_not_call_llm(client)
        await test_debate_agent_associations_are_stored(client)
        await test_user_lists_own_debates(client)
        await test_user_cannot_list_other_users_debates(client)
        await test_user_retrieves_own_debate(client)
        await test_user_cannot_retrieve_other_users_debate(client)
        await test_invalid_debate_id_handled(client)
        await test_transaction_rollback_when_assignment_fails(client)
        await test_list_and_detail_require_authentication(client)
        await test_core_agents_endpoint_returns_active_core_agents(client)

    await teardown()
    print("\nAll debate creation / agent selection tests PASSED!")

    print("\nRegression: Module 2 (authentication)...")
    from tests import test_auth

    await test_auth.main()

    print("\nRegression: Module 3 (LLM provider + BaseAgent)...")
    from tests import test_llm

    await test_llm.main()


if __name__ == "__main__":
    asyncio.run(main())
