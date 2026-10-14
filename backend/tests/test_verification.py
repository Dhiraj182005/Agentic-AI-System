import asyncio
import json
import os
import unittest.mock
import uuid
from datetime import datetime, timezone

import httpx
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.llm.base import LLMProviderAPIError, LLMResponse
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.services.verification_service import (
    ClaimVerificationError,
    VerificationOutput,
    assert_sources_stored,
    parse_verification_payload,
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
            content=ARGUMENT_TEXT,
        )
        session.add_all([message_one, message_two])
        await session.commit()
        return {
            "id": str(debate_id),
            "message_ids": [str(message_one.id), str(message_two.id)],
        }


def claims_payload(message_ids: list[str]) -> str:
    m1 = message_ids[0]
    return json.dumps(
        [
            {
                "message_id": m1,
                "claim": "Global temperatures have increased over the last century.",
                "claim_type": "factual",
            }
        ]
    )


async def seed_claim_and_extract(client, token) -> tuple[str, dict]:
    """Create a completed debate and extract one factual claim via mocked LLM."""
    debate = await seed_completed_debate(client, token)
    fake = FakeLLM(claims_payload(debate["message_ids"]))
    with unittest.mock.patch(
        "app.services.claim_extraction.get_llm_provider", return_value=fake
    ):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/claims/extract",
            headers=auth(token),
        )
    assert resp.status_code == 200, resp.text
    claims = resp.json()["claims"]
    assert len(claims) == 1, claims
    return claims[0]["id"], debate


def sample_evidence() -> list[dict]:
    return [
        {
            "title": "Climate trends report",
            "url": "https://example.org/climate/trends",
            "snippet": "Observations confirm global average temperatures have risen since 1900.",
            "source_name": "example.org",
            "relevance_score": 0.9,
        },
        {
            "title": "Energy market outlook",
            "url": "https://example.com/energy/2030",
            "snippet": "Independent datasets report the same long-term warming trend.",
            "source_name": "example.com",
            "relevance_score": 0.8,
        },
    ]


async def seed_evidence(claim_id: str, items: list[dict] | None = None) -> list[str]:
    items = items if items is not None else sample_evidence()
    stored_ids = []
    async with _test_session() as session:
        for position, item in enumerate(items):
            evidence_id = uuid.uuid4()
            evidence = Evidence(
                id=evidence_id,
                claim_id=uuid.UUID(claim_id),
                position=position,
                **item,
            )
            session.add(evidence)
            stored_ids.append(evidence_id)
        await session.commit()
    return [str(i) for i in stored_ids]


async def fetch_verifications(claim_id: str) -> list[ClaimVerification]:
    async with _test_session() as session:
        rows = await session.execute(
            select(ClaimVerification).where(
                ClaimVerification.claim_id == uuid.UUID(claim_id)
            )
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


def verification_json(
    verdict: str,
    confidence: str = "medium",
    explanation: str = "The retrieved sources are consistent with the claim.",
    summary: str = "The provided sources discuss the claim topic.",
) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "confidence": confidence,
            "explanation": explanation,
            "evidence_summary": summary,
        }
    )


# ---------------------------------------------------------------------------
# 1-2. Model + migration
# ---------------------------------------------------------------------------


async def test_verification_model_and_migration(client):
    async with _test_session() as session:
        rows = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = 'claim_verifications'"
            )
        )
        assert rows.scalar() == "claim_verifications"

        rows = await session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname = 'uq_claim_verifications_claim_id'"
            )
        )
        assert rows.scalar() == "uq_claim_verifications_claim_id"

        rows = await session.execute(
            text(
                "SELECT typname FROM pg_type "
                "WHERE typname IN ('claim_verdict_enum', "
                "'verification_confidence_enum')"
            )
        )
        assert len(rows.all()) == 2

    # model read/write with a real claim row
    token = await register_and_login(client, unique_email("vmodel"))
    debate = await seed_completed_debate(client, token)
    async with _test_session() as session:
        message = (
            (
                await session.execute(
                    select(DebateMessage)
                    .where(DebateMessage.debate_id == uuid.UUID(debate["id"]))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        claim = Claim(
            debate_id=uuid.UUID(debate["id"]),
            message_id=message.id,
            agent_id=message.agent_id,
            text="Model verification claim.",
            claim_type="factual",
            position=0,
        )
        session.add(claim)
        await session.flush()

        verification = ClaimVerification(
            claim_id=claim.id,
            verdict="supported",
            confidence="medium",
            explanation="Stored explanation.",
            evidence_summary="Stored summary.",
            evidence_ids=[],
        )
        session.add(verification)
        await session.commit()

        rows = await session.execute(
            select(ClaimVerification).where(
                ClaimVerification.claim_id == claim.id
            )
        )
        stored = rows.scalar_one()
        assert stored.verdict == "supported"
        assert stored.confidence == "medium"
        assert stored.explanation == "Stored explanation."
        assert stored.evidence_ids == []
        assert stored.created_at is not None
        assert stored.updated_at is not None
        stored_id = stored.id
        claim_pk = claim.id

        # uniqueness: one current result per claim (Option A)
        session.add(
            ClaimVerification(
                claim_id=claim_pk,
                verdict="contradicted",
                confidence="low",
                explanation="Duplicate.",
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        else:
            raise AssertionError("expected unique constraint on claim_id")

        rows = await session.execute(
            select(ClaimVerification).where(
                ClaimVerification.claim_id == claim_pk
            )
        )
        kept = rows.scalars().all()
        assert len(kept) == 1 and kept[0].id == stored_id

    print("ClaimVerification model + migration parity + uniqueness: PASSED")


# ---------------------------------------------------------------------------
# 3. Structured output validation (STEP 8)
# ---------------------------------------------------------------------------


def test_parse_verification_payload():
    parsed = parse_verification_payload(
        verification_json("supported", "high")
    )
    assert parsed.verdict == "supported"
    assert parsed.confidence == "high"

    fenced = f"```json\n{verification_json('contradicted')}\n```"
    parsed = parse_verification_payload(fenced)
    assert parsed.verdict == "contradicted"

    # alias normalization
    parsed = parse_verification_payload(
        verification_json("Insufficient Evidence", "MED")
    )
    assert parsed.verdict == "insufficient_evidence"
    assert parsed.confidence == "medium"

    # missing evidence_summary defaults to empty
    parsed = parse_verification_payload(
        json.dumps({"verdict": "supported", "confidence": "low", "explanation": "ok"})
    )
    assert parsed.evidence_summary == ""

    for bad in ("", "no json here", '{"not": "an object"}'):
        try:
            parse_verification_payload(bad)
        except ClaimVerificationError:
            pass
        else:
            raise AssertionError(f"expected ClaimVerificationError for {bad!r}")

    try:
        parse_verification_payload("```json\nnot json\n```")
    except ClaimVerificationError:
        pass
    else:
        raise AssertionError("expected ClaimVerificationError for malformed JSON")

    # invalid verdict / confidence / empty or missing explanation
    for bad_payload in (
        {"verdict": "true", "confidence": "high", "explanation": "x"},
        {"verdict": "supported", "confidence": "extreme", "explanation": "x"},
        {"verdict": "supported", "confidence": "high", "explanation": "   "},
        {"verdict": "supported", "confidence": "high"},
        {"verdict": 42, "confidence": "high", "explanation": "x"},
        {"confidence": "high", "explanation": "x"},
    ):
        try:
            parse_verification_payload(json.dumps(bad_payload))
        except ClaimVerificationError:
            pass
        else:
            raise AssertionError(
                f"expected ClaimVerificationError for {bad_payload}"
            )

    print("verification payload parsing and validation: PASSED")


# ---------------------------------------------------------------------------
# 4. Evidence-only rule (STEP 6)
# ---------------------------------------------------------------------------


def test_sources_must_be_stored():
    evidence_items = sample_evidence()
    evidence = [
        Evidence(
            claim_id=uuid.uuid4(),
            title=item["title"],
            url=item["url"],
            snippet=item["snippet"],
            source_name=item["source_name"],
            position=position,
        )
        for position, item in enumerate(evidence_items)
    ]

    ok = VerificationOutput(
        verdict="supported",
        confidence="medium",
        explanation="See https://example.org/climate/trends for details.",
        evidence_summary="",
    )
    assert_sources_stored(ok, evidence)

    ok_www = VerificationOutput(
        verdict="supported",
        confidence="low",
        explanation="As reported by www.example.com the trend holds.",
        evidence_summary="",
    )
    assert_sources_stored(ok_www, evidence)

    fabricated = VerificationOutput(
        verdict="supported",
        confidence="high",
        explanation="See https://fabricated-news.example.net/study for proof.",
        evidence_summary="",
    )
    try:
        assert_sources_stored(fabricated, evidence)
    except ClaimVerificationError:
        pass
    else:
        raise AssertionError(
            "expected ClaimVerificationError for a fabricated source URL"
        )

    fabricated_summary = VerificationOutput(
        verdict="contradicted",
        confidence="high",
        explanation="The sources disagree with the claim.",
        evidence_summary="Source: https://invented.example.org/report",
    )
    try:
        assert_sources_stored(fabricated_summary, evidence)
    except ClaimVerificationError:
        pass
    else:
        raise AssertionError(
            "expected ClaimVerificationError for a fabricated summary URL"
        )

    print("verification only references stored evidence: PASSED")


# ---------------------------------------------------------------------------
# 5-8. Service with mocked LLM
# ---------------------------------------------------------------------------


async def test_verification_service_mocked_llm(client):
    token = await register_and_login(client, unique_email("vsvc"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id)

    fake = FakeLLM(verification_json("supported", "medium"))
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "supported"
    assert body["confidence"] == "medium"
    assert body["claim_id"] == claim_id
    assert fake.calls == 1
    assert fake.last_messages[0].role == "system"
    prompt_text = fake.last_messages[1].content
    assert "Global temperatures" in prompt_text
    assert "https://example.org/climate/trends" in prompt_text

    print("verification service with mocked LLM (supported): PASSED")


async def test_verdict_contradicted_and_insufficient(client):
    token = await register_and_login(client, unique_email("vverd"))

    # contradicted
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id)
    fake = FakeLLM(verification_json("contradicted", "high"))
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verdict"] == "contradicted"
    assert resp.json()["confidence"] == "high"

    # insufficient_evidence decided by the LLM
    claim_id_two, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id_two)
    fake = FakeLLM(
        verification_json(
            "insufficient_evidence",
            "low",
            explanation="The provided sources do not establish the claim either way.",
        )
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id_two}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verdict"] == "insufficient_evidence"

    print("contradicted and insufficient verdicts: PASSED")


async def test_conflicting_evidence_not_forced(client):
    token = await register_and_login(client, unique_email("vconf"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(
        claim_id,
        [
            {
                "title": "Study A",
                "url": "https://example.org/study-a",
                "snippet": "Study A finds the effect exists.",
                "source_name": "example.org",
            },
            {
                "title": "Study B",
                "url": "https://example.org/study-b",
                "snippet": "Study B finds no effect at all.",
                "source_name": "example.org",
            },
        ],
    )

    fake = FakeLLM(
        verification_json(
            "insufficient_evidence",
            "low",
            explanation="The provided sources disagree and the snippets do not resolve the conflict.",
            summary="Study A and Study B report opposing findings.",
        )
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verdict"] == "insufficient_evidence"

    stored = await fetch_verifications(claim_id)
    assert len(stored) == 1

    print("conflicting evidence maps to insufficient_evidence: PASSED")


async def test_no_evidence_short_circuits_without_llm(client):
    token = await register_and_login(client, unique_email("vnone"))
    claim_id, _ = await seed_claim_and_extract(client, token)

    exploding = unittest.mock.MagicMock()
    exploding.generate = unittest.mock.AsyncMock(
        side_effect=AssertionError("LLM must not be called without evidence")
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=exploding,
    ), unittest.mock.patch(
        "app.services.claim_service.get_evidence_provider",
        side_effect=AssertionError("search provider must not be called"),
    ) as provider_mock:
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "insufficient_evidence"
    assert body["confidence"] == "low"
    assert body["evidence_ids"] == []
    assert "no retrieved sources" in body["explanation"].lower()
    assert provider_mock.call_count == 0

    stored = await fetch_verifications(claim_id)
    assert len(stored) == 1
    assert stored[0].verdict == "insufficient_evidence"

    # GET still works and never calls the LLM
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=exploding,
    ):
        resp = await client.get(
            f"/api/v1/claims/{claim_id}/verification", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verdict"] == "insufficient_evidence"
    assert exploding.generate.await_count == 0

    print("no evidence -> insufficient_evidence without LLM/Tavily: PASSED")


# ---------------------------------------------------------------------------
# 9-10. Invalid LLM output rejected (502, nothing persisted)
# ---------------------------------------------------------------------------


async def test_invalid_llm_output_returns_502(client):
    token = await register_and_login(client, unique_email("vbad"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id)

    for bad in (
        "Sorry, I cannot evaluate this right now.",
        verification_json("true", "high"),
        verification_json("supported", "unbelievable"),
        verification_json("supported", "high", explanation="   "),
        "```json\n{broken json\n```",
    ):
        fake = FakeLLM(bad)
        with unittest.mock.patch(
            "app.services.verification_service.get_llm_provider",
            return_value=fake,
        ):
            resp = await client.post(
                f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
            )
        assert resp.status_code == 502, (bad, resp.text)
        detail = resp.json()["detail"].lower()
        assert "internal error" not in detail
        assert "chain" not in detail

    assert await fetch_verifications(claim_id) == []

    print("invalid LLM JSON/verdict returns 502 without records: PASSED")


async def test_fabricated_source_rejected(client):
    token = await register_and_login(client, unique_email("vfabric"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id)

    fake = FakeLLM(
        verification_json(
            "supported",
            "high",
            explanation="A study at https://invented-journal.example.net/a confirms it.",
        )
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text
    assert await fetch_verifications(claim_id) == []

    print("fabricated source URL rejected before persistence: PASSED")


async def test_llm_provider_failure_returns_502(client):
    token = await register_and_login(client, unique_email("vfail"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id)

    failing = FakeLLM("")
    failing.generate = unittest.mock.AsyncMock(
        side_effect=LLMProviderAPIError("boom secret-groq-key-123")
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=failing,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 502, resp.text
    assert "secret-groq-key-123" not in resp.text
    assert await fetch_verifications(claim_id) == []

    print("LLM provider failure returns safe 502: PASSED")


# ---------------------------------------------------------------------------
# 11-14. Persistence, GET, re-verification
# ---------------------------------------------------------------------------


async def test_verification_persistence_and_get(client):
    token = await register_and_login(client, unique_email("vpersist"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    evidence_ids = await seed_evidence(claim_id)

    fake = FakeLLM(verification_json("supported", "medium"))
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert sorted(str(u) for u in body["evidence_ids"]) == sorted(evidence_ids)
    assert body["created_at"] and body["updated_at"]
    assert body["evidence_summary"]

    stored = await fetch_verifications(claim_id)
    assert len(stored) == 1
    assert stored[0].verdict == "supported"
    assert sorted(str(u) for u in stored[0].evidence_ids) == sorted(evidence_ids)

    # GET reads the stored result and never calls the LLM
    exploding = unittest.mock.MagicMock()
    exploding.generate = unittest.mock.AsyncMock(
        side_effect=AssertionError("GET must not call the LLM")
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=exploding,
    ):
        resp = await client.get(
            f"/api/v1/claims/{claim_id}/verification", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == body["id"]
    assert exploding.generate.await_count == 0

    # GET 404 when the claim was never verified
    claim_id_two, _ = await seed_claim_and_extract(client, token)
    resp = await client.get(
        f"/api/v1/claims/{claim_id_two}/verification", headers=auth(token)
    )
    assert resp.status_code == 404, resp.text

    print("verification persistence + GET endpoint: PASSED")


async def test_reverification_updates_single_row(client):
    token = await register_and_login(client, unique_email("vagain"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id)

    fake_one = FakeLLM(verification_json("supported", "medium"))
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake_one,
    ):
        first = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert first.status_code == 200, first.text

    fake_two = FakeLLM(
        verification_json(
            "contradicted",
            "high",
            explanation="Newly retrieved sources report the opposite outcome.",
        )
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake_two,
    ):
        second = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert second.status_code == 200, second.text
    assert second.json()["verdict"] == "contradicted"
    assert second.json()["id"] == first.json()["id"]

    stored = await fetch_verifications(claim_id)
    assert len(stored) == 1
    assert stored[0].verdict == "contradicted"
    assert stored[0].updated_at >= stored[0].created_at

    print("re-verification updates one current row: PASSED")


# ---------------------------------------------------------------------------
# 15-16. Ownership + authorization
# ---------------------------------------------------------------------------


async def test_verification_ownership_authorization(client):
    owner = await register_and_login(client, unique_email("vowner"))
    other = await register_and_login(client, unique_email("vother"))
    claim_id, _ = await seed_claim_and_extract(client, owner)
    await seed_evidence(claim_id)

    resp = await client.post(f"/api/v1/claims/{claim_id}/verify")
    assert resp.status_code == 401, resp.text

    resp = await client.get(f"/api/v1/claims/{claim_id}/verification")
    assert resp.status_code == 401

    exploding = unittest.mock.MagicMock()
    exploding.generate = unittest.mock.AsyncMock(
        side_effect=AssertionError("other user must not reach the LLM")
    )
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=exploding,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(other)
        )
        assert resp.status_code == 404, resp.text

        resp = await client.get(
            f"/api/v1/claims/{claim_id}/verification", headers=auth(other)
        )
        assert resp.status_code == 404, resp.text

        resp = await client.post(
            f"/api/v1/claims/{uuid.uuid4()}/verify", headers=auth(other)
        )
        assert resp.status_code == 404

        resp = await client.get(
            f"/api/v1/claims/{uuid.uuid4()}/verification", headers=auth(other)
        )
        assert resp.status_code == 404

    assert exploding.generate.await_count == 0
    assert await fetch_verifications(claim_id) == []

    print("verification ownership authorization enforced: PASSED")


async def test_verification_response_has_no_secrets(client):
    token = await register_and_login(client, unique_email("vsec"))
    claim_id, _ = await seed_claim_and_extract(client, token)
    await seed_evidence(claim_id)

    fake = FakeLLM(verification_json("supported"))
    with unittest.mock.patch(
        "app.services.verification_service.get_llm_provider",
        return_value=fake,
    ):
        resp = await client.post(
            f"/api/v1/claims/{claim_id}/verify", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    text_body = resp.text.lower()
    for secret in ("groq", "tvly-", "api_key", "secret", "system prompt"):
        assert secret not in text_body, secret

    print("verification responses leak no secrets or prompts: PASSED")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    app = await setup()
    async with client_for(app) as client:
        await test_verification_model_and_migration(client)

        test_parse_verification_payload()
        test_sources_must_be_stored()

        await test_verification_service_mocked_llm(client)
        await test_verdict_contradicted_and_insufficient(client)
        await test_conflicting_evidence_not_forced(client)
        await test_no_evidence_short_circuits_without_llm(client)

        await test_invalid_llm_output_returns_502(client)
        await test_fabricated_source_rejected(client)
        await test_llm_provider_failure_returns_502(client)

        await test_verification_persistence_and_get(client)
        await test_reverification_updates_single_row(client)

        await test_verification_ownership_authorization(client)
        await test_verification_response_has_no_secrets(client)

    await teardown()
    print("\nAll Module 9 (claim verification) tests PASSED!")

    print("\nRegression: Module 2 (authentication)...")
    from tests import test_auth

    await test_auth.main()

    print("\nRegression: Module 5 (debate creation + agent selection)...")
    from tests import test_debates

    await test_debates.main()

    print("\nRegression: Module 8 (claims + evidence)...")
    from tests import test_claims

    await test_claims.main()


if __name__ == "__main__":
    asyncio.run(main())
