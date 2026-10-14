"""Module 7 — live debate streaming + WebSocket tests.

Sections 27-32 of prompt 7:
  27) ConnectionManager unit tests (no server, no DB)
  28) WebSocket authentication and close codes (4401/4403/4404)
  29) Event types and ordering during a full 2-agent x 2-round debate
  30) Persistence happens before broadcasting
  31) A failing client never disturbs the others
  32) Reconnecting after a drop works

The TestClient keeps a single portal/event loop, so the app, the WebSocket
sessions and the in-app database session all run on the same loop. Schema
setup uses a separate engine that is disposed before the app starts.
"""

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from app.llm.base import LLMProviderAPIError, LLMResponse
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test",
)

_app_engine = None
_app_sessionmaker = None


# ---------------------------------------------------------------------------
# setup / teardown
# ---------------------------------------------------------------------------


async def setup():
    """Fresh schema (setup engine, disposed) + app session (app loop only)."""
    global _app_engine, _app_sessionmaker

    setup_engine = create_async_engine(TEST_DB_URL)
    setup_session = async_sessionmaker(setup_engine, expire_on_commit=False)

    async with setup_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    from app.db.database import Base
    import app.models  # noqa: F401  (register models)

    async with setup_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.services.seed import seed_agents

    async with setup_session() as session:
        await seed_agents(session)
    await setup_engine.dispose()

    # Created here but only ever used from inside the TestClient portal loop.
    _app_engine = create_async_engine(TEST_DB_URL)
    _app_sessionmaker = async_sessionmaker(_app_engine, expire_on_commit=False)

    from app.db.database import get_db
    from app.main import app
    from app.websocket.manager import connection_manager

    async def override_get_db():
        async with _app_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    connection_manager.drop_all()
    return app


async def teardown():
    from app.main import app
    from app.websocket.manager import connection_manager

    app.dependency_overrides.clear()
    connection_manager.drop_all()


@asynccontextmanager
async def app_db():
    """Session bound to the app loop; only usable inside the TestClient."""
    async with _app_sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def register_login(client, email, password="securepassword") -> str:
    resp = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def base_payload(**overrides) -> dict:
    payload = {
        "topic": "Should cities ban private cars from downtown?",
        "expert_selection_mode": "manual",
        "agent_ids": ["economist", "scientist"],
        "domain_tags": ["policy"],
        "mode": "balanced",
        "total_rounds": 2,
        "verify_evidence": False,
    }
    payload.update(overrides)
    return payload


def create_debate(client, token, **overrides) -> str:
    resp = client.post(
        "/api/v1/debates", json=base_payload(**overrides), headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def ws_url(debate_id: str, token: str | None = None) -> str:
    url = f"/ws/debates/{debate_id}"
    if token is not None:
        url += f"?token={token}"
    return url


def expect_close(client, url: str, expected_code: int) -> None:
    """The server accepts, then refuses the subscription with `expected_code`."""
    try:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    except WebSocketDisconnect as exc:
        assert exc.code == expected_code, f"close {exc.code}, want {expected_code}"
        return
    raise AssertionError(f"expected the server to close with {expected_code}")


def wait_for_connection_count(debate_id, expected: int, timeout: float = 5.0):
    from app.websocket.manager import connection_manager

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if connection_manager.connection_count(debate_id) == expected:
            return
        time.sleep(0.05)
    raise AssertionError(
        f"connection count for {debate_id} stayed at "
        f"{connection_manager.connection_count(debate_id)}, want {expected}"
    )


def read_events(ws, expected_terminal: str = "debate_completed", limit: int = 64):
    """Read events until the terminal one arrives (bounded)."""
    events = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event["type"] == expected_terminal:
            return events
    raise AssertionError("terminal event never arrived")


class MockSocket:
    """Stands in for a real client inside the ConnectionManager."""

    def __init__(self, name="socket", fail=False, on_event=None):
        self.name = name
        self.fail = fail
        self.events = []
        self.on_event = on_event

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError(f"{self.name} is broken")
        self.events.append(data)
        if self.on_event is not None:
            await self.on_event(data)

    def types(self):
        return [event["type"] for event in self.events]


class FakeProvider:
    """Deterministic LLM double; shared call counter across agent instances."""

    def __init__(self, counter: list, mode: str = "ok"):
        self.counter = counter
        self.mode = mode

    async def generate(self, messages, temperature=None, max_tokens=None):
        index = len(self.counter)
        self.counter.append(index)
        await asyncio.sleep(0)
        if self.mode == "internal":
            raise RuntimeError("secret-internal-stacktrace-details")
        if self.mode == "provider":
            raise LLMProviderAPIError("simulated provider failure")
        return LLMResponse(
            content=f"[message {index}] reasoned answer about the debate topic.",
            provider="fake",
            model="fake-model",
        )


@contextmanager
def fake_llm(mode: str = "ok"):
    import app.agents.base_agent as base_agent_module

    counter: list = []
    original = base_agent_module.get_llm_provider
    base_agent_module.get_llm_provider = lambda: FakeProvider(counter, mode=mode)
    try:
        yield counter
    finally:
        base_agent_module.get_llm_provider = original


def expected_event_sequence(rounds: int = 2, agents: int = 2) -> list[str]:
    sequence = ["debate_started"]
    for round_number in range(1, rounds + 1):
        sequence.append("round_started")
        for _ in range(agents):
            sequence.extend(
                ["agent_turn_started", "agent_message", "agent_turn_completed"]
            )
        sequence.append("round_completed")
    sequence.append("debate_completed")
    return sequence


# ---------------------------------------------------------------------------
# 27) ConnectionManager unit tests
# ---------------------------------------------------------------------------


async def test_manager_tracks_connections_per_debate():
    from app.websocket.manager import ConnectionManager

    manager = ConnectionManager()
    s1, s2, s3 = MockSocket("s1"), MockSocket("s2"), MockSocket("s3")

    manager.register(s1, "debate-a")
    manager.register(s2, "debate-a")
    manager.register(s3, "debate-b")

    assert manager.connection_count("debate-a") == 2
    assert manager.connection_count("debate-b") == 1
    assert manager.connection_count() == 3
    assert manager.is_watched("debate-a")
    assert not manager.is_watched("debate-c")

    manager.unregister(s1, "debate-a")
    assert manager.connection_count("debate-a") == 1

    manager.unregister(s2, "debate-a")
    assert manager.connection_count("debate-a") == 0
    assert not manager.is_watched("debate-a")

    # Unregistering unknown sockets/debates is harmless.
    manager.unregister(s2, "debate-a")
    manager.unregister(s3, "unknown-debate")
    assert manager.connection_count("debate-b") == 1

    manager.drop_all()
    assert manager.connection_count() == 0
    print("Manager tracks connections per debate: PASSED")


async def test_manager_broadcast_targets_only_its_debate():
    from app.websocket.manager import ConnectionManager

    manager = ConnectionManager()
    a1, a2, b1 = MockSocket("a1"), MockSocket("a2"), MockSocket("b1")
    manager.register(a1, "debate-a")
    manager.register(a2, "debate-a")
    manager.register(b1, "debate-b")

    delivered = await manager.broadcast(
        "debate-a", {"type": "round_started", "debate_id": "debate-a"}
    )

    assert delivered == 2
    assert a1.types() == ["round_started"]
    assert a2.types() == ["round_started"]
    assert b1.types() == []

    # And a debate with exactly one client receives exactly one copy.
    manager2 = ConnectionManager()
    only = MockSocket("only")
    manager2.register(only, "debate-solo")
    delivered = await manager2.broadcast("debate-solo", {"type": "error"})
    assert delivered == 1
    assert only.types() == ["error"]
    print("Broadcast reaches only the matching debate: PASSED")


async def test_manager_broadcast_drops_failing_socket():
    from app.websocket.manager import ConnectionManager

    manager = ConnectionManager()
    good, bad = MockSocket("good"), MockSocket("bad", fail=True)
    manager.register(good, "debate-a")
    manager.register(bad, "debate-a")

    delivered = await manager.broadcast("debate-a", {"type": "debate_started"})

    assert delivered == 1
    assert good.types() == ["debate_started"]
    assert bad.types() == []
    assert manager.connection_count("debate-a") == 1  # the broken one was dropped
    print("Failing socket dropped without affecting others: PASSED")


async def test_manager_broadcast_without_connections_is_a_noop():
    from app.websocket.manager import ConnectionManager

    manager = ConnectionManager()
    delivered = await manager.broadcast("nobody-listening", {"type": "error"})
    assert delivered == 0
    print("Broadcast with no connections is a no-op: PASSED")


# ---------------------------------------------------------------------------
# 28) authentication + close codes
# ---------------------------------------------------------------------------


def test_missing_token_closes_with_4401(client):
    from app.websocket.manager import connection_manager

    token = register_login(client, unique_email("ws-missing"))
    debate_id = create_debate(client, token)

    expect_close(client, ws_url(debate_id), 4401)
    assert connection_manager.connection_count(debate_id) == 0
    print("Missing token closes with 4401: PASSED")


def test_invalid_token_closes_with_4401(client):
    token = register_login(client, unique_email("ws-invalid"))
    debate_id = create_debate(client, token)

    expect_close(client, ws_url(debate_id, "not.a.valid.jwt"), 4401)
    print("Invalid token closes with 4401: PASSED")


def test_expired_token_closes_with_4401(client):
    from app.core.security import create_access_token, decode_access_token

    token = register_login(client, unique_email("ws-expired"))
    debate_id = create_debate(client, token)
    subject = decode_access_token(token)
    assert subject

    expired = create_access_token(subject, expires_minutes=-5)
    expect_close(client, ws_url(debate_id, expired), 4401)
    print("Expired token closes with 4401: PASSED")


def test_other_users_debate_closes_with_4403(client):
    owner_token = register_login(client, unique_email("ws-owner"))
    debate_id = create_debate(client, owner_token)
    intruder_token = register_login(client, unique_email("ws-intruder"))

    expect_close(client, ws_url(debate_id, intruder_token), 4403)
    print("Another user's debate closes with 4403: PASSED")


def test_unknown_debate_closes_with_4404(client):
    token = register_login(client, unique_email("ws-ghost"))
    ghost_id = str(uuid.uuid4())

    expect_close(client, ws_url(ghost_id, token), 4404)
    print("Unknown debate closes with 4404: PASSED")


def test_valid_connection_registers_and_answers_malformed_events(client):
    from app.websocket.manager import connection_manager

    token = register_login(client, unique_email("ws-valid"))
    debate_id = create_debate(client, token)

    with client.websocket_connect(ws_url(debate_id, token)) as ws:
        wait_for_connection_count(debate_id, 1)

        ws.send_text("this is not json")
        event = ws.receive_json()
        assert event["type"] == "error"
        assert event["debate_id"] == debate_id
        assert event["data"]["message"]

        ws.send_text('{"type": "ping"}')
        # Unknown-but-valid events are ignored; the connection stays open.
        ws.send_text("still not json")
        event = ws.receive_json()
        assert event["type"] == "error"

    wait_for_connection_count(debate_id, 0)
    print("Valid connection registers, answers malformed events: PASSED")


# ---------------------------------------------------------------------------
# 29) event types + ordering (real WebSocket, full debate)
# ---------------------------------------------------------------------------


def test_full_debate_streams_ordered_events_over_websocket(client):
    token = register_login(client, unique_email("ws-order"))
    debate_id = create_debate(client, token, total_rounds=2)

    with client.websocket_connect(ws_url(debate_id, token)) as ws:
        with fake_llm():
            resp = client.post(
                f"/api/v1/debates/{debate_id}/start", headers=auth(token)
            )
        assert resp.status_code == 200, resp.text

        events = read_events(ws, "debate_completed")

    wait_for_connection_count(debate_id, 0)

    types = [event["type"] for event in events]
    assert types == expected_event_sequence(rounds=2, agents=2), types

    # Shape of every event.
    for event in events:
        assert event["debate_id"] == debate_id
        assert event["timestamp"], "timestamp missing"
        assert isinstance(event["data"], dict)

    # Round numbers advance exactly once per round.
    round_started = [
        event["data"]["round_number"]
        for event in events
        if event["type"] == "round_started"
    ]
    round_completed = [
        event["data"]["round_number"]
        for event in events
        if event["type"] == "round_completed"
    ]
    assert round_started == [1, 2]
    assert round_completed == [1, 2]

    # Agent payload and message content on every agent_message.
    messages = [e for e in events if e["type"] == "agent_message"]
    assert len(messages) == 4
    for event in messages:
        data = event["data"]
        assert data["agent"]["id"]
        assert data["agent"]["name"]
        assert data["agent"]["role"]
        assert data["message_id"]
        assert data["content"].startswith("[message ")
        assert data["round_number"] in (1, 2)
        assert data["turn_number"] in (1, 2)
        assert data["message_type"] == (
            "opening" if data["round_number"] == 1 else "closing"
        )

    # Speaker announced before, and turn completed after, each message.
    started = [e["data"]["turn_number"] for e in events if e["type"] == "agent_turn_started"]
    completed = [e["data"]["turn_number"] for e in events if e["type"] == "agent_turn_completed"]
    assert started == [1, 2, 1, 2]
    assert completed == [1, 2, 1, 2]
    assert events[-1]["data"]["status"] == "completed"
    print("Full debate streams ordered events over WebSocket: PASSED")


def test_provider_failure_broadcasts_safe_debate_failed(client):
    token = register_login(client, unique_email("ws-failure"))
    debate_id = create_debate(client, token, total_rounds=1)

    socket = MockSocket("listener")
    from app.websocket.manager import connection_manager

    connection_manager.register(socket, debate_id)
    try:
        with fake_llm(mode="internal"):
            resp = client.post(
                f"/api/v1/debates/{debate_id}/start", headers=auth(token)
            )
        assert resp.status_code == 500, resp.text
    finally:
        connection_manager.unregister(socket, debate_id)

    types = socket.types()
    assert types[0] == "debate_started"
    assert types[-1] == "debate_failed"
    assert "round_started" in types
    assert "debate_completed" not in types

    failed = socket.events[-1]
    assert failed["data"]["status"] == "failed"
    assert failed["data"]["message"] == (
        "The debate failed because of an unexpected internal error."
    )

    serialized = str(socket.events)
    assert "secret-internal-stacktrace-details" not in serialized
    assert "Traceback" not in serialized
    assert "gsk_" not in serialized
    print("Failure broadcasts safe debate_failed event: PASSED")


# ---------------------------------------------------------------------------
# 30) persistence happens before broadcasting
# ---------------------------------------------------------------------------


def test_state_is_persisted_before_the_event_is_broadcast(client):
    token = register_login(client, unique_email("ws-persist"))
    debate_id = create_debate(client, token, total_rounds=2)

    observed = {"messages": [], "rounds": [], "debate": []}

    async def verify_before_delivery(event):
        event_type = event["type"]
        if event_type == "agent_message":
            message_id = uuid.UUID(event["data"]["message_id"])
            async with app_db() as session:
                row = await session.get(DebateMessage, message_id)
            assert row is not None, "message must exist before it is broadcast"
            assert row.content == event["data"]["content"]
            observed["messages"].append(message_id)
        elif event_type == "round_completed":
            number = event["data"]["round_number"]
            async with app_db() as session:
                result = await session.execute(
                    select(DebateRound).where(
                        DebateRound.debate_id == uuid.UUID(debate_id),
                        DebateRound.round_number == number,
                    )
                )
                row = result.scalar_one()
            assert row.status == "completed", "round must be committed first"
            observed["rounds"].append(number)
        elif event_type == "debate_completed":
            async with app_db() as session:
                row = await session.get(Debate, uuid.UUID(debate_id))
            assert row is not None and row.status == "completed"
            assert row.completed_at is not None
            observed["debate"].append(row.status)

    socket = MockSocket("verifier", on_event=verify_before_delivery)
    from app.websocket.manager import connection_manager

    connection_manager.register(socket, debate_id)
    try:
        with fake_llm():
            resp = client.post(
                f"/api/v1/debates/{debate_id}/start", headers=auth(token)
            )
        assert resp.status_code == 200, resp.text
    finally:
        connection_manager.unregister(socket, debate_id)

    assert len(observed["messages"]) == 4
    assert observed["rounds"] == [1, 2]
    assert observed["debate"] == ["completed"]

    # The HTTP transcript agrees with what was broadcast.
    transcript = client.get(
        f"/api/v1/debates/{debate_id}/messages", headers=auth(token)
    )
    assert transcript.status_code == 200
    http_ids = {message["id"] for message in transcript.json()["messages"]}
    assert http_ids == {str(mid) for mid in observed["messages"]}
    print("Persisted before broadcast: PASSED")


# ---------------------------------------------------------------------------
# 31) a failing client never disturbs the others
# ---------------------------------------------------------------------------


def test_failing_client_does_not_disturb_the_others(client):
    token = register_login(client, unique_email("ws-isolation"))
    debate_id = create_debate(client, token, total_rounds=2)

    from app.websocket.manager import connection_manager

    healthy = MockSocket("healthy")
    broken = MockSocket("broken", fail=True)
    leaving = MockSocket("leaving")
    other_debate = MockSocket("other-debate")

    async def drop_after_round_one(event):
        # Simulates a browser closing the tab after round 1.
        if event["type"] == "round_completed" and event["data"]["round_number"] == 1:
            connection_manager.unregister(leaving, debate_id)

    leaving.on_event = drop_after_round_one

    connection_manager.register(healthy, debate_id)
    connection_manager.register(broken, debate_id)
    connection_manager.register(leaving, debate_id)
    connection_manager.register(other_debate, "unrelated-debate")

    try:
        with fake_llm():
            resp = client.post(
                f"/api/v1/debates/{debate_id}/start", headers=auth(token)
            )
        assert resp.status_code == 200, resp.text

        # broken was dropped on the first broadcast, leaving went away after
        # round 1; the healthy client is the only one left registered.
        assert connection_manager.connection_count(debate_id) == 1
        assert healthy.types() == expected_event_sequence(rounds=2, agents=2)
        assert broken.types() == []
        assert other_debate.types() == []
        assert leaving.types() == expected_event_sequence(rounds=2, agents=2)[:9]
        assert "debate_completed" not in leaving.types()

        # The debate still finished and the transcript kept being persisted.
        debate = client.get(f"/api/v1/debates/{debate_id}", headers=auth(token))
        assert debate.status_code == 200
        assert debate.json()["status"] == "completed"

        transcript = client.get(
            f"/api/v1/debates/{debate_id}/messages", headers=auth(token)
        )
        assert transcript.status_code == 200
        assert len(transcript.json()["messages"]) == 4

        rounds = client.get(f"/api/v1/debates/{debate_id}/rounds", headers=auth(token))
        assert [r["status"] for r in rounds.json()["rounds"]] == [
            "completed",
            "completed",
        ]
    finally:
        connection_manager.unregister(healthy, debate_id)
        connection_manager.unregister(leaving, debate_id)
        connection_manager.unregister(other_debate, "unrelated-debate")

    print("Failing client does not disturb the others: PASSED")


# ---------------------------------------------------------------------------
# 32) reconnect after a drop
# ---------------------------------------------------------------------------


def test_reconnect_after_drop_receives_live_events(client):
    """Sections 16 and 32: drop, keep running, reconnect, recover over HTTP."""
    token = register_login(client, unique_email("ws-reconnect"))
    debate_id = create_debate(client, token, total_rounds=1)

    from app.websocket.manager import connection_manager

    # 1) first connection authenticates and then drops.
    with client.websocket_connect(ws_url(debate_id, token)) as ws:
        wait_for_connection_count(debate_id, 1)
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "error"
    wait_for_connection_count(debate_id, 0)

    # A client that leaves mid-debate must not stop anything.
    leaver = MockSocket("leaver")

    async def leave_after_round_start(event):
        if event["type"] == "round_completed":
            connection_manager.unregister(leaver, debate_id)

    leaver.on_event = leave_after_round_start
    connection_manager.register(leaver, debate_id)

    # 2)+3) reconnect (ownership is revalidated on every connection) and run.
    with client.websocket_connect(ws_url(debate_id, token)) as ws:
        wait_for_connection_count(debate_id, 2)
        with fake_llm():
            resp = client.post(
                f"/api/v1/debates/{debate_id}/start", headers=auth(token)
            )
        assert resp.status_code == 200, resp.text

        events = read_events(ws, "debate_completed")

    wait_for_connection_count(debate_id, 0)
    assert [event["type"] for event in events] == expected_event_sequence(
        rounds=1, agents=2
    )
    assert leaver.types() == expected_event_sequence(rounds=1, agents=2)[:-1]

    # 5)+6) current state is recoverable over plain HTTP after reconnecting.
    debate = client.get(f"/api/v1/debates/{debate_id}", headers=auth(token))
    assert debate.status_code == 200
    assert debate.json()["status"] == "completed"

    transcript = client.get(
        f"/api/v1/debates/{debate_id}/messages", headers=auth(token)
    )
    assert transcript.status_code == 200
    assert len(transcript.json()["messages"]) == 2  # 2 agents x 1 round

    # No event replay: a socket that connects after the run stays silent.
    late = MockSocket("late")
    connection_manager.register(late, debate_id)
    try:
        assert late.types() == []
        assert connection_manager.connection_count(debate_id) == 1
    finally:
        connection_manager.unregister(late, debate_id)

    print("Reconnect after drop receives live events: PASSED")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def run_manager_tests():
    print("Section 27: ConnectionManager unit tests...")
    asyncio.run(test_manager_tracks_connections_per_debate())
    asyncio.run(test_manager_broadcast_targets_only_its_debate())
    asyncio.run(test_manager_broadcast_drops_failing_socket())
    asyncio.run(test_manager_broadcast_without_connections_is_a_noop())


def main():
    run_manager_tests()

    print("Setting up isolated test DB (aidebate_test)...")
    app = setup_app()

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        try:
            print("Section 28: authentication + close codes...")
            test_missing_token_closes_with_4401(client)
            test_invalid_token_closes_with_4401(client)
            test_expired_token_closes_with_4401(client)
            test_other_users_debate_closes_with_4403(client)
            test_unknown_debate_closes_with_4404(client)
            test_valid_connection_registers_and_answers_malformed_events(client)

            print("Section 29: event types + ordering...")
            test_full_debate_streams_ordered_events_over_websocket(client)
            test_provider_failure_broadcasts_safe_debate_failed(client)

            print("Section 30: persistence before broadcast...")
            test_state_is_persisted_before_the_event_is_broadcast(client)

            print("Section 31: disconnect isolation...")
            test_failing_client_does_not_disturb_the_others(client)

            print("Section 32: reconnect...")
            test_reconnect_after_drop_receives_live_events(client)
        finally:
            dispose_app_engine(client)
    asyncio.run(teardown())
    print("\nAll Module 7 (live streaming) tests PASSED!")


def setup_app():
    global _app_engine, _app_sessionmaker
    app = asyncio.run(setup())
    return app


def dispose_app_engine(client):
    """Dispose the app engine on the portal loop it was used from."""
    global _app_engine
    if _app_engine is None:
        return
    engine = _app_engine
    _app_engine = None
    try:
        client.portal.call(engine.dispose)
    except Exception:
        pass


if __name__ == "__main__":
    main()
