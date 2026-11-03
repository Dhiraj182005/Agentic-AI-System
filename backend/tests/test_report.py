"""Final UI task tests: PDF conclusion report endpoint.

The report must be a valid PDF served as application/pdf with a safe
filename, built only from persisted data (no LLM or evidence provider
calls, no new debates), with honest unavailable states for missing
judgments and missing analyses, and safe handling of long/unicode text.
"""

import asyncio
import base64
import contextlib
import os
import re
import subprocess
import sys
import uuid
import zlib
from unittest import mock

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
from app.models.evidence import Evidence
from app.models.fallacy import Fallacy
from app.models.judge import DebateJudgment
from app.models.verdict import DebateVerdict
from app.services import judge_rubric

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test",
)

_test_engine = None
_test_session = None

TOPIC = "Should cities subsidize Zephyridium tidal power?"
CLAIM_ONE = "Bayfield turbines delivered 41 percent output last winter."
CLAIM_TWO = "Households deserve transparent tidal tariffs."
SUMMARY = "The Bayledger cost accounting was clearer in round two."
EVIDENCE_TITLE = "Tidal capacity overview from tidalsource"
LIMITATION = "Scores rely on two stored rounds only."
VERDICT_ANSWER = "Subsidies are justified where tidal output is verified."
COUNTER_POINT = "Capital costs remain high."

OPENING = (
    "Zephyridium installations are growing along the northern coast. "
    "Bayfield turbines delivered 41 percent output last winter."
)
ARGUMENT = (
    "Households deserve transparent tidal tariffs. "
    "Opaque subsidy tables hide the real cost."
)

URL_RE = re.compile(
    r'attachment; filename="maves-[a-z0-9-]+-[0-9a-f]{8}\.pdf"'
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
        "topic": TOPIC,
        "expert_selection_mode": "manual",
        "agent_ids": ["economist", "lawyer"],
        "domain_tags": ["energy"],
        "mode": "balanced",
        "total_rounds": 2,
        "verify_evidence": False,
    }
    payload.update(overrides)
    return payload


async def create_debate(client, token, **overrides):
    resp = await client.post(
        "/api/v1/debates", json=base_payload(**overrides), headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    debate_id = uuid.UUID(resp.json()["id"])
    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        debate.status = "completed"
        await session.commit()
    return debate_id


def dims(value=8.0):
    return {
        "logical_soundness": value,
        "evidence_quality": value,
        "factual_support": value,
        "relevance": value,
        "effectiveness": value,
        "completeness": value,
        "fallacy_risk": 1.0,
    }


def judgment_card(agent, final_score):
    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "agent_role": agent.role,
        "dimensions": dims(final_score),
        "unavailable_dimensions": [],
        "final_score": final_score,
        "strengths": ["Clear cost framing"],
        "weaknesses": ["Cites few stored sources"],
        "reasoning_quality": "Premises follow from the stated evidence.",
        "evidence_quality_assessment": "Some sources back the main claims.",
        "factual_support_assessment": "Stored verdicts mostly support the claims.",
        "fallacy_impact_assessment": "Only minor rhetorical issues detected.",
        "confidence": "medium",
        "limitations": [],
    }


async def seed_full(
    client, token, *, with_judgment=True, with_analysis=True, topic=TOPIC,
    with_verdict=False,
) -> dict:
    """Completed debate with rounds, messages, claims, evidence and rows."""
    debate_id = await create_debate(client, token, topic=topic)
    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        agents = list(debate.agents)
        round_one = DebateRound(
            debate_id=debate_id, round_number=1, status="completed"
        )
        round_two = DebateRound(
            debate_id=debate_id, round_number=2, status="completed"
        )
        session.add_all([round_one, round_two])
        await session.flush()

        msg_one = DebateMessage(
            debate_id=debate_id,
            round_id=round_one.id,
            agent_id=agents[0].id,
            turn_number=1,
            message_type="opening",
            content=OPENING,
        )
        msg_two = DebateMessage(
            debate_id=debate_id,
            round_id=round_two.id,
            agent_id=agents[1].id,
            turn_number=1,
            message_type="argument",
            content=ARGUMENT,
        )
        session.add_all([msg_one, msg_two])
        await session.flush()

        claim_one = Claim(
            debate_id=debate_id,
            message_id=msg_one.id,
            agent_id=agents[0].id,
            text=CLAIM_ONE,
            claim_type="factual",
            position=0,
        )
        claim_two = Claim(
            debate_id=debate_id,
            message_id=msg_two.id,
            agent_id=agents[1].id,
            text=CLAIM_TWO,
            claim_type="opinion",
            position=0,
        )
        session.add_all([claim_one, claim_two])
        await session.flush()

        session.add(
            ClaimVerification(
                claim_id=claim_one.id,
                verdict="supported",
                confidence="medium",
                explanation="Stored sources are consistent with the claim.",
                evidence_summary="Coastal grid reports match the output figure.",
                evidence_ids=[],
            )
        )
        session.add(
            Evidence(
                claim_id=claim_one.id,
                title=EVIDENCE_TITLE,
                url="https://tidalsource.example/overview",
                snippet="Regional tidal installations produced steady output.",
                source_name="tidalsource",
                relevance_score=0.91,
                position=0,
            )
        )
        if with_analysis:
            session.add(
                Fallacy(
                    debate_id=debate_id,
                    message_id=msg_two.id,
                    agent_id=agents[1].id,
                    fallacy_type="ad_hominem",
                    severity="low",
                    confidence=0.6,
                    explanation="The reply targets the speaker, not the argument.",
                    evidence_span="you always say that",
                )
            )
            session.add(
                ArgumentEvaluation(
                    debate_id=debate_id,
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
        if with_judgment:
            session.add(
                DebateJudgment(
                    debate_id=debate_id,
                    status="completed",
                    overall_score=7.5,
                    winner_agent_id=agents[0].id,
                    outcome="winner",
                    summary=SUMMARY,
                    scoring_rubric=judge_rubric.rubric_snapshot(0.5),
                    agent_scores=[
                        judgment_card(agents[0], 8.0),
                        judgment_card(agents[1], 7.0),
                    ],
                    limitations=[LIMITATION],
                )
            )
        if with_verdict:
            session.add(
                DebateVerdict(
                    debate_id=debate_id,
                    position="supports",
                    answer=VERDICT_ANSWER,
                    preferred_position="Subsidize verified tidal projects",
                    summary="Verified output data favours targeted subsidies.",
                    reasoning="The output claim was supported by stored sources.",
                    supporting_arguments=[
                        {"point": "Output is reliable.", "agent_name": agents[0].name,
                         "claim_ids": [str(claim_one.id)]}
                    ],
                    counterarguments=[
                        {"point": COUNTER_POINT, "agent_name": agents[1].name,
                         "impact": "Limits scale.", "claim_ids": []}
                    ],
                    confidence="medium",
                    confidence_basis="Only 1 of 2 claims is verified.",
                    limitations=["Only one claim verified."],
                    unresolved_questions=["Maintenance costs?"],
                    evidence_snapshot={"total_claims": 2, "supported": 1,
                                       "contradicted": 0, "insufficient_evidence": 0,
                                       "unverified": 1, "evidence_sources": 1},
                )
            )
        await session.commit()
        return {
            "debate_id": debate_id,
            "agent_names": [agent.name for agent in agents],
        }


async def seed_bare(client, token) -> dict:
    """Completed debate with only messages - no judgment or analysis rows."""
    debate_id = await create_debate(
        client, token, topic="Bare debate with stored messages only."
    )
    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        agents = list(debate.agents)
        round_one = DebateRound(
            debate_id=debate_id, round_number=1, status="completed"
        )
        session.add(round_one)
        await session.flush()
        session.add(
            DebateMessage(
                debate_id=debate_id,
                round_id=round_one.id,
                agent_id=agents[0].id,
                turn_number=1,
                message_type="opening",
                content=OPENING,
            )
        )
        await session.commit()
    return {"debate_id": debate_id}


def _decode_stream(raw: bytes) -> bytes:
    """Decode a PDF content stream (optionally ASCII85 + Flate compressed)."""
    data = raw.strip(b"\r\n")
    candidates = []
    a85 = data[:-2] if data.endswith(b"~>") else data
    if a85.startswith(b"<~"):
        a85 = a85[2:]
    candidates.append(lambda: zlib.decompress(base64.a85decode(a85)))
    candidates.append(lambda: zlib.decompress(data))
    candidates.append(lambda: data)
    for decode in candidates:
        try:
            return decode()
        except Exception:
            continue
    return data


def pdf_text_fragments(body: bytes) -> str:
    """Extract text drawn in content streams (compressed or not)."""
    chunks: list[str] = []
    for match in re.finditer(rb"(?<![A-Za-z])stream\r?\n(.*?)endstream", body, re.S):
        data = _decode_stream(match.group(1))
        for raw in re.findall(rb"\((?:\\.|[^()\\])*\)", data):
            chunks.append(raw[1:-1].decode("latin-1", "replace"))
    return " ".join(chunks)


@contextlib.contextmanager
def no_external_services():
    """Fail loudly if any LLM or evidence provider factory gets called."""
    calls: list[str] = []

    def guard(*args, **kwargs):
        calls.append("external")
        raise AssertionError("external service called while building report")

    targets = (
        "app.llm.factory.get_llm_provider",
        "app.agents.base_agent.get_llm_provider",
        "app.services.claim_extraction.get_llm_provider",
        "app.services.verification_service.get_llm_provider",
        "app.services.fallacy_detection.get_llm_provider",
        "app.services.argument_evaluation.get_llm_provider",
        "app.services.debate_judge_service.get_llm_provider",
        "app.services.agent_selection.get_llm_provider",
        "app.services.verdict_service.get_llm_provider",
        "app.evidence.factory.get_evidence_provider",
    )
    with contextlib.ExitStack() as stack:
        for target in targets:
            try:
                stack.enter_context(mock.patch(target, side_effect=guard))
            except (AttributeError, ImportError):
                continue
        yield calls


async def fetch_report(client, token, debate_id) -> httpx.Response:
    return await client.get(
        f"/api/v1/debates/{debate_id}/report.pdf",
        headers=auth(token) if token else {},
    )


def assert_valid_pdf(resp: httpx.Response):
    assert resp.status_code == 200, resp.text
    content_type = resp.headers.get("content-type", "")
    assert content_type.startswith("application/pdf"), content_type
    body = resp.content
    assert body[:5] == b"%PDF-", body[:16]
    assert b"%%EOF" in body[-2048:], "missing PDF trailer"
    assert len(body) > 1500, "suspiciously small PDF"
    disposition = resp.headers.get("content-disposition", "")
    match = URL_RE.search(disposition)
    assert match, f"unexpected content-disposition: {disposition}"
    filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
    filename.encode("ascii")  # filename must be plain ASCII
    return body, filename


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_valid_pdf_for_judged_debate(client):
    token = await register_and_login(client, unique_email("m14-valid"))
    seeded = await seed_full(client, token)

    resp = await fetch_report(client, token, seeded["debate_id"])
    body, filename = assert_valid_pdf(resp)
    assert filename.startswith("maves-should-cities-subsidize-zephyridium")
    assert filename.endswith(f"{seeded['debate_id'].hex[:8]}.pdf")
    # Cover, header/footer and at least two rendered pages worth of content.
    assert b"/Type /Page" in body or b"/Type/Page" in body
    print("valid PDF for judged debate: PASSED")


async def test_report_reflects_persisted_data(client):
    token = await register_and_login(client, unique_email("m14-data"))
    seeded = await seed_full(client, token)

    resp = await fetch_report(client, token, seeded["debate_id"])
    body, _ = assert_valid_pdf(resp)
    text = pdf_text_fragments(body)

    assert "Zephyridium" in text, "topic missing from report"
    assert "Bayfield turbines" in text, "claim text missing from report"
    assert "Bayledger" in text, "judgment summary missing from report"
    assert "Supported" in text, "stored verdict missing from report"
    assert "tidalsource" in text, "evidence source missing from report"
    assert seeded["agent_names"][0] in text, "agent name missing from report"
    assert LIMITATION in text, "judgment limitations missing from report"
    assert "0.20" in text or "20%" in text, "rubric weights missing from report"
    print("report reflects persisted data: PASSED")


async def test_report_without_judgment_reports_missing_data(client):
    token = await register_and_login(client, unique_email("m14-nojudge"))
    seeded = await seed_full(client, token, with_judgment=False)

    resp = await fetch_report(client, token, seeded["debate_id"])
    body, _ = assert_valid_pdf(resp)
    text = pdf_text_fragments(body)
    assert "No final judgment has been generated" in text
    assert "Zephyridium" in text
    assert "Bayledger" not in text
    print("report without judgment reports missing data: PASSED")


async def test_report_without_optional_analyses(client):
    token = await register_and_login(client, unique_email("m14-bare"))
    seeded = await seed_bare(client, token)

    resp = await fetch_report(client, token, seeded["debate_id"])
    body, _ = assert_valid_pdf(resp)
    text = pdf_text_fragments(body)
    assert "No claims have been extracted" in text
    assert "No retrieved evidence is stored" in text
    assert "No fallacy analysis is stored" in text
    assert "No argument evaluations are stored" in text
    assert "No final judgment has been generated" in text
    print("report without optional analyses: PASSED")


async def test_report_with_judgment_but_missing_analyses(client):
    token = await register_and_login(client, unique_email("m14-partial"))
    seeded = await seed_full(
        client, token, with_judgment=True, with_analysis=False
    )

    resp = await fetch_report(client, token, seeded["debate_id"])
    body, _ = assert_valid_pdf(resp)
    text = pdf_text_fragments(body)
    assert "Bayledger" in text, "judgment must still render"
    assert "No fallacy analysis is stored" in text
    assert "No argument evaluations are stored" in text
    print("report with judgment but missing analyses: PASSED")


async def test_report_handles_long_and_unicode_text(client):
    token = await register_and_login(client, unique_email("m14-unicode"))
    unicode_topic = "Caf\u00e9 na\u00efve \u2014 \u201csmart\u201d grid Zephyridium"
    long_claim = (
        "Bayfield output held steady \u2014 caf\u00e9 reports, na\u00efve models "
        "and \u201csmart\u201d grids across 14 coastal towns. "
    ) * 40  # well over 1000 characters, with CJK and emoji below
    long_claim += "\u6d77\u5e95\u7535\u7f51 \U0001f600 end."
    debate_id = await create_debate(client, token, topic=unicode_topic)
    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        agents = list(debate.agents)
        round_one = DebateRound(
            debate_id=debate_id, round_number=1, status="completed"
        )
        session.add(round_one)
        await session.flush()
        msg = DebateMessage(
            debate_id=debate_id,
            round_id=round_one.id,
            agent_id=agents[0].id,
            turn_number=1,
            message_type="opening",
            content=long_claim,
        )
        session.add(msg)
        await session.flush()
        session.add(
            Claim(
                debate_id=debate_id,
                message_id=msg.id,
                agent_id=agents[0].id,
                text=long_claim,
                claim_type="factual",
                position=0,
            )
        )
        await session.commit()

    resp = await fetch_report(client, token, debate_id)
    body, _ = assert_valid_pdf(resp)
    text = pdf_text_fragments(body)
    assert "Cafe naive" in text, "unicode topic must fold safely"
    assert "Zephyridium" in text
    print("report handles long and unicode text: PASSED")


async def test_report_requires_authentication(client):
    token = await register_and_login(client, unique_email("m14-auth"))
    seeded = await seed_full(client, token)

    resp = await fetch_report(client, None, seeded["debate_id"])
    assert resp.status_code == 401, resp.text
    print("report requires authentication: PASSED")


async def test_report_hides_other_users_debates(client):
    token_a = await register_and_login(client, unique_email("m14-own-a"))
    token_b = await register_and_login(client, unique_email("m14-own-b"))
    seeded = await seed_full(client, token_a)

    resp = await fetch_report(client, token_b, seeded["debate_id"])
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Debate not found"
    print("report hides other users debates: PASSED")


async def test_report_unknown_and_invalid_debate_ids(client):
    token = await register_and_login(client, unique_email("m14-missing"))

    resp = await fetch_report(client, token, uuid.uuid4())
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Debate not found"

    resp = await client.get(
        "/api/v1/debates/not-a-uuid/report.pdf", headers=auth(token)
    )
    assert resp.status_code == 422, resp.text
    print("report unknown and invalid debate ids: PASSED")


async def test_report_never_calls_external_services(client):
    token = await register_and_login(client, unique_email("m14-external"))
    seeded = await seed_full(client, token)

    before = (await client.get("/api/v1/debates", headers=auth(token))).json()
    with no_external_services() as calls:
        resp = await fetch_report(client, token, seeded["debate_id"])
    after = (await client.get("/api/v1/debates", headers=auth(token))).json()

    assert_valid_pdf(resp)
    assert calls == [], f"external service was called: {calls}"
    assert len(after["items"]) == len(before["items"]), "report created a debate"
    print("report never calls external services: PASSED")


async def test_report_safe_filename_from_unusual_topic(client):
    token = await register_and_login(client, unique_email("m14-fname"))
    seeded = await seed_full(
        client, token, topic="  What if AI <rules> everything? \u2603  "
    )

    resp = await fetch_report(client, token, seeded["debate_id"])
    _, filename = assert_valid_pdf(resp)
    assert re.fullmatch(
        r"maves-what-if-ai-rules-everything-[0-9a-f]{8}\.pdf", filename
    ), filename
    print("report safe filename from unusual topic: PASSED")


async def test_report_includes_transcript_and_partial_label(client):
    token = await register_and_login(client, unique_email("m14-transcript"))
    judged = await seed_full(client, token, with_verdict=True)
    unjudged = await seed_full(client, token, with_judgment=False)

    body, _ = assert_valid_pdf(await fetch_report(client, token, judged["debate_id"]))
    text = pdf_text_fragments(body)
    assert "Debate Transcript" in text, "transcript section missing"
    assert "Round 2" in text
    assert "Opaque subsidy tables" in text, "transcript message missing"
    assert "PARTIAL REPORT" not in text, "completed debate with verdict is not partial"

    body, _ = assert_valid_pdf(
        await fetch_report(client, token, unjudged["debate_id"])
    )
    text = pdf_text_fragments(body)
    assert "PARTIAL REPORT" in text, "debate without verdict must be labelled partial"
    assert "no final verdict is stored" in text
    assert "no final judgment is stored" in text

    async with _test_session() as session:
        debate = await session.get(Debate, judged["debate_id"])
        debate.status = "failed"
        await session.commit()
    body, _ = assert_valid_pdf(await fetch_report(client, token, judged["debate_id"]))
    text = pdf_text_fragments(body)
    assert "PARTIAL REPORT" in text, "failed debate must be labelled partial"
    assert "Bayledger" in text, "stored judgment still renders for failed debate"
    print("report includes transcript and partial label: PASSED")


async def test_report_long_transcript_spans_pages(client):
    token = await register_and_login(client, unique_email("m14-longtx"))
    debate_id = await create_debate(client, token, topic="Long transcript paging")
    paragraph = "Tidal subsidies need audited ledgers before expansion. " * 30
    async with _test_session() as session:
        debate = await session.get(Debate, debate_id)
        agents = list(debate.agents)
        for number in range(1, 4):
            round_row = DebateRound(
                debate_id=debate_id, round_number=number, status="completed"
            )
            session.add(round_row)
            await session.flush()
            for turn, agent in enumerate(agents, start=1):
                session.add(
                    DebateMessage(
                        debate_id=debate_id,
                        round_id=round_row.id,
                        agent_id=agent.id,
                        turn_number=turn,
                        message_type="argument",
                        content=f"## Point {number}\n\n**{paragraph}**\n\n{paragraph}",
                    )
                )
        await session.commit()

    body, _ = assert_valid_pdf(await fetch_report(client, token, debate_id))
    pages = len(re.findall(rb"/Type\s*/Page(?!s)", body))
    assert pages >= 5, f"long transcript should span several pages, got {pages}"
    text = pdf_text_fragments(body)
    assert "Round 3" in text
    assert "**" not in text and "## Point" not in text, "markdown markers leaked"
    print("report long transcript spans pages: PASSED")


async def test_report_leads_with_final_verdict(client):
    token = await register_and_login(client, unique_email("m14-verdict"))
    seeded = await seed_full(client, token, with_verdict=True)

    body, _ = assert_valid_pdf(await fetch_report(client, token, seeded["debate_id"]))
    text = pdf_text_fragments(body)
    assert "Final Debate Verdict" in text
    assert "SUPPORTS THE PROPOSITION" in text
    assert "Subsidies are justified" in text, "verdict answer missing"
    assert COUNTER_POINT in text, "counterargument missing"
    assert "Cited claim" in text and "Bayfield turbines" in text, "cited stored claim missing"
    assert "Agent Performance" in text
    assert "separate from the final verdict" in text
    assert "Confidence and Uncertainty" in text
    # The verdict comes before the agent-performance ranking.
    assert text.index("Final Debate Verdict") < text.index("Agent Performance")

    without = await seed_full(client, token)
    body, _ = assert_valid_pdf(await fetch_report(client, token, without["debate_id"]))
    text = pdf_text_fragments(body)
    assert "No final debate verdict has been generated" in text
    assert "Bayledger" in text, "agent performance still renders without a verdict"
    print("report leads with final verdict: PASSED")


async def main():
    app = await setup()
    async with client_for(app) as client:
        await test_valid_pdf_for_judged_debate(client)
        await test_report_reflects_persisted_data(client)
        await test_report_without_judgment_reports_missing_data(client)
        await test_report_without_optional_analyses(client)
        await test_report_with_judgment_but_missing_analyses(client)
        await test_report_handles_long_and_unicode_text(client)
        await test_report_requires_authentication(client)
        await test_report_hides_other_users_debates(client)
        await test_report_unknown_and_invalid_debate_ids(client)
        await test_report_never_calls_external_services(client)
        await test_report_safe_filename_from_unusual_topic(client)
        await test_report_includes_transcript_and_partial_label(client)
        await test_report_long_transcript_spans_pages(client)
        await test_report_leads_with_final_verdict(client)

    await teardown()
    print("\nAll final UI (PDF conclusion report) tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
