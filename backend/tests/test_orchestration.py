import asyncio
import os
import uuid
from contextlib import contextmanager

import httpx
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.economist import EconomistAgent
from app.agents.factory import AGENT_REGISTRY
from app.agents.lawyer import LawyerAgent
from app.agents.scientist import ScientistAgent
from app.llm.base import LLMProviderAPIError, LLMResponse
from app.models.agent import Agent
from app.models.debate import Debate
from app.models.debate_agent import DebateAgent
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound

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
        "agent_ids": ["economist", "lawyer", "scientist"],
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


# ---------------------------------------------------------------------------
# fake LLM provider
# ---------------------------------------------------------------------------


class Recorder:
    """Records every prompt sent to the fake provider."""

    def __init__(self, fail_at: int | None = None):
        self.calls: list[dict] = []
        self.fail_at = fail_at
        self.max_concurrent = 0
        self._in_flight = 0
        self.on_call = None  # optional async hook(index)

    async def begin(self, system: str, user: str) -> int:
        self._in_flight += 1
        self.max_concurrent = max(self.max_concurrent, self._in_flight)
        index = len(self.calls)
        self.calls.append({"index": index, "system": system, "user": user})
        if self.on_call is not None:
            await self.on_call(index)
        await asyncio.sleep(0)  # lets a parallel implementation interleave
        return index

    async def end(self) -> None:
        self._in_flight -= 1

    @property
    def should_fail(self) -> bool:
        return self.fail_at is not None


class FakeProvider:
    def __init__(self, recorder: Recorder, internal_error: bool = False):
        self.recorder = recorder
        self.internal_error = internal_error

    async def generate(self, messages, temperature=None, max_tokens=None):
        system = messages[0].content
        user = messages[1].content
        index = await self.recorder.begin(system, user)
        try:
            if self.recorder.should_fail and index >= self.recorder.fail_at:
                raise LLMProviderAPIError("simulated provider failure")
            if self.internal_error:
                raise RuntimeError("secret-internal-stacktrace-details")
            return LLMResponse(
                content=f"[message {index}] reasoned answer about the debate topic.",
                provider="fake",
                model="fake-model",
            )
        finally:
            await self.recorder.end()


@contextmanager
def fake_llm(recorder: Recorder, internal_error: bool = False):
    import app.agents.base_agent as base_agent_module

    original = base_agent_module.get_llm_provider
    base_agent_module.get_llm_provider = lambda: FakeProvider(
        recorder, internal_error=internal_error
    )
    try:
        yield recorder
    finally:
        base_agent_module.get_llm_provider = original


# ---------------------------------------------------------------------------
# database helpers
# ---------------------------------------------------------------------------


async def fetch_debate(debate_id) -> Debate | None:
    async with _test_session() as db:
        result = await db.execute(select(Debate).where(Debate.id == debate_id))
        return result.scalar_one_or_none()


async def fetch_rounds(debate_id) -> list[DebateRound]:
    async with _test_session() as db:
        result = await db.execute(
            select(DebateRound)
            .where(DebateRound.debate_id == debate_id)
            .order_by(DebateRound.round_number)
        )
        return list(result.scalars().all())


async def fetch_messages(debate_id) -> list[dict]:
    """Messages ordered by round_number then turn_number."""
    async with _test_session() as db:
        result = await db.execute(
            select(
                DebateMessage,
                DebateRound.round_number,
                Agent.role,
                DebateAgent.position,
            )
            .join(DebateRound, DebateRound.id == DebateMessage.round_id)
            .join(Agent, Agent.id == DebateMessage.agent_id)
            .outerjoin(
                DebateAgent,
                (DebateAgent.agent_id == DebateMessage.agent_id)
                & (DebateAgent.debate_id == DebateMessage.debate_id),
            )
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateRound.round_number, DebateMessage.turn_number)
        )
        return [
            {
                "id": message.id,
                "round_id": message.round_id,
                "round_number": round_number,
                "turn_number": message.turn_number,
                "message_type": message.message_type,
                "content": message.content,
                "agent_id": message.agent_id,
                "role": role,
                "position": position,
            }
            for message, round_number, role, position in result.all()
        ]


async def fetch_associations(debate_id) -> list[DebateAgent]:
    async with _test_session() as db:
        result = await db.execute(
            select(DebateAgent)
            .where(DebateAgent.debate_id == debate_id)
            .order_by(DebateAgent.position)
        )
        return list(result.scalars().all())


async def count_messages(debate_id) -> int:
    async with _test_session() as db:
        result = await db.execute(
            select(DebateMessage).where(DebateMessage.debate_id == debate_id)
        )
        return len(list(result.scalars().all()))


# ---------------------------------------------------------------------------
# 1. successful start
# ---------------------------------------------------------------------------


async def test_start_debate_success(client):
    token = await register_and_login(client, unique_email("start"))
    created = await create_debate(client, token)
    debate_id = created.json()["id"]

    recorder = Recorder()
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert data["round_count"] == 3
    assert data["started_at"] is not None
    assert data["completed_at"] is not None
    assert len(data["agents"]) == 3
    assert len(recorder.calls) == 9  # 3 agents x 3 rounds
    print("debate starts successfully (200, completed, 9 responses): PASSED")


async def test_start_requires_authentication(client):
    created_token = await register_and_login(client, unique_email("unauthstart"))
    created = await create_debate(client, created_token)
    debate_id = created.json()["id"]

    resp = await client.post(f"/api/v1/debates/{debate_id}/start")
    assert resp.status_code == 401, resp.text
    print("unauthenticated user cannot start a debate (401): PASSED")


async def test_user_cannot_start_other_users_debate(client):
    token_a = await register_and_login(client, unique_email("ownstart"))
    token_b = await register_and_login(client, unique_email("otherstart"))
    created = await create_debate(client, token_a)
    debate_id = created.json()["id"]

    with fake_llm(Recorder()):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token_b)
        )
    assert resp.status_code == 404, resp.text

    debate = await fetch_debate(uuid.UUID(debate_id))
    assert debate.status == "pending"
    print("user cannot start another user's debate (404): PASSED")


# ---------------------------------------------------------------------------
# 2. duplicate start protection
# ---------------------------------------------------------------------------


async def test_running_debate_cannot_start_again(client):
    token = await register_and_login(client, unique_email("running"))
    created = await create_debate(client, token)
    debate_id = uuid.UUID(created.json()["id"])

    async with _test_session() as db:
        await db.execute(
            text("UPDATE debates SET status = 'running' WHERE id = :id"),
            {"id": debate_id},
        )
        await db.commit()

    with fake_llm(Recorder()):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 409, resp.text
    rounds = await fetch_rounds(debate_id)
    assert rounds == [], "a running debate must not create rounds"
    print("running debate cannot start again (409): PASSED")


async def test_completed_debate_cannot_start_again(client):
    token = await register_and_login(client, unique_email("again"))
    created = await create_debate(client, token)
    debate_id = created.json()["id"]

    with fake_llm(Recorder()):
        first = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
        assert first.status_code == 200, first.text
        calls_after_first = 9
        second = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert second.status_code == 409, second.text

    rounds = await fetch_rounds(uuid.UUID(debate_id))
    assert len(rounds) == 3, "duplicate rounds were created"
    messages = await fetch_messages(uuid.UUID(debate_id))
    assert len(messages) == calls_after_first
    print("completed debate cannot start again, no duplicate rounds (409): PASSED")


async def test_failed_debate_cannot_start_again(client):
    token = await register_and_login(client, unique_email("failedagain"))
    created = await create_debate(client, token)
    debate_id = created.json()["id"]

    recorder = Recorder(fail_at=3)
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text

    with fake_llm(Recorder()):
        retry = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert retry.status_code == 409, retry.text
    print("failed debate cannot start again (409): PASSED")


# ---------------------------------------------------------------------------
# 3. agents, order and rounds
# ---------------------------------------------------------------------------


async def test_correct_agents_are_loaded(client):
    token = await register_and_login(client, unique_email("loadagents"))
    selected = ["scientist", "economist", "lawyer"]
    created = await create_debate(client, token, agent_ids=selected)
    debate_id = uuid.UUID(created.json()["id"])

    recorder = Recorder()
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text

    assoc = await fetch_associations(debate_id)
    assert [row.position for row in assoc] == [1, 2, 3]
    assert len({row.agent_id for row in assoc}) == 3

    rows = await fetch_messages(debate_id)
    round_one_roles = [r["role"] for r in rows if r["round_number"] == 1]
    assert round_one_roles == selected, round_one_roles
    print("correct agents are loaded with stored positions: PASSED")


async def test_agent_order_is_deterministic(client):
    token = await register_and_login(client, unique_email("order"))
    selected = ["ethicist", "analyst", "doctor"]
    created = await create_debate(client, token, agent_ids=selected)
    debate_id = uuid.UUID(created.json()["id"])

    recorder = Recorder()
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text

    rows = await fetch_messages(debate_id)
    for round_number in (1, 2, 3):
        roles = [r["role"] for r in rows if r["round_number"] == round_number]
        assert roles == selected, f"round {round_number}: {roles}"

    expected_systems = [AGENT_REGISTRY[role].system_prompt for role in selected]
    for offset in (0, 3, 6):
        systems = [c["system"] for c in recorder.calls[offset:offset + 3]]
        assert systems == expected_systems, "runtime agents used wrong system prompts"

    assert recorder.max_concurrent == 1, "agents did not run sequentially"
    print("agent turn order is deterministic across all rounds: PASSED")


async def test_correct_number_of_rounds_created(client):
    token = await register_and_login(client, unique_email("rounds"))
    created = await create_debate(client, token, total_rounds=4)
    debate_id = uuid.UUID(created.json()["id"])

    with fake_llm(Recorder()):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["round_count"] == 4

    rounds = await fetch_rounds(debate_id)
    assert [r.round_number for r in rounds] == [1, 2, 3, 4]
    assert all(r.status == "completed" for r in rounds)
    assert all(r.started_at is not None and r.completed_at is not None for r in rounds)
    print("correct number of rounds is created (4): PASSED")


async def test_message_types_per_round(client):
    token = await register_and_login(client, unique_email("types"))
    created = await create_debate(client, token, total_rounds=4)
    debate_id = uuid.UUID(created.json()["id"])

    with fake_llm(Recorder()):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text

    rows = await fetch_messages(debate_id)
    expected = {1: "opening", 2: "rebuttal", 3: "rebuttal", 4: "closing"}
    assert len(rows) == 12
    for row in rows:
        assert row["message_type"] == expected[row["round_number"]], row
    print("round 1 opening, middle rebuttal, final closing: PASSED")


async def test_single_round_uses_opening_and_closing(client):
    token = await register_and_login(client, unique_email("one_round"))
    created = await create_debate(client, token, total_rounds=1)
    debate_id = uuid.UUID(created.json()["id"])

    with fake_llm(Recorder()):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    rows = await fetch_messages(debate_id)
    assert {r["message_type"] for r in rows} == {"opening"}
    print("single round debate uses opening message type: PASSED")


# ---------------------------------------------------------------------------
# 4. sequencing, context and persistence
# ---------------------------------------------------------------------------


async def test_responses_are_sequential(client):
    token = await register_and_login(client, unique_email("seq"))
    created = await create_debate(client, token, agent_ids=["economist", "lawyer"])
    debate_id = uuid.UUID(created.json()["id"])

    recorder = Recorder()
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert len(recorder.calls) == 6
    assert recorder.max_concurrent == 1, "agent calls overlapped"
    print("agent responses are generated sequentially (no parallelism): PASSED")


async def test_context_of_every_generation(client):
    token = await register_and_login(client, unique_email("ctx"))
    created = await create_debate(client, token)
    debate_id = uuid.UUID(created.json()["id"])

    recorder = Recorder()
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    calls = recorder.calls
    topic = base_payload()["topic"]

    first = calls[0]["user"]
    assert topic in first
    assert "Present your strongest reasoned position" in first
    assert "Previous debate transcript" not in first, "round 1 must not see history"

    second = calls[1]["user"]
    assert topic in second
    assert "[message 0]" in second, "second agent must receive the first message"
    assert "Previous debate transcript" in second

    third = calls[2]["user"]
    assert "[message 0]" in third and "[message 1]" in third

    round_two_first = calls[3]["user"]
    assert "[message 0]" in round_two_first
    assert "[message 1]" in round_two_first
    assert "[message 2]" in round_two_first
    assert "Respond to the arguments presented" in round_two_first
    assert topic in round_two_first

    last = calls[8]["user"]
    assert "Provide your final position" in last
    assert "[message 0]" in last, "final round must include earlier messages"
    assert "[message 7]" in last

    print("agents receive the correct context per round: PASSED")


async def test_messages_persisted_immediately(client):
    token = await register_and_login(client, unique_email("persist"))
    created = await create_debate(client, token, total_rounds=4)
    debate_id = uuid.UUID(created.json()["id"])

    recorder = Recorder()

    async def check_persisted(index: int):
        stored = await count_messages(debate_id)
        assert stored == index, (
            f"expected {index} persisted messages before call {index}, found {stored}"
        )

    recorder.on_call = check_persisted
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert await count_messages(debate_id) == 12
    print("every message is persisted immediately after generation: PASSED")


async def test_message_ordering_is_deterministic(client):
    token = await register_and_login(client, unique_email("msgorder"))
    created = await create_debate(client, token)
    debate_id = uuid.UUID(created.json()["id"])

    with fake_llm(Recorder()):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text

    rows = await fetch_messages(debate_id)
    sequence = [(r["round_number"], r["turn_number"]) for r in rows]
    expected = [(round_number, turn) for round_number in (1, 2, 3) for turn in (1, 2, 3)]
    assert sequence == expected, sequence
    print("messages are ordered by round_number then turn_number: PASSED")


async def test_debate_status_lifecycle(client):
    token = await register_and_login(client, unique_email("lifecycle"))
    created = await create_debate(client, token, total_rounds=2)
    debate_id = uuid.UUID(created.json()["id"])
    assert created.json()["status"] == "pending"

    recorder = Recorder()
    observed: list[str] = []

    async def observe(index: int):
        debate = await fetch_debate(debate_id)
        observed.append(debate.status)

    recorder.on_call = observe
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert observed and all(s == "running" for s in observed), observed

    final = await fetch_debate(debate_id)
    assert final.status == "completed"
    assert final.started_at is not None
    assert final.completed_at is not None
    print("debate status goes pending -> running -> completed: PASSED")


# ---------------------------------------------------------------------------
# 5. failure handling
# ---------------------------------------------------------------------------


async def test_llm_failure_marks_round_and_debate_failed(client):
    token = await register_and_login(client, unique_email("failure"))
    created = await create_debate(client, token)
    debate_id = uuid.UUID(created.json()["id"])

    recorder = Recorder(fail_at=3)
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert "simulated provider failure" not in detail
    assert "Traceback" not in detail

    debate = await fetch_debate(debate_id)
    assert debate.status == "failed"
    assert debate.completed_at is not None

    rounds = await fetch_rounds(debate_id)
    assert len(rounds) == 2
    assert rounds[0].status == "completed"
    assert rounds[1].status == "failed"
    print("LLM failure marks round failed and debate failed: PASSED")


async def test_previous_messages_survive_failure(client):
    token = await register_and_login(client, unique_email("survive"))
    created = await create_debate(client, token)
    debate_id = uuid.UUID(created.json()["id"])

    recorder = Recorder(fail_at=4)
    with fake_llm(recorder):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text

    rows = await fetch_messages(debate_id)
    assert len(rows) == 4, [r["content"] for r in rows]
    assert [r["message_type"] for r in rows] == [
        "opening",
        "opening",
        "opening",
        "rebuttal",
    ]
    print("previous messages remain after a failure: PASSED")


async def test_internal_error_does_not_leak_details(client):
    token = await register_and_login(client, unique_email("internal"))
    created = await create_debate(client, token, total_rounds=2)
    debate_id = uuid.UUID(created.json()["id"])

    with fake_llm(Recorder(), internal_error=True):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 500, resp.text
    detail = resp.json()["detail"]
    assert "secret-internal-stacktrace-details" not in detail
    assert "Traceback" not in detail
    assert "Error" not in detail

    debate = await fetch_debate(debate_id)
    assert debate.status == "failed"
    rounds = await fetch_rounds(debate_id)
    assert rounds[0].status == "failed"
    print("internal errors are not exposed to the frontend (500): PASSED")


# ---------------------------------------------------------------------------
# 6. transcript and round endpoints
# ---------------------------------------------------------------------------


async def test_transcript_endpoint_returns_ordered_messages(client):
    token = await register_and_login(client, unique_email("transcript"))
    created = await create_debate(client, token)
    debate_id = created.json()["id"]

    with fake_llm(Recorder()):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/start", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        f"/api/v1/debates/{debate_id}/messages", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["debate_id"] == debate_id
    messages = data["messages"]
    assert len(messages) == 9

    sequence = [(m["round_number"], m["turn_number"]) for m in messages]
    assert sequence == sorted(sequence)
    for message in messages:
        assert message["content"].startswith("[message ")
        assert message["id"]
        assert message["created_at"]
        assert message["message_type"] in {"opening", "rebuttal", "closing"}
        assert set(message["agent"]) == {"id", "name", "role"}
        assert message["agent"]["role"] in {
            "economist",
            "lawyer",
            "doctor",
            "scientist",
            "ethicist",
            "analyst",
        }
    print("transcript endpoint returns ordered messages with agent info: PASSED")


async def test_round_endpoint_returns_round_status(client):
    token = await register_and_login(client, unique_email("roundep"))
    created = await create_debate(client, token, total_rounds=2)
    debate_id = created.json()["id"]

    with fake_llm(Recorder()):
        await client.post(f"/api/v1/debates/{debate_id}/start", headers=auth(token))

    resp = await client.get(f"/api/v1/debates/{debate_id}/rounds", headers=auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["debate_id"] == debate_id
    rounds = data["rounds"]
    assert [r["round_number"] for r in rounds] == [1, 2]
    for round_data in rounds:
        assert round_data["status"] == "completed"
        assert round_data["started_at"] is not None
        assert round_data["completed_at"] is not None
        assert set(round_data) == {
            "round_number",
            "status",
            "started_at",
            "completed_at",
        }
    print("round endpoint returns round status and timestamps: PASSED")


async def test_round_endpoint_on_not_started_debate(client):
    token = await register_and_login(client, unique_email("emptyrounds"))
    created = await create_debate(client, token)
    debate_id = created.json()["id"]

    resp = await client.get(f"/api/v1/debates/{debate_id}/rounds", headers=auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["rounds"] == []

    resp = await client.get(
        f"/api/v1/debates/{debate_id}/messages", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["messages"] == []
    print("rounds/messages endpoints work before execution: PASSED")


async def test_user_cannot_access_other_users_transcript(client):
    token_a = await register_and_login(client, unique_email("mytranscript"))
    token_b = await register_and_login(client, unique_email("yourtranscript"))
    created = await create_debate(client, token_a)
    debate_id = created.json()["id"]

    with fake_llm(Recorder()):
        await client.post(f"/api/v1/debates/{debate_id}/start", headers=auth(token_a))

    for path in ("messages", "rounds"):
        resp = await client.get(
            f"/api/v1/debates/{debate_id}/{path}", headers=auth(token_b)
        )
        assert resp.status_code == 404, resp.text
        resp = await client.get(f"/api/v1/debates/{debate_id}/{path}")
        assert resp.status_code == 401, resp.text

    resp = await client.post(
        f"/api/v1/debates/{debate_id}/start", headers=auth(token_b)
    )
    assert resp.status_code == 404, resp.text
    print("another user's transcript/rounds/start are inaccessible (404): PASSED")


async def test_debate_detail_includes_execution_fields(client):
    token = await register_and_login(client, unique_email("detailfields"))
    created = await create_debate(client, token, total_rounds=2)
    debate_id = created.json()["id"]

    before = await client.get(f"/api/v1/debates/{debate_id}", headers=auth(token))
    assert before.status_code == 200, before.text
    assert before.json()["round_count"] == 0
    assert before.json()["started_at"] is None

    with fake_llm(Recorder()):
        await client.post(f"/api/v1/debates/{debate_id}/start", headers=auth(token))

    after = await client.get(f"/api/v1/debates/{debate_id}", headers=auth(token))
    data = after.json()
    assert data["round_count"] == 2
    assert data["status"] == "completed"
    assert data["started_at"] is not None
    assert data["completed_at"] is not None
    assert len(data["agents"]) == 3
    assert "messages" not in data
    print("debate detail includes status, round count and timestamps: PASSED")


# ---------------------------------------------------------------------------
# 7. Module 5 regression
# ---------------------------------------------------------------------------


async def test_module5_creation_still_works(client):
    token = await register_and_login(client, unique_email("m5"))
    resp = await create_debate(
        client, token, agent_ids=["economist", "doctor"], total_rounds=2
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "pending"
    assert data["round_count"] == 0
    assert data["started_at"] is None
    assert {a["role"] for a in data["agents"]} == {"economist", "doctor"}

    debate_id = uuid.UUID(data["id"])
    rounds = await fetch_rounds(debate_id)
    assert rounds == [], "creation must not create rounds"
    assert await count_messages(debate_id) == 0

    listing = await client.get("/api/v1/debates", headers=auth(token))
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["items"]) == 1
    print("Module 5 debate creation still works without execution: PASSED")


async def test_creation_never_starts_execution(client):
    import app.agents.base_agent as base_agent_module

    token = await register_and_login(client, unique_email("nollm6"))
    original = base_agent_module.get_llm_provider

    def guarded():
        raise RuntimeError("unexpected LLM access during debate creation")

    base_agent_module.get_llm_provider = guarded
    try:
        resp = await create_debate(client, token)
        assert resp.status_code == 201, resp.text
        detail = await client.get(
            f"/api/v1/debates/{resp.json()['id']}", headers=auth(token)
        )
        assert detail.status_code == 200, detail.text
    finally:
        base_agent_module.get_llm_provider = original

    print("POST /debates does not call the LLM or start execution: PASSED")


async def main():
    print("Setting up isolated test DB (aidebate_test)...")
    app = await setup()

    async with client_for(app) as client:
        await test_start_debate_success(client)
        await test_start_requires_authentication(client)
        await test_user_cannot_start_other_users_debate(client)
        await test_running_debate_cannot_start_again(client)
        await test_completed_debate_cannot_start_again(client)
        await test_failed_debate_cannot_start_again(client)
        await test_correct_agents_are_loaded(client)
        await test_agent_order_is_deterministic(client)
        await test_correct_number_of_rounds_created(client)
        await test_message_types_per_round(client)
        await test_single_round_uses_opening_and_closing(client)
        await test_responses_are_sequential(client)
        await test_context_of_every_generation(client)
        await test_messages_persisted_immediately(client)
        await test_message_ordering_is_deterministic(client)
        await test_debate_status_lifecycle(client)
        await test_llm_failure_marks_round_and_debate_failed(client)
        await test_previous_messages_survive_failure(client)
        await test_internal_error_does_not_leak_details(client)
        await test_transcript_endpoint_returns_ordered_messages(client)
        await test_round_endpoint_returns_round_status(client)
        await test_round_endpoint_on_not_started_debate(client)
        await test_user_cannot_access_other_users_transcript(client)
        await test_debate_detail_includes_execution_fields(client)
        await test_module5_creation_still_works(client)
        await test_creation_never_starts_execution(client)

    await teardown()
    print("\nAll debate orchestration tests PASSED!")

    print("\nRegression: Module 2 (authentication)...")
    from tests import test_auth

    await test_auth.main()

    print("\nRegression: Module 3 (LLM provider + BaseAgent)...")
    from tests import test_llm

    await test_llm.main()

    print("\nRegression: Module 4 (core role-based agents)...")
    from tests import test_agents

    await test_agents.main()


if __name__ == "__main__":
    asyncio.run(main())
