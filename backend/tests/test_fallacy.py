import asyncio
import json
import os
import subprocess
import sys
import unittest.mock
import uuid
from datetime import datetime, timezone

import httpx
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.llm.base import LLMProviderAPIError, LLMResponse
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.models.fallacy import FALLACY_TYPES, Fallacy
from app.services.argument_evaluation import (
    ArgumentEvaluationError,
    parse_evaluation_payload,
)
from app.services.fallacy_detection import (
    FallacyDetectionError,
    parse_fallacy_payload,
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
STRAW_MAN_TEXT = (
    "My opponent wants to ban all technology and drag us back to the "
    "stone age, which proves their plan is ridiculous."
)


async def seed_completed_debate(client, token, content2: str | None = None) -> dict:
    resp = await client.post(
        "/api/v1/debates", json=base_payload(), headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    debate_id = uuid.UUID(resp.json()["id"])

    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        debate.status = "completed"
        debate.started_at = datetime.now(timezone.utc)
        debate.completed_at = datetime.now(timezone.utc)
        agents = list(debate.agents)
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
            content=content2 or ARGUMENT_TEXT,
        )
        session.add_all([message_one, message_two])
        await session.commit()
        return {
            "id": str(debate_id),
            "message_ids": [str(message_one.id), str(message_two.id)],
        }


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


class FailingLLM:
    """LLM provider stand-in that raises like a provider outage."""

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        raise LLMProviderAPIError("The LLM provider request failed.")


def fallacy_json(
    fallacy_type: str = "straw_man",
    severity: str = "medium",
    confidence=0.87,
    explanation: str = (
        "The response reframes the opposing position into a stronger claim "
        "that was not actually made."
    ),
    evidence_span: str | None = "drag us back to the stone age",
) -> str:
    return json.dumps(
        {
            "fallacy_type": fallacy_type,
            "severity": severity,
            "confidence": confidence,
            "explanation": explanation,
            "evidence_span": evidence_span,
        }
    )


def evaluation_json(
    logical=8, evidence=7, relevance=9, effectiveness=8, overall=8.0,
    explanation: str = "Clear structure with concrete examples and on-topic reasoning.",
) -> str:
    return json.dumps(
        {
            "logical_soundness": logical,
            "evidence_score": evidence,
            "relevance_score": relevance,
            "effectiveness_score": effectiveness,
            "overall_score": overall,
            "explanation": explanation,
        }
    )


async def fetch_fallacies(debate_id: str) -> list[Fallacy]:
    async with _test_session() as session:
        rows = await session.execute(
            select(Fallacy).where(Fallacy.debate_id == uuid.UUID(debate_id))
        )
        return list(rows.scalars().all())


async def fetch_evaluations(debate_id: str) -> list[ArgumentEvaluation]:
    async with _test_session() as session:
        rows = await session.execute(
            select(ArgumentEvaluation).where(
                ArgumentEvaluation.debate_id == uuid.UUID(debate_id)
            )
        )
        return list(rows.scalars().all())


async def seed_claim_for_message(message_id: str) -> str:
    async with _test_session() as session:
        message = await session.get(DebateMessage, uuid.UUID(message_id))
        claim = Claim(
            debate_id=message.debate_id,
            message_id=message.id,
            agent_id=message.agent_id,
            text="Global temperatures have increased over the last century.",
            claim_type="factual",
            position=0,
        )
        session.add(claim)
        await session.flush()
        verification = ClaimVerification(
            claim_id=claim.id,
            verdict="supported",
            confidence="medium",
            explanation="The retrieved sources are consistent with the claim.",
            evidence_summary="Two climate reports confirm the warming trend.",
            evidence_ids=[],
        )
        evidence = Evidence(
            claim_id=claim.id,
            title="Climate trends report",
            url="https://example.org/climate/trends",
            snippet="Observations confirm rising temperatures.",
            source_name="example.org",
            relevance_score=0.9,
            position=0,
        )
        session.add_all([verification, evidence])
        await session.commit()
        return str(claim.id)


# ---------------------------------------------------------------------------
# STEP 2-7: model + payload parsing and validation
# ---------------------------------------------------------------------------


def test_parse_valid_fallacy_payload():
    parsed = parse_fallacy_payload(fallacy_json())
    assert parsed.fallacy_type == "straw_man"
    assert parsed.severity == "medium"
    assert parsed.confidence == 0.87
    assert parsed.evidence_span == "drag us back to the stone age"

    fenced = "```json\n" + fallacy_json(fallacy_type="Red Herring") + "\n```"
    parsed = parse_fallacy_payload(fenced)
    assert parsed.fallacy_type == "red_herring"

    parsed = parse_fallacy_payload(
        fallacy_json(fallacy_type="ad hominem", severity="High", confidence="0.5")
    )
    assert parsed.fallacy_type == "ad_hominem"
    assert parsed.severity == "high"
    assert parsed.confidence == 0.5

    print("parse: valid fallacy JSON and aliases: PASSED")


def test_no_fallacy_detection():
    parsed = parse_fallacy_payload(
        fallacy_json(
            fallacy_type="no_fallacy",
            severity="low",
            confidence=0.91,
            explanation="The argument does not show a clear recognizable logical fallacy.",
            evidence_span=None,
        )
    )
    assert parsed.fallacy_type == "no_fallacy"
    assert parsed.evidence_span is None

    # A stray span on a no_fallacy result is dropped, not kept.
    parsed = parse_fallacy_payload(
        fallacy_json(fallacy_type="no fallacy", evidence_span="something")
    )
    assert parsed.fallacy_type == "no_fallacy"
    assert parsed.evidence_span is None

    print("parse: no_fallacy preferred result handled: PASSED")


def test_each_major_fallacy_type():
    for fallacy_type in FALLACY_TYPES:
        parsed = parse_fallacy_payload(fallacy_json(fallacy_type=fallacy_type))
        assert parsed.fallacy_type == fallacy_type, fallacy_type
    print("parse: every controlled fallacy type accepted: PASSED")


def test_confidence_validation():
    for value in (0, 1, 0.5, "0.25"):
        parsed = parse_fallacy_payload(fallacy_json(confidence=value))
        assert 0.0 <= parsed.confidence <= 1.0

    for value in (-0.1, 1.5, 87, "abc", True, None):
        try:
            parse_fallacy_payload(fallacy_json(confidence=value))
        except FallacyDetectionError:
            continue
        raise AssertionError(f"confidence {value!r} should be rejected")

    print("confidence validation (0-1, rejects invalid): PASSED")


def test_severity_validation():
    for severity in ("low", "medium", "high", "Moderate", "severe"):
        parsed = parse_fallacy_payload(fallacy_json(severity=severity))
        assert parsed.severity in ("low", "medium", "high")

    for severity in ("critical", 42, None, "catastrophic"):
        try:
            parse_fallacy_payload(fallacy_json(severity=severity))
        except FallacyDetectionError:
            continue
        raise AssertionError(f"severity {severity!r} should be rejected")

    print("severity validation (low/medium/high, rejects invalid): PASSED")


def test_invalid_json_and_missing_fields():
    for raw in (
        "Sorry, I cannot produce JSON right now.",
        "",
        '["not", "an", "object"]',
        '{"fallacy_type": "straw_man"}',
    ):
        try:
            parse_fallacy_payload(raw)
        except FallacyDetectionError:
            continue
        raise AssertionError(f"payload {raw!r} should be rejected")

    print("invalid JSON and missing fields rejected: PASSED")


def test_invalid_fallacy_type():
    for fallacy_type in ("banana", "totally_made_up", 42, ""):
        try:
            parse_fallacy_payload(fallacy_json(fallacy_type=fallacy_type))
        except FallacyDetectionError:
            continue
        raise AssertionError(f"fallacy_type {fallacy_type!r} should be rejected")

    print("invalid fallacy types rejected: PASSED")


# ---------------------------------------------------------------------------
# STEP 13-15: evaluation payload parsing and validation
# ---------------------------------------------------------------------------


def test_parse_valid_evaluation():
    parsed = parse_evaluation_payload(evaluation_json())
    assert parsed.logical_soundness == 8.0
    assert parsed.overall_score == 8.0
    assert parsed.relevance_score == 9.0

    fenced = "```json\n" + evaluation_json() + "\n```"
    parsed = parse_evaluation_payload(fenced)
    assert parsed.evidence_score == 7.0

    parsed = parse_evaluation_payload(
        evaluation_json(logical="6.5", evidence="0", effectiveness="10")
    )
    assert parsed.logical_soundness == 6.5
    assert parsed.evidence_score == 0.0
    assert parsed.effectiveness_score == 10.0

    print("parse: valid evaluation JSON (0-10 scores): PASSED")


def test_invalid_evaluation_scores():
    for overrides in (
        {"logical": 15},
        {"logical": -1},
        {"overall": 11.5},
        {"relevance": "abc"},
        {"evidence": None},
        {"effectiveness": True},
    ):
        try:
            parse_evaluation_payload(evaluation_json(**overrides))
        except ArgumentEvaluationError:
            continue
        raise AssertionError(f"scores {overrides} should be rejected")

    for raw in ("no json here", "", '{"logical_soundness": 8}'):
        try:
            parse_evaluation_payload(raw)
        except ArgumentEvaluationError:
            continue
        raise AssertionError(f"payload {raw!r} should be rejected")

    print("invalid evaluation scores and JSON rejected: PASSED")


# ---------------------------------------------------------------------------
# STEP 9-12: fallacy endpoints
# ---------------------------------------------------------------------------


async def test_message_fallacy_analysis_with_mocked_llm(client):
    token = await register_and_login(client, unique_email("fallacy"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(fallacy_json())

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{debate['message_ids'][1]}/fallacies/analyze",
            headers=auth(token),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallacy_type"] == "straw_man"
    assert body["severity"] == "medium"
    assert body["confidence"] == 0.87
    assert body["id"], body
    assert body["message_id"] == debate["message_ids"][1]
    assert body["agent_name"]
    assert body["explanation"]
    assert body["evidence_span"] == "drag us back to the stone age"
    assert fake.calls == 1
    assert fake.last_messages[0].role == "system"

    stored = await fetch_fallacies(debate["id"])
    assert len(stored) == 1
    assert stored[0].fallacy_type == "straw_man"
    assert stored[0].message_id == uuid.UUID(debate["message_ids"][1])

    print("POST message fallacy analysis persists a real fallacy: PASSED")


async def test_no_fallacy_not_persisted(client):
    token = await register_and_login(client, unique_email("nofallacy"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(
        fallacy_json(
            fallacy_type="no_fallacy",
            severity="low",
            confidence=0.91,
            explanation="The argument does not show a clear recognizable logical fallacy.",
            evidence_span=None,
        )
    )

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{debate['message_ids'][0]}/fallacies/analyze",
            headers=auth(token),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallacy_type"] == "no_fallacy"
    assert body["id"] is None
    assert body["evidence_span"] is None
    assert "clear" in body["explanation"].lower()

    assert await fetch_fallacies(debate["id"]) == []

    get_resp = await client.get(
        f"/api/v1/debates/{debate['id']}/fallacies", headers=auth(token)
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["fallacies"] == []

    print("no_fallacy result shown but never persisted: PASSED")


async def test_debate_fallacy_analysis_endpoint(client):
    token = await register_and_login(client, unique_email("fallall"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(fallacy_json())

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/fallacies/analyze",
            headers=auth(token),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["analyzed_count"] == 2, body
    assert len(body["fallacies"]) == 2
    assert fake.calls == 2
    assert all(item["fallacy_type"] == "straw_man" for item in body["fallacies"])

    stored = await fetch_fallacies(debate["id"])
    assert len(stored) == 2
    assert {row.message_id for row in stored} == {
        uuid.UUID(mid) for mid in debate["message_ids"]
    }

    print("POST debate fallacy analysis analyzes every message: PASSED")


async def test_fallacy_duplicate_protection(client):
    token = await register_and_login(client, unique_email("dupe"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(fallacy_json())
    message_id = debate["message_ids"][0]

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        first = await client.post(
            f"/api/v1/messages/{message_id}/fallacies/analyze", headers=auth(token)
        )
        second = await client.post(
            f"/api/v1/messages/{message_id}/fallacies/analyze", headers=auth(token)
        )
        third = await client.post(
            f"/api/v1/debates/{debate['id']}/fallacies/analyze", headers=auth(token)
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert third.status_code == 200, third.text

    stored = await fetch_fallacies(debate["id"])
    # One row per message+type: repeats replace instead of appending.
    assert len(stored) == 2, [str(row.id) for row in stored]
    assert len({row.message_id for row in stored}) == 2

    print("repeated analysis never creates duplicate rows: PASSED")


async def test_fallacy_invalid_llm_output_returns_502(client):
    token = await register_and_login(client, unique_email("f502"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM("Sorry, I cannot produce JSON right now.")

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{debate['message_ids'][0]}/fallacies/analyze",
            headers=auth(token),
        )
    assert resp.status_code == 502, resp.text
    assert "internal error" not in resp.json()["detail"].lower()
    assert await fetch_fallacies(debate["id"]) == []

    print("invalid fallacy LLM output returns 502, nothing stored: PASSED")


async def test_fallacy_provider_failure_returns_502(client):
    token = await register_and_login(client, unique_email("fprov"))
    debate = await seed_completed_debate(client, token)

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider",
        return_value=FailingLLM(),
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/fallacies/analyze",
            headers=auth(token),
        )
    assert resp.status_code == 502, resp.text
    assert "internal error" not in resp.json()["detail"].lower()
    assert await fetch_fallacies(debate["id"]) == []

    print("fallacy provider outage returns 502 atomically: PASSED")


async def test_fallacy_debate_ownership(client):
    owner_token = await register_and_login(client, unique_email("fown"))
    other_token = await register_and_login(client, unique_email("fother"))
    debate = await seed_completed_debate(client, owner_token)
    fake = FakeLLM(fallacy_json())

    # GET by a non-owner -> 404
    resp = await client.get(
        f"/api/v1/debates/{debate['id']}/fallacies", headers=auth(other_token)
    )
    assert resp.status_code == 404, resp.text

    # POST analyze on someone else's debate -> 404 and no LLM call
    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/fallacies/analyze",
            headers=auth(other_token),
        )
    assert resp.status_code == 404, resp.text
    assert fake.calls == 0
    assert await fetch_fallacies(debate["id"]) == []

    print("debate ownership enforced on fallacy endpoints: PASSED")


async def test_fallacy_message_ownership(client):
    owner_token = await register_and_login(client, unique_email("mown"))
    other_token = await register_and_login(client, unique_email("mother"))
    debate = await seed_completed_debate(client, owner_token)
    fake = FakeLLM(fallacy_json())
    message_id = debate["message_ids"][0]

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{message_id}/fallacies/analyze",
            headers=auth(other_token),
        )
    assert resp.status_code == 404, resp.text
    assert fake.calls == 0
    assert await fetch_fallacies(debate["id"]) == []

    print("message ownership enforced through the debate owner: PASSED")


async def test_get_fallacies_deterministic_and_llm_free(client):
    token = await register_and_login(client, unique_email("fget"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(fallacy_json(fallacy_type="straw_man"))

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider", return_value=fake
    ):
        await client.post(
            f"/api/v1/debates/{debate['id']}/fallacies/analyze",
            headers=auth(token),
        )
    calls_after_analyze = fake.calls

    resp = await client.get(
        f"/api/v1/debates/{debate['id']}/fallacies", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debate_id"] == debate["id"]
    assert len(body["fallacies"]) == 2
    first = body["fallacies"]
    assert all(item["id"] for item in first)
    assert all(item["agent_name"] for item in first)
    assert all(item["severity"] in ("low", "medium", "high") for item in first)
    # GET is a pure database read: no additional LLM call.
    assert fake.calls == calls_after_analyze

    resp_again = await client.get(
        f"/api/v1/debates/{debate['id']}/fallacies", headers=auth(token)
    )
    assert [item["id"] for item in resp_again.json()["fallacies"]] == [
        item["id"] for item in first
    ]

    print("GET fallacies is deterministic and never calls the LLM: PASSED")


async def test_fallacy_analysis_on_empty_debate(client):
    token = await register_and_login(client, unique_email("fempty"))
    resp = await client.post(
        "/api/v1/debates", json=base_payload(), headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    debate_id = resp.json()["id"]

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider",
        return_value=FakeLLM(fallacy_json()),
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate_id}/fallacies/analyze", headers=auth(token)
        )
    assert resp.status_code == 400, resp.text

    print("analyzing a debate without messages returns 400: PASSED")


async def test_fallacy_missing_message_returns_404(client):
    token = await register_and_login(client, unique_email("fmiss"))
    missing = str(uuid.uuid4())

    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider",
        return_value=FakeLLM(fallacy_json()),
    ):
        resp = await client.post(
            f"/api/v1/messages/{missing}/fallacies/analyze", headers=auth(token)
        )
    assert resp.status_code == 404, resp.text

    print("missing message returns 404 for fallacy analysis: PASSED")


async def test_fallacy_model_and_unique_constraints(client):
    token = await register_and_login(client, unique_email("fmodel"))
    debate = await seed_completed_debate(client, token)
    message_id = uuid.UUID(debate["message_ids"][0])

    async with _test_session() as session:
        message = await session.get(DebateMessage, message_id)
        row = Fallacy(
            debate_id=message.debate_id,
            message_id=message.id,
            agent_id=message.agent_id,
            fallacy_type="bandwagon",
            severity="low",
            confidence=0.6,
            explanation="Everyone agrees, so it must be true.",
            evidence_span=None,
        )
        session.add(row)
        await session.commit()

        # Same message + type is rejected by the unique constraint.
        session.add(
            Fallacy(
                debate_id=message.debate_id,
                message_id=message.id,
                agent_id=message.agent_id,
                fallacy_type="bandwagon",
                severity="high",
                confidence=0.9,
                explanation="Duplicate attempt.",
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        else:
            raise AssertionError("duplicate message+type row should be rejected")

    print("fallacy model and unique constraint enforced: PASSED")


# ---------------------------------------------------------------------------
# STEP 17: argument evaluation endpoints
# ---------------------------------------------------------------------------


async def test_post_evaluation_with_mocked_llm(client):
    token = await register_and_login(client, unique_email("eval"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(evaluation_json())
    message_id = debate["message_ids"][0]

    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{message_id}/evaluation", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["logical_soundness"] == 8.0
    assert body["evidence_score"] == 7.0
    assert body["relevance_score"] == 9.0
    assert body["effectiveness_score"] == 8.0
    assert body["overall_score"] == 8.0
    assert body["explanation"]
    assert body["message_id"] == message_id
    assert body["agent_name"]
    assert body["id"]
    assert fake.calls == 1

    stored = await fetch_evaluations(debate["id"])
    assert len(stored) == 1
    assert stored[0].overall_score == 8.0

    print("POST evaluation validates, persists and returns scores: PASSED")


async def test_evaluation_duplicate_protection(client):
    token = await register_and_login(client, unique_email("edupe"))
    debate = await seed_completed_debate(client, token)
    message_id = debate["message_ids"][0]

    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider",
        return_value=FakeLLM(evaluation_json(overall=6.0)),
    ):
        first = await client.post(
            f"/api/v1/messages/{message_id}/evaluation", headers=auth(token)
        )
    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider",
        return_value=FakeLLM(evaluation_json(overall=8.0)),
    ):
        second = await client.post(
            f"/api/v1/messages/{message_id}/evaluation", headers=auth(token)
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    stored = await fetch_evaluations(debate["id"])
    assert len(stored) == 1, "one evaluation row per message"
    assert stored[0].overall_score == 8.0, "re-evaluation updates the row"
    assert first.json()["id"] == second.json()["id"]

    print("re-evaluation updates a single row (no duplicates): PASSED")


async def test_evaluation_invalid_llm_output_returns_502(client):
    token = await register_and_login(client, unique_email("e502"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM('{"logical_soundness": 15, "explanation": "off scale"}')

    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{debate['message_ids'][0]}/evaluation",
            headers=auth(token),
        )
    assert resp.status_code == 502, resp.text
    assert "internal error" not in resp.json()["detail"].lower()
    assert await fetch_evaluations(debate["id"]) == []

    print("invalid evaluation output returns 502, nothing stored: PASSED")


async def test_evaluation_missing_message_returns_404(client):
    token = await register_and_login(client, unique_email("emiss"))
    missing = str(uuid.uuid4())

    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider",
        return_value=FakeLLM(evaluation_json()),
    ):
        resp = await client.post(
            f"/api/v1/messages/{missing}/evaluation", headers=auth(token)
        )
    assert resp.status_code == 404, resp.text

    print("missing message returns 404 for evaluation: PASSED")


async def test_evaluation_ownership(client):
    owner_token = await register_and_login(client, unique_email("eown"))
    other_token = await register_and_login(client, unique_email("eother"))
    debate = await seed_completed_debate(client, owner_token)
    fake = FakeLLM(evaluation_json())
    message_id = debate["message_ids"][0]

    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{message_id}/evaluation", headers=auth(other_token)
        )
    assert resp.status_code == 404, resp.text
    assert fake.calls == 0
    assert await fetch_evaluations(debate["id"]) == []

    resp = await client.get(
        f"/api/v1/debates/{debate['id']}/evaluations", headers=auth(other_token)
    )
    assert resp.status_code == 404, resp.text

    print("evaluation ownership enforced: PASSED")


async def test_get_evaluations_deterministic_and_llm_free(client):
    token = await register_and_login(client, unique_email("eget"))
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(evaluation_json())

    # Empty before any evaluation.
    resp = await client.get(
        f"/api/v1/debates/{debate['id']}/evaluations", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["evaluations"] == []

    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider", return_value=fake
    ):
        for message_id in debate["message_ids"]:
            resp = await client.post(
                f"/api/v1/messages/{message_id}/evaluation", headers=auth(token)
            )
            assert resp.status_code == 200, resp.text
    calls_after = fake.calls

    resp = await client.get(
        f"/api/v1/debates/{debate['id']}/evaluations", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    evaluations = resp.json()["evaluations"]
    assert len(evaluations) == 2
    assert all(item["id"] for item in evaluations)
    assert all(0.0 <= item["overall_score"] <= 10.0 for item in evaluations)
    assert fake.calls == calls_after, "GET must not call the LLM"

    resp_again = await client.get(
        f"/api/v1/debates/{debate['id']}/evaluations", headers=auth(token)
    )
    assert [item["id"] for item in resp_again.json()["evaluations"]] == [
        item["id"] for item in evaluations
    ]

    print("GET evaluations is deterministic and never calls the LLM: PASSED")


async def test_evaluation_uses_stored_claim_context(client):
    token = await register_and_login(client, unique_email("ectx"))
    debate = await seed_completed_debate(client, token)
    await seed_claim_for_message(debate["message_ids"][0])
    fake = FakeLLM(evaluation_json())

    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/messages/{debate['message_ids'][0]}/evaluation",
            headers=auth(token),
        )
    assert resp.status_code == 200, resp.text
    prompt = fake.last_messages[1].content
    assert "Stored context for claims" in prompt
    assert "Global temperatures have increased" in prompt
    assert "supported" in prompt
    assert "Climate trends report" in prompt

    print("evaluation uses stored claim/evidence context as reference: PASSED")


async def test_verification_still_intact_after_analysis(client):
    """Module 9 verification results are untouched by Module 10."""
    token = await register_and_login(client, unique_email("vkeep"))
    debate = await seed_completed_debate(client, token)

    # Store a claim + evidence + verification (Module 8/9 flow, mocked LLMs).
    claims_payload = json.dumps(
        [
            {
                "message_id": debate["message_ids"][0],
                "claim": "Global temperatures have increased over the last century.",
                "claim_type": "factual",
            }
        ]
    )
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider",
        return_value=FakeLLM(claims_payload),
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    claim_id = resp.json()["claims"][0]["id"]

    async with _test_session() as session:
        session.add(
            Evidence(
                claim_id=uuid.UUID(claim_id),
                title="Climate trends report",
                url="https://example.org/climate/trends",
                snippet="Observations confirm rising temperatures.",
                source_name="example.org",
                relevance_score=0.9,
                position=0,
            )
        )
        await session.commit()

    verification_payload = json.dumps(
        {
            "verdict": "supported",
            "confidence": "medium",
            "explanation": "The retrieved sources are consistent with the claim.",
            "evidence_summary": "One climate report confirms the trend.",
        }
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=FakeLLM(verification_payload),
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    verdict_before = resp.json()["verdict"]

    # Run Module 10 analysis on the same debate.
    with unittest.mock.patch(
        "app.services.fallacy_detection.get_llm_provider",
        return_value=FakeLLM(fallacy_json()),
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/fallacies/analyze",
            headers=auth(token),
        )
    assert resp.status_code == 200, resp.text
    with unittest.mock.patch(
        "app.services.argument_evaluation.get_llm_provider",
        return_value=FakeLLM(evaluation_json()),
    ):
        resp = await client.post(
            f"/api/v1/messages/{debate['message_ids'][0]}/evaluation",
            headers=auth(token),
        )
    assert resp.status_code == 200, resp.text

    # Claim, evidence and verification results are unchanged.
    resp = await client.get(f"/api/v1/debates/{debate['id']}/claims", headers=auth(token))
    assert resp.status_code == 200
    assert len(resp.json()["claims"]) == 1
    resp = await client.get(
        f"/api/v1/claims/{claim_id}/verification", headers=auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["verdict"] == verdict_before
    resp = await client.get(f"/api/v1/claims/{claim_id}/evidence", headers=auth(token))
    assert resp.status_code == 200
    assert len(resp.json()["evidence"]) == 1

    print("claims/evidence/verification unaffected by Module 10: PASSED")


async def main():
    app = await setup()
    async with client_for(app) as client:
        test_parse_valid_fallacy_payload()
        test_no_fallacy_detection()
        test_each_major_fallacy_type()
        test_confidence_validation()
        test_severity_validation()
        test_invalid_json_and_missing_fields()
        test_invalid_fallacy_type()

        test_parse_valid_evaluation()
        test_invalid_evaluation_scores()

        await test_fallacy_model_and_unique_constraints(client)
        await test_message_fallacy_analysis_with_mocked_llm(client)
        await test_no_fallacy_not_persisted(client)
        await test_debate_fallacy_analysis_endpoint(client)
        await test_fallacy_duplicate_protection(client)
        await test_fallacy_invalid_llm_output_returns_502(client)
        await test_fallacy_provider_failure_returns_502(client)
        await test_fallacy_debate_ownership(client)
        await test_fallacy_message_ownership(client)
        await test_get_fallacies_deterministic_and_llm_free(client)
        await test_fallacy_analysis_on_empty_debate(client)
        await test_fallacy_missing_message_returns_404(client)

        await test_post_evaluation_with_mocked_llm(client)
        await test_evaluation_duplicate_protection(client)
        await test_evaluation_invalid_llm_output_returns_502(client)
        await test_evaluation_missing_message_returns_404(client)
        await test_evaluation_ownership(client)
        await test_get_evaluations_deterministic_and_llm_free(client)
        await test_evaluation_uses_stored_claim_context(client)

        await test_verification_still_intact_after_analysis(client)

    await teardown()
    print("\nAll Module 10 (fallacy detection + argument evaluation) tests PASSED!")

    print("\nRegression: Module 2 (authentication)...")
    from tests import test_auth

    await test_auth.main()

    print("\nRegression: Module 3 (LLM provider + agents)...")
    from tests import test_llm

    await test_llm.main()

    print("\nRegression: Module 5 (debate creation + agent selection)...")
    from tests import test_debates

    await test_debates.main()

    print("\nRegression: Module 6 (debate orchestration)...")
    from tests import test_orchestration

    await test_orchestration.main()

    print("\nRegression: Module 7 (WebSocket streaming)...")
    # test_websocket.main() drives its own event loops with asyncio.run, so
    # it cannot run inside this async main: execute it as a subprocess.
    websocket_run = subprocess.run([sys.executable, "-m", "tests.test_websocket"])
    assert websocket_run.returncode == 0, "test_websocket regression failed"

    print("\nRegression: Module 8 (claims + evidence)...")
    from tests import test_claims

    await test_claims.main()

    print("\nRegression: Module 9 (claim verification)...")
    from tests import test_verification

    await test_verification.main()


if __name__ == "__main__":
    asyncio.run(main())
