"""Module 11 tests: debate judge + overall scoring.

All LLM calls are mocked (no real Groq / Tavily). Ends with regression runs
of every earlier module's suite.
"""

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

from app.llm.base import LLMResponse
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.models.fallacy import Fallacy
from app.models.judge import DebateJudgment
from app.services import judge_rubric
from app.services.debate_judge_service import parse_judge_payload, JudgeLLMError

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


async def seed_completed_debate(client, token, second_message: bool = True) -> dict:
    """Create a completed two-agent debate with persisted messages."""
    resp = await client.post("/api/v1/debates", json=base_payload(), headers=auth(token))
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
        session.add(message_one)
        await session.flush()
        message_ids = [message_one.id]
        if second_message:
            message_two = DebateMessage(
                debate_id=debate_id,
                round_id=round_two.id,
                agent_id=agents[1].id,
                turn_number=1,
                message_type="argument",
                content=ARGUMENT_TEXT,
            )
            session.add(message_two)
            await session.flush()
            message_ids.append(message_two.id)
        await session.commit()
        return {
            "id": str(debate_id),
            "message_ids": [str(m) for m in message_ids],
            "agent_ids": [str(a.id) for a in agents],
            "agent_names": [a.name for a in agents],
        }


async def add_argument_evaluation(message_id: str, **scores) -> None:
    async with _test_session() as session:
        message = await session.get(DebateMessage, uuid.UUID(message_id))
        session.add(
            ArgumentEvaluation(
                debate_id=message.debate_id,
                message_id=message.id,
                agent_id=message.agent_id,
                logical_soundness=scores.get("logical_soundness", 7.0),
                evidence_score=scores.get("evidence_score", 6.0),
                relevance_score=scores.get("relevance_score", 8.0),
                effectiveness_score=scores.get("effectiveness_score", 7.0),
                overall_score=scores.get("overall_score", 7.0),
                explanation="Structured argument with a clear line of reasoning.",
            )
        )
        await session.commit()


async def add_claim_with_verdict(
    message_id: str, verdict: str, *, with_evidence: bool = False, position: int = 0
) -> None:
    async with _test_session() as session:
        message = await session.get(DebateMessage, uuid.UUID(message_id))
        claim = Claim(
            debate_id=message.debate_id,
            message_id=message.id,
            agent_id=message.agent_id,
            text="Global temperatures have increased over the last century.",
            claim_type="factual",
            position=position,
        )
        session.add(claim)
        await session.flush()
        session.add(
            ClaimVerification(
                claim_id=claim.id,
                verdict=verdict,
                confidence="medium",
                explanation="The retrieved sources are consistent with the claim.",
                evidence_summary="Climate reports confirm the trend.",
                evidence_ids=[],
            )
        )
        if with_evidence:
            session.add(
                Evidence(
                    claim_id=claim.id,
                    title="Climate trends report",
                    url="https://example.org/climate/trends",
                    snippet="Observations confirm rising temperatures.",
                    source_name="example.org",
                    relevance_score=0.9,
                    position=0,
                )
            )
        await session.commit()


async def add_fallacy(
    message_id: str, *, fallacy_type="straw_man", severity="medium", confidence=0.8
) -> None:
    async with _test_session() as session:
        message = await session.get(DebateMessage, uuid.UUID(message_id))
        session.add(
            Fallacy(
                debate_id=message.debate_id,
                message_id=message.id,
                agent_id=message.agent_id,
                fallacy_type=fallacy_type,
                severity=severity,
                confidence=confidence,
                explanation="The response reframes the opposing position.",
                evidence_span="that is what you always say",
            )
        )
        await session.commit()


def judge_json(name_scores: dict, summary: str | None = None) -> str:
    """Build a valid judge LLM response for the given participant names."""
    agents = []
    for name, dims in name_scores.items():
        agents.append(
            {
                "agent_name": name,
                "dimensions": {
                    "logical_soundness": dims.get("logical_soundness", 8.0),
                    "evidence_quality": dims.get("evidence_quality", 7.0),
                    "relevance": dims.get("relevance", 8.0),
                    "effectiveness": dims.get("effectiveness", 7.0),
                    "completeness": dims.get("completeness", 7.0),
                },
                "strengths": ["Clear claim structure"],
                "weaknesses": ["Could cite more sources"],
                "reasoning_quality": "Premises follow from the stated evidence.",
                "evidence_quality_explanation": "Some sources back the main claims.",
                "factual_support_explanation": "Stored verdicts mostly support the claims.",
                "completeness_assessment": "Addresses the main aspects of the topic.",
                "fallacy_impact_assessment": "Only minor rhetorical issues detected.",
                "confidence": "medium",
            }
        )
    return json.dumps(
        {
            "agents": agents,
            "summary": summary
            or "Both agents engaged the topic; evidence use separated them.",
            "limitations": ["Only one round of exchanges was available."],
        }
    )


EQUAL_DIMS = {
    "logical_soundness": 7.0,
    "evidence_quality": 7.0,
    "relevance": 7.0,
    "effectiveness": 7.0,
    "completeness": 7.0,
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
        raise RuntimeError("simulated provider outage")


def patch_provider(fake):
    return unittest.mock.patch(
        "app.services.debate_judge_service.get_llm_provider", return_value=fake
    )


# ---------------------------------------------------------------------------
# Unit tests: rubric formula, bounds, inversion, outcome policy
# ---------------------------------------------------------------------------


def test_score_calculation_and_weights():
    assert abs(sum(judge_rubric.WEIGHTS.values()) - 1.0) < 1e-9
    assert judge_rubric.WEIGHTS["logical_soundness"] == 0.20
    assert judge_rubric.WEIGHTS["evidence_quality"] == 0.20
    assert judge_rubric.WEIGHTS["factual_support"] == 0.15
    assert judge_rubric.WEIGHTS["relevance"] == 0.15
    assert judge_rubric.WEIGHTS["effectiveness"] == 0.10
    assert judge_rubric.WEIGHTS["completeness"] == 0.10
    assert judge_rubric.WEIGHTS["fallacy_risk"] == 0.10

    dims = {
        "logical_soundness": 8.0,
        "evidence_quality": 7.0,
        "factual_support": 6.0,
        "relevance": 9.0,
        "effectiveness": 5.0,
        "completeness": 7.0,
        "fallacy_risk": 3.0,
    }
    expected = (
        0.20 * 8.0
        + 0.20 * 7.0
        + 0.15 * 6.0
        + 0.15 * 9.0
        + 0.10 * 5.0
        + 0.10 * 7.0
        + 0.10 * (10.0 - 3.0)
    )
    assert abs(judge_rubric.compute_agent_score(dims) - expected) < 1e-9

    uniform_value = 8.0
    uniform = {dim: uniform_value for dim in judge_rubric.WEIGHTS}
    # risk inverts to quality: give a risk of 10-value so all effective
    # contributions are equal
    uniform["fallacy_risk"] = 10.0 - uniform_value
    assert abs(judge_rubric.compute_agent_score(uniform) - uniform_value) < 1e-9

    # Unavailable dimensions are excluded and the rest renormalized.
    partial = dict(uniform)
    partial["factual_support"] = None
    partial["fallacy_risk"] = None
    partial_weight = 1.0 - 0.15 - 0.10
    expected_partial = (8.0 * partial_weight) / partial_weight
    assert abs(judge_rubric.compute_agent_score(partial) - expected_partial) < 1e-9


def test_score_bounds_and_rounding():
    assert judge_rubric.clamp_score(-4.0) == 0.0
    assert judge_rubric.clamp_score(42.0) == 10.0

    too_high = {dim: 15.0 for dim in judge_rubric.WEIGHTS}
    too_low = {dim: -5.0 for dim in judge_rubric.WEIGHTS}
    assert 0.0 <= judge_rubric.compute_agent_score(too_high) <= 10.0
    assert 0.0 <= judge_rubric.compute_agent_score(too_low) <= 10.0

    assert judge_rubric.round_final(7.154) == 7.15
    assert judge_rubric.round_final(7.156) == 7.16
    assert judge_rubric.round_final(3.0) == 3.0

    try:
        judge_rubric.compute_agent_score(
            {dim: None for dim in judge_rubric.WEIGHTS}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("all-unavailable dimensions must raise ValueError")


def test_fallacy_risk_inversion():
    base = {
        "logical_soundness": 6.0,
        "evidence_quality": 6.0,
        "factual_support": 6.0,
        "relevance": 6.0,
        "effectiveness": 6.0,
        "completeness": 6.0,
    }
    low_risk = dict(base, fallacy_risk=1.0)
    high_risk = dict(base, fallacy_risk=9.0)
    assert judge_rubric.compute_agent_score(low_risk) > judge_rubric.compute_agent_score(
        high_risk
    )
    assert judge_rubric.fallacy_quality(9.0) == 1.0
    assert judge_rubric.fallacy_quality(0.0) == 10.0

    # Deterministic risk model
    assert judge_rubric.compute_fallacy_risk([], 3) is None
    assert judge_rubric.compute_fallacy_risk([("low", 0.5)], 1) == 2.5
    assert judge_rubric.compute_fallacy_risk([("medium", 1.0)], 2) == 5.0
    assert judge_rubric.compute_fallacy_risk([("high", 1.0)], 1) == 10.0
    # More messages with the same findings dilutes the risk.
    assert judge_rubric.compute_fallacy_risk([("medium", 1.0)], 4) == 2.5


def test_factual_support_from_verdicts():
    assert judge_rubric.compute_factual_support([]) is None
    neutral = judge_rubric.compute_factual_support(
        ["insufficient_evidence", "insufficient_evidence"]
    )
    assert neutral == 5.0, "insufficient evidence must be neutral, never 'supported'"
    supported = judge_rubric.compute_factual_support(["supported", "supported"])
    assert supported == 10.0
    contradicted = judge_rubric.compute_factual_support(["contradicted"])
    assert contradicted == 0.0
    mixed = judge_rubric.compute_factual_support(
        ["supported", "supported", "contradicted"]
    )
    assert supported > mixed > contradicted
    assert abs(mixed - 6.666666) < 0.001


def test_decide_outcome_policy():
    a = uuid.uuid4()
    b = uuid.uuid4()

    outcome, winner = judge_rubric.decide_outcome([(a, 8.5), (b, 7.0)], 0.5, True)
    assert outcome == "winner" and winner == a

    outcome, winner = judge_rubric.decide_outcome([(a, 8.0), (b, 7.75)], 0.5, True)
    assert outcome == "tie" and winner is None

    outcome, winner = judge_rubric.decide_outcome([(a, 8.5), (b, 7.0)], 0.5, False)
    assert outcome == "inconclusive" and winner is None

    outcome, winner = judge_rubric.decide_outcome([(a, 9.0)], 0.5, True)
    assert outcome == "inconclusive" and winner is None


def test_parse_judge_payload():
    payload = json.loads(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    output = parse_judge_payload(json.dumps(payload))
    assert len(output.agents) == 2
    assert output.summary

    # markdown fences are tolerated
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert parse_judge_payload(fenced).agents[0].agent_name == "Economist"

    for bad in ("", "not json at all", '{"agents": [], "summary": "x"}'):
        try:
            parse_judge_payload(bad)
        except JudgeLLMError:
            pass
        else:
            raise AssertionError(f"expected JudgeLLMError for {bad!r}")

    out_of_range = json.loads(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    out_of_range["agents"][0]["dimensions"]["logical_soundness"] = 11
    try:
        parse_judge_payload(json.dumps(out_of_range))
    except JudgeLLMError:
        pass
    else:
        raise AssertionError("expected JudgeLLMError for out-of-range dimension")


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


async def test_judge_endpoint_clear_lead(client):
    token = await register_and_login(client, unique_email("judge-lead"))
    debate = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate["message_ids"][0])

    fake = FakeLLM(
        judge_json(
            {
                "Economist": {
                    "logical_soundness": 9.0,
                    "evidence_quality": 9.0,
                    "relevance": 9.0,
                    "effectiveness": 9.0,
                    "completeness": 9.0,
                },
                "Lawyer": {
                    "logical_soundness": 5.0,
                    "evidence_quality": 4.0,
                    "relevance": 6.0,
                    "effectiveness": 5.0,
                    "completeness": 4.0,
                },
            }
        )
    )
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert fake.calls == 1

    assert body["outcome"] == "winner"
    assert body["winner_name"] == "Economist"
    assert body["winner_agent_id"] is not None
    assert body["status"] == "completed"
    assert 0.0 <= body["overall_score"] <= 10.0

    # scoring rubric snapshot contains the documented weights
    from app.core.config import get_settings

    weights = body["scoring_rubric"]["weights"]
    assert weights == judge_rubric.WEIGHTS
    assert body["scoring_rubric"]["min_score_gap"] == get_settings().JUDGE_MIN_SCORE_GAP
    assert body["scoring_rubric"]["formula"] == judge_rubric.FORMULA_TEXT

    assert len(body["agent_scores"]) == 2
    by_name = {card["agent_name"]: card for card in body["agent_scores"]}
    economist = by_name["Economist"]
    lawyer = by_name["Lawyer"]
    assert economist["final_score"] > lawyer["final_score"]

    # Endpoint-level formula check: stored final_score equals the rubric
    # calculation over the card's own (available) dimensions.
    for card in body["agent_scores"]:
        dims = card["dimensions"]
        expected = judge_rubric.round_final(judge_rubric.compute_agent_score(dims))
        assert abs(card["final_score"] - expected) < 0.005, (
            card["agent_name"],
            card["final_score"],
            expected,
        )

    expected_overall = judge_rubric.round_final(
        (economist["final_score"] + lawyer["final_score"]) / 2
    )
    assert abs(body["overall_score"] - expected_overall) < 0.005

    # strengths/weaknesses and assessments present
    assert economist["strengths"] and economist["weaknesses"]
    assert economist["reasoning_quality"]
    assert economist["factual_support_assessment"]
    assert economist["fallacy_impact_assessment"]
    assert economist["confidence"] in ("low", "medium", "high")


async def test_judge_tie_when_scores_close(client):
    token = await register_and_login(client, unique_email("judge-tie"))
    debate = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate["message_ids"][0])

    fake = FakeLLM(
        judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS})
    )
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "tie"
    assert body["winner_agent_id"] is None
    assert body["winner_name"] is None
    scores = [card["final_score"] for card in body["agent_scores"]]
    assert scores[0] == scores[1]


async def test_judge_inconclusive_when_data_missing(client):
    token = await register_and_login(client, unique_email("judge-inc"))
    debate = await seed_completed_debate(client, token)  # no analyses at all

    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "inconclusive"
    assert body["winner_agent_id"] is None
    assert len(body["agent_scores"]) == 2
    limitations = " ".join(body["limitations"] or [])
    assert "inconclusive" in limitations
    assert "Fallacy analysis has not been run" in limitations
    assert "No claim verification results" in limitations


async def test_judge_factual_support_rules(client):
    token = await register_and_login(client, unique_email("judge-fact"))
    debate = await seed_completed_debate(client, token)
    # Economist: supported + insufficient + contradicted -> neutral-leaning 5.0
    await add_claim_with_verdict(debate["message_ids"][0], "supported")
    await add_claim_with_verdict(debate["message_ids"][0], "insufficient_evidence")
    await add_claim_with_verdict(debate["message_ids"][0], "contradicted")
    # Lawyer: one supported claim with stored evidence
    await add_claim_with_verdict(
        debate["message_ids"][1], "supported", with_evidence=True
    )

    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_name = {card["agent_name"]: card for card in body["agent_scores"]}

    economist_dims = by_name["Economist"]["dimensions"]
    lawyer_dims = by_name["Lawyer"]["dimensions"]
    assert abs(economist_dims["factual_support"] - 5.0) < 0.001, (
        "supported+insufficient+contradicted must net out neutrally - "
        "insufficient is never 'supported'"
    )
    assert lawyer_dims["factual_support"] == 10.0
    assert economist_dims["factual_support"] < lawyer_dims["factual_support"]

    # Evidence availability gates the evidence-quality dimension.
    assert economist_dims["evidence_quality"] is None
    assert "Evidence Quality" in by_name["Economist"]["unavailable_dimensions"]
    assert lawyer_dims["evidence_quality"] == EQUAL_DIMS["evidence_quality"]


async def test_judge_fallacy_dimension(client):
    token = await register_and_login(client, unique_email("judge-fb"))
    debate = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate["message_ids"][0])

    # Part A: no fallacy analysis -> unavailable, reported not fabricated
    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for card in body["agent_scores"]:
        assert card["dimensions"]["fallacy_risk"] is None
        assert "Fallacy Risk" in card["unavailable_dimensions"]
        assert any("Fallacy analysis has not been run" in note for note in card["limitations"])
    assert any(
        "Fallacy analysis has not been run" in note
        for note in (body["limitations"] or [])
    )

    # Part B: stored fallacy analysis -> deterministic risk, inverted by rubric
    debate_b = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate_b["message_ids"][0])
    await add_fallacy(
        debate_b["message_ids"][0], severity="medium", confidence=0.9
    )
    fake_b = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    with patch_provider(fake_b):
        resp = await client.post(
            f"/api/v1/debates/{debate_b['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body_b = resp.json()
    by_name = {card["agent_name"]: card for card in body_b["agent_scores"]}
    # medium(2) * 0.9 confidence / 1 message * 5 = 9.0 risk
    assert abs(by_name["Economist"]["dimensions"]["fallacy_risk"] - 9.0) < 0.001
    assert by_name["Lawyer"]["dimensions"]["fallacy_risk"] is None


async def test_judge_only_participants_scored(client):
    token = await register_and_login(client, unique_email("judge-part"))
    debate = await seed_completed_debate(client, token, second_message=False)
    await add_argument_evaluation(debate["message_ids"][0])

    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS}))
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["agent_scores"]) == 1
    assert body["agent_scores"][0]["agent_name"] == "Economist"
    assert body["outcome"] == "inconclusive"
    assert any("Fewer than two agents" in note for note in (body["limitations"] or []))


async def test_judge_canonical_names_when_llm_lowercases(client):
    token = await register_and_login(client, unique_email("judge-case"))
    debate = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate["message_ids"][0])

    # The model echoes participant names in lowercase; canonical database
    # names must still be stored on the judgment cards.
    fake = FakeLLM(judge_json({"economist": EQUAL_DIMS, "lawyer": EQUAL_DIMS}))
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = sorted(card["agent_name"] for card in body["agent_scores"])
    assert names == ["Economist", "Lawyer"], names

    stored = await client.get(
        f"/api/v1/debates/{debate['id']}/judgment", headers=auth(token)
    )
    assert stored.status_code == 200, stored.text
    stored_names = sorted(
        card["agent_name"] for card in stored.json()["agent_scores"]
    )
    assert stored_names == ["Economist", "Lawyer"], stored_names


async def test_judge_persistence_and_retrieval(client):
    token = await register_and_login(client, unique_email("judge-persist"))
    debate = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate["message_ids"][0])

    # GET before generation -> 404 (no LLM call)
    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    with patch_provider(fake):
        resp = await client.get(
            f"/api/v1/debates/{debate['id']}/judgment", headers=auth(token)
        )
        assert resp.status_code == 404, resp.text
        assert fake.calls == 0

        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
        assert resp.status_code == 200, resp.text
        created = resp.json()

        resp = await client.get(
            f"/api/v1/debates/{debate['id']}/judgment", headers=auth(token)
        )
        assert resp.status_code == 200, resp.text
        fetched = resp.json()

    assert created["id"] == fetched["id"]
    assert created["overall_score"] == fetched["overall_score"]
    assert created["agent_scores"] == fetched["agent_scores"]
    assert fake.calls == 1, "GET must never call the LLM"

    async with _test_session() as session:
        rows = (
            await session.execute(
                select(DebateJudgment).where(
                    DebateJudgment.debate_id == uuid.UUID(debate["id"])
                )
            )
        ).scalars().all()
        assert len(rows) == 1

        # The database itself rejects duplicate judgments per debate.
        session.add(
            DebateJudgment(
                debate_id=uuid.UUID(debate["id"]),
                status="completed",
                overall_score=5.0,
                outcome="tie",
                summary="duplicate",
                scoring_rubric={},
                agent_scores=[],
            )
        )
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
        else:
            raise AssertionError("duplicate debate_id must violate uniqueness")
        await session.rollback()


async def test_judge_auth_and_ownership(client):
    owner_token = await register_and_login(client, unique_email("judge-owner"))
    debate = await seed_completed_debate(client, owner_token)
    await add_argument_evaluation(debate["message_ids"][0])

    # Unauthenticated -> 401
    resp = await client.post(f"/api/v1/debates/{debate['id']}/judge")
    assert resp.status_code == 401, resp.text
    resp = await client.get(f"/api/v1/debates/{debate['id']}/judgment")
    assert resp.status_code == 401, resp.text

    # Another user -> 404 on both endpoints (no results leak)
    other_token = await register_and_login(client, unique_email("judge-other"))
    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(other_token)
        )
        assert resp.status_code == 404, resp.text
        assert fake.calls == 0
        resp = await client.get(
            f"/api/v1/debates/{debate['id']}/judgment", headers=auth(other_token)
        )
        assert resp.status_code == 404, resp.text

    # Unknown debate id -> 404
    resp = await client.post(
        f"/api/v1/debates/{uuid.uuid4()}/judge", headers=auth(owner_token)
    )
    assert resp.status_code == 404, resp.text


async def test_judge_incomplete_and_empty_debates(client):
    token = await register_and_login(client, unique_email("judge-inc2"))
    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))

    # Pending (never run) debate -> 400, no LLM call
    resp = await client.post("/api/v1/debates", json=base_payload(), headers=auth(token))
    assert resp.status_code == 201, resp.text
    pending_id = resp.json()["id"]
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{pending_id}/judge", headers=auth(token)
        )
    assert resp.status_code == 400, resp.text
    assert "completed" in resp.json()["detail"]
    assert fake.calls == 0
    resp = await client.get(f"/api/v1/debates/{pending_id}/judgment", headers=auth(token))
    assert resp.status_code == 404, resp.text

    # Completed debate with no messages -> 400, no LLM call
    debate = await seed_completed_debate(client, token)
    async with _test_session() as session:
        messages = (
            await session.execute(
                select(DebateMessage).where(
                    DebateMessage.debate_id == uuid.UUID(debate["id"])
                )
            )
        ).scalars().all()
        for message in messages:
            await session.delete(message)
        await session.commit()
    with patch_provider(fake):
        resp = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert resp.status_code == 400, resp.text
    assert "no messages" in resp.json()["detail"]
    assert fake.calls == 0


async def test_judge_duplicate_requests(client):
    token = await register_and_login(client, unique_email("judge-dup"))
    debate = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate["message_ids"][0])

    fake = FakeLLM(judge_json({"Economist": EQUAL_DIMS, "Lawyer": EQUAL_DIMS}))
    with patch_provider(fake):
        first = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
        second = await client.post(
            f"/api/v1/debates/{debate['id']}/judge", headers=auth(token)
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert fake.calls == 1, "the second request must reuse the stored judgment"

    async with _test_session() as session:
        rows = (
            await session.execute(
                select(DebateJudgment).where(
                    DebateJudgment.debate_id == uuid.UUID(debate["id"])
                )
            )
        ).scalars().all()
        assert len(rows) == 1


async def test_judge_invalid_llm_output(client):
    token = await register_and_login(client, unique_email("judge-bad"))
    debate = await seed_completed_debate(client, token)
    await add_argument_evaluation(debate["message_ids"][0])
    url = f"/api/v1/debates/{debate['id']}/judge"

    scenarios = [
        ("malformed JSON", FakeLLM("definitely not json")),
        (
            "wrong participants",
            FakeLLM(judge_json({"Ada": EQUAL_DIMS, "Bob": EQUAL_DIMS})),
        ),
        (
            "out-of-range dimension",
            FakeLLM(
                judge_json(
                    {
                        "Economist": dict(EQUAL_DIMS, logical_soundness=11.0),
                        "Lawyer": EQUAL_DIMS,
                    }
                )
            ),
        ),
        ("provider outage", FailingLLM()),
    ]
    for label, fake in scenarios:
        with patch_provider(fake):
            resp = await client.post(url, headers=auth(token))
        assert resp.status_code == 502, f"{label}: {resp.status_code} {resp.text}"
        assert resp.json()["detail"], label

    # Nothing was persisted after the failures
    async with _test_session() as session:
        rows = (
            await session.execute(
                select(DebateJudgment).where(
                    DebateJudgment.debate_id == uuid.UUID(debate["id"])
                )
            )
        ).scalars().all()
        assert rows == []
    resp = await client.get(f"/api/v1/debates/{debate['id']}/judgment", headers=auth(token))
    assert resp.status_code == 404, resp.text


async def main():
    app = await setup()
    async with client_for(app) as client:
        test_score_calculation_and_weights()
        test_score_bounds_and_rounding()
        test_fallacy_risk_inversion()
        test_factual_support_from_verdicts()
        test_decide_outcome_policy()
        test_parse_judge_payload()

        await test_judge_endpoint_clear_lead(client)
        await test_judge_tie_when_scores_close(client)
        await test_judge_inconclusive_when_data_missing(client)
        await test_judge_factual_support_rules(client)
        await test_judge_fallacy_dimension(client)
        await test_judge_only_participants_scored(client)
        await test_judge_canonical_names_when_llm_lowercases(client)
        await test_judge_persistence_and_retrieval(client)
        await test_judge_auth_and_ownership(client)
        await test_judge_incomplete_and_empty_debates(client)
        await test_judge_duplicate_requests(client)
        await test_judge_invalid_llm_output(client)

    await teardown()
    print("\nAll Module 11 (debate judge + overall scoring) tests PASSED!")

    print("\nRegression: Module 0 (foundation)...")
    from tests import test_basic

    await test_basic.main()

    print("\nRegression: Module 2 (authentication)...")
    from tests import test_auth

    await test_auth.main()

    print("\nRegression: Module 3 (LLM provider + Base Agent)...")
    from tests import test_llm

    await test_llm.main()

    print("\nRegression: Module 4 (core role-based agents)...")
    from tests import test_agents

    await test_agents.main()

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

    print("\nRegression: Module 10 (fallacy detection + evaluations)...")
    from tests import test_fallacy

    await test_fallacy.main()


if __name__ == "__main__":
    asyncio.run(main())
