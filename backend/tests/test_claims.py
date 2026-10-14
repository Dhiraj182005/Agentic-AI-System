import asyncio
import inspect
import json
import os
import unittest.mock
import uuid
from datetime import datetime, timezone

import httpx
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evidence.base import (
    EvidenceConfigurationError,
    EvidenceProviderAPIError,
    EvidenceProviderResponseError,
    EvidenceProviderError,
    SearchResult,
)
from app.evidence.factory import get_evidence_provider
from app.evidence.tavily import TavilyEvidenceProvider
from app.llm.base import LLMResponse
from app.models.claim import Claim
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.services.claim_extraction import (
    ClaimExtractionError,
    parse_claims_payload,
)

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test",
)

_test_engine = None
_test_session = None


async def setup():
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
        "domain_tags": ["technology"],
        "mode": "balanced",
        "total_rounds": 2,
        "verify_evidence": False,
    }
    payload.update(overrides)
    return payload


OPENING_TEXT = (
    "Global temperatures have increased over the last century. "
    "Carbon pricing can reduce emissions. I believe this policy is unfair."
)
ARGUMENT_TEXT = (
    "Energy prices will double by 2030 if we act now. "
    "Consumers deserve transparent markets."
)


async def seed_completed_debate(client, token, **overrides) -> dict:
    """Create a debate via the API and seed two completed rounds/messages."""
    resp = await client.post(
        "/api/v1/debates", json=base_payload(**overrides), headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    debate_id = uuid.UUID(resp.json()["id"])

    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        debate.status = "completed"
        debate.started_at = datetime.now(timezone.utc)
        debate.completed_at = datetime.now(timezone.utc)
        agents = list(debate.agents)  # position order from debate_agents
        round_one = DebateRound(
            debate_id=debate_id, round_number=1, status="completed"
        )
        round_two = DebateRound(
            debate_id=debate_id, round_number=2, status="completed"
        )
        session.add_all([round_one, round_two])
        await session.flush()
        message_one = DebateMessage(
            debate_id=debate_id,
            round_id=round_one.id,
            agent_id=agents[0].id,
            turn_number=1,
            message_type="opening",
            content=OPENING_TEXT,
        )
        message_two = DebateMessage(
            debate_id=debate_id,
            round_id=round_two.id,
            agent_id=agents[1].id,
            turn_number=1,
            message_type="argument",
            content=ARGUMENT_TEXT,
        )
        session.add_all([message_one, message_two])
        await session.commit()
        return {
            "id": str(debate_id),
            "message_ids": [str(message_one.id), str(message_two.id)],
            "agent_names": [agents[0].name, agents[1].name],
        }


async def fetch_message_ids(debate_id: str) -> list[str]:
    async with _test_session() as session:
        rows = await session.execute(
            select(DebateMessage.id)
            .where(DebateMessage.debate_id == uuid.UUID(debate_id))
            .order_by(DebateMessage.turn_number)
        )
        return [str(row[0]) for row in rows.all()]


async def fetch_claims(debate_id: str) -> list[Claim]:
    async with _test_session() as session:
        rows = await session.execute(
            select(Claim)
            .where(Claim.debate_id == uuid.UUID(debate_id))
            .order_by(Claim.created_at, Claim.id)
        )
        return list(rows.scalars().all())


async def fetch_evidence(claim_id: str) -> list[Evidence]:
    async with _test_session() as session:
        rows = await session.execute(
            select(Evidence).where(Evidence.claim_id == uuid.UUID(claim_id))
        )
        return list(rows.scalars().all())


class FakeLLM:
    """LLM provider stand-in returning a fixed content string."""

    def __init__(self, content: str):
        self.content = content
        self.calls = 0
        self.last_messages = None

    async def generate(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        self.last_messages = messages
        return LLMResponse(content=self.content, provider="fake", model="fake-model")


class StaticEvidenceProvider:
    """Evidence provider stand-in with fixed results or a fixed error."""

    provider_name = "static"

    def __init__(self, results=None, error=None):
        self.results = results if results is not None else []
        self.error = error
        self.calls = 0
        self.last_query = None

    async def search(self, query, max_results=5):
        self.calls += 1
        self.last_query = query
        if self.error is not None:
            raise self.error
        return self.results


def sample_results() -> list[SearchResult]:
    return [
        SearchResult(
            title="Climate trends report",
            url="https://example.org/climate/trends",
            snippet="Summary of observed temperature changes.",
            source_name="example.org",
            relevance_score=0.91,
        ),
        SearchResult(
            title="Energy market outlook",
            url="https://example.com/energy/2030",
            snippet="Projected energy price scenarios.",
            source_name="example.com",
            relevance_score=0.77,
        ),
    ]


def claims_payload(message_ids: list[str]) -> str:
    m1, m2 = message_ids
    return json.dumps(
        [
            {
                "message_id": m1,
                "claim": "Global temperatures have increased over the last century.",
                "claim_type": "factual",
            },
            {
                "message_id": m1,
                "claim": "I believe this policy is unfair.",
                "claim_type": "FACT!!",
            },
            {
                "message_id": m2,
                "claim": "Energy prices will double by 2030 if we act now.",
                "claim_type": "prediction",
            },
            {
                "message_id": m2,
                "claim": "Consumers deserve transparent markets.",
                "claim_type": "banana",
            },
            {
                "message_id": m1,
                "claim": "Global temperatures have increased over the last century.",
                "claim_type": "factual",
            },
        ]
    )


# ---------------------------------------------------------------------------
# 1-2. Model creation
# ---------------------------------------------------------------------------


async def test_claim_and_evidence_model_creation(client):
    token = await register_and_login(client, unique_email("models"))
    debate = await seed_completed_debate(client, token)
    message_id = uuid.UUID(debate["message_ids"][0])

    async with _test_session() as session:
        message = await session.get(DebateMessage, message_id)
        claim = Claim(
            debate_id=uuid.UUID(debate["id"]),
            message_id=message.id,
            agent_id=message.agent_id,
            text="Direct model claim.",
            claim_type="factual",
            position=0,
        )
        session.add(claim)
        await session.commit()

    async with _test_session() as session:
        rows = await session.execute(
            select(Claim).where(Claim.text == "Direct model claim.")
        )
        stored_claim = rows.scalar_one()
        assert stored_claim.claim_type == "factual"
        assert stored_claim.position == 0
        assert stored_claim.created_at is not None
        claim_id = stored_claim.id

        evidence = Evidence(
            claim_id=claim_id,
            title="Model evidence",
            url="https://example.org/model",
            snippet="Snippet",
            source_name="example.org",
            relevance_score=0.5,
            position=0,
        )
        session.add(evidence)
        await session.commit()

        rows = await session.execute(
            select(Evidence).where(Evidence.claim_id == claim_id)
        )
        stored_evidence = rows.scalar_one()
        assert stored_evidence.title == "Model evidence"
        assert stored_evidence.relevance_score == 0.5
        assert stored_evidence.retrieved_at is not None

    print("Claim model creation: PASSED")
    print("Evidence model creation: PASSED")


# ---------------------------------------------------------------------------
# 3-6. Claim extraction service
# ---------------------------------------------------------------------------


def test_parse_valid_json_and_fences():
    ids = {"m1", "m2"}
    plain = json.dumps(
        [{"message_id": "m1", "claim": "The sky is blue.", "claim_type": "factual"}]
    )
    parsed = parse_claims_payload(plain, ids)
    assert len(parsed) == 1 and parsed[0].claim_type == "factual"

    fenced = f"```json\n{plain}\n```"
    parsed = parse_claims_payload(fenced, ids)
    assert len(parsed) == 1

    print("parse: valid JSON and fenced JSON: PASSED")


def test_parse_invalid_json_and_missing_fields():
    ids = {"m1"}

    for bad in ("", "no json here", '{"not": "an array"}'):
        try:
            parse_claims_payload(bad, ids)
        except ClaimExtractionError:
            pass
        else:
            raise AssertionError(f"expected ClaimExtractionError for {bad!r}")

    try:
        parse_claims_payload(json.dumps([{"foo": 1}]), ids)
    except ClaimExtractionError:
        pass
    else:
        raise AssertionError("expected ClaimExtractionError for items without claims")

    # unknown message ids and empty claims are dropped, not persisted
    parsed = parse_claims_payload(
        json.dumps(
            [
                {"message_id": "unknown", "claim": "Alien claim.", "claim_type": "factual"},
                {"message_id": "m1", "claim": "   ", "claim_type": "factual"},
                {"message_id": "m1", "claim": "A kept claim.", "claim_type": "factual"},
            ]
        ),
        ids,
    )
    assert len(parsed) == 1 and parsed[0].claim == "A kept claim."

    assert parse_claims_payload("[]", ids) == []

    print("parse: malformed output handled safely: PASSED")


def test_claim_type_validation():
    ids = {"m1"}
    parsed = parse_claims_payload(
        json.dumps(
            [
                {"message_id": "m1", "claim": "One.", "claim_type": "FACTUAL"},
                {"message_id": "m1", "claim": "Two.", "claim_type": "Fact"},
                {"message_id": "m1", "claim": "Three.", "claim_type": "banana"},
                {"message_id": "m1", "claim": "Four."},
                {"message_id": "m1", "claim": "Five.", "claim_type": 42},
            ]
        ),
        ids,
    )
    types = {c.claim: c.claim_type for c in parsed}
    assert types["One."] == "factual"
    assert types["Two."] == "factual"
    assert types["Three."] == "other"
    assert types["Four."] == "other"
    assert types["Five."] == "other"

    print("claim type validation and normalization: PASSED")


async def test_extraction_with_mocked_llm(client):
    token = await register_and_login(client, unique_email("extract"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))

    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debate_id"] == debate["id"]
    claims = body["claims"]
    assert len(claims) == 4, body  # duplicate dropped
    assert fake.calls == 1
    assert fake.last_messages[0].role == "system"

    by_text = {c["text"]: c for c in claims}
    assert (
        by_text["Global temperatures have increased over the last century."]
        ["claim_type"]
        == "factual"
    )
    assert by_text["I believe this policy is unfair."]["claim_type"] == "factual"
    assert (
        by_text["Energy prices will double by 2030 if we act now."]["claim_type"]
        == "prediction"
    )
    assert (
        by_text["Consumers deserve transparent markets."]["claim_type"] == "other"
    )

    m1, m2 = debate["message_ids"]
    assert by_text["Global temperatures have increased over the last century."][
        "message_id"
    ] == m1
    assert by_text["Energy prices will double by 2030 if we act now."][
        "message_id"
    ] == m2

    # agent association comes from the original message
    assert by_text["Global temperatures have increased over the last century."][
        "agent_name"
    ] == debate["agent_names"][0]
    assert by_text["Consumers deserve transparent markets."]["agent_name"] == (
        debate["agent_names"][1]
    )

    stored = await fetch_claims(debate["id"])
    assert len(stored) == 4

    print("claim extraction with mocked LLM response: PASSED")


async def test_extraction_invalid_llm_json(client):
    token = await register_and_login(client, unique_email("badjson"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM("Sorry, I cannot produce JSON right now.")

    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text
    assert "internal error" not in resp.json()["detail"].lower()
    assert await fetch_claims(debate["id"]) == []

    print("invalid LLM JSON returns 502 without corrupt records: PASSED")


async def test_extraction_duplicate_protection(client):
    token = await register_and_login(client, unique_email("dupe"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))

    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        first = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
        second = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    assert first.status_code == 200 and second.status_code == 200
    assert len(first.json()["claims"]) == 4
    assert len(second.json()["claims"]) == 4
    stored = await fetch_claims(debate["id"])
    assert len(stored) == 4

    print("duplicate extraction does not duplicate claims: PASSED")


async def test_extraction_empty_llm_list(client):
    token = await register_and_login(client, unique_email("emptyllm"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM("[]")

    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["claims"] == []
    assert await fetch_claims(debate["id"]) == []

    print("empty claim list from LLM handled: PASSED")


async def test_extraction_rejected_on_empty_debate(client):
    token = await register_and_login(client, unique_email("emptydeb"))
    resp = await client.post(
        "/api/v1/debates", json=base_payload(), headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    debate_id = resp.json()["id"]

    fake = FakeLLM("[]")
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/claims/extract", headers=auth(token)
        )
    assert resp.status_code == 400, resp.text
    assert fake.calls == 0

    resp = await client.get(
        f"/api/v1/debates/{debate_id}/claims", headers=auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["claims"] == []

    print("extraction rejected on a debate without messages: PASSED")


# ---------------------------------------------------------------------------
# 7-8. Claim API authorization and listing
# ---------------------------------------------------------------------------


async def test_claim_ownership_authorization(client):
    owner = await register_and_login(client, unique_email("owner"))
    other = await register_and_login(client, unique_email("other"))
    debate = await seed_completed_debate(client, owner)
    fake = FakeLLM(claims_payload(debate["message_ids"]))

    resp = await client.post(
        f"/api/v1/debates/{debate['id']}/claims/extract"
    )
    assert resp.status_code == 401, resp.text

    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(other)
        )
    assert resp.status_code == 404, resp.text

    resp = await client.get(f"/api/v1/debates/{debate['id']}/claims")
    assert resp.status_code == 401

    resp = await client.get(
        f"/api/v1/debates/{debate['id']}/claims", headers=auth(other)
    )
    assert resp.status_code == 404, resp.text

    assert await fetch_claims(debate["id"]) == []

    print("claim extraction/list authorization enforced: PASSED")


async def test_claim_list_endpoint(client):
    token = await register_and_login(client, unique_email("list"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))

    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )

    resp = await client.get(
        f"/api/v1/debates/{debate['id']}/claims", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debate_id"] == debate["id"]
    claims = body["claims"]
    assert len(claims) == 4

    # deterministic order: message one's claims before message two's
    m1, m2 = debate["message_ids"]
    assert claims[0]["message_id"] == m1
    assert claims[1]["message_id"] == m1
    assert claims[2]["message_id"] == m2
    assert claims[3]["message_id"] == m2

    for claim in claims:
        assert claim["id"]
        assert claim["agent_id"]
        assert claim["agent_name"] in debate["agent_names"]
        assert claim["claim_type"] in (
            "factual",
            "opinion",
            "prediction",
            "definition",
            "other",
        )
        assert claim["created_at"]

    # repeated reads are stable
    resp_again = await client.get(
        f"/api/v1/debates/{debate['id']}/claims", headers=auth(token)
    )
    assert [c["id"] for c in resp_again.json()["claims"]] == [
        c["id"] for c in claims
    ]

    resp_missing = await client.get(
        f"/api/v1/debates/{uuid.uuid4()}/claims", headers=auth(token)
    )
    assert resp_missing.status_code == 404

    print("claim list endpoint deterministic with metadata: PASSED")


# ---------------------------------------------------------------------------
# 9-10. Evidence provider abstraction + Tavily provider
# ---------------------------------------------------------------------------


def test_evidence_provider_abstraction():
    provider = get_evidence_provider()
    assert isinstance(provider, TavilyEvidenceProvider)
    assert provider.provider_name == "tavily"
    assert inspect.iscoroutinefunction(provider.search)

    from app.evidence.base import EvidenceProvider

    assert isinstance(provider, EvidenceProvider)

    with unittest.mock.patch(
        "app.evidence.factory.get_settings"
    ) as settings:
        settings.return_value.EVIDENCE_PROVIDER = "unknown"
        try:
            get_evidence_provider()
        except EvidenceConfigurationError:
            pass
        else:
            raise AssertionError("expected EvidenceConfigurationError")

    print("evidence provider abstraction and factory: PASSED")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, invalid_json=False):
        self.status_code = status_code
        self._payload = payload
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("invalid json")
        return self._payload


class FakeHTTPClient:
    def __init__(self, response: FakeResponse | None = None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.response


async def test_tavily_provider_mocked_http():
    payload = {
        "query": "test",
        "results": [
            {"title": "Report", "url": "https://news.example.com/a", "content": "Body one"},
            {
                "title": "No URL item",
                "content": "should be skipped",
            },
            {
                "url": "https://blog.example.org/b",
                "content": "Body two",
                "score": 0.42,
            },
            {"title": "No url either"},
        ],
    }
    client = FakeHTTPClient(FakeResponse(200, payload))
    provider = TavilyEvidenceProvider(api_key="tvly-test-key", client=client)

    results = await provider.search("test query", max_results=5)
    assert len(results) == 2, results
    assert results[0].title == "Report"
    assert results[0].url == "https://news.example.com/a"
    assert results[0].source_name == "news.example.com"
    assert results[0].snippet == "Body one"
    assert results[1].url == "https://blog.example.org/b"
    assert results[1].title == "https://blog.example.org/b"  # title fallback
    assert results[1].source_name == "blog.example.org"
    assert results[1].relevance_score == 0.42

    url, kwargs = client.calls[0]
    assert url == "https://api.tavily.com/search"
    assert kwargs["headers"]["Authorization"] == "Bearer tvly-test-key"
    assert kwargs["json"]["query"] == "test query"

    # missing key
    no_key = TavilyEvidenceProvider(api_key="", client=FakeHTTPClient())
    try:
        await no_key.search("query")
    except EvidenceConfigurationError:
        pass
    else:
        raise AssertionError("expected EvidenceConfigurationError for missing key")

    # empty query blocked
    try:
        await provider.search("   ")
    except EvidenceProviderAPIError:
        pass
    else:
        raise AssertionError("expected EvidenceProviderAPIError for empty query")

    # HTTP error status
    failing = TavilyEvidenceProvider(
        api_key="k", client=FakeHTTPClient(FakeResponse(500, {}))
    )
    try:
        await failing.search("query")
    except EvidenceProviderAPIError:
        pass
    else:
        raise AssertionError("expected EvidenceProviderAPIError for status 500")

    # malformed payload
    malformed = TavilyEvidenceProvider(
        api_key="k", client=FakeHTTPClient(FakeResponse(200, invalid_json=True))
    )
    try:
        await malformed.search("query")
    except EvidenceProviderResponseError:
        pass
    else:
        raise AssertionError("expected EvidenceProviderResponseError")

    # results not a list
    malformed_list = TavilyEvidenceProvider(
        api_key="k", client=FakeHTTPClient(FakeResponse(200, {"results": "oops"}))
    )
    try:
        await malformed_list.search("query")
    except EvidenceProviderResponseError:
        pass
    else:
        raise AssertionError("expected EvidenceProviderResponseError for bad list")

    print("Tavily provider with mocked HTTP: PASSED")


# ---------------------------------------------------------------------------
# 11-16. Evidence retrieval service + API
# ---------------------------------------------------------------------------


async def test_evidence_retrieve_persists_and_caches(client):
    token = await register_and_login(client, unique_email("ev"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    claims = resp.json()["claims"]
    claim_id = next(
        c["id"] for c in claims if c["claim_type"] == "factual"
    )

    provider = StaticEvidenceProvider(sample_results())
    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider", return_value=provider
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["claim_id"] == claim_id
    assert len(body["evidence"]) == 2
    first = body["evidence"][0]
    assert first["title"] == "Climate trends report"
    assert first["url"] == "https://example.org/climate/trends"
    assert first["source_name"] == "example.org"
    assert first["snippet"] == "Summary of observed temperature changes."
    assert provider.calls == 1
    assert provider.last_query  # non-empty query from claim text

    stored = await fetch_evidence(claim_id)
    assert len(stored) == 2
    assert [e.position for e in stored] == [0, 1]
    assert all(e.claim_id == uuid.UUID(claim_id) for e in stored)

    # second POST returns stored evidence without calling the provider again
    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider", return_value=provider
    ):
        resp_again = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(token)
        )
    assert resp_again.status_code == 200
    assert provider.calls == 1
    assert len(resp_again.json()["evidence"]) == 2

    # GET reads from the database only and never calls the provider
    resp_get = await client.get(
        f"/api/v1/claims/{claim_id}/evidence", headers=auth(token)
    )
    assert resp_get.status_code == 200
    assert len(resp_get.json()["evidence"]) == 2
    assert provider.calls == 1

    print("evidence persistence, caching and GET-from-database: PASSED")


async def test_evidence_ownership_authorization(client):
    owner = await register_and_login(client, unique_email("evowner"))
    other = await register_and_login(client, unique_email("evother"))
    debate = await seed_completed_debate(client, owner)
    fake = FakeLLM(claims_payload(debate["message_ids"]))
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(owner)
        )
    claim_id = resp.json()["claims"][0]["id"]

    provider = StaticEvidenceProvider(sample_results())
    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider", return_value=provider
    ):
        resp = await client.post(f"/api/v1/claims/{claim_id}/evidence/retrieve")
        assert resp.status_code == 401, resp.text

        resp = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(other)
        )
        assert resp.status_code == 404, resp.text

        resp = await client.get(f"/api/v1/claims/{claim_id}/evidence")
        assert resp.status_code == 401

        resp = await client.get(
            f"/api/v1/claims/{claim_id}/evidence", headers=auth(other)
        )
        assert resp.status_code == 404, resp.text

        resp = await client.post(
            f"/api/v1/claims/{uuid.uuid4()}/evidence/retrieve", headers=auth(other)
        )
        assert resp.status_code == 404

    assert provider.calls == 0
    assert await fetch_evidence(claim_id) == []

    print("evidence ownership authorization enforced: PASSED")


async def test_evidence_provider_missing_key(client):
    token = await register_and_login(client, unique_email("nokey"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    claim_id = resp.json()["claims"][0]["id"]

    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider",
        return_value=TavilyEvidenceProvider(api_key=""),
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(token)
        )
    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert "configured" in detail.lower()
    assert "tvly" not in resp.text.lower()
    assert await fetch_evidence(claim_id) == []

    print("missing Tavily API key returns 503 without leaking secrets: PASSED")


async def test_evidence_provider_failure(client):
    token = await register_and_login(client, unique_email("fail"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    claim_id = resp.json()["claims"][0]["id"]

    failing = StaticEvidenceProvider(
        error=EvidenceProviderAPIError("upstream exploded with secret kvly-123")
    )
    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider", return_value=failing
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert "failed" in detail.lower()
    assert "kvly-123" not in resp.text  # provider internals never leak

    timeout = StaticEvidenceProvider(error=EvidenceProviderAPIError("timeout"))
    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider", return_value=timeout
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text
    assert await fetch_evidence(claim_id) == []

    print("provider failure returns safe 502: PASSED")


async def test_evidence_empty_search_result(client):
    token = await register_and_login(client, unique_email("nores"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    claim_id = resp.json()["claims"][0]["id"]

    empty = StaticEvidenceProvider(results=[])
    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider", return_value=empty
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["evidence"] == []
    assert empty.calls == 1
    assert await fetch_evidence(claim_id) == []

    # nothing stored, so a later request searches again
    with unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider", return_value=empty
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/evidence/retrieve", headers=auth(token)
        )
    assert resp.status_code == 200
    assert empty.calls == 2

    print("empty search result handled without errors: PASSED")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    app = await setup()
    async with client_for(app) as client:
        await test_claim_and_evidence_model_creation(client)

        test_parse_valid_json_and_fences()
        test_parse_invalid_json_and_missing_fields()
        test_claim_type_validation()

        await test_extraction_with_mocked_llm(client)
        await test_extraction_invalid_llm_json(client)
        await test_extraction_duplicate_protection(client)
        await test_extraction_empty_llm_list(client)
        await test_extraction_rejected_on_empty_debate(client)

        await test_claim_ownership_authorization(client)
        await test_claim_list_endpoint(client)

        test_evidence_provider_abstraction()
        await test_tavily_provider_mocked_http()

        await test_evidence_retrieve_persists_and_caches(client)
        await test_evidence_ownership_authorization(client)
        await test_evidence_provider_missing_key(client)
        await test_evidence_provider_failure(client)
        await test_evidence_empty_search_result(client)

    await teardown()
    print("\nAll Module 8 (claims + evidence) tests PASSED!")

    print("\nRegression: Module 2 (authentication)...")
    from tests import test_auth

    await test_auth.main()

    print("\nRegression: Module 5 (debate creation + agent selection)...")
    from tests import test_debates

    await test_debates.main()


if __name__ == "__main__":
    asyncio.run(main())
