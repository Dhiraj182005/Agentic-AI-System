"""Phase 3: judgment input completeness, distinct scoring, explicit states.

Regression for the observed "5.09 for every agent": the judge saw only the
first 600 characters of each message and no rebuttal structure, gave all
agents identical dimension scores, and the ranking refused to run without
optional analyses. These tests pin the fixed behaviour.
"""

import asyncio
import json
import unittest.mock

from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from tests import test_report as base
from tests.test_verdict import FakeLLM, FailingLLM, payload, post_verdict, seed_debate

LONG_TAIL = "DISTINCTIVE-LATE-ARGUMENT-MARKER"


def judge_payload(scores: dict[str, dict]) -> str:
    return json.dumps({
        "agents": [
            {
                "agent_name": name,
                "dimensions": dims,
                "strengths": ["s"], "weaknesses": ["w"],
                "reasoning_quality": f"See R1-{name}.",
                "evidence_quality_explanation": "e", "factual_support_explanation": "f",
                "completeness_assessment": "c", "fallacy_impact_assessment": "none",
                "confidence": "medium",
            }
            for name, dims in scores.items()
        ],
        "summary": "Comparison of argument quality.",
        "limitations": [],
    })


def dims(logical, responsiveness):
    return {"logical_soundness": logical, "evidence_quality": 6.0, "relevance": 7.0,
            "effectiveness": 6.5, "completeness": 6.0, "responsiveness": responsiveness}


def patch_judge(fake):
    return unittest.mock.patch(
        "app.services.debate_judge_service.get_llm_provider", return_value=fake
    )


async def seed_structured_debate(client, token):
    """Completed 2-round debate: a long legacy opening and a structured
    rebuttal that links to it and concedes a point."""
    debate_id = await base.create_debate(client, token, topic="Should cities subsidize tidal power?")
    async with base._test_session() as session:
        debate = await session.get(Debate, debate_id)
        econ, lawyer = list(debate.agents)
        r1 = DebateRound(debate_id=debate_id, round_number=1, status="completed")
        r2 = DebateRound(debate_id=debate_id, round_number=2, status="completed")
        session.add_all([r1, r2])
        await session.flush()
        opening = DebateMessage(
            debate_id=debate_id, round_id=r1.id, agent_id=econ.id, turn_number=1,
            message_type="opening",
            content="Preamble about the topic. " * 40 + LONG_TAIL,  # ~1.07k chars: past the old 600 cut
        )
        session.add(opening)
        await session.flush()
        session.add(DebateMessage(
            debate_id=debate_id, round_id=r2.id, agent_id=lawyer.id, turn_number=1,
            message_type="closing", content="rendered",
            structured={
                "position": "Subsidies need legal guardrails.", "position_changed": False,
                "main_argument": "Procurement law limits open-ended subsidies.",
                "rebuttal_to": {"ref": f"R1-{econ.name}", "message_id": str(opening.id),
                                "agent_name": econ.name, "round_number": 1,
                                "argument": "subsidies pay off"},
                "reasoning": "State-aid rules apply.", "factual_claims": [],
                "evidence_references": [], "concession": "Pilots are lawful.",
                "recommendation": None, "uncertainties": ["Court rulings pending."],
            },
        ))
        await session.commit()
        return debate_id, econ.name, lawyer.name


async def add_verified_claim(debate_id, verdict="supported"):
    async with base._test_session() as session:
        debate = await session.get(Debate, debate_id)
        message = (await session.execute(
            DebateMessage.__table__.select().where(DebateMessage.debate_id == debate_id).limit(1)
        )).first()
        claim = Claim(debate_id=debate_id, message_id=message.id, agent_id=debate.agents[0].id,
                      text="Tides are predictable.", claim_type="factual", position=99)
        session.add(claim)
        await session.flush()
        session.add(ClaimVerification(claim_id=claim.id, verdict=verdict, confidence="high",
                                      explanation="x", evidence_summary="y", evidence_ids=[]))
        await session.commit()


async def test_judge_input_completeness_and_distinct_scores(client):
    token = await base.register_and_login(client, base.unique_email("jq-input"))
    debate_id, econ, lawyer = await seed_structured_debate(client, token)
    prompts: list[str] = []

    class RecordingLLM(FakeLLM):
        async def generate(self, messages, temperature=None, max_tokens=None):
            prompts.append(messages[1].content)
            return await super().generate(messages, temperature, max_tokens)

    fake = RecordingLLM(judge_payload({econ: dims(6.0, 4.0), lawyer: dims(8.0, 8.5)}))
    with patch_judge(fake):
        resp = await client.post(f"/api/v1/debates/{debate_id}/judge", headers=base.auth(token))
    assert resp.status_code == 200, resp.text
    # One call per agent: each targets one participant, the others are context.
    assert len(prompts) == 2
    econ_prompt, lawyer_prompt = prompts
    assert f"Evaluate ONLY {econ}." in econ_prompt and f"Evaluate ONLY {lawyer}." in lawyer_prompt
    assert LONG_TAIL in econ_prompt, "the judge sees beyond the first 600 characters"
    assert LONG_TAIL not in lawyer_prompt, "other agents are shown compactly"
    assert f"{econ} (" in lawyer_prompt and "context only, do not score" in lawyer_prompt
    prompt = lawyer_prompt
    assert f"[R2-{lawyer}, closing]" in prompt and "main argument: Procurement law" in prompt
    assert f"rebutted R1-{econ}" in prompt and "1 concession(s)" in prompt
    assert "Format: balanced" in prompt
    assert "responsiveness" in fake.last_messages[0].content
    assert "Never copy one agent's scores" in fake.last_messages[0].content

    body = resp.json()
    scores = {c["agent_name"]: c["final_score"] for c in body["agent_scores"]}
    assert scores[lawyer] > scores[econ], scores
    assert body["outcome"] == "winner" and body["winner_name"] == lawyer
    assert body["scoring_rubric"]["version"] == 2
    assert body["scoring_rubric"]["inputs"]["messages"] == 2
    assert body["stale"] is False
    print("judge gets full turns + responsiveness and scores agents distinctly: PASSED")
    return token, debate_id, econ, lawyer


async def test_stale_judgment_and_regenerate(client, token, debate_id, econ, lawyer):
    await add_verified_claim(debate_id)
    got = await client.get(f"/api/v1/debates/{debate_id}/judgment", headers=base.auth(token))
    assert got.json()["stale"] is True, "new verification makes the judgment stale"

    fake = FakeLLM(judge_payload({econ: dims(6.0, 4.0), lawyer: dims(8.0, 8.5)}))
    with patch_judge(fake):
        same = await client.post(f"/api/v1/debates/{debate_id}/judge", headers=base.auth(token))
        assert fake.calls == 0 and same.json()["stale"] is True, "plain POST stays idempotent"
        fresh = await client.post(f"/api/v1/debates/{debate_id}/judge?regenerate=true",
                                  headers=base.auth(token))
    assert fake.calls == 2 and fresh.json()["stale"] is False
    assert fresh.json()["scoring_rubric"]["inputs"]["verifications"] == 1

    # A failed re-run keeps the stored judgment and reports an error, not a verdict.
    with patch_judge(FailingLLM()):
        failed = await client.post(f"/api/v1/debates/{debate_id}/judge?regenerate=true",
                                   headers=base.auth(token))
    assert failed.status_code == 502
    kept = await client.get(f"/api/v1/debates/{debate_id}/judgment", headers=base.auth(token))
    assert kept.status_code == 200 and kept.json()["id"] == fresh.json()["id"]
    print("stale judgment detection, regenerate, failed re-run keeps result: PASSED")


async def test_verdict_evidence_basis_and_reasons(client):
    token = await base.register_and_login(client, base.unique_email("jq-basis"))
    cases = [
        ([], "inconclusive", "none", "no_verified_evidence"),
        (["supported", "contradicted"], "inconclusive", "substantial", "conflicting_evidence"),
        (["supported", None, None, None], "inconclusive", "partial", "incomplete_evidence"),
        (["supported", "supported", "supported"], "supports", "substantial", None),
    ]
    for verdicts, position, basis, reason in cases:
        debate_id, _ = await seed_debate(client, token, verdicts)
        fake = FakeLLM(payload(position=position, preferred_position=None if position == "inconclusive" else "Yes"))
        with unittest.mock.patch("app.services.verdict_service.get_llm_provider", return_value=fake):
            body = (await post_verdict(client, token, debate_id)).json()
        assert body["position"] == position, (verdicts, body["position"])
        assert body["evidence_basis"] == basis, (verdicts, body["evidence_basis"])
        assert body["inconclusive_reason"] == reason, (verdicts, body["inconclusive_reason"])
        assert body["stale"] is False
    # Verifying another claim afterwards marks the verdict stale.
    await add_verified_claim(debate_id, "contradicted")
    got = await client.get(f"/api/v1/debates/{debate_id}/verdict", headers=base.auth(token))
    assert got.json()["stale"] is True
    print("verdict evidence basis, inconclusive reasons and staleness: PASSED")


async def test_verdict_prompt_completeness(client):
    token = await base.register_and_login(client, base.unique_email("jq-vprompt"))
    debate_id, econ, lawyer = await seed_structured_debate(client, token)
    fake = FakeLLM(payload(position="inconclusive", preferred_position=None))
    with unittest.mock.patch("app.services.verdict_service.get_llm_provider", return_value=fake):
        await post_verdict(client, token, debate_id)
    prompt = fake.last_messages[1].content
    assert "Format: balanced" in prompt
    assert f"[R2-{lawyer}, closing]" in prompt and "concedes: Pilots are lawful." in prompt
    assert "Claims: 0 extracted" in prompt and "claim extraction has not been run" in prompt
    assert "Fallacy checks: not run" in prompt and "Argument quality: not run" in prompt
    assert "winner" not in prompt.lower()
    print("verdict prompt carries turns, format and analysis status: PASSED")


async def test_states_are_separate(client):
    token = await base.register_and_login(client, base.unique_email("jq-states"))
    # Failed / incomplete debates: no judgment and no verdict, never "inconclusive".
    for status in ("failed", "running", "pending"):
        debate_id, _ = await seed_debate(client, token, ["supported"], status=status)
        judge = FakeLLM(judge_payload({}))
        verdict = FakeLLM(payload())
        with patch_judge(judge), unittest.mock.patch(
            "app.services.verdict_service.get_llm_provider", return_value=verdict
        ):
            j = await client.post(f"/api/v1/debates/{debate_id}/judge", headers=base.auth(token))
            v = await post_verdict(client, token, debate_id)
        assert j.status_code == 400 and v.status_code == 400, (status, j.text, v.text)
        assert judge.calls == 0 and verdict.calls == 0

    # Completed but not yet judged: 404 (pending), not an empty verdict.
    debate_id, _ = await seed_debate(client, token, ["supported"])
    assert (await client.get(f"/api/v1/debates/{debate_id}/judgment",
                             headers=base.auth(token))).status_code == 404
    assert (await client.get(f"/api/v1/debates/{debate_id}/verdict",
                             headers=base.auth(token))).status_code == 404
    # Provider failure: an error, never stored as an inconclusive result.
    with patch_judge(FailingLLM()), unittest.mock.patch(
        "app.services.verdict_service.get_llm_provider", return_value=FailingLLM()
    ):
        assert (await client.post(f"/api/v1/debates/{debate_id}/judge",
                                  headers=base.auth(token))).status_code == 502
        assert (await post_verdict(client, token, debate_id)).status_code == 502
    assert (await client.get(f"/api/v1/debates/{debate_id}/judgment",
                             headers=base.auth(token))).status_code == 404
    assert (await client.get(f"/api/v1/debates/{debate_id}/verdict",
                             headers=base.auth(token))).status_code == 404
    print("failed / incomplete / pending / provider-error states stay separate: PASSED")


async def test_opposing_position_and_missing_data(client):
    token = await base.register_and_login(client, base.unique_email("jq-oppose"))
    # Evidence contradicts the proposition: verdict opposes it, with a basis.
    debate_id, _ = await seed_debate(client, token, ["contradicted", "contradicted", "contradicted"])
    fake = FakeLLM(payload(position="opposes", preferred_position="No - subsidies are not justified",
                           confidence="high"))
    with unittest.mock.patch("app.services.verdict_service.get_llm_provider", return_value=fake):
        body = (await post_verdict(client, token, debate_id)).json()
    assert body["position"] == "opposes" and body["evidence_basis"] == "substantial"
    assert body["inconclusive_reason"] is None and body["confidence"] == "high"

    # Completed debate with no messages: missing required data -> 400, no LLM.
    empty_id = await base.create_debate(client, token, topic="Empty debate")
    judge, verdict = FakeLLM(judge_payload({})), FakeLLM(payload())
    with patch_judge(judge), unittest.mock.patch(
        "app.services.verdict_service.get_llm_provider", return_value=verdict
    ):
        j = await client.post(f"/api/v1/debates/{empty_id}/judge", headers=base.auth(token))
        v = await post_verdict(client, token, empty_id)
    assert j.status_code == 400 and v.status_code == 400, (j.text, v.text)
    assert "no messages" in j.json()["detail"] and "no messages" in v.json()["detail"]
    assert judge.calls == 0 and verdict.calls == 0
    print("opposing-evidence verdict; missing required data rejected: PASSED")


async def main():
    app = await base.setup()
    async with base.client_for(app) as client:
        state = await test_judge_input_completeness_and_distinct_scores(client)
        await test_stale_judgment_and_regenerate(client, *state)
        await test_verdict_evidence_basis_and_reasons(client)
        await test_verdict_prompt_completeness(client)
        await test_states_are_separate(client)
        await test_opposing_position_and_missing_data(client)
    await base.teardown()
    print("\nAll judgment quality tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
