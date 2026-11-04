"""Persisted lifecycle, structured extraction, job joining, fencing and recovery."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import patch
from types import SimpleNamespace
from sqlalchemy import select, text
from app.llm.base import LLMResponse, LLMProviderAPIError
from app.models.debate import Debate
from app.services import analysis_pipeline, debate_service
from app.services.claim_extraction import ClaimExtractionService, ClaimExtractionError, MessageContext, parse_claims_payload
from tests.test_analysis_pipeline import base, completed_debate, providers, ExtractionLLM


def test_structured_claim_contract():
    mid = str(uuid4())
    item = {"source_message_id": mid, "claim_text": "Water freezes at zero degrees Celsius under standard pressure.", "claim_type": "factual", "agent_name": "Scientist"}
    for raw in (json.dumps({"claims": [item]}), '```json\n' + json.dumps({"claims": [item]}) + '\n```', 'Result: ' + json.dumps({"claims": [item]}) + ' end'):
        claims = parse_claims_payload(raw, {mid})
        assert len(claims) == 1 and claims[0].message_id == mid and claims[0].claim_type == "factual"
    assert parse_claims_payload('{"claims": []}', {mid}) == []
    for raw in ('{"claims": "bad"}', '{"claims": [}', 'I cannot extract this', '{"claims": [{"claim_text":"Invented", "source_message_id":"unknown"}]}'):
        try:
            parse_claims_payload(raw, {mid})
        except ClaimExtractionError:
            pass
        else:
            raise AssertionError("Invalid extraction must never become an empty success")
    print("Structured envelope, legacy compatibility, source validation and zero vs failure: PASSED")


async def test_bounded_repair():
    class Repair:
        def __init__(self, always_fail=False):
            self.calls = 0
            self.modes = []
            self.always_fail = always_fail
        async def generate(self, messages, temperature=None, max_tokens=None, json_mode=False):
            self.calls += 1
            self.modes.append(json_mode)
            raw = 'not JSON' if self.calls == 1 or self.always_fail else '{"claims": []}'
            return LLMResponse(content=raw, provider="mock", model="mock")
    contexts = [MessageContext(uuid4(), uuid4(), "Scientist", "This is an opinion.")]
    model = Repair()
    assert await ClaimExtractionService(model).extract(contexts) == []
    assert model.calls == 2 and all(model.modes)
    failure = Repair(always_fail=True)
    try:
        await ClaimExtractionService(failure).extract(contexts)
    except ClaimExtractionError:
        pass
    else:
        raise AssertionError("Failed repair must remain a failure")
    assert failure.calls == 2
    print("Provider JSON mode and one bounded formatting repair: PASSED")


class Runtime:
    def __init__(self, entered, release, fail_at=None):
        self.entered, self.release, self.fail_at = entered, release, fail_at
        self.calls = 0
    async def generate_response(self, *args, **kwargs):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        if self.calls == self.fail_at:
            raise LLMProviderAPIError("mock outage")
        return LLMResponse(content="A concise argument based on the supplied topic.", provider="mock", model="mock")


async def test_async_debate(client):
    token = await base.register_and_login(client, base.unique_email("live-execution"))
    headers = base.auth(token)
    response = await client.post('/api/v1/debates', headers=headers, json=base.base_payload(total_rounds=2))
    did = response.json()["id"]
    entered, release = asyncio.Event(), asyncio.Event()
    model = Runtime(entered, release)
    with patch('app.orchestration.debate_engine.get_agent_by_role', return_value=model):
        started = await client.post(f'/api/v1/debates/{did}/execute', headers=headers)
        assert started.status_code == 202
        await asyncio.wait_for(entered.wait(), 5)
        duplicate = await client.post(f'/api/v1/debates/{did}/execute', headers=headers)
        assert duplicate.status_code == 202 and model.calls == 1
        snapshot = (await client.get(f'/api/v1/debates/{did}/execution', headers=headers)).json()
        assert snapshot["execution_state"] == "running" and snapshot["current_round"] == 1
        assert snapshot["completed_turns"] == 0 and snapshot["total_turns"] == 4
        assert sum(a["status"] == "generating_argument" for a in snapshot["agents"]) == 1
        release.set()
        await debate_service.wait_for_execution()
    snapshot = (await client.get(f'/api/v1/debates/{did}/execution', headers=headers)).json()
    assert snapshot["transcript_status"] == "completed" and snapshot["execution_state"] == "analyzing"
    assert snapshot["completed_turns"] == 4 and snapshot["debate_progress"] == 100
    assert snapshot["completed_rounds"] == 2 and not snapshot["verdict_available"]
    ids = [e["sequence"] for e in snapshot["events"]]
    assert ids == sorted(set(ids)) and len(ids) >= 10
    assert all(a["status"] == "completed" for a in snapshot["agents"])
    other = await base.register_and_login(client, base.unique_email("execution-other"))
    assert (await client.get(f'/api/v1/debates/{did}/execution', headers=base.auth(other))).status_code == 404
    print("Async start, duplicate prevention, refresh snapshot, exact progress and ownership: PASSED")


async def test_failed_turn_resume(client):
    token = await base.register_and_login(client, base.unique_email("execution-retry"))
    headers = base.auth(token)
    did = (await client.post('/api/v1/debates', headers=headers, json=base.base_payload(total_rounds=2))).json()["id"]
    release = asyncio.Event(); release.set()
    failing = Runtime(asyncio.Event(), release, fail_at=2)
    with patch('app.orchestration.debate_engine.get_agent_by_role', return_value=failing):
        await client.post(f'/api/v1/debates/{did}/execute', headers=headers)
        await debate_service.wait_for_execution()
    failed = (await client.get(f'/api/v1/debates/{did}/execution', headers=headers)).json()
    assert failed["execution_state"] == "failed" and failed["completed_turns"] == 1
    assert sum(a["status"] == "failed" for a in failed["agents"]) == 1
    working = Runtime(asyncio.Event(), release)
    with patch('app.orchestration.debate_engine.get_agent_by_role', return_value=working):
        await client.post(f'/api/v1/debates/{did}/execute?resume=true', headers=headers)
        await debate_service.wait_for_execution()
    result = (await client.get(f'/api/v1/debates/{did}/execution', headers=headers)).json()
    assert result["completed_turns"] == 4 and working.calls == 3
    print("Failed agent identified; completed turns survive and resume without duplicates: PASSED")


async def test_join_analysis(client):
    token = await base.register_and_login(client, base.unique_email("analysis-join"))
    did = await completed_debate(client, token, agents=2, rounds=1)
    entered, release = asyncio.Event(), asyncio.Event()
    class Slow(ExtractionLLM):
        async def generate(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return await super().generate(*args, **kwargs)
    model = Slow()
    with providers(extraction=model):
        left, right = await asyncio.gather(*[client.post(f'/api/v1/debates/{did}/analysis', headers=base.auth(token)) for _ in range(2)])
        assert left.status_code == right.status_code == 202
        assert left.json()["run_id"] == right.json()["run_id"]
        assert left.json()["joined"] != right.json()["joined"]
        await asyncio.wait_for(entered.wait(), 5)
        state = (await client.get(f'/api/v1/debates/{did}/analysis', headers=base.auth(token))).json()
        assert state["state"] == "running" and state["stages"]["extraction"]["state"] == "running"
        assert state["stages"]["verdict"]["state"] == "pending"
        release.set()
        await analysis_pipeline.wait_for_background()
    assert model.calls == 1
    state = (await client.get(f'/api/v1/debates/{did}/analysis', headers=base.auth(token))).json()
    assert state["state"] == "completed", state
    assert state["stages"]["publishing"]["state"] == "completed"
    assert all(s["state"] in ("completed", "skipped") for s in state["stages"].values())
    snapshot = (await client.get(f'/api/v1/debates/{did}/execution', headers=base.auth(token))).json()
    assert snapshot["execution_state"] == "completed" and snapshot["verdict_available"]
    print("Concurrent analysis requests join one run; full persisted timeline reaches saved verdict: PASSED")


async def test_stale_and_fencing(client):
    token = await base.register_and_login(client, base.unique_email("analysis-stale"))
    did = await completed_debate(client, token, agents=2, rounds=1)
    async with base._test_session() as db:
        debate = await db.get(Debate, did)
        debate.analysis_status = {"state": "running", "started_at": "invalid", "run_id": "old"}
        await db.commit()
    with providers():
        resumed = await client.post(f'/api/v1/debates/{did}/analysis', headers=base.auth(token))
        assert resumed.status_code == 202 and resumed.json()["run_id"] != "old"
        await analysis_pipeline.wait_for_background()
    async with base._test_session() as db:
        debate = await db.get(Debate, did)
        current = dict(debate.analysis_status)
        old = dict(current, run_id="superseded", state="failed")
        try:
            await analysis_pipeline._save_status(db, did, old)
        except analysis_pipeline.AnalysisInProgressError:
            pass
        else:
            raise AssertionError("An old run must not overwrite current state")
        await db.refresh(debate)
        assert debate.analysis_status["run_id"] == current["run_id"]
    print("Malformed stale leases recover; superseded run writes are fenced: PASSED")


async def test_extraction_recovery(client):
    token = await base.register_and_login(client, base.unique_email("extraction-recovery"))
    did = await completed_debate(client, token, agents=2, rounds=1)
    headers = base.auth(token)
    with providers(extraction=ExtractionLLM(fail=True)):
        await client.post(f'/api/v1/debates/{did}/analysis', headers=headers)
        await analysis_pipeline.wait_for_background()
    failed = (await client.get(f'/api/v1/debates/{did}/analysis', headers=headers)).json()
    assert failed['stages']['extraction']['state'] == 'failed' and failed['claims_total'] == 0
    from app.models.fallacy import Fallacy
    from app.models.argument_evaluation import ArgumentEvaluation
    async with base._test_session() as db:
        saved = [list((await db.execute(select(model.id).where(model.debate_id == did))).scalars())
                 for model in (Fallacy, ArgumentEvaluation)]
    with providers():
        await client.post(f'/api/v1/debates/{did}/analysis', headers=headers)
        await analysis_pipeline.wait_for_background()
    recovered = (await client.get(f'/api/v1/debates/{did}/analysis', headers=headers)).json()
    assert recovered['stages']['extraction']['state'] == 'completed' and recovered['claims_total'] == 6
    async with base._test_session() as db:
        current = [list((await db.execute(select(model.id).where(model.debate_id == did))).scalars())
                   for model in (Fallacy, ArgumentEvaluation)]
    assert [set(ids) for ids in current] == [set(ids) for ids in saved] and all(len(ids) == 2 for ids in saved)
    print('Failed extraction remains explicit; retry preserves successful message analyses: PASSED')


async def test_interrupted_analysis(client):
    token = await base.register_and_login(client, base.unique_email("analysis-interrupted"))
    did = await completed_debate(client, token, agents=2, rounds=1)
    entered = asyncio.Event()
    class BlockingClaims(ExtractionLLM):
        async def generate(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
    with providers(extraction=BlockingClaims()):
        await client.post(f'/api/v1/debates/{did}/analysis', headers=base.auth(token))
        await asyncio.wait_for(entered.wait(), 5)
        for task in list(analysis_pipeline._background_tasks):
            task.cancel()
        await analysis_pipeline.wait_for_background()
    interrupted = (await client.get(f'/api/v1/debates/{did}/analysis', headers=base.auth(token))).json()
    assert interrupted['state'] == 'failed' and interrupted['stages']['extraction']['state'] == 'failed'
    with providers():
        retry = await client.post(f'/api/v1/debates/{did}/analysis', headers=base.auth(token))
        assert not retry.json()['joined']
        await analysis_pipeline.wait_for_background()
    print('Interrupted analysis releases its lease and permits a safe retry: PASSED')


def test_factual_coverage():
    from app.services.verdict_service import evidence_snapshot, confidence_cap, evidence_basis
    facts = [SimpleNamespace(claim_type='factual', evidence=[], verification=SimpleNamespace(verdict='supported')) for _ in range(3)]
    opinions = [SimpleNamespace(claim_type='opinion', evidence=[], verification=None) for _ in range(12)]
    snapshot = evidence_snapshot(facts + opinions)
    assert snapshot['total_claims'] == 15 and snapshot['factual_claims'] == 3
    assert snapshot['non_factual_claims'] == 12 and snapshot['unverified'] == 0
    assert confidence_cap(snapshot)[0] == 'high' and evidence_basis(snapshot) == 'substantial'
    print('Opinions and predictions do not inflate missing factual verification counts: PASSED')


async def main():
    test_structured_claim_contract()
    test_factual_coverage()
    await test_bounded_repair()
    app = await base.setup()
    async with base.client_for(app) as client:
        await test_async_debate(client)
        await test_failed_turn_resume(client)
        await test_join_analysis(client)
        await test_stale_and_fencing(client)
        await test_extraction_recovery(client)
        await test_interrupted_analysis(client)
    await base.teardown()
    from app.db.redis import redis_client
    await redis_client.aclose()
    print("All live execution tests PASSED")


if __name__ == '__main__':
    asyncio.run(main())
