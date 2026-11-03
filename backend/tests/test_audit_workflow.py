"""Acceptance regressions for persisted multi-agent analyses. Providers are mocked."""
import asyncio
import json
from unittest.mock import patch

from sqlalchemy import select
from app.llm.base import LLMResponse, LLMProviderAPIError
from app.models.argument_evaluation import ArgumentEvaluation
from app.models.claim_verification import ClaimVerification
from app.services import judge_rubric, analysis_pipeline
from tests.test_analysis_pipeline import base, completed_debate, providers, MessageLLM, VerdictLLM


class CountingLLM(MessageLLM):
    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at
    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls == self.fail_at:
            raise LLMProviderAPIError("test outage")
        return await super().generate(messages, **kwargs)


async def main():
    app = await base.setup()
    async with base.client_for(app) as client:
        token = await base.register_and_login(client, base.unique_email("audit"))
        did = await completed_debate(client, token, agents=3, rounds=2)
        headers = base.auth(token)
        fallacy, quality = CountingLLM(fail_at=2), CountingLLM(fail_at=3)
        with providers(), patch("app.services.fallacy_detection.get_llm_provider", return_value=fallacy), patch(
            "app.services.argument_evaluation.get_llm_provider", return_value=quality):
            response = await client.post(f"/api/v1/debates/{did}/verdict?run_missing_analysis=true", headers=headers)
        assert response.status_code == 200, response.text
        status = (await client.get(f"/api/v1/debates/{did}/analysis", headers=headers)).json()
        assert status["state"] == "partial", status
        assert status["coverage"]["fallacy_analyses"] == 5
        assert status["coverage"]["quality_evaluations"] == 5
        assert len(status["failures"]) == 2
        print("Partial failures retain five successful independent results per stage: PASSED")

        retry_f, retry_q = CountingLLM(), CountingLLM()
        with providers(), patch("app.services.fallacy_detection.get_llm_provider", return_value=retry_f), patch(
            "app.services.argument_evaluation.get_llm_provider", return_value=retry_q):
            response = await client.post(f"/api/v1/debates/{did}/verdict?run_missing_analysis=true", headers=headers)
        assert response.status_code == 200, response.text
        assert retry_f.calls == retry_q.calls == 1
        checks = (await client.get(f"/api/v1/debates/{did}/fallacies", headers=headers)).json()["fallacies"]
        scores = (await client.get(f"/api/v1/debates/{did}/evaluations", headers=headers)).json()["evaluations"]
        assert len(checks) == len(scores) == 6
        assert all(c["fallacy_type"] == "no_fallacy" and c["id"] and c["created_at"] for c in checks)
        assert len({c["agent_id"] for c in checks}) == len({e["agent_id"] for e in scores}) == 3
        for score in scores:
            assert score["rubric_version"] == 2 and score["evaluated_at"]
            assert score["overall_score"] == judge_rubric.round_final(judge_rubric.compute_agent_score(score["criterion_scores"]))
            assert score["strengths"] and score["weaknesses"]
        status = (await client.get(f"/api/v1/debates/{did}/analysis", headers=headers)).json()
        assert status["coverage"]["fallacy_status"] == status["coverage"]["quality_status"] == "completed"
        print("Retry only missing messages; all participants scored; explicit clean records and deterministic rubric: PASSED")

        # Failed explicit reanalysis must leave the successful row intact.
        mid = scores[0]["message_id"]
        with patch("app.services.argument_evaluation.get_llm_provider", return_value=CountingLLM(fail_at=1)):
            response = await client.post(f"/api/v1/messages/{mid}/evaluation?force=true", headers=headers)
        assert response.status_code == 502
        saved = (await client.get(f"/api/v1/debates/{did}/evaluations", headers=headers)).json()["evaluations"]
        assert next(s for s in saved if s["message_id"] == mid) == scores[0]
        print("Failed re-evaluation preserves the last successful score: PASSED")

        # Changes in analysis with identical row counts must invalidate the verdict.
        async with base._test_session() as db:
            score = (await db.execute(select(ArgumentEvaluation).where(ArgumentEvaluation.message_id == mid))).scalar_one()
            score.explanation = "Updated reasoning assessment with unchanged counts."
            await db.commit()
        stored = (await client.get(f"/api/v1/debates/{did}/verdict", headers=headers)).json()
        assert stored["stale"] is True
        with providers():
            regenerated = await client.post(f"/api/v1/debates/{did}/verdict?regenerate=true", headers=headers)
        assert regenerated.status_code == 200 and regenerated.json()["stale"] is False
        print("Same-count material changes invalidate verdict; explicit regeneration uses current data: PASSED")

        # Repeated batch actions perform zero extra successful-message inference.
        f, q = CountingLLM(), CountingLLM()
        with patch("app.services.fallacy_detection.get_llm_provider", return_value=f), patch(
            "app.services.argument_evaluation.get_llm_provider", return_value=q):
            assert (await client.post(f"/api/v1/debates/{did}/fallacies/analyze", headers=headers)).status_code == 200
            assert (await client.post(f"/api/v1/debates/{did}/evaluations", headers=headers)).status_code == 200
        assert f.calls == q.calls == 0
        print("Both batch endpoints are idempotent: PASSED")

        class VerdictFailure:
            async def generate(self, *args, **kwargs):
                raise LLMProviderAPIError("test outage")
        before = (await client.get(f"/api/v1/debates/{did}/verdict", headers=headers)).json()
        with providers(), patch("app.services.verdict_service.get_llm_provider", return_value=VerdictFailure()):
            failed = await client.post(f"/api/v1/debates/{did}/verdict?run_missing_analysis=true&regenerate=true", headers=headers)
        assert failed.status_code == 502
        after = (await client.get(f"/api/v1/debates/{did}/verdict", headers=headers)).json()
        assert before["id"] == after["id"] and before["updated_at"] == after["updated_at"]
        print("Failed pipeline regeneration returns an error and preserves the successful verdict: PASSED")

        from app.services.verification_service import parse_verification_payload
        result = parse_verification_payload(json.dumps(dict(verdict="partially_supported", confidence="medium",
            explanation="Only part of the claim is established.", evidence_summary="Partial evidence.")))
        assert result.verdict == "partially_supported"

        class ConcurrentVerdict(VerdictLLM):
            async def generate(self, *args, **kwargs):
                await asyncio.sleep(.05)
                return await super().generate(*args, **kwargs)
        other = await completed_debate(client, token, agents=2, rounds=1)
        model = ConcurrentVerdict()
        with patch("app.services.verdict_service.get_llm_provider", return_value=model):
            left, right = await asyncio.gather(*[
                client.post(f"/api/v1/debates/{other}/verdict", headers=headers) for _ in range(2)])
        assert left.status_code == right.status_code == 200
        assert left.json()["id"] == right.json()["id"] and model.calls == 1
        print("Concurrent verdict creation performs one inference and persists one row: PASSED")

        class UpdatingVerdict(VerdictLLM):
            async def generate(self, *args, **kwargs):
                async with base._test_session() as db:
                    row = (await db.execute(select(ArgumentEvaluation).where(
                        ArgumentEvaluation.message_id == mid))).scalar_one()
                    row.explanation = "A new persisted assessment arrived during verdict generation."
                    await db.commit()
                return await super().generate(*args, **kwargs)
        with patch("app.services.verdict_service.get_llm_provider", return_value=UpdatingVerdict()):
            changed = await client.post(f"/api/v1/debates/{did}/verdict?regenerate=true", headers=headers)
        assert changed.status_code == 200 and changed.json()["stale"] is True
        print("Material arriving during inference marks the resulting verdict outdated: PASSED")
    await base.teardown()
    from app.db.redis import redis_client
    await redis_client.aclose()
    print("All audit workflow tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
