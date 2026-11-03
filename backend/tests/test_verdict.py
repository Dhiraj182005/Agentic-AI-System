"""Final debate verdict tests.

The verdict answers the debate question from stored material. These tests
use a fake LLM and check the server-side guarantees: citations resolve only
to stored claims, insufficient evidence forces an inconclusive verdict,
confidence is capped by evidence coverage, and the judge's agent winner is
never fed into (or equated with) the verdict.
"""

import asyncio
import json
import unittest.mock
import uuid

from sqlalchemy import select

from app.llm.base import LLMResponse
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.models.judge import DebateJudgment
from app.models.verdict import DebateVerdict
from app.orchestration.round_manager import RoundManager
from app.services import judge_rubric
from tests import test_report as base

JUDGE_MARKER = "JUDGE-SUMMARY-MARKER-7731"


class FakeLLM:
    def __init__(self, payload):
        self.content = payload if isinstance(payload, str) else json.dumps(payload)
        self.calls = 0
        self.last_messages = None

    async def generate(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        self.last_messages = messages
        return LLMResponse(content=self.content, provider="fake", model="fake-model")


class FailingLLM:
    calls = 0

    async def generate(self, messages, temperature=None, max_tokens=None):
        FailingLLM.calls += 1
        raise RuntimeError("simulated provider outage")


def patch_provider(fake):
    return unittest.mock.patch(
        "app.services.verdict_service.get_llm_provider", return_value=fake
    )


def payload(**overrides) -> dict:
    data = {
        "position": "supports",
        "answer": "Yes - the verified evidence favours subsidising tidal power.",
        "preferred_position": "Cities should subsidise tidal power",
        "summary": "Verified output figures support the case.",
        "reasoning": "Two verified claims back reliable output.",
        "supporting_arguments": [
            {"point": "Output is predictable.", "agent": "economist", "claim_refs": ["C1", "C2", "C99"]}
        ],
        "counterarguments": [
            {"point": "Capital costs are high.", "agent": "Lawyer", "impact": "Limits scale.", "claim_refs": []}
        ],
        "confidence": "high",
        "limitations": ["Only two rounds."],
        "unresolved_questions": ["Long-term maintenance cost?"],
    }
    data.update(overrides)
    return data


async def seed_debate(client, token, verdicts, *, status="completed", with_judgment=False):
    """Debate with two messages and one claim per entry in `verdicts`
    (None = claim without verification). Each verified claim gets a source."""
    debate_id = await base.create_debate(client, token, topic="Should cities subsidize tidal power?")
    async with base._test_session() as session:
        debate = await session.get(Debate, debate_id)
        debate.status = status
        agents = list(debate.agents)
        rnd = DebateRound(debate_id=debate_id, round_number=1, status="completed")
        session.add(rnd)
        await session.flush()
        messages = []
        for turn, agent in enumerate(agents, start=1):
            message = DebateMessage(
                debate_id=debate_id, round_id=rnd.id, agent_id=agent.id,
                turn_number=turn, message_type="opening",
                content=f"{agent.name} argues about tidal subsidies.",
            )
            session.add(message)
            messages.append(message)
        await session.flush()
        for index, verdict in enumerate(verdicts):
            claim = Claim(
                debate_id=debate_id, message_id=messages[0].id, agent_id=agents[0].id,
                text=f"Stored claim number {index + 1} about tidal output.",
                claim_type="factual", position=index,
            )
            session.add(claim)
            await session.flush()
            if verdict is not None:
                session.add(ClaimVerification(
                    claim_id=claim.id, verdict=verdict, confidence="medium",
                    explanation="Stored check.", evidence_summary="Stored sources.",
                    evidence_ids=[],
                ))
                session.add(Evidence(
                    claim_id=claim.id, title=f"Source {index + 1}",
                    url=f"https://example.org/source-{index + 1}", snippet="Snippet.",
                    source_name="example.org", relevance_score=0.8, position=0,
                ))
        if with_judgment:
            session.add(DebateJudgment(
                debate_id=debate_id, status="completed", overall_score=7.0,
                winner_agent_id=agents[0].id, outcome="winner", summary=JUDGE_MARKER,
                scoring_rubric=judge_rubric.rubric_snapshot(0.5),
                agent_scores=[base.judgment_card(agents[0], 8.5), base.judgment_card(agents[1], 6.0)],
                limitations=[],
            ))
        await session.commit()
    return debate_id, [agent.name for agent in agents]


async def post_verdict(client, token, debate_id, regenerate=False):
    suffix = "?regenerate=true" if regenerate else ""
    return await client.post(
        f"/api/v1/debates/{debate_id}/verdict{suffix}", headers=base.auth(token)
    )


async def stored_verdicts(debate_id):
    async with base._test_session() as session:
        return (
            await session.execute(select(DebateVerdict).where(DebateVerdict.debate_id == debate_id))
        ).scalars().all()


# ---------------------------------------------------------------------------


async def test_evidence_supported_conclusion(client):
    token = await base.register_and_login(client, base.unique_email("v-clear"))
    debate_id, names = await seed_debate(client, token, ["supported", "supported", "supported"])
    fake = FakeLLM(payload())
    with patch_provider(fake):
        resp = await post_verdict(client, token, debate_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["position"] == "supports"
    assert body["preferred_position"] == "Cities should subsidise tidal power"
    assert body["confidence"] == "high", body["confidence_basis"]
    supporting = body["supporting_arguments"][0]
    assert supporting["agent_name"] == names[0], "agent names map to stored names"
    cited = supporting["claims"]
    assert [c["text"] for c in cited] == [
        "Stored claim number 1 about tidal output.",
        "Stored claim number 2 about tidal output.",
    ], "only stored claims are cited; C99 is dropped"
    assert cited[0]["verdict"] == "supported"
    assert cited[0]["sources"][0]["url"] == "https://example.org/source-1"
    assert any("did not match a stored claim" in item for item in body["limitations"])
    assert body["evidence_snapshot"]["supported"] == 3
    assert body["counterarguments"][0]["impact"] == "Limits scale."

    # Stored and idempotent: GET and a second POST never call the LLM again.
    with patch_provider(fake):
        again = await post_verdict(client, token, debate_id)
        got = await client.get(f"/api/v1/debates/{debate_id}/verdict", headers=base.auth(token))
    assert fake.calls == 1
    assert again.json()["id"] == body["id"] == got.json()["id"]
    print("evidence-supported conclusion: PASSED")


async def test_conflicting_evidence_caps_confidence(client):
    token = await base.register_and_login(client, base.unique_email("v-conflict"))
    debate_id, _ = await seed_debate(
        client, token, ["supported", "contradicted", "insufficient_evidence", None]
    )
    fake = FakeLLM(payload(position="mixed", preferred_position="It depends on site costs",
                           confidence="high"))
    with patch_provider(fake):
        resp = await post_verdict(client, token, debate_id)
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["position"] == "mixed"
    assert body["confidence"] == "medium", "2 decisive of 4 claims cannot be high"
    assert "cannot exceed medium" in body["confidence_basis"]
    assert body["evidence_snapshot"]["contradicted"] == 1
    assert body["evidence_snapshot"]["unverified"] == 1
    print("conflicting evidence caps confidence: PASSED")


async def test_insufficient_evidence_forces_inconclusive(client):
    token = await base.register_and_login(client, base.unique_email("v-insufficient"))
    debate_id, _ = await seed_debate(client, token, ["insufficient_evidence", None])
    fake = FakeLLM(payload(position="supports", confidence="high"))
    with patch_provider(fake):
        resp = await post_verdict(client, token, debate_id)
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["position"] == "inconclusive", "no decisive evidence -> inconclusive"
    assert body["preferred_position"] is None
    assert body["confidence"] == "low"
    assert "inconclusive" in body["limitations"][0]
    print("insufficient evidence forces inconclusive: PASSED")


async def test_missing_optional_analyses(client):
    token = await base.register_and_login(client, base.unique_email("v-bare"))
    debate_id, _ = await seed_debate(client, token, [])  # messages only
    fake = FakeLLM(payload(position="inconclusive", preferred_position=None,
                           supporting_arguments=[], counterarguments=[], confidence="low"))
    with patch_provider(fake):
        resp = await post_verdict(client, token, debate_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["position"] == "inconclusive"
    assert body["evidence_snapshot"]["total_claims"] == 0
    prompt = fake.last_messages[1].content
    assert "none extracted" in prompt
    print("missing optional analyses: PASSED")


async def test_without_judgment_and_winner_is_not_verdict(client):
    token = await base.register_and_login(client, base.unique_email("v-winner"))
    # No judgment: verdict still works.
    debate_id, _ = await seed_debate(client, token, ["supported"])
    with patch_provider(FakeLLM(payload())):
        assert (await post_verdict(client, token, debate_id)).status_code == 200

    # Judgment names agent A the winner; the verdict opposes A's position.
    debate_id, names = await seed_debate(
        client, token, ["contradicted", "contradicted", "contradicted"], with_judgment=True
    )
    fake = FakeLLM(payload(
        position="opposes", preferred_position="Cities should not subsidise tidal power",
        answer="No - the stored evidence contradicts the key output claims.",
        supporting_arguments=[{"point": "Output claims were contradicted.",
                               "agent": names[1], "claim_refs": ["C1", "C2"]}],
    ))
    with patch_provider(fake):
        resp = await post_verdict(client, token, debate_id)
    body = resp.json()
    assert resp.status_code == 200, resp.text
    prompt = " ".join(m.content for m in fake.last_messages)
    assert JUDGE_MARKER not in prompt, "judge output must not feed the verdict"
    assert "winner" not in fake.last_messages[1].content.lower()
    assert body["position"] == "opposes"
    judgment = await client.get(f"/api/v1/debates/{debate_id}/judgment", headers=base.auth(token))
    assert judgment.json()["winner_name"] == names[0]
    assert body["supporting_arguments"][0]["agent_name"] == names[1], (
        "the verdict is not tied to the best-performing agent"
    )
    print("verdict without judgment; winner is not the verdict: PASSED")


async def test_regenerate_and_failures(client):
    token = await base.register_and_login(client, base.unique_email("v-errors"))
    other = await base.register_and_login(client, base.unique_email("v-errors-other"))
    debate_id, _ = await seed_debate(client, token, ["supported"])

    resp = await client.get(f"/api/v1/debates/{debate_id}/verdict", headers=base.auth(token))
    assert resp.status_code == 404 and resp.json()["detail"] == "Verdict not found"

    with patch_provider(FailingLLM()):
        resp = await post_verdict(client, token, debate_id)
    assert resp.status_code == 502, resp.text
    assert "simulated" not in resp.text, "internal errors are not exposed"
    assert await stored_verdicts(debate_id) == []

    with patch_provider(FakeLLM("not json at all")):
        assert (await post_verdict(client, token, debate_id)).status_code == 502
    assert await stored_verdicts(debate_id) == []

    with patch_provider(FakeLLM(payload(answer="First answer."))):
        first = (await post_verdict(client, token, debate_id)).json()
    with patch_provider(FakeLLM(payload(answer="Second answer."))):
        second = (await post_verdict(client, token, debate_id, regenerate=True)).json()
    assert second["id"] == first["id"] and second["answer"] == "Second answer."
    assert len(await stored_verdicts(debate_id)) == 1

    # A failed regeneration keeps the stored verdict.
    with patch_provider(FailingLLM()):
        assert (await post_verdict(client, token, debate_id, regenerate=True)).status_code == 502
    kept = await client.get(f"/api/v1/debates/{debate_id}/verdict", headers=base.auth(token))
    assert kept.json()["answer"] == "Second answer."

    fake = FakeLLM(payload())
    with patch_provider(fake):
        assert (await post_verdict(client, other, debate_id)).status_code == 404
        assert (await client.get(f"/api/v1/debates/{debate_id}/verdict",
                                 headers=base.auth(other))).status_code == 404
        assert (await client.post(f"/api/v1/debates/{debate_id}/verdict")).status_code == 401
        assert (await post_verdict(client, token, uuid.uuid4())).status_code == 404
    assert fake.calls == 0, "unauthorized requests never reach the LLM"

    running_id, _ = await seed_debate(client, token, ["supported"], status="running")
    with patch_provider(fake):
        resp = await post_verdict(client, token, running_id)
    assert resp.status_code == 400 and fake.calls == 0
    print("regenerate, errors and authorization: PASSED")


async def test_compound_question_position_follows_parts(client):
    token = await base.register_and_login(client, base.unique_email("v-parts"))
    debate_id, _ = await seed_debate(client, token, ["supported", "supported", "contradicted"])
    parts = [{"question": "Is X harmful?", "position": "supports", "answer": "Yes"},
             {"question": "Should X be strictly regulated?", "position": "opposes", "answer": "No"}]
    with patch_provider(FakeLLM(payload(position="supports", sub_verdicts=parts))):
        body = (await post_verdict(client, token, debate_id)).json()
    assert body["position"] == "mixed", "parts disagree -> mixed"
    assert any("from the separate verdicts" in item for item in body["limitations"])

    debate_id, _ = await seed_debate(client, token, ["contradicted", "contradicted", "contradicted"])
    agree = [dict(p, position="opposes") for p in parts]
    with patch_provider(FakeLLM(payload(position="mixed", sub_verdicts=agree))):
        body = (await post_verdict(client, token, debate_id)).json()
    assert body["position"] == "opposes", "parts agree -> their position"
    print("compound question: overall position follows the parts: PASSED")


async def test_debate_context_reaches_agents(client):
    token = await base.register_and_login(client, base.unique_email("v-context"))
    resp = await client.post(
        "/api/v1/debates",
        json=base.base_payload(context="  Focus on coastal cities in Europe.  "),
        headers=base.auth(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["context"] == "Focus on coastal cities in Europe."
    resp = await client.post(
        "/api/v1/debates", json=base.base_payload(context="x" * 2001), headers=base.auth(token)
    )
    assert resp.status_code == 422
    prompt = RoundManager(None).build_user_prompt(
        "Topic?", 1, 2, [], context="Focus on coastal cities in Europe."
    )
    assert "Background provided by the user: Focus on coastal cities in Europe." in prompt
    assert "Background" not in RoundManager(None).build_user_prompt("Topic?", 1, 2, [])
    print("debate context stored and passed to agents: PASSED")


async def main():
    app = await base.setup()
    async with base.client_for(app) as client:
        await test_evidence_supported_conclusion(client)
        await test_conflicting_evidence_caps_confidence(client)
        await test_insufficient_evidence_forces_inconclusive(client)
        await test_missing_optional_analyses(client)
        await test_without_judgment_and_winner_is_not_verdict(client)
        await test_regenerate_and_failures(client)
        await test_compound_question_position_follows_parts(client)
        await test_debate_context_reaches_agents(client)
    await base.teardown()
    print("\nAll final verdict tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
