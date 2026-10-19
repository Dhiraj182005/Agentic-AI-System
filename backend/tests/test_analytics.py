"""Module 12 tests: analytics dashboard endpoints.

All analytics are computed from stored records; no external service is
called. Ends with regression runs of every earlier module's suite.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.fallacy import Fallacy
from app.models.judge import DebateJudgment
from app.schemas.analytics import CLAIM_VERDICTS, CONFIDENCE_LEVELS, DEBATE_STATUSES

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test",
)

_test_engine = None
_test_session = None

ANALYTICS_ENDPOINTS = (
    "/api/v1/analytics/summary",
    "/api/v1/analytics/debate-activity",
    "/api/v1/analytics/claim-verification",
    "/api/v1/analytics/agent-performance",
    "/api/v1/analytics/argument-quality",
    "/api/v1/analytics/recent-debates",
)

OPENING = (
    "Global temperatures have increased over the last century. "
    "Carbon pricing can reduce emissions."
)
ARGUMENT = (
    "Energy prices could rise under a carbon tax. "
    "Consumers deserve transparent markets."
)


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


def utc_days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def create_debate(client, token, *, status, created_at=None):
    resp = await client.post(
        "/api/v1/debates", json=base_payload(), headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    debate_id = uuid.UUID(resp.json()["id"])
    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        debate.status = status
        if created_at is not None:
            debate.created_at = created_at
        await session.commit()
    return debate_id


def judgment_card(agent, final_score, dims, strengths=None, weaknesses=None):
    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "agent_role": agent.role,
        "dimensions": dims,
        "unavailable_dimensions": [
            key for key, value in dims.items() if value is None
        ],
        "final_score": final_score,
        "strengths": strengths or ["Clear claim structure"],
        "weaknesses": weaknesses or ["Could cite more sources"],
        "reasoning_quality": "Premises follow from the stated evidence.",
        "evidence_quality_assessment": "Some sources back the main claims.",
        "factual_support_assessment": "Stored verdicts mostly support the claims.",
        "fallacy_impact_assessment": "Only minor rhetorical issues detected.",
        "confidence": "medium",
        "limitations": [],
    }


FULL_DIMS = {
    "logical_soundness": 8.0,
    "evidence_quality": 8.0,
    "factual_support": 8.0,
    "relevance": 8.0,
    "effectiveness": 8.0,
    "completeness": 8.0,
    "fallacy_risk": 1.0,
}
PARTIAL_DIMS = {
    "logical_soundness": 6.0,
    "evidence_quality": None,
    "factual_support": None,
    "relevance": 6.0,
    "effectiveness": 6.0,
    "completeness": 6.0,
    "fallacy_risk": None,
}


async def seed_user_a(client, token) -> dict:
    """Completed + running + failed debates with analysis records."""
    completed = await create_debate(
        client, token, status="completed", created_at=utc_days_ago(0)
    )
    running = await create_debate(
        client, token, status="running", created_at=utc_days_ago(3)
    )
    failed = await create_debate(
        client, token, status="failed", created_at=utc_days_ago(10)
    )

    async with _test_session() as session:
        debate = await session.get(Debate, completed)
        agents = list(debate.agents)
        round_one = DebateRound(debate_id=completed, round_number=1, status="completed")
        round_two = DebateRound(debate_id=completed, round_number=2, status="completed")
        session.add_all([round_one, round_two])
        await session.flush()

        msg_one = DebateMessage(
            debate_id=completed,
            round_id=round_one.id,
            agent_id=agents[0].id,
            turn_number=1,
            message_type="opening",
            content=OPENING,
        )
        msg_two = DebateMessage(
            debate_id=completed,
            round_id=round_two.id,
            agent_id=agents[1].id,
            turn_number=1,
            message_type="argument",
            content=ARGUMENT,
        )
        # One message in the running debate as well.
        running_round = DebateRound(debate_id=running, round_number=1, status="running")
        session.add(running_round)
        await session.flush()
        msg_running = DebateMessage(
            debate_id=running,
            round_id=running_round.id,
            agent_id=agents[0].id,
            turn_number=1,
            message_type="opening",
            content=OPENING,
        )
        session.add_all([msg_one, msg_two, msg_running])
        await session.flush()

        claim_one = Claim(
            debate_id=completed,
            message_id=msg_one.id,
            agent_id=agents[0].id,
            text="Global temperatures have increased over the last century.",
            claim_type="factual",
            position=0,
        )
        claim_two = Claim(
            debate_id=completed,
            message_id=msg_two.id,
            agent_id=agents[1].id,
            text="Consumers deserve transparent energy markets.",
            claim_type="opinion",
            position=0,
        )
        claim_three = Claim(
            debate_id=running,
            message_id=msg_running.id,
            agent_id=agents[0].id,
            text="Carbon pricing can reduce emissions.",
            claim_type="factual",
            position=0,
        )
        session.add_all([claim_one, claim_two, claim_three])
        await session.flush()
        session.add(
            ClaimVerification(
                claim_id=claim_one.id,
                verdict="supported",
                confidence="medium",
                explanation="The retrieved sources are consistent with the claim.",
                evidence_summary="Climate reports confirm the trend.",
                evidence_ids=[],
            )
        )
        session.add(
            ArgumentEvaluation(
                debate_id=completed,
                message_id=msg_one.id,
                agent_id=agents[0].id,
                logical_soundness=7.0,
                evidence_score=6.0,
                relevance_score=8.0,
                effectiveness_score=7.0,
                overall_score=7.0,
                explanation="Structured argument with a clear line of reasoning.",
            )
        )
        session.add(
            Fallacy(
                debate_id=completed,
                message_id=msg_two.id,
                agent_id=agents[1].id,
                fallacy_type="ad_hominem",
                severity="low",
                confidence=0.6,
                explanation="The response attacks the speaker instead of the argument.",
                evidence_span="you always say that",
            )
        )
        session.add(
            DebateJudgment(
                debate_id=completed,
                status="completed",
                overall_score=7.0,
                winner_agent_id=agents[0].id,
                outcome="winner",
                summary="The Economist presented better-structured reasoning.",
                scoring_rubric={"weights": {}},
                agent_scores=[
                    judgment_card(agents[0], 8.0, FULL_DIMS),
                    judgment_card(agents[1], 6.0, PARTIAL_DIMS),
                ],
                limitations=None,
            )
        )
        await session.commit()
        return {
            "completed": str(completed),
            "running": str(running),
            "failed": str(failed),
            "agent_names": [a.name for a in agents],
        }


async def seed_user_b(client, token) -> dict:
    """Isolation fixture: one completed debate with its own records."""
    completed = await create_debate(client, token, status="completed")
    async with _test_session() as session:
        debate = await session.get(Debate, completed)
        agents = list(debate.agents)
        round_one = DebateRound(debate_id=completed, round_number=1, status="completed")
        session.add(round_one)
        await session.flush()
        msg = DebateMessage(
            debate_id=completed,
            round_id=round_one.id,
            agent_id=agents[1].id,
            turn_number=1,
            message_type="opening",
            content=ARGUMENT,
        )
        session.add(msg)
        await session.flush()
        claim = Claim(
            debate_id=completed,
            message_id=msg.id,
            agent_id=agents[1].id,
            text="Regulation always harms innovation.",
            claim_type="opinion",
            position=0,
        )
        session.add(claim)
        await session.flush()
        session.add(
            ClaimVerification(
                claim_id=claim.id,
                verdict="contradicted",
                confidence="high",
                explanation="The stored sources conflict with the claim.",
                evidence_summary="Mixed evidence on regulation effects.",
                evidence_ids=[],
            )
        )
        session.add(
            DebateJudgment(
                debate_id=completed,
                status="completed",
                overall_score=2.0,
                winner_agent_id=None,
                outcome="tie",
                summary="Weak arguments on both sides.",
                scoring_rubric={"weights": {}},
                agent_scores=[judgment_card(agents[0], 2.0, FULL_DIMS)],
                limitations=None,
            )
        )
        await session.commit()
        return {"completed": str(completed)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_summary_counts(client):
    token = await register_and_login(client, unique_email("m12-sum"))
    await seed_user_a(client, token)

    resp = await client.get("/api/v1/analytics/summary", headers=auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_debates"] == 3
    assert body["completed_debates"] == 1
    assert body["running_debates"] == 1
    assert body["failed_debates"] == 1
    assert body["pending_debates"] == 0
    assert body["cancelled_debates"] == 0
    assert body["total_messages"] == 3
    assert body["total_claims"] == 3
    assert body["verified_claims"] == 1
    assert body["unverified_claims"] == 2
    assert body["debates_with_judgment"] == 1
    assert abs(body["completion_rate"] - round(1 / 3, 4)) < 1e-9


async def test_status_distribution_matches_model(client):
    token = await register_and_login(client, unique_email("m12-status"))
    await seed_user_a(client, token)

    resp = await client.get("/api/v1/analytics/summary", headers=auth(token))
    body = resp.json()
    distribution = body["status_distribution"]
    assert [item["status"] for item in distribution] == list(DEBATE_STATUSES)
    counts = {item["status"]: item["count"] for item in distribution}
    assert counts == {
        "pending": 0,
        "running": 1,
        "completed": 1,
        "failed": 1,
        "cancelled": 0,
    }


async def test_debate_activity_range_and_grouping(client):
    token = await register_and_login(client, unique_email("m12-activity"))
    await seed_user_a(client, token)

    resp = await client.get(
        "/api/v1/analytics/debate-activity?days=7", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 7
    assert body["bucket"] == "day"
    assert len(body["buckets"]) == 7
    assert body["total_debates_in_range"] == 2  # today + 3 days ago
    today = datetime.now(timezone.utc).date()
    by_date = {item["date"]: item["count"] for item in body["buckets"]}
    assert by_date[today.isoformat()] == 1
    assert by_date[(today - timedelta(days=3)).isoformat()] == 1
    assert by_date[(today - timedelta(days=1)).isoformat()] == 0

    resp = await client.get(
        "/api/v1/analytics/debate-activity?days=30", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_debates_in_range"] == 3  # failed debate included


async def test_claim_verification_counts(client):
    token = await register_and_login(client, unique_email("m12-verif"))
    await seed_user_a(client, token)

    resp = await client.get(
        "/api/v1/analytics/claim-verification", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_verifications"] == 1
    verdicts = {item["name"]: item["count"] for item in body["verdict_counts"]}
    assert list(verdicts.keys()) == list(CLAIM_VERDICTS)
    assert verdicts == {"supported": 1, "contradicted": 0, "insufficient_evidence": 0}
    confidences = {item["name"]: item["count"] for item in body["confidence_counts"]}
    assert list(confidences.keys()) == list(CONFIDENCE_LEVELS)
    assert confidences == {"low": 0, "medium": 1, "high": 0}
    # The two unverified claims must not be counted as insufficient evidence.
    assert body["verified_claims"] == 1
    assert body["unverified_claims"] == 2
    assert "factual-accuracy" in body["scope"]


async def test_agent_performance_aggregation(client):
    token_a = await register_and_login(client, unique_email("m12-perf-a"))
    token_b = await register_and_login(client, unique_email("m12-perf-b"))
    await seed_user_a(client, token_a)
    await seed_user_b(client, token_b)

    resp = await client.get(
        "/api/v1/analytics/agent-performance", headers=auth(token_a)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["judgments_analyzed"] == 1
    by_name = {item["agent_name"]: item for item in body["agents"]}
    economist = by_name["Economist"]
    assert economist["appearances"] == 1
    assert economist["average_score"] == 8.0
    assert economist["strengths"] and economist["weaknesses"]
    lawyer = by_name["Lawyer"]
    assert lawyer["average_score"] == 6.0
    lawyer_dims = {d["dimension"]: d["average"] for d in lawyer["dimension_averages"]}
    assert lawyer_dims["evidence_quality"] is None
    assert lawyer_dims["logical_soundness"] == 6.0
    # Core agents without judged appearances are unavailable, not zero.
    doctor = by_name["Doctor"]
    assert doctor["appearances"] == 0
    assert doctor["average_score"] is None
    assert all(
        d["average"] is None for d in doctor["dimension_averages"]
    )

    # Ownership isolation: user B only sees their own judgment aggregate.
    resp_b = await client.get(
        "/api/v1/analytics/agent-performance", headers=auth(token_b)
    )
    body_b = resp_b.json()
    by_name_b = {item["agent_name"]: item for item in body_b["agents"]}
    assert by_name_b["Economist"]["average_score"] == 2.0
    assert by_name_b["Lawyer"]["average_score"] is None


async def test_agent_performance_missing_judgments(client):
    token = await register_and_login(client, unique_email("m12-perf-none"))
    resp = await client.get(
        "/api/v1/analytics/agent-performance", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is False
    assert body["judgments_analyzed"] == 0
    assert len(body["agents"]) >= 6  # every core agent is still listed
    assert all(item["average_score"] is None for item in body["agents"])
    assert all(item["appearances"] == 0 for item in body["agents"])


async def test_argument_quality(client):
    token_a = await register_and_login(client, unique_email("m12-aq-a"))
    token_b = await register_and_login(client, unique_email("m12-aq-b"))
    await seed_user_a(client, token_a)
    await seed_user_b(client, token_b)

    resp = await client.get(
        "/api/v1/analytics/argument-quality", headers=auth(token_a)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["fallacy_available"] is True
    assert body["evaluation_available"] is True
    assert body["fallacy_total"] == 1
    assert body["fallacy_type_counts"] == [{"name": "ad_hominem", "count": 1}]
    assert body["severity_counts"] == [{"name": "low", "count": 1}]
    assert body["fallacy_analyzed_message_count"] == 1
    assert body["evaluation_total"] == 1
    assert body["evaluated_message_count"] == 1
    assert body["unevaluated_message_count"] == 2  # 3 messages - 1 evaluated
    averages = {d["dimension"]: d["average"] for d in body["dimension_averages"]}
    assert averages["logical_soundness"] == 7.0
    assert averages["overall_score"] == 7.0

    resp_b = await client.get(
        "/api/v1/analytics/argument-quality", headers=auth(token_b)
    )
    body_b = resp_b.json()
    assert body_b["available"] is False
    assert body_b["fallacy_total"] == 0
    assert body_b["evaluation_total"] == 0
    assert any("fallacy" in note.lower() for note in body_b["notes"])
    assert any("argument evaluations" in note.lower() for note in body_b["notes"])


async def test_recent_debates_pagination(client):
    token = await register_and_login(client, unique_email("m12-recent"))
    seeded = await seed_user_a(client, token)

    resp = await client.get(
        "/api/v1/analytics/recent-debates?page=1&page_size=2", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total_pages"] == 2
    assert len(body["debates"]) == 2
    # Newest first: completed (today), running (3 days ago)
    assert body["debates"][0]["id"] == seeded["completed"]
    assert body["debates"][0]["status"] == "completed"
    assert body["debates"][0]["has_verification"] is True
    assert body["debates"][0]["has_judgment"] is True
    assert body["debates"][0]["message_count"] == 2
    assert body["debates"][0]["agent_count"] == 2
    assert body["debates"][1]["id"] == seeded["running"]
    assert body["debates"][1]["has_verification"] is False
    assert body["debates"][1]["has_judgment"] is False

    resp = await client.get(
        "/api/v1/analytics/recent-debates?page=2&page_size=2", headers=auth(token)
    )
    body = resp.json()
    assert len(body["debates"]) == 1
    assert body["debates"][0]["id"] == seeded["failed"]
    assert body["debates"][0]["message_count"] == 0


async def test_query_parameter_validation(client):
    token = await register_and_login(client, unique_email("m12-validate"))
    cases = (
        "/api/v1/analytics/debate-activity?days=0",
        "/api/v1/analytics/debate-activity?days=366",
        "/api/v1/analytics/debate-activity?days=abc",
        "/api/v1/analytics/recent-debates?page=0",
        "/api/v1/analytics/recent-debates?page_size=0",
        "/api/v1/analytics/recent-debates?page_size=51",
    )
    for path in cases:
        resp = await client.get(path, headers=auth(token))
        assert resp.status_code == 422, (path, resp.status_code, resp.text)


async def test_auth_required(client):
    for path in ANALYTICS_ENDPOINTS:
        resp = await client.get(path)
        assert resp.status_code == 401, (path, resp.status_code)


async def test_ownership_isolation(client):
    token_a = await register_and_login(client, unique_email("m12-own-a"))
    token_b = await register_and_login(client, unique_email("m12-own-b"))
    seeded_a = await seed_user_a(client, token_a)
    seeded_b = await seed_user_b(client, token_b)

    summary_b = (
        await client.get("/api/v1/analytics/summary", headers=auth(token_b))
    ).json()
    assert summary_b["total_debates"] == 1
    assert summary_b["completed_debates"] == 1
    assert summary_b["total_messages"] == 1
    assert summary_b["verified_claims"] == 1
    assert summary_b["unverified_claims"] == 0
    assert summary_b["debates_with_judgment"] == 1

    recent_b = (
        await client.get("/api/v1/analytics/recent-debates", headers=auth(token_b))
    ).json()
    assert [item["id"] for item in recent_b["debates"]] == [seeded_b["completed"]]
    assert seeded_a["completed"] not in [item["id"] for item in recent_b["debates"]]


async def test_no_duplicate_join_inflation(client):
    token = await register_and_login(client, unique_email("m12-join"))
    await seed_user_a(client, token)

    summary = (
        await client.get("/api/v1/analytics/summary", headers=auth(token))
    ).json()
    # 3 claims but only 1 verification row -> verified stays 1.
    assert summary["total_claims"] == 3
    assert summary["verified_claims"] == 1
    # 2 judgment agent cards but 1 judgment row -> one judged debate.
    assert summary["debates_with_judgment"] == 1

    quality = (
        await client.get("/api/v1/analytics/argument-quality", headers=auth(token))
    ).json()
    # Dimension columns must not multiply evaluation rows.
    assert quality["evaluation_total"] == 1
    assert quality["evaluated_message_count"] == 1


async def test_empty_account(client):
    token = await register_and_login(client, unique_email("m12-empty"))

    summary = (
        await client.get("/api/v1/analytics/summary", headers=auth(token))
    ).json()
    assert summary["total_debates"] == 0
    assert summary["completion_rate"] is None
    assert summary["total_messages"] == 0
    assert summary["verified_claims"] == 0
    assert summary["debates_with_judgment"] == 0

    activity = (
        await client.get("/api/v1/analytics/debate-activity?days=7", headers=auth(token))
    ).json()
    assert len(activity["buckets"]) == 7
    assert activity["total_debates_in_range"] == 0
    assert all(item["count"] == 0 for item in activity["buckets"])

    quality = (
        await client.get("/api/v1/analytics/argument-quality", headers=auth(token))
    ).json()
    assert quality["available"] is False
    assert quality["unevaluated_message_count"] is None

    recent = (
        await client.get("/api/v1/analytics/recent-debates", headers=auth(token))
    ).json()
    assert recent["debates"] == []
    assert recent["total"] == 0
    assert recent["total_pages"] == 1


async def main():
    app = await setup()
    async with client_for(app) as client:
        await test_summary_counts(client)
        await test_status_distribution_matches_model(client)
        await test_debate_activity_range_and_grouping(client)
        await test_claim_verification_counts(client)
        await test_agent_performance_aggregation(client)
        await test_agent_performance_missing_judgments(client)
        await test_argument_quality(client)
        await test_recent_debates_pagination(client)
        await test_query_parameter_validation(client)
        await test_auth_required(client)
        await test_ownership_isolation(client)
        await test_no_duplicate_join_inflation(client)
        await test_empty_account(client)

    await teardown()
    print("\nAll Module 12 (analytics dashboard) tests PASSED!")

    regressions = (
        ("Module 0 (foundation)", "tests.test_basic"),
        ("Module 2 (authentication)", "tests.test_auth"),
        ("Module 3 (LLM provider + Base Agent)", "tests.test_llm"),
        ("Module 4 (core role-based agents)", "tests.test_agents"),
        ("Module 5 (debate creation + agent selection)", "tests.test_debates"),
        (
            "Topic-aware automatic agent selection",
            "tests.test_agent_selection",
        ),
        ("Module 6 (orchestration)", "tests.test_orchestration"),
        ("Module 11 (debate judge + overall scoring)", "tests.test_judge"),
    )
    for label, module in regressions:
        print(f"\nRegression: {label}...")
        imported = __import__(module, fromlist=["main"])
        await imported.main()

    print("\nRegression: Module 7 (live streaming)...")
    result = subprocess.run(
        [sys.executable, "-m", "tests.test_websocket"],
        cwd=os.getcwd(),
        env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "/app")},
    )
    assert result.returncode == 0, "websocket regression failed"

    regressions_tail = (
        ("Module 8 (claims + evidence)", "tests.test_claims"),
        ("Module 9 (claim verification)", "tests.test_verification"),
        ("Module 10 (fallacy detection + argument evaluation)", "tests.test_fallacy"),
    )
    for label, module in regressions_tail:
        print(f"\nRegression: {label}...")
        imported = __import__(module, fromlist=["main"])
        await imported.main()

    print("\nAll Module 12 analytics + regression suites PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
