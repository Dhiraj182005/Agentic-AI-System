"""Post-debate analysis pipeline: automatic claim extraction, evidence
retrieval and verification after a debate, regenerate-with-missing-stages,
technical failure vs insufficient evidence, duplicates, concurrency,
authorization and bias-aware verdicts. All providers are mocked."""

import asyncio
import contextlib
import json
import re
import unittest.mock

from sqlalchemy import func, select

from app.evidence.base import EvidenceProviderAPIError, SearchResult
from app.llm.base import LLMResponse
from app.models.claim import Claim
from app.models.claim_verification import ClaimVerification
from app.models.debate import Debate
from app.models.debate_message import DebateMessage
from app.models.debate_round import DebateRound
from app.models.evidence import Evidence
from app.services import analysis_pipeline
from tests import test_report as base

TOPIC = ("Social media does more harm than good, and governments should strictly "
         "regulate it despite free-speech concerns.")


class ExtractionLLM:
    """Returns one factual + one opinion + one prediction claim per message."""

    def __init__(self, fail=False):
        self.calls = 0
        self.prompt_sizes = []
        self.max_tokens = []
        self.fail = fail

    async def generate(self, messages, temperature=None, max_tokens=None, **_):
        self.calls += 1
        self.prompt_sizes.append(len(messages[1].content))
        self.max_tokens.append(max_tokens)
        if self.fail:
            from app.llm.base import LLMServerError
            raise LLMServerError("boom")
        ids = re.findall(r"Message ([0-9a-f-]{36}) \|", messages[1].content)
        claims = []
        for i, mid in enumerate(ids):
            claims += [
                {"message_id": mid, "claim": f"Teen social media use rose {10 + i} percent.", "claim_type": "factual"},
                {"message_id": mid, "claim": "Platforms are bad for society.", "claim_type": "opinion"},
                {"message_id": mid, "claim": "Regulation will reduce harm by 2030.", "claim_type": "prediction"},
            ]
        return LLMResponse(content=json.dumps(claims), provider="fake", model="fake")


class Search:
    def __init__(self, results=2, fail_on: set[int] | None = None):
        self.calls = 0
        self.results = results
        self.fail_on = fail_on or set()

    async def search(self, query, max_results=5):
        self.calls += 1
        if self.calls in self.fail_on:
            raise EvidenceProviderAPIError("tavily down")
        return [
            SearchResult(title=f"Study {n} on {query[:20]}", url=f"https://example.org/study-{self.calls}-{n}",
                         snippet="Survey data on adolescent social media use.", source_name="example.org",
                         relevance_score=0.8)
            for n in range(self.results)
        ]


class VerifyLLM:
    def __init__(self, verdict="supported", fail=False):
        self.calls = 0
        self.verdict = verdict
        self.fail = fail

    async def generate(self, messages, temperature=None, max_tokens=None, **_):
        self.calls += 1
        if self.fail:
            from app.llm.base import LLMServerError
            raise LLMServerError("boom")
        urls = re.findall(r"https://example\.org/[a-z0-9-]+", messages[1].content)
        return LLMResponse(content=json.dumps({
            "verdict": self.verdict, "confidence": "medium",
            "explanation": "The stored survey sources report this increase.",
            "evidence_summary": "Survey data.", "sources": urls[:1],
        }), provider="fake", model="fake")


class VerdictLLM:
    def __init__(self, position="mixed"):
        self.calls = 0
        self.prompts = []
        self.position = position

    async def generate(self, messages, temperature=None, max_tokens=None, **_):
        self.calls += 1
        self.prompts.append(messages[1].content)
        return LLMResponse(content=json.dumps({
            "position": self.position, "answer": "Partly: harms are documented, strict regulation is not shown to be justified.",
            "preferred_position": "Targeted rather than strict regulation", "summary": "Mixed.",
            "reasoning": "Verified data show some harms; evidence on strict regulation is thin.",
            "supporting_arguments": [{"point": "Usage rose", "claim_refs": ["C1"]}], "counterarguments": [],
            "confidence": "medium", "limitations": [], "unresolved_questions": [],
            "question_assumptions": [
                {"assumption": "Social media does more harm than good", "assessment": "Evidence shows some harms but also benefits.", "status": "contested"},
                {"assumption": "Strict regulation is the right remedy", "assessment": "Not established by the evidence.", "status": "unsupported"},
            ],
            "sub_verdicts": [
                {"question": "Does social media do more harm than good?", "position": "mixed", "answer": "Harms and benefits both documented."},
                {"question": "Should governments strictly regulate it despite free-speech concerns?", "position": "inconclusive", "answer": "Not established."},
            ],
        }), provider="fake", model="fake")


class MessageLLM:
    async def generate(self, messages, **kwargs):
        system = messages[0].content
        if 'fallacy_type' in system:
            output = dict(fallacy_type='no_fallacy', severity='low', confidence=0.9,
                          explanation='No recognizable fallacy in this test argument.', evidence_span=None)
        else:
            output = dict(logical_soundness=7, evidence_score=6, relevance_score=8,
                          effectiveness_score=7, overall_score=7, responsiveness=6,
                          completeness=7, explanation='Clear but limited argument.',
                          strengths=['Clear'], weaknesses=['Limited detail'])
        return LLMResponse(content=json.dumps(output), provider='fake', model='fake')


class PerformanceLLM:
    async def generate(self, messages, **kwargs):
        from tests.test_judge import judge_json
        target = re.search(r"Evaluate ONLY (.*?)\.", messages[1].content).group(1)
        dims = {key: 7.0 for key in ("logical_soundness", "evidence_quality", "responsiveness", "relevance", "effectiveness", "completeness")}
        return LLMResponse(content=judge_json({target: dims}), provider="fake", model="fake")


@contextlib.contextmanager
def providers(extraction=None, search=None, verify=None, verdict=None):
    class NoMatchFactChecks:
        configured = True
        async def search(self, *args, **kwargs):
            return []
    patches = [
        unittest.mock.patch("app.services.debate_judge_service.get_llm_provider", return_value=PerformanceLLM()),
        unittest.mock.patch("app.services.claim_service.get_fact_check_client", return_value=NoMatchFactChecks()),
        unittest.mock.patch("app.services.fallacy_detection.get_llm_provider", return_value=MessageLLM()),
        unittest.mock.patch("app.services.argument_evaluation.get_llm_provider", return_value=MessageLLM()),
        unittest.mock.patch("app.services.claim_extraction.get_llm_provider", return_value=extraction or ExtractionLLM()),
        unittest.mock.patch("app.services.claim_service.get_evidence_provider", return_value=search or Search()),
        unittest.mock.patch("app.services.verification_service.get_llm_provider", return_value=verify or VerifyLLM()),
        unittest.mock.patch("app.services.verdict_service.get_llm_provider", return_value=verdict or VerdictLLM()),
    ]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


async def completed_debate(client, token, agents=3, rounds=3, verify=True):
    debate_id = await base.create_debate(client, token, topic=TOPIC, verify_evidence=verify,
                                         agent_ids=["economist", "lawyer", "ethicist", "doctor", "scientist", "analyst"][:agents])
    async with base._test_session() as session:
        debate = await session.get(Debate, debate_id)
        for r in range(1, rounds + 1):
            rnd = DebateRound(debate_id=debate_id, round_number=r, status="completed")
            session.add(rnd)
            await session.flush()
            for t, agent in enumerate(debate.agents, start=1):
                session.add(DebateMessage(debate_id=debate_id, round_id=rnd.id, agent_id=agent.id, turn_number=t,
                                          message_type="opening", content=f"{agent.name} round {r} argument about social media."))
        await session.commit()
    return debate_id


async def counts(debate_id):
    async with base._test_session() as session:
        claims = (await session.execute(select(Claim).where(Claim.debate_id == debate_id))).scalars().all()
        ids = [c.id for c in claims]
        verifications = (await session.execute(select(ClaimVerification).where(ClaimVerification.claim_id.in_(ids)))).scalars().all() if ids else []
        evidence = (await session.execute(select(func.count(Evidence.id)).where(Evidence.claim_id.in_(ids)))).scalar_one() if ids else 0
        debate = await session.get(Debate, debate_id)
        return claims, verifications, evidence, debate.analysis_status


def verdict_url(debate_id, regenerate=True):
    return f"/api/v1/debates/{debate_id}/verdict?run_missing_analysis=true" + ("&regenerate=true" if regenerate else "")


# ---------------------------------------------------------------------------


async def test_auto_analysis_after_completion(client):
    token = await base.register_and_login(client, base.unique_email("ap-auto"))
    debate_id = await base.create_debate(client, token, topic=TOPIC, verify_evidence=True)
    # Make it pending again and run it through the real start endpoint.
    async with base._test_session() as session:
        (await session.get(Debate, debate_id)).status = "pending"
        await session.commit()

    class TurnLLM:
        async def generate(self, messages, temperature=None, max_tokens=None, **_):
            return LLMResponse(content="Teen usage rose sharply; harms are documented.", provider="f", model="f")

    extraction, search, verify, verdict = ExtractionLLM(), Search(), VerifyLLM(), VerdictLLM()
    with unittest.mock.patch("app.agents.base_agent.get_llm_provider", return_value=TurnLLM()), \
            unittest.mock.patch.object(analysis_pipeline, "auto_analysis_enabled", return_value=True), \
            providers(extraction, search, verify, verdict):
        resp = await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))
        assert resp.status_code == 200 and resp.json()["status"] == "completed", resp.text
        await analysis_pipeline.wait_for_background()

    claims, verifications, evidence, status = await counts(debate_id)
    assert status["state"] == "completed" and status["trigger"] == "auto", status
    assert {c.claim_type for c in claims} == {"factual", "opinion", "prediction"}
    factual = [c for c in claims if c.claim_type == "factual"]
    verified_ids = {v.claim_id for v in verifications}
    assert verified_ids <= {c.id for c in factual}, "opinions/predictions are never verified as facts"
    assert len(verifications) == min(len(factual), 8) == status["verified"]
    assert all(v.verdict == "supported" and v.evidence_ids for v in verifications)
    assert evidence == 2 * len(verifications), "real stored sources per verified claim"
    assert verdict.calls == 1 and status["verdict"] == "generated"

    body = (await client.get(f"/api/v1/debates/{debate_id}/verdict", headers=base.auth(token))).json()
    assert body["evidence_basis"] in ("partial", "substantial") and body["inconclusive_reason"] is None
    assert body["evidence_snapshot"]["analysis_state"] == "completed"
    assert body["supporting_arguments"][0]["claims"][0]["sources"][0]["url"].startswith("https://example.org/")

    analysis = (await client.get(f"/api/v1/debates/{debate_id}/analysis", headers=base.auth(token))).json()
    assert analysis["state"] == "completed" and analysis["failures"] == []
    print("automatic analysis after debate completion (factual claims only): PASSED")


async def test_no_auto_analysis_when_disabled(client):
    token = await base.register_and_login(client, base.unique_email("ap-off"))
    debate_id = await base.create_debate(client, token, topic=TOPIC, verify_evidence=False)
    async with base._test_session() as session:
        (await session.get(Debate, debate_id)).status = "pending"
        await session.commit()

    class TurnLLM:
        async def generate(self, messages, temperature=None, max_tokens=None, **_):
            return LLMResponse(content="text", provider="f", model="f")

    extraction = ExtractionLLM()
    with unittest.mock.patch("app.agents.base_agent.get_llm_provider", return_value=TurnLLM()), \
            unittest.mock.patch.object(analysis_pipeline, "auto_analysis_enabled", return_value=True), \
            providers(extraction=extraction):
        await client.post(f"/api/v1/debates/{debate_id}/start", headers=base.auth(token))
        await analysis_pipeline.wait_for_background()
    claims, _, _, status = await counts(debate_id)
    assert claims == [] and status is None and extraction.calls == 0
    print("debates without 'verify evidence' are not auto-analysed: PASSED")


async def test_regenerate_runs_missing_stages_without_duplicates(client):
    token = await base.register_and_login(client, base.unique_email("ap-regen"))
    debate_id = await completed_debate(client, token, agents=6, rounds=3, verify=False)
    extraction, search, verify, verdict = ExtractionLLM(), Search(), VerifyLLM(), VerdictLLM()
    with providers(extraction, search, verify, verdict):
        resp = await client.post(verdict_url(debate_id), headers=base.auth(token))
    assert resp.status_code == 200, resp.text
    # 18 messages -> 3 batched extraction requests, each small.
    assert extraction.calls == 3 and max(extraction.max_tokens) <= 6000
    assert max(extraction.prompt_sizes) < 3000
    claims, verifications, _, status = await counts(debate_id)
    assert len(claims) == 54 and len(verifications) == 18 and status["state"] == "completed"
    body = resp.json()
    # Bias-aware verdict for the compound, loaded question.
    assert [a["status"] for a in body["assumptions"]] == ["contested", "unsupported"]
    assert len(body["sub_verdicts"]) == 2 and body["sub_verdicts"][1]["position"] == "inconclusive"
    assert "Evidence analysis run: completed" in verdict.prompts[0]

    # Second regenerate: nothing missing -> no extraction/search/verification calls.
    e2, s2, v2, d2 = ExtractionLLM(), Search(), VerifyLLM(), VerdictLLM()
    with providers(e2, s2, v2, d2):
        again = await client.post(verdict_url(debate_id), headers=base.auth(token))
    assert again.status_code == 200 and (e2.calls, s2.calls, v2.calls) == (0, 0, 0)
    # Consistency: unchanged evidence -> the stored verdict stands (no new
    # LLM call that could flip the label between clicks).
    assert d2.calls == 1 and again.json()["id"] == body["id"]
    assert again.json()["position"] == body["position"]
    claims2, verifications2, _, _ = await counts(debate_id)
    assert len(claims2) == 54 and len(verifications2) == 18, "no duplicate claims or verifications"

    # New evidence (a verification changes) -> regenerate refreshes it.
    async with base._test_session() as session:
        claim_ids = [c.id for c in claims2]
        row = (await session.execute(select(ClaimVerification).where(
            ClaimVerification.claim_id.in_(claim_ids)))).scalars().first()
        row.verdict = "contradicted"
        await session.commit()
    d4 = VerdictLLM()
    with providers(verdict=d4):
        refreshed = await client.post(verdict_url(debate_id), headers=base.auth(token))
    assert refreshed.status_code == 200 and d4.calls == 1
    assert refreshed.json()["evidence_snapshot"]["contradicted"] == 1

    # Without regenerate and with nothing new, the stored verdict is kept.
    d3 = VerdictLLM()
    with providers(verdict=d3):
        kept = await client.post(verdict_url(debate_id, regenerate=False), headers=base.auth(token))
    assert kept.status_code == 200 and d3.calls == 0
    print("regenerate runs only missing stages; batched extraction; no duplicates; bias-aware verdict: PASSED")


async def test_missing_evidence_vs_failures(client):
    token = await base.register_and_login(client, base.unique_email("ap-fail"))
    # Search finds nothing: genuine insufficient evidence (no verification LLM call).
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    verify = VerifyLLM()
    with providers(search=Search(results=0), verify=verify, verdict=VerdictLLM(position="inconclusive")):
        body = (await client.post(verdict_url(debate_id), headers=base.auth(token))).json()
    claims, verifications, evidence, status = await counts(debate_id)
    assert status["state"] == "completed" and status["no_sources"] == 2 and evidence == 0
    assert {v.verdict for v in verifications} == {"insufficient_evidence"} and verify.calls == 0
    assert all(c.evidence_retrieved_at is not None for c in claims if c.claim_type == "factual")
    assert body["inconclusive_reason"] == "no_verified_evidence"

    # Search fails for one claim, verification fails for another: technical,
    # recorded as failures - never stored as insufficient evidence.
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    with providers(search=Search(fail_on={1}), verify=VerifyLLM(fail=True),
                   verdict=VerdictLLM(position="inconclusive")):
        body = (await client.post(verdict_url(debate_id), headers=base.auth(token))).json()
    claims, verifications, _, status = await counts(debate_id)
    stages = sorted(f["stage"] for f in status["failures"])
    assert status["state"] == "partial" and stages == ["retrieval", "verification"], status
    assert verifications == [], "failures never become verification records"
    assert "tavily down" not in json.dumps(status) and "boom" not in json.dumps(status)
    assert body["inconclusive_reason"] == "analysis_incomplete"
    assert body["evidence_snapshot"]["analysis_failures"] == 2

    # Extraction fails entirely: state failed, verdict still explains it.
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    with providers(extraction=ExtractionLLM(fail=True), verdict=VerdictLLM(position="inconclusive")):
        body = (await client.post(verdict_url(debate_id), headers=base.auth(token))).json()
    _, _, _, status = await counts(debate_id)
    assert status["state"] == "failed" and status["extraction"] == "failed"
    assert body["inconclusive_reason"] == "analysis_incomplete"
    print("no sources = insufficient evidence; search/LLM failures = analysis incomplete: PASSED")


async def test_legacy_unsearched_verification_is_redone(client):
    token = await base.register_and_login(client, base.unique_email("ap-legacy"))
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    with providers():
        claims = (await client.post(f"/api/v1/debates/{debate_id}/claims/extract",
                                    headers=base.auth(token))).json()["claims"]
    factual = next(c for c in claims if c["claim_type"] == "factual")
    # Old manual flow: Verify before Retrieve -> insufficient without a search.
    resp = await client.post(f"/api/v1/claims/{factual['id']}/verify", headers=base.auth(token))
    assert resp.json()["verdict"] == "insufficient_evidence"
    search, verify = Search(), VerifyLLM()
    with providers(search=search, verify=verify):
        await client.post(verdict_url(debate_id), headers=base.auth(token))
    async with base._test_session() as session:
        row = (await session.execute(select(ClaimVerification).where(
            ClaimVerification.claim_id == base.uuid.UUID(factual["id"])))).scalar_one()
    assert row.verdict == "supported" and row.evidence_ids, "never-searched result was redone"
    print("verification made without any search is redone with evidence: PASSED")


async def test_concurrency_and_authorization(client):
    token = await base.register_and_login(client, base.unique_email("ap-auth"))
    other = await base.register_and_login(client, base.unique_email("ap-auth-other"))
    debate_id = await completed_debate(client, token, agents=2, rounds=1)

    # Another run in progress -> 409, nothing extracted.
    async with base._test_session() as session:
        debate = await session.get(Debate, debate_id)
        debate.analysis_status = {"state": "running", "started_at": analysis_pipeline._now().isoformat()}
        await session.commit()
    extraction = ExtractionLLM()
    with providers(extraction=extraction):
        busy = await client.post(verdict_url(debate_id), headers=base.auth(token))
        busy_bg = await client.post(f"/api/v1/debates/{debate_id}/analysis", headers=base.auth(token))
    assert busy.status_code == 202 and busy_bg.status_code == 202 and extraction.calls == 0
    assert busy.json()["joined"] and busy_bg.json()["joined"]

    # Concurrent regenerate requests: exactly one runs.
    async with base._test_session() as session:
        (await session.get(Debate, debate_id)).analysis_status = None
        await session.commit()

    class SlowExtraction(ExtractionLLM):
        async def generate(self, *a, **k):
            await asyncio.sleep(0.05)
            return await super().generate(*a, **k)

    slow = SlowExtraction()
    with providers(extraction=slow):
        r1, r2 = await asyncio.gather(
            client.post(verdict_url(debate_id), headers=base.auth(token)),
            client.post(verdict_url(debate_id), headers=base.auth(token)),
        )
    assert sorted([r1.status_code, r2.status_code]) == [200, 202] and slow.calls == 1
    assert next(r for r in (r1, r2) if r.status_code == 202).json()["joined"]
    claims, _, _, _ = await counts(debate_id)
    assert len(claims) == 6, "one extraction, no duplicates"

    for method, url in (("get", f"/api/v1/debates/{debate_id}/analysis"),
                        ("post", f"/api/v1/debates/{debate_id}/analysis"),
                        ("post", verdict_url(debate_id))):
        resp = await getattr(client, method)(url, headers=base.auth(other))
        assert resp.status_code == 404, (url, resp.status_code)
        assert (await getattr(client, method)(url)).status_code == 401

    # Incomplete debate cannot be analysed.
    running = await completed_debate(client, token, agents=2, rounds=1)
    async with base._test_session() as session:
        (await session.get(Debate, running)).status = "failed"
        await session.commit()
    assert (await client.post(verdict_url(running), headers=base.auth(token))).status_code == 400
    assert (await client.post(f"/api/v1/debates/{running}/analysis", headers=base.auth(token))).status_code == 400
    print("concurrent runs refused (409); authorization and completion enforced: PASSED")


async def test_background_endpoint_and_stale_runs(client):
    token = await base.register_and_login(client, base.unique_email("ap-bg"))
    debate_id = await completed_debate(client, token, agents=2, rounds=1)
    with providers():
        resp = await client.post(f"/api/v1/debates/{debate_id}/analysis", headers=base.auth(token))
        assert resp.status_code == 202
        await analysis_pipeline.wait_for_background()
    status = (await client.get(f"/api/v1/debates/{debate_id}/analysis", headers=base.auth(token))).json()
    assert status["state"] == "completed" and status["trigger"] == "manual"

    # A run abandoned long ago (server stopped) is reported as failed and can be re-run.
    async with base._test_session() as session:
        (await session.get(Debate, debate_id)).analysis_status = {
            "state": "running", "started_at": "2020-01-01T00:00:00+00:00"}
        await session.commit()
    status = (await client.get(f"/api/v1/debates/{debate_id}/analysis", headers=base.auth(token))).json()
    assert status["state"] == "failed"
    with providers():
        assert (await client.post(verdict_url(debate_id), headers=base.auth(token))).status_code == 200
    print("background analysis endpoint; abandoned runs recoverable: PASSED")


async def main():
    app = await base.setup()
    async with base.client_for(app) as client:
        await test_auto_analysis_after_completion(client)
        await test_no_auto_analysis_when_disabled(client)
        await test_regenerate_runs_missing_stages_without_duplicates(client)
        await test_missing_evidence_vs_failures(client)
        await test_legacy_unsearched_verification_is_redone(client)
        await test_concurrency_and_authorization(client)
        await test_background_endpoint_and_stale_runs(client)
    await base.teardown()
    print("\nAll analysis pipeline tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
